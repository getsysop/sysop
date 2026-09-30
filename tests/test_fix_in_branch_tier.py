"""Drift guards for the fix-by-default rule (Phase 323, `Q-591`; replaces Phase 276's tier).

The rule is stated in three prompt bodies, recorded by one task-body heading, and
checked at one gate. Every one of those places can be edited independently.

**What changed, and why these guards changed with it.** Phase 276 shipped a three-tier
fallthrough (fix in-branch under a narrow bound, extend an open task, file), and Phase
278 added a filing bar that sent anything unable to name what it blocked to a
`tasks/notes.md` ledger. Phase 322's re-measurement found the open queue growing anyway,
at close to three findings per close, and Wade decided the opposite of the pre-written
tightening: **fix by default, close-time review as the safety net, three outcomes (fix,
task, drop), the notes ledger retired, and net open work per close as the measure.**
The never-list is exactly migrations, production writes, and auth or payment logic --
Wade's choice, over keeping prompt bodies, declared security files and the gate-weakening
backstop. So the guards below pin the new rule in both directions: the default is to
fix, and the parking paths the old rule prescribed must not come back.

Two deliberate negative guards survive from Phase 276:

* `test_validator_gains_no_also_fixed_invariant` pins a *decision not to build*.
  `tasks/schema.md` argues against a warn-only validator invariant for both of the
  reasons that apply to `## Also fixed` at once.
* `test_also_fixed_arm_is_not_silenced_by_the_doc_only_skip` pins the one thing the
  arm gets wrong if it is written carelessly: Step 2d's doc-only skip would otherwise
  silence it on precisely the branches most likely to carry an in-branch doc fix.
"""
from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _prose_guard_helpers import carries, locate  # noqa: E402

import pytest

from _reversal import assert_no_reversal, slice_between

REPO_ROOT = Path(__file__).resolve().parent.parent

CLAIM = REPO_ROOT / "core" / "skills" / "claim-task" / "SKILL.md"
BUILD = REPO_ROOT / "core" / "skills" / "auto-build" / "SKILL.md"
DOCWORK = REPO_ROOT / "core" / "skills" / "document-work" / "SKILL.md"
CLOSE = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"
JUDGE = REPO_ROOT / "core" / "skills" / "auto-judge" / "SKILL.md"
FIX = REPO_ROOT / "core" / "skills" / "auto-fix" / "SKILL.md"
SCHEMA = REPO_ROOT / "core" / "companion" / "tasks" / "schema.md"
VALIDATOR = REPO_ROOT / "core" / "companion" / "scripts" / "validate_tasks.py"
BASELINE = REPO_ROOT / "tools" / "FIX_IN_BRANCH_BASELINE.md"
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

# The three sites an executor actually reads. document-work is here because it is
# also invoked directly, outside either executor, and it is the site that *decides*
# to file -- Step 3b only verifies that an already-named follow-up exists.
RULE_SITES = [
    pytest.param(CLAIM, id="claim-task"),
    pytest.param(BUILD, id="auto-build"),
    pytest.param(DOCWORK, id="document-work"),
]


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")

def live_prose(text: str, start: str, end: str, name: str) -> str:
    """A slice with fenced blocks and blockquotes REMOVED.

    Phase 280's round walked twelve mutations through `needle in slice` checks, and
    the two cheapest did not touch the live text at all: gut the rules, then park
    every pinned needle in a `> **Superseded drafting note**` blockquote, or inside a
    ```text fence labelled "a rule this step does NOT follow". Both are legal Markdown
    that a reader plainly does not execute, and both left every pin green.

    So a needle only counts where an executing reader would actually meet it.
    """
    block = re.sub(r"<!--.*?-->", "", slice_between(text, start, end, name), flags=re.S)
    out, fenced = [], False
    for ln in block.split("\n"):
        s = ln.strip()
        if s.startswith("```") or s.startswith("~~~"):
            fenced = not fenced
            continue
        if fenced or s.startswith(">"):
            continue
        out.append(ln)
    return "\n".join(out)


def require_maintainer_side(p: Path) -> str:
    """Read a mirror-excluded file, or skip.

    `CLAUDE.md`, `tools/FIX_IN_BRANCH_BASELINE.md` and `tools/baselines/` are all
    stripped from the public snapshot (`tools/` never ships). On that tree these
    files are absent through no fault of anyone who can see it, and the snapshot
    runs the same required `pytest` check -- so a hard read here reddens a repo
    nobody can fix from. Per tests/test_mirror_skip_discipline.py's rule, skip.
    """
    if not p.is_file():
        pytest.skip(f"{p.name} is mirror-excluded and absent on this tree")
    return p.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# The rule itself -- fix by default (Phase 323)
# --------------------------------------------------------------------------

# Each site's rule block: (path, start anchor, end anchor). Sliced rather than read
# whole, because every assertion below is about THIS rule and a file-wide read is
# satisfied by an unrelated mention elsewhere in the same file.
RULE_BLOCKS = {
    "claim-task": (
        CLAIM,
        "2b. **When the work surfaces something adjacent, fix it here",
        "\n3. **Persist the `## Test decision`**",
    ),
    "auto-build": (
        BUILD,
        "3‑tier. **When the work surfaces something adjacent, fix it here",
        "\n3‑record. **Persist the `## Test decision`**",
    ),
    "document-work": (
        DOCWORK,
        "**Before filing one, fix it if you can",
        "\nA fix or a drop puts no",
    ),
}


def rule_block(name: str) -> str:
    """The rule as an executing reader meets it: fences and blockquotes removed.

    `live_prose` rather than a bare slice, so a needle parked in a blockquote or a
    fence labelled "a rule this step does NOT follow" does not count. The one fence the
    claim-task block legitimately carries is the `questions.md` shape, which is read
    separately by `questions_shape()`.
    """
    path, start, end = RULE_BLOCKS[name]
    return live_prose(read(path), start, end, f"{name} rule block")


def raw_rule_block(name: str) -> str:
    path, start, end = RULE_BLOCKS[name]
    return slice_between(read(path), start, end, f"{name} rule block")


@pytest.mark.parametrize("name", sorted(RULE_BLOCKS))
def test_fixing_is_the_stated_default(name: str) -> None:
    """The reversal Phase 323 made, pinned where each executor reads it."""
    block = rule_block(name)
    assert "that is the default" in block or "filing is not the default" in block, (
        f"{name}: the rule no longer states that fixing is the default. Without it the "
        "three outcomes read as a menu, and a menu drifts back to filing."
    )
    assert "nothing is parked" in block, (
        f"{name}: the rule lost 'nothing is parked'. Parking is the failure the "
        "re-measurement measured: findings moved between piles and the open work grew."
    )


@pytest.mark.parametrize("name", sorted(RULE_BLOCKS))
def test_the_three_outcomes_are_present_and_ordered(name: str) -> None:
    """Fix, then task, then drop -- by position AND by the visible numeral."""
    block = rule_block(name)
    fix_at = block.find("**Fix it in this branch**")
    task_at = block.find("**File a task**")
    drop_at = block.find("**Drop it**")
    assert -1 not in (fix_at, task_at, drop_at), (
        f"{name} is missing one of the three outcomes (fix={fix_at}, task={task_at}, drop={drop_at})."
    )
    assert fix_at < task_at < drop_at, f"{name}: the outcomes are out of order"
    # An executor reads the numeral, not the byte offset. Three literal `1.`s state
    # three first choices -- the Phase 276 decision on the markdown auto-numbering idiom,
    # kept because these files are read as raw text.
    markers = [block[block.rfind("\n", 0, at) + 1:at].strip() for at in (fix_at, task_at, drop_at)]
    assert [m.replace(")", ".") for m in markers] == ["1.", "2.", "3."], f"{name}: the outcomes are numbered {markers!r}"


@pytest.mark.parametrize("name", sorted(RULE_BLOCKS))
def test_the_never_list_is_exactly_the_decided_three(name: str) -> None:
    """Migrations, production writes, auth or payment logic -- no more, no fewer.

    Both directions are the decision. Losing a category puts a migration in a branch
    under review that cannot make it safe. Re-adding one of the categories Wade chose
    to drop (prompt bodies, declared security files, the gate-weakening backstop)
    rebuilds the narrow bound the re-measurement retired, one clause at a time.
    Bounded by the sentence, so an exception appended inside it is read.
    """
    m = re.search(r"\*\*Never, at any size:\*\*(.*?production[^.]*\.)", _WS_NORM.sub(" ", rule_block(name)))
    assert m, f"{name}: the never-list or its 'at any size' qualifier is gone"
    clause = m.group(1).lower()
    for cat in ("migration", "production", "auth", "payment"):
        assert cat in clause, f"{name}: the never-list lost {cat!r}"
    for dropped in ("prompt", "security-critical", "gate", "money-path", "eval"):
        assert dropped not in clause, (
            f"{name}: the never-list gained {dropped!r}. Wade decided on 2026-09-23 that "
            "the list is exactly migrations, production writes, and auth or payment logic."
        )
    for escape in ("unless the", "though a one-line", "except when", "use judgment", "is fine"):
        assert escape not in clause, f"{name}: the never-list carries an escape clause ({escape!r})"


_WS_NORM = re.compile(r"\s+")


# The four reasons a finding cannot be fixed now. Each is a different kind of block, and
# losing one either forces a fix nobody can make safely here or, if one is widened,
# reopens filing as the easy path.
CANNOT_REASONS = {
    "design decision": "it needs a design decision or a human action",
    "too large": "it is too large to review in this branch",
    "never-list": "it is on the never-list",
}


@pytest.mark.parametrize("name", sorted(RULE_BLOCKS))
@pytest.mark.parametrize("label,needle", sorted(CANNOT_REASONS.items()))
def test_a_task_is_only_for_what_cannot_be_fixed_now(name: str, label: str, needle: str) -> None:
    block = rule_block(name)
    assert "**File a task** only when it cannot be fixed now" in block, (
        f"{name}: filing is no longer conditional on the finding being unfixable now."
    )
    assert needle in block, f"{name}: the 'cannot be fixed now' list lost {label!r} ({needle!r})"
    # The list as one sentence, so a fifth reason ("or it is inconvenient") cannot join it
    # with every pinned reason still present.
    assert carries(block, "only when it cannot be fixed now: it needs a design decision or a human "
                          "action, it is too large to review in this branch, or it is on the never-list."), (
        f"{name}: the 'cannot be fixed now' list is no longer exactly the decided reasons"
    )


@pytest.mark.parametrize("name", sorted(RULE_BLOCKS))
def test_a_task_extends_before_it_adds(name: str) -> None:
    """Phase 276's tier 2 survives as a rule inside the task outcome."""
    assert carries(rule_block(name), "Add it to an existing open task in that module before opening a new entry."), (
        f"{name}: the task outcome no longer extends an existing open task first, so "
        "one module's findings become several entries against the same code."
    )


@pytest.mark.parametrize("name", sorted(RULE_BLOCKS))
def test_a_drop_is_only_for_what_is_not_wrong(name: str) -> None:
    block = rule_block(name)
    # The whole sentence, period included: a criterion appended inside it ("..., or it
    # would take long to fix.") widens the drop into a discard path and keeps every
    # shorter needle green.
    assert carries(block, "**Drop it** when nothing is wrong: nothing is broken today, it is a "
                          "preference or a hypothetical, or it is already handled."), (
        f"{name}: the drop criteria are no longer exactly the four decided ones."
    )
    assert "**Drop it** when nothing is wrong" in block, (
        f"{name}: the drop outcome is no longer limited to findings that are not wrong. "
        "A drop licensed by anything wider discards real defects silently."
    )
    assert "not in a ledger" in block, (
        f"{name}: the drop outcome no longer routes a real future condition to the site. "
        "Without it a future condition has nowhere to go but a ledger again."
    )


# How each site handles a finding an answer would unblock. Three sites, three shapes,
# because the three are run by agents with different access to a human.
ASK_ROUTING = {
    "claim-task": ("`<ARTIFACT_DIR>/questions.md`", "this run has nobody to ask. File the task in the worktree with the question and both candidate fixes"),
    "auto-build": ("this run has nobody to ask, so file the task", "write the question into its body"),
    "document-work": ("ask with `AskUserQuestion`", "Under `--non-interactive`, or when no answer comes, file the task"),
}


@pytest.mark.parametrize("name", sorted(ASK_ROUTING))
def test_each_site_routes_the_question_for_who_can_answer_it(name: str) -> None:
    block = rule_block(name)
    assert "**When an answer from the human would make it fixable**" in block, (
        f"{name}: the rule lost the ask-before-file case. Without it a finding one "
        "answer away from a fix is filed, and the next session re-derives the question."
    )
    for needle in ASK_ROUTING[name]:
        assert needle in block, f"{name}: the question routing lost {needle!r}"


def questions_shape() -> str:
    """The `questions.md` entry shape the claim-task executor is told to write."""
    block = raw_rule_block("claim-task")
    m = re.search(r"(```|~~~)markdown\n(.*?)\1", block, re.S)
    assert m, "claim-task's rule block no longer carries the questions.md shape"
    return textwrap.dedent(m.group(2))


def test_the_questions_shape_carries_what_the_orchestrator_needs() -> None:
    """Step 8 reports each entry, so each has to name the task it was filed as."""
    shape = questions_shape()
    assert shape.startswith("## "), "a questions.md entry no longer opens with a `## ` heading"
    for field in ("filed as:", "where:", "question:", "recommended:"):
        assert re.search(r"(?m)^[-*+] " + re.escape(field), shape), f"the questions.md shape lost {field!r}"


def test_claim_task_step_8_reports_then_asks_a_human() -> None:
    """Step 8 reports the executor's questions, then asks them on option A or a resume.

    Phase 323 shipped report-only after two rounds disqualified in-branch ask-and-fix: first
    the orchestrator was told to edit files, then a follow-up executor could report a failed
    fix as success. `Q-593` recorded what a build must carry, and Phase 345 built it as Steps
    8b and 8c on Wade's answers of 2026-09-29. The orchestrator still never fixes; it asks,
    records and spawns.
    """
    text = read(CLAIM)
    step = slice_between(
        text, "**Then report the questions the executor filed.**", "\n\nThen:\n", "claim-task Step 8 report"
    )
    for needle, why in [
        ("`<ARTIFACT_DIR>/questions.md`", "the file the executor writes"),
        ("filed on the branch as a task carrying the question", "where the finding went"),
        ("`filed as:` id", "the task id the human answers on"),
        ("Do not answer or fix them yourself; this skill never implements.", "the orchestrator boundary"),
        ("on option A, or on any `--resume`", "who is asked"),
        ("**On a fresh option-B run, do not ask**", "option B staying unattended"),
        ("/claim-task <CLAIM_ID> --resume <RUN_ID>", "the command that asks under option B"),
    ]:
        assert carries(step, needle), f"claim-task Step 8's report lost {why} ({needle!r})"
    at = text.index("**Then report the questions the executor filed.**")
    assert text.index("**If that printed `MISSING` or `TEMPLATE`, stop and say so") < at < text.index("## Claim complete: <CLAIM_ID>")

    s8c = text[text.index("### Step 8c: Spawn the answers executor"):]
    for needle, why in [
        ("**verbatim from START to END**", "the full Step 7e prompt, not an inline one"),
        ("`answers` for `<ENVELOPE_PHASE>`", "its own envelope phase"),
        ("never `exec.json`, which is the first executor's", "not reading the first executor's result"),
        ("re-run Step 8's stranded-body check and its test-decision read-back", "the read-back after it commits"),
        ("Handle it as `FAILED`", "a success claim the branch contradicts"),
        ("**Do not rewrite `classification.md`.**", "a BLOCKED park that does not re-run the first executor"),
        ("**No auto-retry.**", "no retry on failure"),
        ("**do not spawn again.**", "a recorded spawn is read, not repeated (round 1)"),
        ("**write nothing to `questions.md`**", "the answers run is not asked again (round 1)"),
        ("records the spawn in `answers-started.md`, and prints the branch tip", "the start record, named where it is made (round 2, X08)"),
    ]:
        assert carries(s8c, needle), f"claim-task Step 8c lost {why} ({needle!r})"
    s8b = slice_between(text, "### Step 8b: Ask the executor's questions", "### Step 8c", "claim-task Step 8b")
    for needle, why in [
        ("**List first:**", "the listing decides whether to ask (round 1)"),
        ("**On `ASK=no`, do not ask.**", "a final record stops the ask (round 1)"),
        ("Build the menu from the listing, not from reading the file", "one parse for the menu and the record"),
        ("**If the record exits non-zero, print the answers you collected and stop**", "answers are never silently lost"),
        ("**A result that says the human may be away**", "a timed-out menu is not an answer (round 2)"),
        ("**is not an answer**, even when it names an option", "a pre-highlighted Fix is not a decision"),
        ("After a record, run Step 8c, whatever the count. After `ASK=no`, do not:", "8c runs only after a record (round 2, X02)"),
        ("If it exits non-zero, report its error and do not ask.", "the listing's failure arm (round 2)"),
    ]:
        assert carries(s8b, needle), f"claim-task Step 8b lost {why} ({needle!r})"
    # Guards lens, R20: after 8c the tip is the answers commit, and amending the executor's
    # commit would rewrite below it.
    assert carries(text, "**amend** the branch's tip commit (the executor's, or Step 8c's)")
    s7pre = slice_between(text, "### Step 7-pre", "### Step 7a", "claim-task Step 7-pre")
    rows = ["| `answers-outcome.md` reads `answers_status: BLOCKED` | **Step 8b** |",
            "| `answers-outcome.md` present | **Step 8** |",
            "| `answers.md` present | **Step 8c** |",
            "| `outcome.md` reads `executor_status: EXECUTED` and `questions.md` holds a `## ` entry |",
            "| `outcome.md` present | **Step 8** |"]
    at = [s7pre.find(r) for r in rows]
    assert -1 not in at, f"Step 7-pre lost an answers row: {[r for r, i in zip(rows, at) if i < 0]}"
    assert at == sorted(at), "Step 7-pre's answers rows are out of order; the table is first-match"


def test_document_work_commits_what_step_3_fixes() -> None:
    """Step 2 is `/document-work`'s last commit; a Step 3 fix has to commit itself.

    Round finding 2 on Phase 323: a fix made under the new rule in Step 3 would sit
    uncommitted, and `/review-close` Step 1a classifies a dirty worktree `dirty` and skips
    the branch.
    """
    block = raw_rule_block("document-work")
    for needle in ("so commit it yourself", "`Doc-Work: <TASK_ID>` trailer", "re-stamp `branch_tip:`"):
        assert needle in block, f"document-work's rule block lost {needle!r}"


@pytest.mark.parametrize("name", sorted(RULE_BLOCKS))
def test_the_rule_retires_the_ledger(name: str) -> None:
    block = rule_block(name)
    assert "`tasks/notes.md` is retired" in block and "write nothing to it" in block, (
        f"{name}: the rule no longer retires the notes ledger, so an executor that "
        "remembers the old rule has nothing telling it the file is closed."
    )
    # Named once, to retire it. A second mention inside the block is a destination --
    # "when unsure, a note in `tasks/notes.md` is fine" keeps every other pin green.
    assert block.count("notes.md") == 1, (
        f"{name}: the rule block names `notes.md` {block.count('notes.md')} times. It is "
        "named once, to retire it; any other mention routes findings back to it."
    )
    assert "theirs to clear; leave it alone" in block, (
        f"{name}: the rule no longer protects a consumer's existing ledger. Retirement "
        "must not delete one; each consumer clears its own."
    )


# Strings only the retired rule used. Each one returning is a piece of the parking path
# coming back, and each is the kind of edit a reader "restoring" the old rule would make.
RETIRED_RULE = (
    "name what the filing blocks",
    "Everything else goes to `tasks/notes.md`",
    "append those lines to `<WORKTREE_PATH>/tasks/notes.md`",
    "on the order of 20 lines",
    "no more than a few per branch",
    "When you are between tiers 1 and 2, take 2",
    "The bound is the design, not a formality.",
    "print the exact line in your final message",
)


@pytest.mark.parametrize("path", RULE_SITES)
@pytest.mark.parametrize("phrase", RETIRED_RULE)
def test_the_retired_rule_does_not_come_back(path: Path, phrase: str) -> None:
    assert phrase not in read(path), (
        f"{path.name} carries {phrase!r}, a clause of the rule Phase 323 retired. "
        "Fix-by-default replaced the tier bound, the filing bar and the notes ledger."
    )


# Where `notes.md` may still be named in each executor-facing file. The rule block names
# it to retire it; claim-task's Step 8 stranded-body probe partitions it out because
# `/add-task` still promotes from an existing ledger. Anywhere else, a mention is a new
# instruction about the file -- the shape a "restore the old rule" edit takes when it is
# reworded rather than copied, which `RETIRED_RULE` cannot see.
LEDGER_SPANS = {
    "claim-task": [
        RULE_BLOCKS["claim-task"][1:],
        ("# The pathspec stays exactly `tasks/`.",
         "**An untracked body is not `STRANDED`"),
    ],
    "auto-build": [RULE_BLOCKS["auto-build"][1:]],
    "document-work": [RULE_BLOCKS["document-work"][1:]],
}


@pytest.mark.parametrize("name", sorted(LEDGER_SPANS))
def test_no_other_part_of_an_executor_file_names_the_ledger(name: str) -> None:
    text = read(RULE_BLOCKS[name][0])
    allowed = []
    for start, end in LEDGER_SPANS[name]:
        a = text.index(start)
        allowed.append((a, text.index(end, a)))
    stray = [m.start() for m in re.finditer(r"notes\.md", text)
             if not any(a <= m.start() < b for a, b in allowed)]
    assert not stray, (
        f"{name}: `notes.md` is named outside the rule block"
        + (" and the stranded probe" if name == "claim-task" else "")
        + f", at {[text.count(chr(10), 0, s) + 1 for s in stray]}. The ledger is retired; a "
        "new mention is a new instruction about it."
    )
    assert allowed and all(b > a for a, b in allowed), "an allowed span is empty -- vacuous"


def test_the_close_arm_never_list_is_exactly_the_decided_three() -> None:
    """The gate's copy of the never-list, held to the same decision as the executors'."""
    arm = slice_between(read(CLOSE), "**2\u2011also. The `## Also fixed` arm", "**3. On a clean match", "2-also arm")
    m = re.search(r"\*\*No line concerns a never-list item without a recorded approval\.\*\*([^.]*\.)", arm)
    assert m, "the arm's check 2 is gone or reworded"
    clause = m.group(1).lower()
    for cat in ("migration", "production", "auth", "payment"):
        assert cat in clause, f"the arm's never-list lost {cat!r}"
    for dropped in ("prompt", "security-critical", "money-path"):
        assert dropped not in clause, f"the arm's never-list gained {dropped!r}"
    for retired in ("never-tier-1", "on the order of 20 lines", "a few per branch", "§ G is explicit"):
        assert retired not in arm, f"the arm carries {retired!r}, a clause of the retired tier bound"


@pytest.mark.parametrize("name", sorted(RULE_BLOCKS))
def test_the_rule_block_carries_no_reversal_vocabulary(name: str) -> None:
    """Presence checks cannot see a sentence added beside a pinned one that cancels it.

    `extra` is this rule's own softenings -- each restores filing, parking, or the
    narrow bound while leaving every pinned string byte-perfect.
    """
    # The RAW block, not `rule_block()`: that strips blockquotes, and a reversal written as a
    # `>` line is still read by an executor. The round's T09 walked through exactly that.
    assert_no_reversal(
        raw_rule_block(name),
        f"{name} rule block",
        extra=(
            "file first",
            "when in doubt, file",
            "prefer filing",
            "filing is never wrong",
            "keep the fix small",
            "only in files the task",
            "a note is fine",
            "park it",
            "leave it for later",
            "at your discretion",
            "use judgment",
            "if you like",
            "whichever fits best",
            "take 2",
            "may go to",
            "worth filing",
            "rough guide",
        ),
    )


@pytest.mark.parametrize("name", sorted(RULE_BLOCKS))
def test_the_fix_records_under_also_fixed(name: str) -> None:
    """An in-branch fix with no record is indistinguishable from unplanned scope."""
    assert "`## Also fixed`" in rule_block(name), (
        f"{name} no longer tells the executor to record the fix under `## Also fixed`. "
        "Without the record, /review-close Step 2a sees a diff hunk the task body does "
        "not explain -- correctly a finding."
    )


@pytest.mark.parametrize(
    "path,ordering_site",
    [
        pytest.param(CLAIM, "Sequence item 3's body write", id="claim-task"),
        pytest.param(BUILD, "Sequence item 3-record's body write", id="auto-build"),
    ],
)
def test_the_placement_rule_names_both_neighbouring_headings(path: Path, ordering_site: str) -> None:
    """The ordering clause must survive, spans intact.

    Phase 276 shipped this sentence into claim-task with three backtick spans EATEN
    by an unquoted heredoc -- each `#`-leading span ran as a command substitution and
    then a comment, and vanished. Keyed to the ordering clause, since that is what the
    eaten spans destroyed and what no other guard reads.
    """
    text = read(path)
    m = re.search(r"placed after [^.]*?`## Test decision`[^.]*?`## Plan` section", text)
    assert m, (
        f"{path.name}: the placement rule at {ordering_site} no longer reads 'placed "
        "after … `## Test decision` … before any `## Plan` section'. If you edited this "
        "file through an UNQUOTED heredoc, check for eaten spans."
    )


@pytest.mark.parametrize(
    "path,start,end,marker,name",
    [
        pytest.param(CLAIM, "- Do **NOT** flip `status:` fields", "- Do **NOT** push to origin",
                     "item 2b's **second** outcome, not the default: fix first",
                     "claim-task filing demotion", id="claim-task"),
        pytest.param(BUILD, "- ADDING a new task entry", "\n\n",
                     "Sequence item 3‑tier's **second** outcome, not the default: fix first",
                     "auto-build filing demotion", id="auto-build"),
    ],
)
def test_the_hard_constraints_keep_filing_second(path: Path, start: str, end: str, marker: str, name: str) -> None:
    """The constraint sentence sits OUTSIDE the rule block and needs its own pin."""
    block = slice_between(read(path), start, end, name)
    assert marker in block, f"{name}: the hard constraint no longer puts filing second"
    assert_no_reversal(block, name, extra=("file first", "usually the right", "filing is never wrong"))


def test_document_work_step_3b_is_named_as_a_filed_task_gate() -> None:
    """Step 3b cannot see an in-branch fix, and must not be relied on as if it could."""
    assert "that gate is a filed-task gate" in read(DOCWORK), (
        "document-work no longer states that Step 3b sees only filed tasks. It fires on "
        "<PREFIX>-<NAME> tokens; a fix or a drop emits none, so a reader who takes it as "
        "the backstop for in-branch fixes is wrong by construction."
    )


def test_document_work_keeps_its_carve_out_count() -> None:
    """Two carve-outs to its do-not-modify rule: filing a body, and `## Also fixed`."""
    text = read(DOCWORK)
    assert "with two exceptions, both named below" in text
    assert "it is not a further exception to the do-not-modify rule above" in text, (
        "document-work no longer says the retired ledger is outside its carve-outs. A "
        "reader who remembers the ledger reads its absence from the list as an oversight."
    )

# --------------------------------------------------------------------------
# The schema
# --------------------------------------------------------------------------

def test_also_fixed_is_declared_in_the_body_layout() -> None:
    assert re.search(r"^## Also fixed$", read(SCHEMA), re.M), (
        "tasks/schema.md no longer declares `## Also fixed` in the per-task body layout."
    )


def test_also_fixed_is_ordered_before_plan() -> None:
    """Same hazard `## Test decision` is ordered around: a fence can quote the heading."""
    text = read(SCHEMA)
    fence = re.search(r"```markdown\n# FEAT-EXAMPLE\n(.*?)```", text, re.S)
    assert fence, "the per-task body layout fence moved or changed shape"
    body = fence.group(1)
    also = body.find("## Also fixed")
    plan = body.find("## Plan")
    assert also != -1 and plan != -1, (also, plan)
    assert also < plan, (
        "`## Also fixed` must be ordered BEFORE `## Plan` in the body layout. The "
        "plan section is a fenced block that can quote either heading, so a "
        "first-match heading reader has to meet the real section first -- the same "
        "reason `## Test decision` sits where it does."
    )


def test_the_schema_section_carries_no_reversal_vocabulary() -> None:
    """The copy a body author reads, guarded like the executors' copies.

    The round turned "match this heading by **search, not equality**" into "by exact
    equality" -- inverting the one requirement the pre-existing `(PR N)` headings make
    non-negotiable -- and appended "a warn-only version is still worth building and
    should be added" directly to the paragraph refusing the validator invariant. Both
    survived: every guard here read the executors' files or a fixed phrase.
    """
    section = slice_between(read(SCHEMA), "### Also fixed", "### User ops", "schema Also fixed section")
    assert "**search, not equality**" in section, (
        "tasks/schema.md no longer requires a search match. `## Also fixed (PR 1)` is a "
        "real heading in a live corpus; equality misses it silently."
    )
    assert_no_reversal(
        section, "schema § Also fixed",
        extra=("still worth building", "should be added", "exact equality",
               "enforced nowhere", "may look", "nowhere automatically"),
    )


def test_schema_states_both_reasons_for_no_invariant() -> None:
    """One reason alone would not settle it; the section is refused for both."""
    text = read(SCHEMA)
    m = re.search(
        r"\*\*The validator does not check this, and will not\*\*, for both of the reasons(.{0,900})",
        text, re.S,
    )
    assert m, "tasks/schema.md lost the paragraph refusing an `## Also fixed` invariant"
    body = m.group(1)
    assert "inside the worktree" in body, "lost the branch-visibility reason"
    assert "optional by design" in body, "lost the optionality reason"


# --------------------------------------------------------------------------
# The gate
# --------------------------------------------------------------------------

def test_review_close_carries_the_also_fixed_arm() -> None:
    assert "The `## Also fixed` arm" in read(CLOSE), (
        "/review-close lost the `## Also fixed` arm. Step 2d is the only gate that "
        "reads the branch tip, so it is the only place the record can be checked at all."
    )


@pytest.mark.parametrize(
    "label,needle",
    [
        ("paths are in the diff", "Every path a line names is in the diff"),
        ("never-list is checked", "No line concerns a never-list item without a recorded approval"),
        ("the set is reviewable", "The fixes are reviewable here"),
    ],
)
def test_also_fixed_arm_checks_all_three_things(label: str, needle: str) -> None:
    assert carries(read(CLOSE), needle), (
        f"the `## Also fixed` arm lost its {label!r} check. A record nobody verifies "
        "against the diff is a record that can assert a fix that never happened."
    )


def test_also_fixed_arm_treats_absence_as_normal() -> None:
    """The opposite of the test-decision arm above it, and easy to get backwards."""
    text = read(CLOSE)
    assert "Absence is never a finding here" in text, (
        "the `## Also fixed` arm no longer states that absence is not a finding. The "
        "section is optional; most branches carry no adjacent fix. Carrying the "
        "test-decision arm's `missing` halt across would fire on nearly every branch."
    )


def test_also_fixed_arm_is_not_silenced_by_the_doc_only_skip() -> None:
    """The skip is scoped to test-decision verification, and must stay scoped."""
    text = read(CLOSE)
    assert "including a task item 0\n       skipped" in text.replace("\n", "\n       ") or "including a task item 0 skipped" in text, (
        "the `## Also fixed` arm no longer overrides Step 2d's doc-only skip. That "
        "skip exists because a docs branch carrying `no test because Z` needs no test "
        "hunt; applied to this arm it would silence it on exactly the branches most "
        "likely to carry a tier-1 fix, since a doc correction is the archetypal one."
    )


def test_the_arm_names_the_pattern_it_actually_matches_on() -> None:
    """Writer and reader can drift apart with every prose guard green.

    The round renamed the heading in document-work's tier text to `## Adjacent fixes`
    and renamed the arm's pattern to `adjacent\\s+fixes`, independently, and nothing
    reddened: one guard pinned the arm's LABEL, another pinned the prose ABOUT the
    match. Neither read the regex the arm tells a reviewer to use.
    """
    arm = slice_between(read(CLOSE), "**2\u2011also. The `## Also fixed` arm", "**3. On a clean match", "2-also arm")
    assert r"`also\s+fixed`" in arm, (
        "the `## Also fixed` arm no longer names the pattern `also\\s+fixed`. If the "
        "arm's pattern and the heading the executors are told to write drift apart, "
        "the arm reads every branch as carrying no record -- and its absence branch is "
        "silent by design, so the drift never surfaces."
    )


def test_the_arm_matches_the_heading_by_search_not_equality() -> None:
    """`## Also fixed (PR 1)` is a real heading in a live consumer corpus.

    Found by this phase's author-side rule-4 pass, which greps the real artefact
    rather than a fixture: gdp-query-system carried eight of these headings across
    seven bodies before the rule existed, two of them with a `(PR N)` suffix. An
    arm written to compare the heading for equality would silently miss those.
    """
    text = read(CLOSE)
    assert "**search, not an equality test**" in text, (
        "the `## Also fixed` arm no longer states that the heading match is a search. "
        "A live consumer corpus carries `## Also fixed (PR 1)`; equality misses it, and "
        "the arm's absence branch is silent, so the miss would never surface."
    )


def test_the_arm_judges_against_the_bound_in_force_not_todays() -> None:
    """A changing convention is judged as of the claim, and the false carve-out stays gone.

    An earlier draft granted a waiver on the ground that the heading "predated any
    rule". The round showed that backwards: the consumer's own copy of this tier
    landed two days before its first `## Also fixed`, so every existing section was
    written under a bound. The waiver's effect would have been a SECOND silencer on
    an arm whose other branch is already silent by design.
    """
    text = read(CLOSE)
    assert "**Judge checks 2 and 3 against today's rule.**" in text, (
        "the `## Also fixed` arm lost its judge-by-today rule. The as-of-claim rule it replaced "
        "(Phase 323) named a bound no shipped text states any more."
    )
    assert "A section that predates this rule is not a finding." not in text, (
        "the false pre-rule carve-out is back. Its stated ground -- that the heading "
        "predated any rule -- was refuted by timestamps: the tier reached the consumer "
        "two days before the first heading appeared there."
    )


def test_schema_refuses_the_corroboration_reading_of_the_eight_headings() -> None:
    """The eight pre-existing headings are the rule's output, not evidence for it.

    The next reader meets the same eight headings and makes the same inference this
    phase made -- that a convention emerged independently and therefore had demand.
    The timestamps say otherwise: the tier reached that consumer's CLAUDE.md two days
    before its first heading appeared. The schema has to say so, or the false reading
    regenerates from the same data.
    """
    text = read(SCHEMA)
    assert "already in use before it was written down here" in text, (
        "tasks/schema.md no longer records that `## Also fixed` was in use before this "
        "section declared it. That fact is what makes the search-not-equality rule "
        "non-arbitrary."
    )
    assert "not independent corroboration and must not be read as any" in text, (
        "tasks/schema.md no longer refuses the corroboration reading of the eight "
        "pre-existing headings. Phase 276 made exactly that inference and shipped it "
        "as 'the strongest evidence the design is right'; the round refuted it with "
        "one timestamp query. Without this sentence the next reader repeats it."
    )


def test_the_arm_carries_no_reversal_vocabulary() -> None:
    """Every check in the arm can be preserved verbatim and cancelled by the next sentence.

    The round wrote eleven such mutations against the arm and all eleven survived: the
    doc-only override kept its needle while the following sentence said the skip DOES
    carry; check 1 kept its wording and became "informational"; the halt became "noted
    for Step 8 and does not join item 3's halt". Step 2d as a whole has carried this
    layer since Phase 249 -- but the arm is sliced out of it here so the failure names
    the arm rather than the step.
    """
    arm = slice_between(read(CLOSE), "**2\u2011also. The `## Also fixed` arm", "**3. On a clean match", "2-also arm")
    assert_no_reversal(
        arm,
        "review-close 2-also arm",
        exempt=(
            "The section is optional by design (`tasks/schema.md` § *Also fixed*)",
        ),
        extra=(
            "informational",
            "does not join item 3's halt",
            "prompt for judgment",
            "do not raise a finding",
            "when time allows",
            "carries here too",
            "fold it into the test-decision totals",
            "prefer \"waive\" over \"hold for fix\"",
            "apply checks 2 and 3 to every section regardless",
            "in spirit",
            "unless the diff shows hunks",
            "raise it as `missing`",
            # Phase 280. Its battery kept every pinned needle in check 3 and added
            # "judging each section's alone is equally valid" beside it -- restoring
            # the per-section reading that undercounts the section-G number.
            "equally valid",
        ),
    )


def test_the_schema_never_list_is_exactly_the_decided_three() -> None:
    """The list a consumer reads when authoring a body, guarded like the executors'."""
    text = read(SCHEMA)
    m = re.search(r"\*\*What may never go in it,\*\* at any size:(.*?)\n\n", text, re.S)
    assert m, "tasks/schema.md lost its `What may never go in it` never-list"
    clause = m.group(1).lower()
    for cat in ("migration", "production", "auth", "payment"):
        assert cat in clause, f"tasks/schema.md's never-list lost {cat!r}"
    for dropped in ("prompt", "security-critical", "money-path"):
        assert dropped not in clause, f"tasks/schema.md's never-list gained {dropped!r}"
    assert "outside the rule by category, not by size" in text, (
        "tasks/schema.md no longer says the never-list excludes by CATEGORY. Without "
        "that, a correct one-line fix to a migration reads as admissible."
    )


@pytest.mark.parametrize(
    "path,start,end,name",
    [
        pytest.param(JUDGE, "**This is narrower than the fix-by-default rule",
                     "</if>", "auto-judge reconciliation", id="auto-judge"),
        pytest.param(FIX, "These limits are **tighter than the fix-by-default rule",
                     "**Report format**", "auto-fix reconciliation", id="auto-fix"),
    ],
)
def test_the_reconciliation_clauses_are_not_reversed(path: Path, start: str, end: str, name: str) -> None:
    """Both clauses say the shipped limit stays NARROWER. One sentence flips that.

    The round appended "Where the two could both apply, the tier wins" to auto-judge --
    flatly contradicting the shipped sentence two clauses later -- and turned auto-fix's
    "Do not read the tier as widening this scan" into "Read the tier as widening this
    scan where the fix is mechanical". Both left the guarded needles intact.
    """
    block = slice_between(read(path), start, end, name)
    assert_no_reversal(
        block, name,
        extra=("the rule wins", "as widening this scan where", "rule takes precedence"),
    )


def test_step_8_tallies_the_arm_separately() -> None:
    assert "Tally the `## Also fixed` arm separately" in read(CLOSE), (
        "Step 8 no longer tallies the arm. It is the tier's measurement surface as "
        "well as its gate: without the tally, a close where no branch carried the "
        "section reads identically to a close where nobody looked."
    )


# --------------------------------------------------------------------------
# The decision not to build a validator invariant
# --------------------------------------------------------------------------

def test_validator_gains_no_also_fixed_invariant(tmp_path: Path) -> None:
    """Pins a decision, not code -- and pins it on BEHAVIOUR, not on source text.

    Phase 58b shipped a warn-only body-heading invariant; Phase 234 retired it for
    reading the filesystem while the record lives on the branch. `## Also fixed`
    inherits that defect AND is optional, so a presence check cannot tell failure from
    the normal case either. An author following the brief rather than the tree would
    add it back.

    The first cut of this guard grepped the source for `also[_\\s-]*fixed`. The round
    defeated it with the shape a careful author is MOST likely to write -- a copy of
    this file's own live `_MANUAL_SMOKE_HEADING_RE` idiom, where `also` and `fixed` are
    separated by `\\s+` inside a regex literal and the character class never matches.
    Two more bypasses followed (a `[Aa]lso[ ]+fixed` class, implicit string
    concatenation). Grepping for an implementation is guessing at its spelling; running
    it is not. So: build a body with no `## Also fixed`, validate it, and assert
    nothing warns about the heading. Any implementation that warns on absence fails,
    however it is spelled.
    """
    import subprocess

    # Fixture shape taken from tests/test_validate_tasks.py::_VALID_INDEX -- the source
    # of truth for what this validator accepts -- not from my model of it. A fixture
    # built from memory proves only that the author is self-consistent, and the first
    # cut of this test used one: it produced four schema ERRORS and validated nothing.
    tasks = tmp_path / "tasks"
    (tasks / "open").mkdir(parents=True)
    (tasks / "open" / "FEAT-NO-ALSO.md").write_text(
        "# FEAT-NO-ALSO\n\n## Context\nNo adjacent fix was made on this branch.\n",
        encoding="utf-8",
    )
    (tasks / "index.yml").write_text(
        "schema_version: 1\n\n"
        "phases:\n"
        "  - number: 1\n"
        '    title: "Active phase"\n'
        "    status: in_progress\n"
        "    current_focus: true\n\n"
        "tasks:\n"
        "  - id: FEAT-NO-ALSO\n"
        '    title: "A task whose branch fixed nothing extra"\n'
        "    phase: 1\n"
        "    status: open\n"
        "    effort: Low\n"
        "    user_action: false\n"
        "    depends_on: []\n"
        "    surfaced_by: []\n"
        "    body: tasks/open/FEAT-NO-ALSO.md\n",
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--path", str(tasks)],
        capture_output=True, text=True,
    )
    out = r.stdout + r.stderr

    # The fixture must be VALID, or this test asserts nothing about warnings.
    assert "0 errors" in out, (
        "the fixture no longer validates, so the warning assertion below is vacuous. "
        f"Rebuild it from tests/test_validate_tasks.py::_VALID_INDEX.\n{out}"
    )
    # Assert on the COUNT, not on wording. The round defeated a wording assertion with
    # a warning that said "body lacks the adjacent-fix heading" -- true to the defect,
    # and containing neither "also" nor "fixed". A count cannot be spelled around.
    assert "0 warnings" in out, (        f"validator output was:\n{r.stdout}\n{r.stderr}"
    )


# --------------------------------------------------------------------------
# Reconciliation with the two shipped scope-limit rules
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "path,needle,why",
    [
        pytest.param(
            JUDGE, "This is narrower than the fix-by-default rule and stays narrower on purpose.",
            "an architectural task's blast radius is the thing under review",
            id="auto-judge",
        ),
        pytest.param(
            FIX, "tighter than the fix-by-default rule",
            "a sibling scan admits only the convention already being enforced",
            id="auto-fix",
        ),
    ],
)
def test_scope_limit_rules_state_their_relation_to_the_tier(path: Path, needle: str, why: str) -> None:
    """Two shipped rules restrict scope; without this, a reader gets two unrelated rules."""
    assert carries(read(path), needle), (
        f"{path.name} no longer states how its scope limit relates to the "
        f"fix-by-default rule ({why}). Both rules are live and one is narrower; a "
        "reader who meets them separately has no way to know which governs."
    )


# --------------------------------------------------------------------------
# The authoritative spec, which described the sequences this rule changed
# --------------------------------------------------------------------------

WORKFLOW = REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md"
GUIDE = REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW_GUIDE.md"


@pytest.mark.parametrize(
    "path,needle,why",
    [
        pytest.param(
            WORKFLOW, "fix-by-default rule",
            "step 10 enumerates the Step 7e executor sequence and gained item 2b",
            id="workflow-executor",
        ),
        pytest.param(
            WORKFLOW, "`2\u2011also` arm",
            "the Step 2d bullet enumerates that step's verifications and gained an arm",
            id="workflow-2also",
        ),
        pytest.param(
            GUIDE, "Fix it in the branch — that is the default.",
            "the guide's 'Record the test decision' section is the human-readable twin",
            id="guide",
        ),
    ],
)
def test_the_workflow_spec_describes_the_tier(path: Path, needle: str, why: str) -> None:
    """CLAUDE.md calls WORKFLOW.md the authoritative spec; it has to know about this.

    Found by the round, which derived the population from the tree instead of from
    this module's own TIER_SITES list. Both files enumerate, step by step, the two
    sequences this rule changed, and neither mentioned it. The repo has a standing
    class for exactly this -- Phase 145 backfilled § 8.4 for the same reason, and
    Phase 161 found three retired behaviours still documented as live.
    """
    assert carries(read(path), needle), f"{path.name} does not describe the rule: {why}"


# --------------------------------------------------------------------------
# Sysop's own adoption, and the measurement
# --------------------------------------------------------------------------

def claude_md_stanza() -> str:
    text = require_maintainer_side(CLAUDE_MD)
    m = re.search(r"- \*\*Fix by default \(Phase 323[^\n]*", text)
    assert m, (
        "CLAUDE.md lost the Sysop-side fix-by-default stanza. Sysop closes phases inline "
        "rather than through /claim-task + /review-close, so the shipped skill change does "
        "not apply here -- this stanza is the only thing that does."
    )
    return m.group(0)


def test_claude_md_carries_the_sysop_side_rule() -> None:
    stanza = claude_md_stanza()
    for needle, why in [
        ("**(1) Fix it in this phase**", "the default outcome"),
        ("**(2) File a `Q-NNN`** only when it cannot be fixed now", "filing as the exception"),
        ("**(3) Drop it** when nothing is wrong", "the drop outcome"),
        ("**When an answer from Wade would make it fixable, ask as a menu", "the ask step"),
        ("**`REVIEW_CHECKLIST.md` § *Notes* is gone**", "the retired ledger"),
        ("`PHASE_LOG.md` entry is the `## Also fixed` equivalent", "this repo's record of an in-branch fix"),
        ("**The measure is net open work per close**", "the measure"),
    ]:
        assert needle in stanza, f"CLAUDE.md's stanza lost {why} ({needle!r})"
    m = re.search(r"\*\*Never in-branch, at any size:\*\*([^.]*\.)", stanza)
    assert m, "CLAUDE.md's stanza lost its never-list"
    clause = m.group(1).lower()
    for cat in ("migration", "production", "auth", "payment"):
        assert cat in clause, f"the Sysop-side never-list lost {cat!r}"
    for dropped in ("prompt", "security", "gate", "core/skills"):
        assert dropped not in clause, f"the Sysop-side never-list gained {dropped!r}"
    assert_no_reversal(stanza, "CLAUDE.md fix-by-default stanza",
                       extra=("is a guideline", "file first", "a note is fine"))
    # § Notes named once, to say it is gone. A second mention is a destination.
    assert stanza.count("§ *Notes*") == 1, (
        f"CLAUDE.md's stanza names § *Notes* {stanza.count('§ *Notes*')} times; it is named "
        "once, to say it is gone, and any other mention routes findings back to it."
    )
    for retired in ("name what it blocks**", "Everything else goes to `REVIEW_CHECKLIST.md` § *Notes*",
                    "on the order of 20 lines"):
        assert retired not in stanza, f"CLAUDE.md's stanza carries the retired clause {retired!r}"


def test_baseline_record_exists_and_states_the_new_measure() -> None:
    text = require_maintainer_side(BASELINE)
    assert "tripwire" in text.lower()
    assert "do not restate the gdp figures as sysop figures" in text.lower(), (
        "tools/FIX_IN_BRANCH_BASELINE.md lost the warning against restating GDP's "
        "numbers as Sysop's. The two denominators are different populations."
    )
    assert "## The measure from Phase 323 on — net open work per close" in text, (
        "the baseline file no longer defines the measure fix-by-default is judged on."
    )
    assert "tools/baselines/net_open_per_close.py" in text


@pytest.mark.parametrize(
    "script",
    ["fix_in_branch_baseline_sysop.py", "fix_in_branch_baseline_consumer.py", "net_open_per_close.py"],
)
def test_baseline_scripts_are_importable(script: str) -> None:
    """A measure whose script no longer parses cannot be taken again."""
    path = REPO_ROOT / "tools" / "baselines" / script
    if not path.is_file():
        pytest.skip(f"{script} lives under mirror-excluded tools/ and is absent here")
    r = subprocess.run(
        [sys.executable, "-c", f"compile(open({str(path)!r}).read(), {script!r}, 'exec')"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"{script} does not compile:\n{r.stderr}"


def _net_open():
    path = REPO_ROOT / "tools" / "baselines" / "net_open_per_close.py"
    if not path.is_file():
        pytest.skip("net_open_per_close.py lives under mirror-excluded tools/")
    import importlib.util
    spec = importlib.util.spec_from_file_location("net_open_per_close", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


_LOG = """## Phase 1 (executed)

### Also fixed
- a
- b
  - a nested sub-point, not an item
1. c

```
this opener is never closed inside Phase 1
## Also fixed
- not a real item either
## Phase 2 (executed)

````markdown
### Also fixed
- quoted inside a real fence, not an item
````

#### Also fixed, in branch
- d
### Next heading
- not under the section
"""


def test_the_fix_counter_counts_every_section_and_skips_what_is_quoted() -> None:
    """The instrument's reading, pinned on a fixture that carries both of its hazards.

    `PHASE_LOG.md` has unclosed openers: a CommonMark reader runs one to EOF and read 18
    of the file's 32 `Also fixed` headings as fenced on 2026-09-23. It also quotes the
    heading inside real fences (Phase 280's two headings, 21 phantom items). The scoped
    reading must take the first hazard as text and the second as quoted.
    """
    mod = _net_open()
    # Scoped: a, b, c from Phase 1 (the indented marker is a sub-point, not an item);
    # the Phase-1 opener closes nowhere before `## Phase 2`, so it is text and the
    # `## Also fixed` after it contributes its one item; the ````markdown fence is real
    # and its quoted heading is skipped; d. 3 + 1 + 1.
    assert mod.also_fixed_items(_LOG, scope=mod.PHASE_HEAD) == 5
    # Fence-blind takes the quoted section as well, and that section (depth 3) runs on
    # past the depth-4 heading, so it takes d a second time: 3 + 1 + 2 + 1.
    assert mod.also_fixed_items(_LOG, fences=False) == 7
    # CommonMark with no scope: the Phase-1 opener runs until the bare ```` closer in
    # Phase 2 and hides everything between, so the Phase-1 section (depth 3) runs on
    # through the hidden lines and past the depth-4 heading: a, b, c, d, and d again.
    # Wrong in both directions at once, which is why the scoped reading exists.
    assert mod.also_fixed_items(_LOG) == 5
    # Phases 302 and 305 write the heading as a code span of itself. The first cut missed
    # both (4 items), which is how its 276-321 reading came out 2 under Phase 322's.
    assert mod.also_fixed_items("### `## Also fixed`\n- x\n- y\n") == 2
    # An explicit none-marker in any of its spellings is zero entries, not one.
    assert mod.also_fixed_items("### Also fixed\n- None\n") == 0
    assert mod.also_fixed_items("### Also fixed\n- _(none)._\n") == 0


# --------------------------------------------------------------------------
# The retired ledger -- what still reads it, and what must not write it
# --------------------------------------------------------------------------

ADDTASK = REPO_ROOT / "core" / "skills" / "add-task" / "SKILL.md"
TASKS_README = REPO_ROOT / "core" / "companion" / "tasks" / "README.md"
INSTALLER = REPO_ROOT / "install.sh"


@pytest.mark.parametrize(
    "path,needle,why",
    [
        pytest.param(WORKFLOW, "`tasks/notes.md` is retired and never written",
                     "the authoritative spec enumerates the Step 7e sequence", id="workflow"),
        pytest.param(WORKFLOW, "`questions.md` in the run directory",
                     "the spec names where an executor's question goes", id="workflow-questions"),
        pytest.param(GUIDE, "`tasks/notes.md` is retired",
                     "the guide is the human-readable twin shipped to consumers", id="guide"),
    ],
)
def test_the_spec_surfaces_describe_the_retirement(path: Path, needle: str, why: str) -> None:
    assert carries(read(path), needle), f"{path.name} does not describe the retired ledger: {why}"


@pytest.mark.parametrize("path", [pytest.param(WORKFLOW, id="workflow"), pytest.param(GUIDE, id="guide")])
def test_the_spec_surfaces_name_the_ledger_only_to_retire_it(path: Path) -> None:
    """A spec sentence routing a finding to the ledger restores it for every reader."""
    text = read(path)
    hits = [m.start() for m in re.finditer(r"`tasks/notes\.md`", text)]
    assert hits, f"{path.name} no longer names the ledger at all -- vacuous"
    stray = [text[max(0, h - 60):h + 40] for h in hits
             if not text.startswith("`tasks/notes.md` is retired", h)]
    assert not stray, f"{path.name} names `tasks/notes.md` other than to retire it: {stray!r}"


def ledger_section() -> str:
    return slice_between(
        read(TASKS_README),
        "## The notes ledger (`notes.md`) — retired",
        "## Migrating from `product_roadmap.md`",
        "tasks/README.md notes-ledger section",
    )


def test_the_readme_retires_the_ledger() -> None:
    section = ledger_section()
    for needle, why in [
        ("**It is retired: no skill writes to it any more.**", "the retirement"),
        ("**An existing ledger is the consumer's to clear, and nothing deletes it.**", "the no-delete contract"),
        ("Triage each line as fix, task or drop", "how a consumer clears it"),
        ("`/add-task` Step 2 dedups against it", "the reader that remains"),
        ("No nesting, no sub-bullets, no sections", "the shape the union resolution rests on"),
        ("`install.sh` never created it and never deletes it", "the ownership contract"),
    ]:
        assert needle in section, f"tasks/README.md's ledger section lost {why} ({needle!r})"


def test_the_ledger_section_carries_no_reversal_vocabulary() -> None:
    assert_no_reversal(
        ledger_section(), "tasks/README.md notes-ledger section",
        extra=("sub-bullet is fine", "nest freely", "append new", "still write", "may still add",
               "may still append", "still append", "append a note", "delete the file",
               "remove the ledger", "when unsure"),
    )


def test_the_installer_does_not_seed_the_ledger() -> None:
    """A decision NOT to build, pinned: the installer neither creates nor deletes it."""
    # `read`, not `require_maintainer_side`: install.sh ships.
    assert "notes.md" not in read(INSTALLER), (
        "install.sh now references the notes ledger. It never created the file, and "
        "retirement must not delete a consumer's existing one."
    )


def test_add_task_dedups_against_the_ledger() -> None:
    """Existing ledgers persist until each consumer clears them, so the reader stays."""
    assert "**Search `tasks/notes.md` too, tolerating its absence** — that is the retired notes ledger" in read(ADDTASK)


def test_add_task_promotion_removes_the_promoted_line() -> None:
    """One finding, one record. A promoted note left behind is a second record."""
    text = read(ADDTASK)
    assert "delete that line from `notes.md` in the same run" in text
    assert "The one write outside that rule is deleting a promoted line" in text

# --------------------------------------------------------------------------
# The readers, and the conflict the ledger causes
# --------------------------------------------------------------------------

def test_review_close_counts_three_shared_append_files() -> None:
    """Three files, and the lead sentence must not contradict the third's bullet.

    The first cut changed the count and left the lead reading "Never resolve
    **either** by stripping the markers and keeping both sides" -- an absolute
    prohibition, two paragraphs above a bullet saying the union IS the resolution
    for this one file. An agent reading top-down aborts on the only file where the
    union is required.
    """
    text = read(CLOSE)
    assert "Three tracked files are appended to across branches" in text, (
        "/review-close no longer counts three shared append files, or has gone back to "
        "the `by *every* branch` framing -- which is false of `tasks/notes.md`: only a "
        "branch that wrote a note appends to it."
    )
    assert "`tasks/notes.md` is the one exception" in " ".join(text.split()), (
        "the lead sentence's never-union rule no longer carves out the ledger, so the "
        "section contradicts its own third bullet."
    )


def ledger_bullet() -> str:
    """The ledger's own bullet in `/review-close`'s shared-append-files section.

    Sliced, not read file-wide, and the reason is that a file-wide version of the
    check below shipped and was walked in the same session that wrote it:
    `byte-identical` occurs three times in `review-close/SKILL.md`, one of them at
    `:1729` predating this phase entirely, so deleting the ledger's own trap left
    the assertion green. Third instance of that class in one phase.
    """
    return slice_between(
        read(CLOSE),
        # `Q-495`: `[-*+]`, because a uniform bullet-marker swap is rendering-identical
        # and reddened this anchor — a guard about the NOTES LEDGER, not about bullets.
        re.compile(r"[-*+] \*\*`tasks/notes\.md`\*\* — the retired notes ledger"),
        "**Resolve `tasks/index.yml` from the merge stages, structurally.**",
        "review-close notes-ledger bullet",
    )


def test_the_ledger_resolution_states_its_own_precondition() -> None:
    """'Keep both sides' is safe HERE and corrupting one bullet above.

    The section's opening rule is *never* resolve by stripping markers and
    keeping both sides. The ledger is the exception, so the exception has to
    carry the property that makes it one and the stop condition for when that
    property no longer holds -- otherwise it reads as a blanket relaxation of
    the rule stated three paragraphs earlier.
    """
    bullet = ledger_bullet()
    assert carries(bullet, "**This is the one of the three where keeping both sides IS the resolution**"), (
        "/review-close no longer marks the ledger as the exception to its own "
        "never-keep-both-sides rule."
    )
    assert "**Two properties make the union safe, and BOTH must hold" in bullet, (
        "the ledger's union resolution no longer states its preconditions."
    )
    assert "Neither side DELETED a line" in bullet, (
        "the union rule lost its DELETE arm -- the one this workflow creates itself. "
        "`/add-task` Step 2 promotes a note by removing its line; union that against "
        "another branch's append and the promoted note comes back, duplicating a filed "
        "task. A delete leaves the file perfectly flat, so the flatness check cannot "
        "see it. Reproduced, not reasoned."
    )
    assert "git show :1:tasks/notes.md" in bullet, (
        "the delete check is stated without the commands that perform it. A precondition "
        "an operator cannot check is a precondition nobody checks."
    )
    assert "`|||||||`" in bullet and "byte-identical" in bullet, (
        "the union rule lost one of its two measured traps: the diff3 fourth marker "
        "(which reinjects the base section, and with it a promoted note), or the "
        "identical-line collapse that produces no conflict for anyone to resolve."
    )


def notes_section_problems(text: str) -> list[str]:
    """Every spelling of a revived `## Notes` section, or of a ledger line parked without one.

    Phase 327's round renamed it `## notes`, wrote it as a setext heading and as a bold lead,
    and changed the bullet and separator of a parked line; each passed the first cut. A
    heading whose text only CONTAINS the word (`## Release Notes checklist`) is not the ledger,
    and going red on it is the over-strictness that gets a guard deleted.
    """
    problems = []
    title = r"(?:sysop[- ]side\s+|sysop\s+)?notes(?![a-z0-9])"
    for pattern, shape in (
        (rf"^#{{1,6}}\s+{title}", "a Notes heading"),
        (rf"^{title}.*\n[=-]+\s*$", "a setext Notes heading"),
        (rf"^(?:\*\*|__){title}", "a bold Notes lead"),
        (r"^\s*[-*+]\s+20\d\d-\d\d-\d\d\s*(?:·|—|-|\|)", "a dated ledger line"),
    ):
        for m in re.finditer(pattern, text, re.M | re.I):
            problems.append(f"{shape}: {m.group(0).splitlines()[0]!r}")
    return problems


def test_the_sysop_notes_section_is_gone() -> None:
    """`REVIEW_CHECKLIST.md` § Notes, the ledger this repo froze, was emptied by `Q-592` and
    DELETED by Phase 327, on Wade's call at Phase 326's open: delete it and pin its absence
    rather than keep an empty marker. An empty `## Notes` heading is a destination waiting for
    the first finding the retired filing bar would have parked there. These replace the three
    tests that pinned it frozen, last and single.
    """
    text = require_maintainer_side(REPO_ROOT / "REVIEW_CHECKLIST.md")
    problems = notes_section_problems(text)
    assert not problems, (
        f"REVIEW_CHECKLIST.md carries the retired notes ledger again: {problems!r}. It was "
        "retired by fix-by-default (Phase 323) and the section deleted by Phase 327: a finding "
        "is fixed, filed as a `Q-NNN`, or dropped."
    )


@pytest.mark.parametrize("revived", [
    "## Notes — frozen 2026-09-23, not queued\n",
    "### notes\n",
    "## Sysop notes\n",
    "Notes\n-----\n",
    "**Notes**\n",
    "- 2026-09-24 · `x` · surfaced by Phase 328 · parked\n",
    "* 2026-09-24 — parked\n",
    # Every other alternative of each arm, one row each (round 2 narrowed each unseen).
    "# Notes\n", "###### Notes\n", "##\tNotes\n", "## Sysop-side notes\n",
    "Notes\n=====\n", "Notes\n--\n", "__Notes__\n",
    "+ 2026-09-24 · parked\n", "- 2026-09-24 - parked\n", "- 2026-09-24 | parked\n",
    "  - 2026-09-24 · an indented parked line\n",
])
def test_every_spelling_of_the_ledger_is_seen(revived: str) -> None:
    assert notes_section_problems("## Planned phases\n\n" + revived), revived


@pytest.mark.parametrize("innocent", [
    "## Release Notes checklist\n",
    "- [ ] <!-- id: Q-999 --> **(Filed 2026-09-24)** a real entry\n",
    "See `_shared/permission-guard.md` § Notes for skill authors.\n",
])
def test_an_innocent_mention_is_not_the_ledger(innocent: str) -> None:
    assert notes_section_problems(innocent) == [], innocent


def test_the_readme_skills_table_lists_every_queue_writer() -> None:
    """The round deleted the `/auto-build` row this phase added, with the suite green."""
    text = read(TASKS_README)
    table = slice_between(text, "## How skills use it", "## Rules", "tasks/README.md skills table")
    for skill in ("`/auto-build`", "`/claim-task <ID>`", "`/add-task`", "`/document-work`"):
        assert skill in table, (
            f"tasks/README.md's skills table no longer lists {skill}. A missing writer "
            "reads as a skill that does not touch the queue, which is how the "
            "`/auto-build` gap this phase closed arose in the first place."
        )


def test_the_ledger_bullet_carries_no_reversal_vocabulary() -> None:
    """The union licence is the most dangerous prose this phase shipped.

    It is the ONE place in `/review-close` that permits a resolution the section
    otherwise forbids absolutely, and it sits beside `tasks/index.yml`, where the
    same resolution corrupts silently and validates green. The round softened it
    (*"or simply take whichever side is longer if the difference looks cosmetic"*)
    and extended the licence to `review_tasks.md` -- both with every pinned string
    intact, because the bullet had presence checks and no screen.
    """
    bullet = ledger_bullet()
    assert "review_tasks.md" not in bullet, (
        "the ledger's union licence now names `review_tasks.md`. That file is an "
        "indented structure -- extending the licence to it is exactly the corruption "
        "the section exists to prevent."
    )
    assert_no_reversal(
        bullet, "review-close notes-ledger bullet",
        extra=(
            "whichever side is longer",
            "looks cosmetic",
            "if the difference",
            "keep both sides anyway",
            "usually safe",
            "as it is for",
            "no need to check",
            "you can skip the",
        ),
    )


def test_the_stranded_probe_excludes_the_ledger() -> None:
    """The F2 fix, guarded -- it shipped without one and the battery walked it out.

    `/claim-task` Step 8's stranded-body probe is `git diff --name-only HEAD --
    tasks/` in the MAIN checkout, and `/add-task` -- which never commits -- deletes a
    line from `tasks/notes.md` there when it promotes a note. Without the exclusion
    that promotion reports `STRANDED`, whose disposition tells the human an executor
    wrote body edits to the wrong tree and **skips the auto-mode chain**. Reproduced
    against the shipped probe by the round; reproduced again after the fix, both
    directions (promotion clean, a real stranded body still reported).
    """
    text = read(CLAIM)
    assert '"--", "tasks/"],' in text, (
        "/claim-task Step 8's stranded probe no longer diffs exactly `tasks/`. "
        "`test_claim_task_step7_contracts.py` pins that pathspec because anything "
        "narrower stops seeing a stranded body -- this phase's FIRST fix for the "
        "false-STRANDED bug added `:(exclude)tasks/notes.md` there and was caught by it."
    )
    assert 'bodies = [p for p in changed if p != "tasks/notes.md"]' in text, (
        "the probe no longer partitions the ledger out of the STRANDED verdict. An "
        "/add-task promotion then reports STRANDED and the auto-mode chain stops, with "
        "a disposition that is false in all three of its claims for a note."
    )
    assert "NOTES PENDING" in text, (
        "the ledger's own arm is gone, so an uncommitted note is either a false halt or "
        "a silence. It still needs committing; it is just not stranded."
    )
    assert "partitioned out of the verdict, and the pathspec is deliberately NOT narrowed" in text, (
        "the partition lost the reason it is a partition rather than an exclusion, which "
        "is the half that stops a future author 'simplifying' it back into the pathspec."
    )


def test_no_other_shared_append_file_gains_the_union_licence() -> None:
    """The licence must not spread to the two files where the union corrupts.

    `ledger_bullet()` screens the ledger's own bullet. The round showed the licence
    can be granted from the NEIGHBOURING bullet instead -- `review_tasks.md` gaining
    "resolvable by union as `tasks/notes.md` is" sits outside that slice and passed
    everything. So the screen is applied to the whole section, minus the one bullet
    that legitimately carries it.
    """
    section = slice_between(
        read(CLOSE),
        "#### Sysop-written shared append files",
        "**Resolve `tasks/index.yml` from the merge stages, structurally.**",
        "review-close shared-append-files section",
    )
    outside = section.replace(ledger_bullet(), "")
    for phrase in ("union", "keeping both sides IS", "keep both sides"):
        assert phrase not in outside, (
            f"the union licence has spread outside the ledger's bullet ({phrase!r}). "
            "`tasks/index.yml` and `review_tasks.md` are indented structures -- for them "
            "that resolution splits an entry across hunks and validates green, which is "
            "the corruption this whole section exists to prevent."
        )


# --------------------------------------------------------------------------
# The tally counts EVERY section, not the first (`Q-464` half 2, Phase 280)
#
# The defect was in the reader, never the writer: `/claim-task`'s option-C
# writer re-emits a two-section body with both sections intact, and Step 2d
# then took the first match. `## Also fixed` lines per branch is one of the
# three numbers section G judges the tier on, and a first-match reader moves
# it DOWN -- the direction that reads as the tier behaving.
#
# The fixture below is not invented. It is the heading order of the one live
# two-section body in the consumer corpus as of 2026-09-10
# (`tasks/open/FEAT-PRICING-LAUNCH-OFFER.md`), reduced to its shape: the
# `(PR 1)` section comes FIRST and its whole content is an explicit `_(none)_`
# marker, an unrelated `## Filed (PR 1)` section sits between the two, and the
# `(PR 0)` section that carries the actual fix entries comes SECOND. Measured
# against that file, a first-match reader reports 0 lines where the body
# carries 2 -- a 100% undercount on the only body in the corpus that can
# produce one. Two closes have already read that body at a branch tip; they
# did not under-report because the arm did not exist yet (Phase 276). Being
# in `open/` proves nothing either way -- a multi-PR task stays there across
# closes. Next exposure is PR 2 of 4.
# --------------------------------------------------------------------------

# The live body's shape, reduced. Heading ORDER is the load-bearing part.
_TWO_SECTION_BODY = """# FEAT-EXAMPLE

## Test decision (PR 0, 2026-09-08)

- test `tests/test_a.py::test_one` proves the thing.

## Also fixed (PR 1)

_(none)_ — every edit is in the plan's scope; the extraction and the helper are
in-scope design items, not adjacent fixes. Money-path files carry no tier-1 fix by rule.

## Filed (PR 1)

_(none)_ — no adjacent defect surfaced that was not already owned by an open task.

## Also fixed (PR 0)

- `src/thing.py::compute` docstring — its enumeration of roles was stale; corrected
  during the in-scope sweep. Doc-only correction, no test gate.
- `docs/configuration.md` — the row named a default the resolver stopped using.

## Plan

```markdown
The reviewed plan, verbatim. It discusses this very rule, so it quotes the heading:

## Also fixed
- a fabricated line naming `never/touched.py`, which is INSIDE a fence.
```
"""

# ATX indented by up to 3 spaces is still a heading; 4+ is a code block.
_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*)$")
# A setext underline: `===` is depth 1, `---` is depth 2. It applies to the line ABOVE.
_SETEXT = re.compile(r"^ {0,3}(=+|-+)\s*$")
_ALSO = re.compile(r"also\s+fixed", re.I)


def _fence_spans(lines: list[str]) -> list[bool]:
    """True for every line inside a fence, tracked the way Step 8's `fence_mark` is.

    A closer uses the same character, is at least as long as the opener, AND carries
    no info string. The first cut of this helper dropped the last clause -- the same
    omission the arm's prose carried -- and it reported a live consumer body as ending
    inside a fence when its fences are balanced: a ```json line nested inside a ```
    fence was read as that fence's closer, inverting the model from there on.

    The round corrected the attribution this docstring used to carry, and **Phase 281
    then made the corrected version stale too** -- which is why this paragraph now names
    no line numbers. The rule is NOT in `fence_mark`, which still only reports that a
    line IS a marker. It used to live inline in `strip_sections`' caller and nowhere
    else, which is what `Q-468` reported; Phase 281 closed that by giving BOTH walkers a
    `fence_closes` predicate, so Step 8 now carries it too. The shape is pinned
    structurally by `tests/test_fence_closer_structure.py` rather than by a line
    citation, because the round walked a substring pin from both the caller and the
    definition.
    """
    inside = [False] * len(lines)
    marker = ""
    for i, ln in enumerate(lines):
        s = ln.strip()
        m = re.match(r"^(`{3,}|~{3,})", s)
        closes = bool(
            m and m.group(1)[0] == marker[:1]
            and len(m.group(1)) >= len(marker)
            and not s.strip(m.group(1)[0])      # no info string
        ) if marker else False
        if not marker and m:
            marker = m.group(1)
            inside[i] = True
            continue
        if marker:
            inside[i] = True
            if closes:
                marker = ""
    return inside


def _heading(lines: list[str], i: int, fenced: list[bool]) -> "tuple[int, str] | None":
    """`(depth, text)` if line *i* is a heading, else None. ATX or setext.

    Both non-ATX shapes were found by the round, and both fail in the OVER-counting
    direction: a terminator model anchored to a column-0 `#` misses them, the section
    over-runs into the next one, and the tally reports the next section's entries too.
    """
    if fenced[i]:
        return None
    m = _HEADING.match(lines[i])
    if m:
        return len(m.group(1)), m.group(2)
    # setext: this line is text and the NEXT line underlines it.
    if i + 1 < len(lines) and not fenced[i + 1] and lines[i].strip():
        u = _SETEXT.match(lines[i + 1])
        if u and not _HEADING.match(lines[i]):
            return (1 if u.group(1)[0] == "=" else 2), lines[i].strip()
    return None


def _is_setext_underline(lines: list[str], i: int, fenced: list[bool]) -> bool:
    """True if line *i* is the underline of a setext heading on line i-1."""
    return (
        i > 0
        and not fenced[i]
        and bool(_SETEXT.match(lines[i]))
        and bool(lines[i - 1].strip())
        and not _HEADING.match(lines[i - 1])
    )


def _sections(body: str, first_only: bool) -> list[list[str]]:
    """Every `also fixed` section outside a fence, or just the first (the defect)."""
    lines = body.split("\n")
    fenced = _fence_spans(lines)
    out: list[list[str]] = []
    for i in range(len(lines)):
        h = _heading(lines, i, fenced)
        if not h or not _ALSO.search(h[1]):
            continue
        depth = h[0]
        start = i + 2 if _is_setext_underline(lines, i + 1, fenced) else i + 1
        content: list[str] = []
        for k in range(start, len(lines)):
            if _is_setext_underline(lines, k, fenced):
                continue          # consumed with its text line below
            nh = _heading(lines, k, fenced)
            if nh and nh[0] <= depth:
                break
            content.append(lines[k])
        out.append(content)
        if first_only:
            break
    return out


def _unterminated(body: str) -> bool:
    """True if the body ends inside a fence -- the shape the arm must REPORT, not guess."""
    lines = body.split("\n")
    marker = ""
    for ln in lines:
        s = ln.strip()
        m = re.match(r"^(`{3,}|~{3,})", s)
        if not marker:
            if m:
                marker = m.group(1)
            continue
        if m and m.group(1)[0] == marker[0] and len(m.group(1)) >= len(marker) \
                and not s.strip(m.group(1)[0]):
            marker = ""
    return bool(marker)


# A top-level list item: `-`, `*`, `+` or `1.`, at column 0..3. NOT a continuation
# line and NOT a nested sub-item -- both belong to the entry above them.
_ITEM = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])\s+\S")


def _fix_lines(content: list[str]) -> int:
    """A line is a TOP-LEVEL list item, per the arm's own rule.

    The first cut of this helper was `ln.startswith("- ")`, which disagreed with
    the shipped prose two ways at once on the phase's own live-derived fixture:
    it missed `*`/`+`/numbered entries entirely (an UNDERCOUNT, the direction the
    arm exists to close) and the prose, read literally as "physical line", would
    have over-counted wrapped entries by 2x.

    "Top-level" is relative to the FIRST item in the section, not to column 0: a
    sub-item indented under a column-0 parent sits at indent 2, which any fixed
    `^ {0,3}` test accepts. Continuation lines and nested sub-items belong to the
    entry above them.
    """
    base = None
    n = 0
    for ln in content:
        m = _ITEM.match(ln)
        if not m:
            continue
        indent = len(ln) - len(ln.lstrip())
        if base is None:
            base = indent
        if indent <= base:
            n += 1
    return n


def _tally(body: str, first_only: bool) -> int:
    return sum(_fix_lines(c) for c in _sections(body, first_only))


def test_the_fixture_actually_discriminates() -> None:
    """The anti-vacuity clause, and it is the reason this pair of tests is worth anything.

    Phase 279 shipped a guard that asserted a PROPERTY a quarter of its subject
    satisfied exactly as well as the whole, and nothing would ever have reported
    the difference. So before asserting that the all-sections tally is right, assert
    that a first-match tally is WRONG on this body -- otherwise both counters agree,
    the fixture proves nothing, and the guard below is green over a reverted rule.
    """
    first = _tally(_TWO_SECTION_BODY, first_only=True)
    every = _tally(_TWO_SECTION_BODY, first_only=False)
    assert first != every, (
        "the fixture no longer discriminates: a first-match reader and an "
        "all-sections reader return the same tally over it, so neither guard below "
        "can fail and the rule they exist to pin is unpinned."
    )
    assert (first, every) == (0, 2), (
        f"the live body's measured shape was first-match=0, all-sections=2; this "
        f"fixture now gives {first} and {every}. If the fixture changed on purpose, "
        f"re-derive both numbers and say where from."
    )


def test_the_none_marker_section_contributes_zero_not_its_prose() -> None:
    """The over-count direction, which corrupts the same section-G number.

    The live `(PR 1)` section's whole content is `_(none)_` plus two lines of prose
    explaining why. Counting prose lines would report 3 where the author recorded
    none -- and the tally would then read as the tier doing MORE than it did.
    """
    sections = _sections(_TWO_SECTION_BODY, first_only=False)
    assert len(sections) == 2, f"expected 2 sections in the fixture, got {len(sections)}"
    assert _fix_lines(sections[0]) == 0, (
        "the `_(none)_` section is being counted as carrying fix entries. A line is a "
        "fix entry; an author who considered the question and recorded nothing "
        "contributes zero, not the length of their explanation."
    )
    assert _fix_lines(sections[1]) == 2, "the second section's two fix entries were lost"


def test_the_fenced_quotation_is_counted_by_neither_reader() -> None:
    """The `## Plan` fence quotes the heading, and the arm forbids reading it.

    This is the arm's worst outcome rather than a miscount: a fence-blind reader
    finds a heading that is a QUOTATION, reads the line under it as a record, and
    raises a check-1 finding against `never/touched.py` -- a path the branch
    legitimately never touched. A fabricated finding.
    """
    for content in _sections(_TWO_SECTION_BODY, first_only=False):
        assert not any("never/touched.py" in ln for ln in content), (
            "a fenced `## Also fixed` inside the `## Plan` section was read as a real "
            "section. The plan is held verbatim in a fence and a plan discussing this "
            "rule quotes the heading."
        )


def test_a_subheading_inside_a_section_does_not_terminate_it() -> None:
    """Same-or-shallower, which is the terminator the arm now states.

    The baseline file's own Sysop-side instrument already terminates this way, and
    for the same stated reason: the undercount is the direction that corrupts this
    measurement, so a `####` sub-heading has to stay INSIDE its section.
    """
    body = (
        "## Also fixed\n"
        "- `a.py` — one.\n"
        "\n"
        "#### A sub-heading the author added\n"
        "- `b.py` — two.\n"
        "\n"
        "## Plan\n"
        "- not a fix entry.\n"
    )
    sections = _sections(body, first_only=False)
    assert len(sections) == 1
    assert _fix_lines(sections[0]) == 2, (
        "a `####` sub-heading terminated its parent section, so the entries below it "
        "were lost. The terminator is same-or-shallower depth."
    )


@pytest.mark.parametrize(
    "label,needle",
    [
        ("iterate every section", "Find **every** section under a heading matching"),
        ("do not stop at the first", "do not stop at the first match"),
        ("the terminator is stated", "ends at the next heading of the **same or shallower** depth"),
        ("the checks run over each section", "Run all three over each section you found"),
        ("the bound is judged on the sum", "**Judge the summed set**"),
        ("the tally sums", "sums every section found"),
        ("a two-section branch counts once", "still counts once in the first field"),
        ("a `_(none)_` section is zero", "contributes **zero**"),
    ],
)
def test_the_arm_iterates_rather_than_taking_the_first_match(label: str, needle: str) -> None:
    """`Q-464` half 2. Each needle is a separate way to restore the undercount.

    Reads LIVE PROSE, not the raw slice: the round gutted every rule here and parked
    all eight needles in a superseded-draft blockquote, then in a labelled fence, and
    both passed. A needle in text a reader does not execute disposes of nothing.
    """
    arm = live_prose(
        read(CLOSE),
        "**2‑also. The `## Also fixed` arm",
        "### 2e. Claim-Artifact Report",
        "2-also arm through item 4",
    )
    assert carries(arm, needle), (
        f"the `## Also fixed` arm lost its {label!r} rule. A first-match reader "
        "undercounts `## Also fixed` lines per branch -- fixes per close, the number "
        "the fix-by-default rule is judged on beside net open work -- and under-reads "
        "how much a branch carries for review."
    )


def test_the_step_8_template_says_all_sections() -> None:
    """The template is the line a human actually reads; the prose above it is not.

    Guarded separately because the two can drift: Phase 280 found the prose and the
    template BOTH saying "the section", and fixing only one would leave the operator
    filling in a field whose own text still asks for a single section's count.
    """
    # The round: this asserted the string was somewhere in a 3,000-line file, so
    # reverting the template and parking the phrase in a fence elsewhere passed. Read
    # the template LINE.
    lines = [l for l in read(CLOSE).split("\n") if l.startswith("Also fixed:")]
    assert len(lines) == 1, (
        f"expected exactly one `Also fixed:` report-template line, found {len(lines)}. "
        "Two would let a reader fill in whichever they met first."
    )
    assert "N lines total across ALL its sections" in lines[0], (
        "the Step 8 `Also fixed:` template no longer says the line count spans every "
        f"section. The template is what an operator fills in. Line is: {lines[0]!r}"
    )
    assert "N branches carrying a section" in lines[0], (
        "the template's branch field changed. `N sections found` would restore the "
        "denominator inflation the arm's item 4 exists to prevent."
    )


def test_a_nested_info_string_fence_is_not_read_as_a_closer() -> None:
    """The omission that inverts the fence model, and it fabricates rather than drops.

    Derived from a live consumer body (`tasks/open/FIX-DRAFTER-JSON-PREAMBLE.md`), which
    nests a ```json line inside a ``` fence -- one body in 912, scanned. A reader that
    accepts an info-string line as a closer believes it has LEFT the fence while still
    inside it, and then reads the fence's own remaining lines as real sections. That is
    the fabricated-finding direction, which the arm calls its worst outcome.

    The round refuted this test's original docstring, which said the shipped Step 8
    verifier already carried the rule. At the time it did not -- it closed a fence on
    any same-char marker of sufficient length, info string or not -- and that was filed
    as `Q-468` and **closed by Phase 281**, which gave both of /claim-task's walkers a
    shared `fence_closes` predicate. What survives unchanged is this arm's reason for
    stating the rule itself rather than pointing at another skill: a rule held by
    pointing at someone else's code moves when that code does, which is exactly what
    happened to the two line numbers this paragraph used to carry.
    """
    body = "\n".join([
        "## Context",
        "",
        "```",
        "a fenced example that itself shows a json block:",
        "```json",
        '{"k": 1}',
        "```",                      # <- the REAL closer of the outer fence
        "",
        "## Also fixed",
        "- `src/real.py` — a genuine entry, outside every fence.",
        "",
    ])
    sections = _sections(body, first_only=False)
    assert len(sections) == 1, (
        f"expected exactly 1 real section, got {len(sections)}. An info-string line "
        "read as a closer inverts the model and changes which headings are visible."
    )
    assert _fix_lines(sections[0]) == 1
    assert any("src/real.py" in ln for ln in sections[0])


def test_the_arm_states_the_info_string_clause() -> None:
    """Pinned in the prose, because the prose is what an agent executes here.

    There is no shipped code for this arm -- a human or an agent reads the paragraph
    and builds the parser. A fence rule stated three-quarters correctly produces a
    parser that is wrong on real input, which is exactly what happened when this
    phase's own helper was written from the paragraph as it stood.
    """
    arm = live_prose(
        read(CLOSE),
        "**2‑also. The `## Also fixed` arm",
        "**3. On a clean match",
        "2-also arm",
    )
    assert carries(arm, "carrying no info string"), (
        "the `## Also fixed` arm's fence rule no longer says a closer carries no info "
        "string. Without it a nested ```json line reads as a closer, the reader believes "
        "it has left the fence, and the fence's own contents are reported as a record."
    )


def test_the_tally_paragraph_carries_no_reversal_vocabulary() -> None:
    """Item 4 sits OUTSIDE the arm's reversal slice, and the battery proved it matters.

    `test_the_arm_carries_no_reversal_vocabulary` ends at "**3. On a clean match", so
    the tally paragraph -- where the two summing rules actually live -- had pins and no
    reversal layer. Phase 280's author-side battery walked two mutations through it:
    both kept every pinned needle and added a sentence beside it licensing the
    first-match count ("judging each section's alone is equally valid", "reporting the
    first section's count alone is acceptable when the others are short"). That is
    verbatim the move that walked 38 of 53 mutations through Phase 247's first guards.

    Scoped to its own slice rather than widening the arm's, so a failure names the
    tally rather than the whole step.
    """
    tally = slice_between(
        read(CLOSE),
        "**4. Record outcomes for Step 8.**",
        "### 2e. Claim-Artifact Report",
        "Step 2d item 4 (the tally)",
    )
    assert_no_reversal(
        tally,
        "review-close Step 2d item 4",
        extra=(
            # Both from this phase's own battery. Neither is generic enough for
            # REVERSAL_VOCAB -- they soften THIS rule and would be noise elsewhere.
            "equally valid",
            # `where convenient` was here and the round showed it a genuine false red --
            # it hits ordinary formatting prose ("where convenient, keep the three
            # numbers on one line"). `equally valid` already kills the mutation it was
            # added for, so it is dropped rather than kept with an exemption.
            "the first section's count alone",
            "fold it into the `Test decisions:` line",
        ),
    )


# --------------------------------------------------------------------------
# What the round forced in (Phase 280, lens 1)
# --------------------------------------------------------------------------

def test_a_setext_heading_terminates_a_section() -> None:
    """`Plan` underlined by `---` is a real H2 and the first model could not see it.

    Over-count direction: the section over-ran into `## Plan` and the tally reported
    the plan's bullets as fix entries -- the same section-G number, pushed the other
    way, which is precisely what item 4 argues corrupts the ratio.
    """
    body = "## Also fixed\n- `a.py` — one.\n\nPlan\n----\n- not a fix entry.\n- nor this.\n"
    sections = _sections(body, first_only=False)
    assert len(sections) == 1
    assert _fix_lines(sections[0]) == 1, (
        "a setext `Plan` heading did not terminate the section, so the plan's own "
        "bullets were counted as fix entries."
    )


def test_an_indented_atx_heading_terminates_a_section() -> None:
    """CommonMark allows up to three spaces of indentation; four makes a code block."""
    body = "## Also fixed\n- `a.py` — one.\n\n   ## Plan\n- not a fix entry.\n"
    sections = _sections(body, first_only=False)
    assert _fix_lines(sections[0]) == 1, (
        "an ATX heading indented by three spaces was not recognised, so the section "
        "over-ran. Four or more spaces WOULD be a code block; three is a heading."
    )


@pytest.mark.parametrize("marker,label", [
    ("-", "dash"), ("*", "star"), ("+", "plus"), ("1.", "numbered"),
])
def test_every_list_marker_counts_as_a_fix_entry(marker: str, label: str) -> None:
    """`- ` only was an UNDERCOUNT, the direction this arm exists to close.

    A section written with `*` bullets carries real entries; a reader that knows only
    `-` tallies it as zero and the branch reads as having fixed nothing.
    """
    body = f"## Also fixed\n{marker} `a.py` — one.\n{marker} `b.py` — two.\n\n## Plan\n"
    assert _tally(body, first_only=False) == 2, f"{label} bullets were not counted"


def test_a_wrapped_entry_counts_once_not_per_physical_line() -> None:
    """The over-count the literal reading of "a line" produces on real input.

    The live corpus wraps entries across three and four physical lines. Counting
    physical lines reports 2x on the phase's own fixture.
    """
    body = (
        "## Also fixed\n"
        "- `src/thing.py::compute` docstring — its enumeration of roles was stale;\n"
        "  corrected during the in-scope sweep. Doc-only correction, no test gate,\n"
        "  verified by reading the five call sites.\n"
        "  - a nested sub-item, which belongs to the entry above it.\n"
        "\n## Plan\n"
    )
    assert _tally(body, first_only=False) == 1, (
        "a wrapped entry with a nested sub-item counted as more than one fix."
    )


def test_an_unterminated_fence_is_detectable_rather_than_guessed() -> None:
    """The shape the arm must REPORT. Silence here picks the worst answer by default.

    A reader that stays inside to EOF loses every real section and says nothing,
    because the arm's absence branch is silent by design. /claim-task Step 8 detects
    the same condition and prints a NOTE; the arm now says to surface it.
    """
    body = "## Plan\n\n```\nan example that never closes\n\n## Also fixed\n- `a.py` — real.\n"
    assert _unterminated(body), "the unterminated fence was not detected"
    assert _tally(body, first_only=False) == 0, (
        "control: a fence-tracking reader DOES lose the entries here -- which is why "
        "the arm must report the condition instead of returning a silent zero."
    )
    ok = "## Also fixed\n- `a.py` — real.\n\n## Plan\n\n```\nclosed\n```\n"
    assert not _unterminated(ok), "false positive on a balanced body"


@pytest.mark.parametrize("label,needle,end", [
    ("states the fence rule itself",
     "A fence opens on ``` or `~~~` and closes on a marker using the **same character**", "**3. On a clean match"),
    # Both rows below were re-pointed by Phase 281, when `Q-468` closed. They used to
    # pin two FACTS about the tree at the time -- that Step 8's walker had no
    # info-string check, and that `claim-task/SKILL.md:1395` was the one shipped site
    # carrying the rule. Phase 281 made both false by fixing Step 8, so pinning them
    # verbatim would have forced the arm to keep asserting something untrue. What the
    # reviewer actually forced in was the DURABLE half of each -- do not hold this rule
    # by pointing at another skill, and do name where the rule lives -- so that is what
    # is pinned now. This is a re-point, not a softening: a fix that deleted either
    # sentence outright still reddens.
    ("retracts the Step 8 pointer",
     "a rule held only by pointing at another skill's code moves when that code does",
     "**3. On a clean match"),
    ("names where the rule lives",
     "delegate the closer decision to one `fence_closes` predicate per block",
     "**3. On a clean match"),
    ("reports an unterminated fence", "unbalanced fences in", "**3. On a clean match"),
    ("covers setext and indented ATX", "a line of text underlined by `===`", "**3. On a clean match"),
    # The count rule lives in item 4, which is PAST the arm's slice end. Sliced to 2e
    # instead of widening the arm's own slice, so a failure still names where it looked.
    ("counts items, not physical lines",
     "**A line is a list ITEM, not a physical line**", "### 2e. Claim-Artifact Report"),
    ("accepts every list marker", "`-`, `*`, `+`, or `1.`", "### 2e. Claim-Artifact Report"),
])
def test_the_arm_carries_what_the_round_forced_in(label: str, needle: str, end: str) -> None:
    arm = live_prose(
        read(CLOSE),
        "**2‑also. The `## Also fixed` arm",
        end,
        "2-also arm",
    )
    assert carries(arm, needle), (
        f"the `## Also fixed` arm lost its {label!r} rule. Every one of these was "
        "forced in by an independent reviewer that executed the arm's instructions "
        "rather than reading them; each has a demonstrated wrong answer behind it."
    )


def test_the_arm_no_longer_claims_step_8_gets_fences_right() -> None:
    """The false claim this phase shipped, pinned so it cannot come back.

    The first cut said "the shipped `fence_mark` gets it right; only this summary of
    it was short". Both halves were false: the rule is not in `fence_mark`, and Step
    8's walker does not carry it anywhere. The claim was the phase's stated reason for
    not fixing a real defect in a shipped gate.
    """
    text = read(CLOSE)
    assert "the shipped `fence_mark` gets it right" not in text, (
        "the refuted claim is back. `fence_mark` reports only that a line IS a marker; "
        "the closer decision -- same character, at least as long, AND no info string -- "
        "lives in `fence_closes`, one copy per shipped block, pinned structurally by "
        "tests/test_fence_closer_structure.py. This was `Q-468`, closed by Phase 281."
    )
    assert "Track fences the way `/claim-task`'s Step 8 verifier does" not in text, (
        "the arm points at Step 8's fence model again. Following it reproduces the "
        "info-string defect this arm exists to avoid."
    )


def test_the_disposition_bullets_carry_no_reversal_vocabulary() -> None:
    """The un-guarded window the round found BETWEEN the two reversal slices.

    `test_the_arm_carries_no_reversal_vocabulary` ends at `**3. On a clean match`;
    `test_the_tally_paragraph_carries_no_reversal_vocabulary` starts at `**4. Record
    outcomes`. Item 3 and the five disposition bullets sit between them, covered by
    neither -- and the round's M03 landed exactly there: every pin intact, plus "the
    sections are duplicates of one another in every case observed, so counting the
    first alone is the reading to use". That sentence reverses the whole arm from a
    position no guard was looking at.
    """
    block = slice_between(
        read(CLOSE),
        "**3. On a clean match",
        "**4. Record outcomes for Step 8.**",
        "Step 2d item 3 + the disposition bullets",
    )
    assert_no_reversal(
        block,
        "review-close Step 2d item 3 + dispositions",
        exempt=(
            # Shipped text: the fourth disposition exists precisely to say nothing was owed.
            "The branch stays approved and **nothing is waived**",
        ),
        extra=(
            "duplicates of one another",
            "counting the first alone",
            "the first section alone",
            "a first-match reading",
            "either reading serves",
        ),
    )


_ARM_REPUDIATION = (
    "is overstated", "that was wrong", "was too strict", "no longer holds",
    "remains the right instruction", "superseded", "that claim is",
)


@pytest.mark.parametrize("label,needle", [
    ("do not hold the rule by pointing at another skill",
     "a rule held only by pointing at another skill's code moves when that code does"),
    ("name where the rule lives",
     "delegate the closer decision to one `fence_closes` predicate per block"),
])
def test_the_re_pointed_rows_are_not_quoted_only_to_be_repudiated(label: str, needle: str) -> None:
    """Round lens 1, MEDIUM 3 — the companion to the presence rows above.

    Phase 281 re-pointed two of those rows onto the durable half of each rule and recorded
    that as "a re-point, not a softening". The lens then walked both by keeping the needles
    and inverting the sentence around them: *"That remains the right instruction, and the
    claim that «a rule held only by pointing at another skill's code moves when that code
    does» is overstated — follow Step 8's walker, which is authoritative."* Both needles
    present; deleting one outright was the only mutation killed.

    Substring presence is a **reversion** guard: it proves the text is wired to the file,
    not that the file asserts it. This row reads the sentence the needle sits in, which is
    where the reversal lives. Same fix as `/auto-build`'s verdict arm, same round.
    """
    arm = live_prose(read(CLOSE), "**2‑also. The `## Also fixed` arm", "**3. On a clean match",
                     "2-also arm")
    # `Q-495`: tolerant, and it names the needle when it moves. `str.index` raised a bare
    # `ValueError("substring not found")` when the shipped sentence was re-wrapped.
    m = locate(arm, needle)
    i = m.start()
    start = max(arm.rfind(". ", 0, i), arm.rfind("\n\n", 0, i)) + 1
    end = arm.find(". ", m.end())
    sentence = arm[start:end if end != -1 else len(arm)].lower()
    found = [v for v in _ARM_REPUDIATION if v in sentence]
    assert not found, (
        f"the `## Also fixed` arm still contains the {label!r} needle, but the sentence "
        f"carrying it repudiates it ({found!r}):\n\n  {sentence.strip()[:400]}\n\n"
        "A rule quoted only to be overturned is not a rule."
    )


# --------------------------------------------------------------------------
# Verbatim pins over the decided text (Phase 323's round)
# --------------------------------------------------------------------------
#
# The round's guards lens walked 39 of 50 mutations through the semantic guards above.
# Nearly all of them were one move: keep every pinned phrase, and widen the rule with a
# clause or a sentence in new words ("…, CI configuration, dependency manifests, and auth",
# "Drop it as well when a fix would take more than an hour"). A phrase guard cannot see
# that, and `_reversal`'s docstring records 25 of 25 out-of-vocabulary softenings surviving
# the same way. The rule text here is Wade's decision, stated at a dozen sites. So each span
# is pinned whole: its whitespace-normalized SHA-256 must equal the one recorded below. Any
# edit, including a correct one, fails until the hash is updated in the same commit. That
# cost is the point: an edit to a ratified rule should be visible in review, not silent.
# Normalization absorbs re-wraps, `N)` for `N.`, and `*`/`+` for `-` list markers, which
# the lens showed are legitimate rewrites a raw pin would false-kill.
#
# `_pin_norm`, `_pin_span` and `_pin_liveness` are shared with
# `test_review_loop_decided_text.py` and `test_review_close_smoke_decided_text.py`, so a
# change here re-derives every hash in all three modules; `test_pin_normalizer.py` holds
# the controls for all of them.

import hashlib  # noqa: E402

from _prose_guard_helpers import _fence_state  # noqa: E402

_WS = re.compile(r"\s+")
# A list marker is followed by a space, a tab, or the end of the line (CommonMark 5.2), so
# `(Step 8),` wrapped to a line start is prose, not an item.
_PIN_MARKER = re.compile(r"^([-+*]|\d{1,9}[.)])(?=[ \t]|$)")
_PIN_HEADING = re.compile(r"^#{1,6}(?=[ \t]|$)")
# What may precede an anchor on its line and still be layout: indentation, a quote prefix,
# a list marker.
_PIN_LEAD = re.compile(r"^[ \t]*(?:>[ \t]?)*[ \t]*(?:(?:[-+*]|\d{1,9}[.)])(?:[ \t]+|$))?$")
_PIN_LAYOUT = re.compile(r"[ \t]*(?:>[ \t]?)*[ \t]*(?:(?:[-+*]|\d{1,9}[.)])[ \t]+)?")


def _pin_quote(body: str) -> tuple[int, int, str]:
    """(blockquote depth, indentation inside the quote, the rest) of a de-indented line."""
    depth, rest = 0, body
    while rest.startswith(">"):
        depth += 1
        rest = rest[1:]
        if rest.startswith(" "):
            rest = rest[1:]
        nxt = rest.lstrip(" ")
        if nxt.startswith(">") and len(rest) - len(nxt) <= 3:
            rest = nxt
    inner = rest.lstrip(" ")
    return depth, len(rest) - len(inner), inner


def _pin_lines(lines: list[str]) -> list[tuple[str, str]]:
    """(kind, record) per line; kind is `blank`, `fence`, `start` or `cont`.

    A `start` line opens a block, so its indentation is structure and is recorded; a `cont`
    line continues a paragraph, where a re-wrap may move it, so only its words are. Tabs
    count to CommonMark's tab stop of 4. Every line of a fenced block, its opener and closer
    included, is recorded whole: a closer moved out of its list item re-fences the rest of
    the document. A line opens a block after a blank, a fence or a heading; as a list item
    with content, a heading, a table row or an HTML comment; or when it deepens a quote.
    """
    fenced = [f for _, f in _fence_state(lines)]
    out: list[tuple[str, str]] = []
    after_para, quote = False, 0
    for i, raw in enumerate(lines):
        line = raw.expandtabs(4)
        body = line.lstrip(" ")
        indent = len(line) - len(body)
        if fenced[i]:
            out.append(("fence", "{}|{}".format(indent, _WS.sub(" ", body.strip()))))
            after_para = False
            continue
        if not body.strip():
            out.append(("blank", ""))
            after_para = False
            continue
        depth, inner_indent, inner = _pin_quote(body)
        inner = inner.rstrip()
        if not inner:
            # A bare `>` is a blank line inside the quote: it ends the paragraph.
            out.append(("start", "{}|{}|0|".format(indent, depth)))
            after_para, quote = False, depth
            continue
        mark = _PIN_MARKER.match(inner)
        rest = inner[mark.end():] if mark else ""
        item = bool(mark and rest.strip())
        closed = _PIN_HEADING.match(inner) or inner.startswith(("|", "<!--"))
        if after_para and not (item or closed or depth > quote):
            out.append(("cont", _WS.sub(" ", inner)))
            continue
        gap = ""
        if mark:
            marker = mark.group(1)
            marker = "-" if marker in "-+*" else marker[:-1] + "."
            # The gap after the marker sets the item's content column, which decides whether
            # a child block below is a paragraph or code; five or more opens code at once.
            gap = str(len(rest) - len(rest.lstrip(" ")))
            inner = marker + " " + rest.strip()
        record = "{}|{}|{}|{}{}".format(indent, depth, inner_indent, gap, _WS.sub(" ", inner))
        out.append(("start", record))
        after_para, quote = not closed, depth
    return out


def _pin_norm(text: str) -> str:
    """Whitespace-normalized, but structure-preserving.

    Each block start keeps its own indentation (and quote depth), each fenced line is kept
    whole, and only paragraph continuation lines are folded into the line above -- which is
    all a re-wrap changes. A removed blank line between two paragraphs is structure too.
    """
    out = []
    for kind, record in _pin_lines(text.split("\n")):
        if kind == "start":
            out.append("\n" + record)
        elif kind == "fence":
            out.append("\nF" + record)
        elif kind == "cont":
            out.append(" " + record)
    return "".join(out).strip()


def _pin_hash(text: str) -> str:
    return hashlib.sha256(_pin_norm(text).encode("utf-8")).hexdigest()[:16]


# A trailing block of its own, so it cannot change how the span's first line parses.
_PIN_INSIDE = "\u2026 span starts inside a paragraph"


def _pin_span(path: Path, text: str, at: int, span: str) -> str:
    """What a pin hashes: *span*, sliced from *text* at offset *at*, with the context a
    slice drops put back.

    * The first line's lead (indentation, quote prefix, list marker) is restored when that
      line opens a block: indenting it four spaces makes a code block (Phase 328's P5).
    * An anchor inside a paragraph, where a re-wrap may move it, gets the layout of the
      line that opened the paragraph instead: indenting that line makes the whole
      paragraph code. It is also marked as inside, so a span that opened a paragraph and
      is joined to the one above (its blank line deleted) moves the pin.
    * A span that starts inside a fence carries the fence's opener line, so its closer
      reads as a closer and removing the fence moves the hash.
    * A last line that is only the next item's marker is dropped, so a swap there is legal.

    HTML files get the slice alone: indentation and fences mean nothing there.
    """
    if path.suffix != ".md":
        return span
    tail = span[span.rfind("\n") + 1:]
    if tail.strip() and _PIN_LEAD.match(tail):
        span = span[:len(span) - len(tail)]
    lines = text.split("\n")
    ln = text.count("\n", 0, at)
    lead = text[text.rfind("\n", 0, at) + 1:at]
    kinds = _pin_lines(lines[:ln + 1])
    kind = kinds[ln][0]
    if _PIN_LEAD.match(lead) and kind != "cont":
        span = lead + span
    else:
        # The anchor sits inside a paragraph (or a code line): the span starts with the
        # layout of the line that opened that block, which is what a re-indent changes.
        # The mark says so: deleting the blank line above a span that opens a paragraph
        # makes it a continuation of the paragraph above, and that must move the pin.
        j = ln
        while j > 0 and kinds[j][0] == "cont":
            j -= 1
        span = _PIN_LAYOUT.match(lines[j]).group(0) + span + "\n\n" + _PIN_INSIDE
    opener = _pin_opener(lines, ln) if kind == "fence" else None
    if opener is not None:
        span = lines[opener] + "\n" + span
    return span


def _pin_opener(lines: list[str], ln: int) -> int | None:
    """The index of the opener of the fence line *ln* sits inside, or None.

    `_fence_state` marks an opener, its body and its closer alike, so a blank line is
    woven in after each line: its state says whether a fence is still open after that line.
    """
    woven = [x for line in lines[:ln] for x in (line, "")]
    open_after = [f for i, f in _fence_state(woven) if i % 2]
    if not open_after or not open_after[-1]:
        return None
    j = len(open_after) - 1
    while j > 0 and open_after[j - 1]:
        j -= 1
    return j


def _comment_open(before: str, markdown: bool) -> bool:
    """Is an HTML comment open at the end of *before*? Read in order, not by counting.

    Phase 335's round (lens 5, G1) disabled a whole pinned block with `<!-- retired` before it
    and `-->` after it, balanced by a literal `` `-->` `` in prose earlier in the file: the
    counts matched, so the span read as live. In markdown a code span is literal text, never a
    comment delimiter, so code spans (and fences, whose backtick runs pair the same way) are
    removed first; then the delimiters are walked in order.
    """
    t = before
    if markdown:
        lines = before.split("\n")
        fenced = dict(_fence_state(lines))
        t = "\n".join(l for n, l in enumerate(lines) if not fenced.get(n, False))
        # A code span never crosses a blank line: an unmatched backtick earlier in the file must
        # not pair with a run past the comment and swallow it (the first cut of this fix did).
        t = re.sub(r"(`+)(?:(?!\1)(?!\n[ \t]*\n)[^`]|`(?!\1))*?\1", "", t, flags=re.S)
    open_, i = False, 0
    while True:
        j = t.find("-->" if open_ else "<!--", i)
        if j < 0:
            return open_
        open_, i = not open_, j + (3 if open_ else 4)


def _pin_liveness(path: Path, text: str, at: int, fenced_ok: bool) -> str | None:
    """Why a span a reader should meet is not live, or None.

    A wrapper outside the anchors keeps every hash: an HTML comment opened before the span,
    or (in markdown) a fence around a span that is not a template. *fenced_ok* marks a
    span that belongs inside its fence; it is checked both ways, so a stale mark fails too.
    """
    before = text[:at]
    # Either reading. The count is the conservative one a fenced prompt needs (a `<!--` pasted
    # into an agent's prompt is not "literal" to the agent); the in-order scan is the one a
    # balanced decoy cannot fool. Neither is sufficient alone.
    if before.count("<!--") != before.count("-->") or _comment_open(before, path.suffix == ".md"):
        return "sits inside an HTML comment"
    if path.suffix != ".md":
        return None
    ln = text.count("\n", 0, at)
    inside = dict(_fence_state(text.split("\n")[:ln + 1])).get(ln, False)
    if inside and not fenced_ok:
        return "sits inside a fenced block"
    if fenced_ok and not inside:
        return "is marked as fenced but is not; drop the mark"
    return None


WORKFLOW_HTML = REPO_ROOT / "docs" / "workflow.html"

def _pin_quoted(phrase: str) -> re.Pattern:
    """An anchor for a phrase inside a blockquote: its words may re-wrap onto a new `> `
    line, which `anchor()` refuses on purpose (its docstring: a site that needs it says so).
    The phrase carries no `>`; `_pin_span` restores the quote prefix as the line's lead."""
    gap = r"(?:[ \t]*\n[ \t]{0,3}(?:>[ \t]?)+[ \t]*|[ \t]+)"
    return re.compile(gap.join(re.escape(word) for word in phrase.split()))


# label: (path, start, end, maintainer_side)
PINNED_SPANS = {
    # Anchors here carry no list marker: `_pin_span` restores a marker lead and drops a
    # trailing one, so a `N.`/`N)` or `-`/`*` swap keeps both the slice and the hash.
    "claim-task rule block": (CLAIM, RULE_BLOCKS["claim-task"][1], "**Persist the `## Test decision`**", False),
    "auto-build rule block": (BUILD, RULE_BLOCKS["auto-build"][1], RULE_BLOCKS["auto-build"][2], False),
    "document-work rule block": (DOCWORK, RULE_BLOCKS["document-work"][1], RULE_BLOCKS["document-work"][2], False),
    "claim-task Step 8 report": (CLAIM, "**Then report the questions the executor filed.**", "\n\nThen:\n", False),
    # Phase 345 (`Q-593`): Step 8's ask, on Wade's four answers of 2026-09-29.
    "claim-task Step 8 ask gate": (CLAIM, "**Then ask them: run Step 8b", "\n\nThen:\n", False),
    "claim-task Step 8b ask": (CLAIM, "Step 8 sends a run here on option A", "Then run the block again with one pair", False),
    "claim-task Step 8b leave rule": (CLAIM, "Then run the block again with one pair", "**If the record exits non-zero", False),
    "claim-task Step 8c spawn arms": (CLAIM, "**`SPAWN=no`**: go back to Step 8's report.", "**START OF ANSWERS ADDENDUM**", False),
    "claim-task Step 8c addendum": (CLAIM, "**START OF ANSWERS ADDENDUM**", "**END OF ANSWERS ADDENDUM**", False),
    "claim-task Step 8c outcomes": (CLAIM, "**`EXECUTED`**: re-run Step 8's", "Every arm but `BLOCKED` then returns", False),
    # Round 1 of Phase 345 (guards lens): every prose site outside a pin walked.
    "claim-task Step 8c read": (CLAIM, "When it returns, read `sysop/runtime/subagent-envelopes/<CLAIM_ID>.answers.json`", "Then record the outcome:", False),
    "claim-task 7-pre answers rows": (CLAIM, "| `classification.md` reads `verdict: BLOCKED` | **7c** |", "| `plan-only.md` present |", False),
    "claim-task auto-mode chaining": (CLAIM, "**Auto-mode chaining.**", "**On `STATUS: BLOCKED`**", False),
    "claim-task 7c park callers": (CLAIM, "**If any finding is `blocker` — park. Do not spawn the executor.**", "supplies its own `<PARK_REASON>`:", False),
    "claim-task hard constraints": (CLAIM, "Do **NOT** invoke the Agent tool — this run is a leaf", "### Required final-message format", False),
    "claim-task record item": (CLAIM, "**Persist the `## Test decision`**", "**Post-fix convention verification", False),
    "claim-task stranded probe": (CLAIM, "# The pathspec stays exactly `tasks/`.", "**An untracked body is not `STRANDED`", False),
    "auto-build record item": (BUILD, "3\u2011record. **Persist the `## Test decision`**", "**Post-fix convention verification", False),
    "document-work carve-out": (DOCWORK, "**Do NOT** modify `PROJECT_STATUS.md`", "**Before filing one, fix it if you can", False),
    "add-task never-does": (ADDTASK, "## What this skill never does", "## Permissions", False),
    "tasks README skills table": (TASKS_README, "| Skill | Reads | Writes |", "## Rules", False),
    "review-close REFERENCE ledger note": (REPO_ROOT / "core" / "skills" / "review-close" / "REFERENCE.md",
                                           "### The retired notes ledger's conflict bullet", "## Step 4a-fix — provenance", False),
    "WORKFLOW 2-also bullet": (WORKFLOW, "Verify any **`## Also fixed` record**", "Verify the recorded **test decision**", False),
    "monograph tier-3 paragraph": (WORKFLOW_HTML, "Tier 3 then needed a bar of its own", "</p>", False),
    "auto-build hard constraints": (BUILD, "Do **NOT** invoke the Agent tool — the orchestrator has already done", "### Required final-message format", False),
    "review-close 2-also arm": (CLOSE, "**2\u2011also. The `## Also fixed` arm.**", "**3. On a clean match", False),
    "review-close shared-append section": (CLOSE, "Three tracked files are appended to across branches",
                                           "**Resolve `tasks/index.yml` from the merge stages, structurally.**", False),
    "schema Also fixed": (SCHEMA, "### Also fixed", "### User ops", False),
    "tasks README ledger": (TASKS_README, "## The notes ledger (`notes.md`) — retired", "## Migrating from `product_roadmap.md`", False),
    "add-task dedup": (ADDTASK, "## Step 2 — Dedup", "## Step 3 — Draft", False),
    "WORKFLOW step 10 rule": (WORKFLOW, "applies the **fix-by-default rule**", ", persists the `## Test decision`", False),
    "GUIDE rule paragraph": (GUIDE, "**Fix it in the branch — that is the default.**", "**Record the test decision.**", False),
    "auto-judge reconciliation": (JUDGE, "**This is narrower than the fix-by-default rule", "</if>", False),
    "auto-fix reconciliation": (FIX, "These limits are **tighter than the fix-by-default rule", "**Report format**", False),
    "monograph addendum": (WORKFLOW_HTML, "<strong>Addendum (2026-09-23).</strong>", "</p>", False),
    "CLAUDE.md conventions": (CLAUDE_MD, "## Conventions for working in this repo", "## Things NOT to do", True),
    # Phase 328 (`Q-459`): the close-time extension of the same rule, decided by Wade's three
    # menu answers of 2026-09-24. Its round walked 23 meaning-changing rewordings through the
    # structural predicates in `test_review_close_fix_at_close.py`; a hash sees every one.
    "review-close 4a-fix step": (CLOSE, "### 4a-fix. Fix the Close's Notes", "### 4a-post. Verify the Merged Tree", False),
    "review-close 2b NOTES block": (CLOSE, "     Then, whatever the verdict:", "     Be thorough.", False),
    "review-close 2b notes collect": (CLOSE, "Collect all verdicts **and every `NOTES:` line**", "**Record outcomes for Step 8.** Tally", False),
    # Item 4's lead is inside the span on purpose: round 2 planted "a fix commit is never the
    # failure; keep it" there, outside a span that began at the arm.
    "review-close 4a-post fix arm": (CLOSE, "**On failure, stop — unless the failure is one this close inherited", "   **The inherited-failure arm fires", False),
    "review-close 4d filing pointer": (CLOSE, "**First, file the notes `4a-fix` routed to a task**", "How the assembled work reaches `main`", False),
    "review-close 4a PR-reuse lead": (CLOSE, "**Skip this step entirely under the Step 4-pre PR-reuse shape**", "For each approved feature branch (oldest first)", False),
    "review-close Step 8 close notes": (CLOSE, "Close notes:   <N collected", "Orchestrator artifacts:", False),
    "review-close 2b twin substitutions": (CLOSE, "The prompt is step 3's, with four substitutions", "Everything else is carried verbatim", False),
    "WORKFLOW 5a item": (WORKFLOW, "5a. **Fix the close's notes**", "\n5b. **Run verification", False),
    # Phase 335 (`Q-570`): Wade's pick, the per-agent scratch directory. Its round's guard lens
    # walked 18 of 40 softenings through the prose predicates in `test_reviewer_scratch_dirs.py`
    # ("make it once for the close and write that one `$SCRATCH` into every prompt", with the
    # bold "is one per agent too" kept). Each span runs from its opener to the next lead.
    "review-close 2b placement": (CLOSE, "**Create each reviewer's checkout AT the target's commit",
                                  "   Then spawn an Agent with:", False),
    "review-close 2b write clause": (CLOSE, "     Do NOT create new files either",
                                     "3b. **Spawn the security twin", False),
    "review-close 2b twin spawn": (CLOSE, "Spawn one Agent per surviving target",
                                   "The prompt is step 3's, with four substitutions", False),
    "adversarial-review scratch bullet": (REPO_ROOT / "core" / "skills" / "_shared" / "adversarial-review.md",
                                          "**Give each concurrent reviewer its own `TMPDIR`.**",
                                          "**Why this is a rule here and not a caveat below.**", False),
    # Phase 337 (`Q-569` + `Q-578`), Wade's pick of 2026-09-27: where §6's entries end, the
    # rotation dedupe's join key, where a missing class heading is judged, and item 5's
    # post-write check with its exit contract. The check's code is inside its span, so a change
    # to what it compares moves the pin as a change to the prose does. Its round reversed the
    # rule from OUTSIDE the first spans (the §6 writer, the Rotation check line, item 7's
    # commit, Step 8's rows), so the spans now run from the §6 writer to the contract's end, and
    # item 7 and Step 8's documentation rows have their own.
    "review-close 4c rotation boundary": (CLOSE, "**PROJECT_STATUS.md §6**: Generate a one-line entry",
                                          _pin_quoted("**The changelog contract — one file, one grammar"), False),
    "review-close 4c changelog contract": (CLOSE, _pin_quoted("**The changelog contract — one file, one grammar"),
                                           _pin_quoted("**Why the second condition.**"), False),
    "review-close 4c post-write check": (CLOSE, "**Check what the writes above did, before the pending-docs are deleted.**",
                                         "**Stage, then commit**: `docs: consolidate", False),
    "review-close 4c stage and commit": (CLOSE, "**Stage, then commit**: `docs: consolidate",
                                         "### 4d. Land on", False),
    "review-close Step 8 documentation rows": (CLOSE, "Documentation written:", "✓ UI_Iterations.md:", False),
}
# Phase 333 (`Q-588`): Wade's 2026-09-25 menu decisions on the two review skills' reviewer
# placement -- a denied `git worktree add` falls back to no isolation, and a refused removal is
# forced only over the runner's own `.venv` symlink. Its round walked meaning-changing rewrites
# ("unless the user says to continue anyway") through the prose predicates that stood here first.
# Round 2 then walked two more around narrow pins -- a sentence BEFORE a pin that started mid-
# paragraph, and a paragraph AFTER a pin that ended on a bare blank line -- so each pin now runs
# from its paragraph's opener to the NEXT paragraph's lead, and anything inserted anywhere in
# between lands inside the hash.
REVIEW_SKILL_PATHS = {
    "codebase-review": REPO_ROOT / "core" / "skills" / "codebase-review" / "SKILL.md",
    "security-audit": REPO_ROOT / "core" / "skills" / "security-audit" / "SKILL.md",
}
# The lead of the paragraph that follows the containment/placement paragraph in each skill.
_AFTER_PLACEMENT = {"codebase-review": "**Sub-agent return contract (`_shared/fanout-evidence.md`).**",
                    "security-audit": "**Do-not-report list (dispatch-side FP guard"}
for _skill, _path in REVIEW_SKILL_PATHS.items():
    PINNED_SPANS.update({
        f"{_skill} placement paragraph": (
            _path, "**This rule has been measured failing, so send it AND check afterwards.**",
            _AFTER_PLACEMENT[_skill], False),
        # Phase 335: the containment rule's lead and pasted block, up to where the placement
        # paragraph's pin begins, so the two pins meet.
        f"{_skill} containment rule": (
            _path, "**Containment rule — paste into every agent's prompt",
            "**This rule has been measured failing, so send it AND check afterwards.**", False),
        f"{_skill} pre-flight stop and worktree note": (
            _path, "If any are missing, stop with", "If `$ARGUMENTS` contains `--skip-permission-guard`", False),
    })
# Phase 338 (`Q-581`, Wade's menu answer 2026-09-27: record the folded set). A mark names the
# round's scope, and records only the in-scope findings, so a deferred finding comes back. Its
# round walked meaning-changing sentences past pins that began at the new text: one line placed
# above the Step 7 block, and the out-of-scope bullet above the pointer. So each pin now runs
# from the step's heading (or the result bullets' first line) to the next heading.
PINNED_SPANS.update({
    "security-audit 3c mark pointer": (
        REVIEW_SKILL_PATHS["security-audit"], "**`findings` (in-scope)**",
        "## Step 4: Deduplicate and Organize", False),
    "security-audit Step 7 mark": (
        REVIEW_SKILL_PATHS["security-audit"], "## Step 7: Commit Generated Tasks",
        "## Step 8: Convention Candidate Extraction", False),
    "security-audit Step 4 marker sentence": (
        REVIEW_SKILL_PATHS["security-audit"],
        "**Ingested findings (Step 3c) dedup against prior-round *closed* tasks too",
        "**Rejected / won't-fix / false-positive**", False),
})

# Phase 339 (`Q-613`): the collision grade `unknown` and its rank, between `possible` and
# `likely` (the maintainer's call). These skill sentences are read by the model, so no
# execution test sees them; the code paths they describe are run by
# `tests/test_overlap_unknown_e2e.py`.
ROADMAP = REPO_ROOT / "core" / "skills" / "roadmap" / "SKILL.md"
PINNED_SPANS.update({
    "auto-build Step 1 inflight grades": (
        BUILD, "the `inflight=<verdict>` field is its collision risk against work building",
        "The list is already sorted **unblocker-first", False),
    "auto-build Step 4 overlap records": (
        BUILD, "Build each line from a `# overlap` record", "This is **advisory, not a veto**", False),
    "roadmap 2b none and unknown": (
        ROADMAP, "A `none` verdict means *no declared overlap*",
        "If `scope_overlap.py` is missing or its permission rule absent", False),
    "roadmap collision marker": (
        ROADMAP, "**Collision marker (only under `--in-flight`, from Step 2b):**", "**Group by kind**", False),
    "roadmap Run-it clear": (
        ROADMAP, "The 💥 marker warns; it never removes the task", "## Design notes", False),
    "claim-task Step 2 verdicts": (
        CLAIM, "prints a note naming that task's workspace, and grades that task `unknown`",
        "The primitive is **non-blocking by construction**", False),
    "roadmap 2b fields": (
        ROADMAP, "Read the JSON `max_verdict`", "Cache the result per task id", False),
    "WORKFLOW overlap advisory": (
        WORKFLOW, "**\"Is this task safe to claim right now?\"**", "**Running more in parallel", False),
    "WORKFLOW scope_overlap row": (
        WORKFLOW, "| `scope_overlap.py <TASK_ID>` |", "| `security_partition.py` |", False),
})

# Phase 344 (`Q-571` + `Q-316`, on Wade's menu answers of 2026-09-28): where /auto-build's
# planner puts its plan, and where the executor puts the plan it revised. Both replaced
# channels a spawned agent could not use -- a message before the hand-back, and
# `ExitPlanMode`.
PINNED_SPANS.update({
    "auto-build planner writes plan.md": (
        BUILD, "### Write the plan to disk", "The file's contents, with no enclosing fence:", False),
    "auto-build item 2 revised plan": (
        BUILD, "**Write the revised plan to `<CLAIM_DIR>/revised-plan.md`**", "**Implement** per the revised plan.", False),
    # Round 1 (lens 1) deleted "Hold the printed absolute path" and "On `File exists`,
    # re-run" from 6a, and handed 6b the path instead of the contents, with every guard green.
    "auto-build 6a mint": (
        BUILD, "**First, mint each task's artifact directory**", "**Then capture each task's pre-plan HEAD.**", False),
    "auto-build 6b reviewer prompt": (
        BUILD, "`prompt`: the **Adversarial-Reviewer Agent Prompt** in Step 7b", "When each reviewer returns", False),
    # Round 2 (lens 4): the Step 8 note's "does not change the status" and /sitrep's
    # auto-build-park sentence were each reversible with every guard green.
    "auto-build revised-plan check": (
        BUILD, "**Then check that `<CLAIM_DIR>/revised-plan.md` exists.**",
        "If the queue still has unstarted batch tasks", False),
    "sitrep auto-build park row": (
        REPO_ROOT / "core" / "skills" / "sitrep" / "SKILL.md",
        "**Rows `6a`, `6b`, `6d` and `6e` withhold the `--resume` line",
        "**Rows `6a`–`6f` report a stall; they never assert one from absence.**", False),
})

PIN_HASHES = {
    # Regenerate with:  .venv/bin/python3 -c "import sys; sys.path.insert(0,'tests'); import test_fix_in_branch_tier as T; T._print_pins()"
    # and review the diff of the SPAN you changed, not just this table.
    "claim-task rule block": "b6ea7f067199d99b",
    "auto-build rule block": "d158bf6def0a688e",
    "document-work rule block": "d03794dec1f817ef",
    "claim-task Step 8 report": "40d99c73aa92f74a",
    "claim-task Step 8 ask gate": "884b01ecfbe029a5",
    "claim-task Step 8b ask": "4475c2fd3cb2243e",
    "claim-task Step 8b leave rule": "5f7feff76f531df8",
    "claim-task Step 8c spawn arms": "6ef7060e43dcf156",
    "claim-task Step 8c addendum": "1a18693dfb996527",
    "claim-task Step 8c outcomes": "a7d4c3561e1b6fa7",
    "claim-task Step 8c read": "9ffd642981cb354f",
    "claim-task 7-pre answers rows": "310136f6d39a3cad",
    "claim-task auto-mode chaining": "2dcd5e7be292f6e9",
    "claim-task 7c park callers": "5e4bbedfb452df98",
    "claim-task hard constraints": "9e52400a383bee4e",
    "claim-task record item": "d3c36f3acc130de6",
    "claim-task stranded probe": "564f368b066357bc",
    "auto-build record item": "90b9df8ae8854ee5",
    "document-work carve-out": "ede14c90a84147d1",
    "add-task never-does": "3616d9ee9d839111",
    "tasks README skills table": "bada255480a1b612",
    "review-close REFERENCE ledger note": "c3e9d55be1fac172",
    "WORKFLOW 2-also bullet": "89f3643416d5bc37",
    "monograph tier-3 paragraph": "331943fca9321557",
    "auto-build hard constraints": "828ad2d5914aad26",
    "review-close 2-also arm": "c2368edf9fe4dd3f",
    # Phase 335: the two stage-extract blocks write into a minted, printed `$STAGES` directory
    # instead of fixed names in the shared temp dir (a concurrent close overwrote them silently).
    # The decided resolution rules in this span are unchanged.
    "review-close shared-append section": "4cb287cb9c4e3b4c",
    "schema Also fixed": "2e6f37f3c52e459d",
    "tasks README ledger": "53f05416e72bcf25",
    "add-task dedup": "96ed49b800bae922",
    "WORKFLOW step 10 rule": "c60fe97f1e01053a",
    "GUIDE rule paragraph": "0e9bb740132f779a",
    "auto-judge reconciliation": "744be3a99d184d53",
    "auto-fix reconciliation": "5a90677d023da92a",
    # Phase 346: the addendum now says /claim-task asks the executor's questions (Phase 345).
    "monograph addendum": "94c1135be6dc894c",
    "CLAUDE.md conventions": "79ce7ef50a1345c0",
    "review-close 2b NOTES block": "287334bc6bb8aa70",
    "review-close 2b notes collect": "04bf180090c9b32c",
    # Phase 335 (`Q-570`): the re-check placement gained its `SCRATCH=$(mktemp -d …)` line, which
    # also prints both paths, and its containment check asks git for the pin's toplevel.
    # The decided fix-at-close rule in this span is unchanged.
    "review-close 4a-fix step": "b7a90b5c0a950ed4",
    "review-close 4a-post fix arm": "3b18633ad2827724",
    "review-close 4d filing pointer": "f0f1ea34763e4ec8",
    "review-close 4a PR-reuse lead": "14bbe3f08cf3eca3",
    "review-close Step 8 close notes": "d2508bea347f6163",
    "review-close 2b twin substitutions": "a2da6151437f458e",
    "WORKFLOW 5a item": "019ee9cc432d2c20",
    # Phase 333: the placement paragraph is identical in both review skills by decision, so its
    # pair shares one hash. The pre-flight spans differ only in each skill's own one-line reason.
    "codebase-review placement paragraph": "cc89d229b5dc483a",
    "codebase-review pre-flight stop and worktree note": "2a51c86ad2c626fc",
    "security-audit placement paragraph": "cc89d229b5dc483a",
    "security-audit pre-flight stop and worktree note": "77ffb4915340c9a8",
    # Phase 335 (`Q-570`). The two containment rules are identical by decision, as the placement
    # paragraphs are, so the pair shares one hash.
    "review-close 2b placement": "060f3f88fcf336dc",
    "review-close 2b write clause": "e9b16c8af664fa35",
    "review-close 2b twin spawn": "351c44f304d6933b",
    "adversarial-review scratch bullet": "a2884d2317529826",
    "codebase-review containment rule": "7c45848ad743f777",
    "security-audit containment rule": "7c45848ad743f777",
    # Phase 337 (`Q-569` + `Q-578`).
    "review-close 4c rotation boundary": "4a4c414ceb762e67",
    "review-close 4c changelog contract": "109f2a2414840e98",
    "review-close 4c post-write check": "f225e3c03d794ccd",
    "review-close 4c stage and commit": "302852b51480be6b",
    "review-close Step 8 documentation rows": "f8835c6c78626835",
    # Phase 338 (`Q-581`).
    "security-audit 3c mark pointer": "f44401cfa8b22c23",
    "security-audit Step 7 mark": "c7ed61435177e009",
    "security-audit Step 4 marker sentence": "35c188ed10ab07ea",
    # Phase 339 (`Q-613`).
    "auto-build Step 1 inflight grades": "3ef12b767dccfb14",
    "auto-build Step 4 overlap records": "2cec7d6b3e66887f",
    "roadmap 2b none and unknown": "5b3990756eb0b6f0",
    "roadmap collision marker": "732cf9853e27e66e",
    "roadmap Run-it clear": "eed08cd451c7a8a5",
    # Round 1 (guards lens): the claim-task span starts one clause earlier, at the
    # unresolved-workspace grade, and the roadmap fields instruction gains its own pin.
    # Round 2 (record lens): that clause still stated the first-cut rule; it now keeps a
    # grade only for an exact-path (`likely`) match.
    "claim-task Step 2 verdicts": "36ba948fd24cecfe",
    "roadmap 2b fields": "cc42b69a5f7520ab",
    "WORKFLOW overlap advisory": "8ade8b7f99a7fd1a",
    "WORKFLOW scope_overlap row": "96575e76334bcf8f",
    # Phase 346: "sees your final message" -> "sees only the report you hand back" (Phase 344's channel).
    "auto-build planner writes plan.md": "9069a8d5f97b6606",
    "auto-build item 2 revised plan": "dc6b545ee1a22ef9",
    "auto-build 6a mint": "b5e67fa3d95f6ace",
    "auto-build 6b reviewer prompt": "f0e1f3582b322044",
    "auto-build revised-plan check": "f0d538b22fb1a02f",
    "sitrep auto-build park row": "723000be52698959",
}


def _located(label: str) -> tuple[Path, str, int, str]:
    path, start, end, maintainer = PINNED_SPANS[label]
    text = require_maintainer_side(path) if maintainer else read(path)
    span = slice_between(text, start, end, label)
    return path, text, text.index(span), span


def _span(label: str) -> str:
    """The slice, with the context `_pin_span` puts back (first-line indentation, and the
    enclosing fence's opener)."""
    span = _pin_span(*_located(label))
    assert len(_pin_norm(span)) > 80, f"{label}: the pinned span is nearly empty -- anchors drifted"
    return span


def _print_pins() -> None:
    for label in PINNED_SPANS:
        print(f'    "{label}": "{_pin_hash(_span(label))}",')


@pytest.mark.parametrize("label", sorted(PINNED_SPANS))
def test_the_decided_text_is_pinned(label: str) -> None:
    got = _pin_hash(_span(label))
    assert label in PIN_HASHES, f"{label}: no pin recorded; add \"{label}\": \"{got}\""
    assert got == PIN_HASHES[label], (
        f"{label} changed (hash {got}, pinned {PIN_HASHES[label]}). This text states the "
        "fix-by-default rule Wade decided on 2026-09-23, or its close-time extension (Phase 328, "
        "2026-09-24), or -- for the review-skill spans -- his reviewer-placement decisions (Phase "
        "333, 2026-09-25), or Step 4c's rotation and changelog contracts (Phase 337, 2026-09-27), or "
        "the collision grade `unknown` and its rank (Phase 339, 2026-09-27), or where /auto-build's plan and "
        "revised plan are written (Phase 344, 2026-09-28), or /claim-task's ask-and-fix (Phase 345, 2026-09-29). The hash covers the span's words, its block structure, its first line's "
        "indentation and the fence it sits in; a re-wrap or a list-marker swap keeps it. If the "
        "edit is a deliberate change to that rule, update the pin in the same commit "
        "(`_print_pins()`) and say so in the phase record; if it is not, it is the widening or "
        "reversal these pins exist to stop."
    )


# The pinned spans that belong inside a fence: a prompt or report template the runner
# copies. Every other span must be live prose. Checked both ways by `_pin_liveness`.
FENCED_PINS = {"claim-task stranded probe", "review-close 2b NOTES block", "review-close Step 8 close notes",
               "review-close 2b write clause", "review-close Step 8 documentation rows"}


@pytest.mark.parametrize("label", sorted(PINNED_SPANS))
def test_every_pinned_span_is_live(label: str) -> None:
    """A wrapper outside the anchors -- `<!--` before the span and `-->` after it, or a
    fence around it -- turns the rule off and keeps every hash."""
    path, text, at, _ = _located(label)
    problem = _pin_liveness(path, text, at, label in FENCED_PINS)
    assert problem is None, f"{label} {problem}"


def test_a_balanced_decoy_cannot_hide_a_comment_around_a_pin() -> None:
    """Lens 5's G1, as a control: a real `<!--` before the span, balanced by a literal
    `` `-->` `` in a code span earlier on, is still an open comment."""
    decoy = "Close a comment with `-->`.\n\n<!-- retired\n\n**The rule.**\n"
    assert _comment_open(decoy, True)
    assert not _comment_open("Open one with `<!--`.\n\n**The rule.**\n", True)
    assert not _comment_open("<!-- a -->\n**The rule.**\n", True)
    assert _comment_open("<!-- a --> <!-- b\n**The rule.**\n", False)


def _anchor_count(text: str, start) -> int:
    from _prose_guard_helpers import anchor as _anchor
    pattern = start if hasattr(start, "finditer") else _anchor(start)
    return len(list(pattern.finditer(text)))


def _anchored_spans():
    for label, (path, start, _end, maintainer) in PINNED_SPANS.items():
        yield label, path, start, maintainer
    for name, (path, start, _end) in RULE_BLOCKS.items():
        yield name + " (rule block)", path, start, False
    for path, spans in LEDGER_ALLOWED.items():
        for start, _end in spans:
            yield f"{path.name} ledger span", path, start, False


def test_every_span_start_anchor_is_unique() -> None:
    """A second copy of a start anchor, earlier in the file, becomes the slice.

    Round 2's decoy: paste the pinned span, end anchor included, into an HTML comment above
    the real one, then edit the real text. Every pin read the copy and stayed green.
    """
    dup = []
    for label, path, start, maintainer in _anchored_spans():
        if maintainer and not path.is_file():
            continue
        n = _anchor_count(read(path), start)
        if n != 1:
            dup.append(f"{label}: {start[:50]!r} occurs {n} times")
    assert not dup, f"span start anchors are not unique, so a decoy copy can stand in: {dup}"


def test_pin_normalization_absorbs_legitimate_rewrites() -> None:
    """Negative control: the rewrites the lens showed a raw pin false-kills."""
    base = "1. **Fix it** — whatever module.\n2. **File a task** only when it cannot.\n- a\n- b"
    assert _pin_hash(base) == _pin_hash("1) **Fix it** — whatever\n   module.\n2) **File a task** only when it cannot.\n* a\n+ b")
    assert _pin_hash(base) != _pin_hash(base.replace("only when", "when"))
    # Structure is not absorbed: an indented block, or a merged paragraph, is a different text.
    para = "First rule here.\n\nSecond rule here."
    assert _pin_hash(para) != _pin_hash(para.replace("\n\n", "\n"))
    assert _pin_hash(para) != _pin_hash("    First rule here.\n\n    Second rule here.")


# The shipped surface a `notes.md` mention can reach a consumer through, derived from the
# tree rather than from the sites this phase edited: the lens re-introduced the ledger at
# add-task, the tasks README's Rules, and the top-level README, none of which a
# site-listed guard read. Case-insensitive, because `tasks/NOTES.md` resolves to the same
# file on macOS and Windows.
LEDGER_ALLOWED = {
    CLAIM: [RULE_BLOCKS["claim-task"][1:], ("# The pathspec stays exactly `tasks/`.", "**An untracked body is not `STRANDED`")],
    BUILD: [RULE_BLOCKS["auto-build"][1:]],
    DOCWORK: [RULE_BLOCKS["document-work"][1:]],
    ADDTASK: [("## Step 2 — Dedup", "## Step 3 — Draft"), ("## What this skill never does", "## Permissions")],
    CLOSE: [("Three tracked files are appended to across branches", "**Resolve `tasks/index.yml` from the merge stages, structurally.**")],
    REPO_ROOT / "core" / "skills" / "review-close" / "REFERENCE.md": [("### The retired notes ledger's conflict bullet", "## Step 4a-post — provenance")],
    TASKS_README: [("| `/add-task` |", "\n"), ("## The notes ledger (`notes.md`) — retired", "## Migrating from `product_roadmap.md`")],
    WORKFLOW: [("applies the **fix-by-default rule**", ", persists the `## Test decision`")],
    GUIDE: [("**Fix it in the branch — that is the default.**", "**Record the test decision.**")],
    WORKFLOW_HTML: [("Tier 3 then needed a bar of its own", "</p>")],
    # `docs/history.md` is deliberately absent. Round 2 showed a per-sentence span there
    # false-kills a historical mention (C4), and the wholesale allowance that fixed it let an
    # instruction through (L10). The page names no ledger file today; a future historical
    # mention needs its own span here, which is a cheaper failure than a silent instruction.
}


_TEXT_SUFFIXES = (".md", ".html", ".sh", ".py", ".yml", ".yaml", ".json", ".txt", ".toml",
                  ".fragment", ".example", "")
_LEDGER_RE = re.compile(r"notes\.md|tasks/notes\b", re.I)


def _shipped_files() -> list[Path]:
    """Every text file under the shipped trees, suffix-less ones included.

    Suffix-less files are real ship paths (`core/companion/git-hooks/pre-commit`), and the
    round showed a ledger instruction there passing a suffix-filtered scan (L5).
    """
    out = [REPO_ROOT / "README.md", REPO_ROOT / "install.sh"]
    for base in ("core", "docs", "packs"):
        for p in (REPO_ROOT / base).rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts and p.suffix in _TEXT_SUFFIXES:
                out.append(p)
    return out


def _visible(text: str) -> str:
    """Format characters removed: `notes\u200b.md` renders as `notes.md` (the round's L7b)."""
    import unicodedata
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def test_the_ledger_is_named_only_where_it_is_retired_or_still_read() -> None:
    files = _shipped_files()
    assert len(files) > 100, f"only {len(files)} shipped files found -- the population is wrong"
    stray = []
    for p in files:
        text = _visible(p.read_text(encoding="utf-8", errors="replace"))
        hits = [m.start() for m in _LEDGER_RE.finditer(text)]
        if not hits:
            continue
        spans = []
        for start, end in LEDGER_ALLOWED.get(p, []):
            a = text.index(start)
            spans.append((a, text.index(end, a + len(start))))
        for h in hits:
            if not any(a <= h < b for a, b in spans):
                stray.append(f"{p.relative_to(REPO_ROOT)}:{text.count(chr(10), 0, h) + 1}")
    assert not stray, (
        f"`notes.md` is named outside the places that retire it or still read it: {stray}. "
        "The ledger is retired (Phase 323); a new mention is a new instruction about it."
    )


def _scratch_repo(tmp_path: Path):
    import os
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")

    def g(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, env=env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(msg, files):
        for rel, body in files.items():
            f = tmp_path / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(body, encoding="utf-8")
        g("add", "-A")
        g("commit", "-q", "-m", msg)
        return g("rev-parse", "HEAD")

    g("init", "-q", "-b", "main")
    return commit


def _run(tmp_path: Path, fn, *args) -> str:
    import contextlib
    import io
    import os
    cwd = os.getcwd()
    buf = io.StringIO()
    try:
        os.chdir(tmp_path)
        with contextlib.redirect_stdout(buf):
            fn(*args)
    finally:
        os.chdir(cwd)
    return buf.getvalue()


def test_the_sysop_reading_counts_what_the_record_says_it_counts(tmp_path: Path) -> None:
    """The instrument's `sysop()` path, run end to end on a scratch repo with no remote.

    Round 1 found `sysop()` unguarded. Round 2 found the first version of this test never
    asserted the headline figures and had an empty FROM side, so 11 of 11 arithmetic
    mutations survived it. Every printed number is asserted here, and FROM carries notes and
    fixes of its own.
    """
    mod = _net_open()
    commit = _scratch_repo(tmp_path)
    q = "- [ ] <!-- id: Q-{} --> x\n"
    n0, n1 = "- 2026-01-01 · a · n0\n", "- 2026-01-02 · a · n1\n"
    log1 = "## Phase 1 (executed)\n### Also fixed\n- z\n```\nunclosed\n"
    log2 = log1 + "## Phase 2 (executed)\n### Also fixed\n- a\n- b\n"
    base = commit("base", {"REVIEW_CHECKLIST.md": "## High\n" + q.format(1) + "## Notes\n" + n0,
                           "PHASE_LOG.md": log1})
    commit("Phase 2: work", {"REVIEW_CHECKLIST.md": "## High\n" + q.format(1) + q.format(2) + "## Notes\n" + n0 + n1,
                             "PHASE_LOG.md": log2})
    # A second PR for the same phase: one close, not two (Phase 277 shipped as four PRs).
    commit("Phase 2: follow-up PR", {"PHASE_LOG.md": log2 + "text\n"})
    commit("docs: inbound triage", {"REVIEW_CHECKLIST.md": "## High\n" + q.format(1) + q.format(2) + q.format(3)
                                    + "## Notes\n" + n0 + n1})
    commit("docs: archive Q-1", {"REVIEW_CHECKLIST.md": "## High\n" + q.format(2) + q.format(3)
                                 + "## Notes\n" + n0 + n1})
    commit("docs: a diagnostic round", {"REVIEW_CHECKLIST.md": "## High\n" + q.format(2) + q.format(3) + q.format(5)
                                        + "## Notes\n" + n0 + n1})
    to = commit("Phase 2.1: correction", {"REVIEW_CHECKLIST.md": "## High\n" + q.format(2) + q.format(3) + q.format(5)
                                          + "## Decisions\n" + q.format(4) + "- 2026-02-02 · a dated decision, not a note\n"
                                          + "## Notes\n" + n0 + n1})
    out = _run(tmp_path, mod.sysop, base, to)
    # Open work: Q1 + n0 = 2 at FROM; Q2, Q3, Q5, Q4 (§ Decisions counts) + n0, n1 = 6 at TO.
    # The dated line under § Decisions is not a note.
    assert "open work   2 -> 6  (delta +4)" in out, out
    assert "closes      2\n" in out, out                       # 2 and 2.1, not three commits
    assert "net open    +2.00 per close" in out, out
    # Scoped: the Phase-1 opener is text, so Phase 2's two items count. FROM has one.
    assert "fixes       1 -> 3  (+2, 1.00 per close)" in out, out
    # +1, -1, +1: the non-phase share is +1, not the 3 a per-commit abs would give, and it is
    # subtracted once: (4 - 1) / 2.
    assert "non-phase   +1 open work from 3 non-phase commits; net open without it +1.50 per close" in out, out
    assert "full phases 1 of the 2 closes (N.M point phases excluded): net open +4.00, fixes 2.00" in out, out


def test_the_consumer_reading_counts_every_pile(tmp_path: Path) -> None:
    """`consumer()` had no test at all; round 2 walked three mutations through it."""
    mod = _net_open()
    commit = _scratch_repo(tmp_path)

    def index(**status):
        rows = "".join(
            "  - id: {i}\n    status: {s}\n    body: open/{i}.md\n".format(i=i, s=s)
            for i, s in status.items())
        return "schema_version: 1\ntasks:\n" + rows

    notes_hdr = "# Notes\n\n## Also fixed (quoted in the ledger header)\n- not a body\n\n"
    base = commit("base", {
        "tasks/index.yml": index(A="open", B="open", H="open", C="deferred", D="in_progress", E="done"),
        "tasks/notes.md": notes_hdr + "- 2026-01-01 · a · n0\n",
        "tasks/open/A.md": "# A\n\n## Also fixed\n- one\n",
    })
    to = commit("later", {
        "tasks/index.yml": index(A="done", B="done", H="deferred", C="deferred", D="in_progress", E="done",
                                 F="open", G="open"),
        "tasks/notes.md": notes_hdr + "- 2026-01-01 · a · n0\n- 2026-01-02 · a · n1\n",
        "tasks/open/A.md": "# A\n\n## Also fixed\n- one\n- two\n",
    })
    out = _run(tmp_path, mod.consumer, str(tmp_path), base, to)
    # FROM: A, B, H open + D + C deferred = 5, + 1 note = 6. TO: F, G + D + C, H deferred = 5,
    # + 2 notes = 7. H moving to deferred is not a close and not a fall.
    assert "open work   6 -> 7  (delta +1)" in out, out
    assert "closes      2\n" in out, out                       # A and B; E was already done
    assert "net open    +0.50 per close" in out, out
    # notes.md is not a body, so its quoted heading counts nowhere.
    assert "fixes       1 -> 2  (+1, 0.50 per close)" in out, out


def test_no_test_in_this_module_carries_a_skip_marker() -> None:
    """A `@pytest.mark.skip` on the pin test disables all of it, and every other test stays green.

    Round 2's S8. The module's legitimate skips are `pytest.skip()` CALLS inside a test,
    for maintainer-side files absent from the public mirror; a marker skips the test on
    every tree, which is never what this module means.
    """
    import ast
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for d in node.decorator_list:
                src = ast.unparse(d)
                if any(k in src for k in ("mark.skip", "mark.xfail", "mark.skipif")):
                    bad.append(f"{node.name}: {src}")
    assert not bad, f"skip/xfail markers in the fix-by-default guards: {bad}"
