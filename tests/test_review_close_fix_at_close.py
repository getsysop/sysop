"""Phase 328 (`Q-459`) — the close fixes Step 2b's non-blocking notes instead of filing them.

Two changes to `/review-close`, and these guards pin both:

* **Step 2b's prompt gains a `NOTES:` block.** Its verdict was binary, so a finding that is
  wrong but does not block had nowhere to go but prose the session happened to notice.
* **Step 4 gains `4a-fix`**, after the merges and before `4a-post`. The session fixes each
  qualifying note in ONE commit on the merge target, one `convention-gate` agent re-checks
  it, and a failed fix is dropped (`git rebase --onto <fix-sha>~1 <fix-sha>`, which binds the
  seeded `git rebase:*` rule) with its notes filed after Step 4c's commit.

**What these guards are, and are not.** The step's decided TEXT is hash-pinned in
`tests/test_fix_in_branch_tier.py` (`PINNED_SPANS`), which catches any rewording or addition,
legitimate or not, and asks the editor to move the pin deliberately. The predicates here pin
STRUCTURE the hash cannot see as meaning: order, scope, which fence says what, which commands
bind which rules, and cross-step pointers. The execution half runs the fences the step ships.
Phase 328's round showed the first version's controls "killed" 11 mutants only because the
mutation stranded a control's anchor. So controls here anchor on short, stable phrases, and
prose checks read comment-stripped, whitespace-folded text (`_live`).
"""
from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

from _prose_guard_helpers import anchor, locate, rewrapped, states, swap

REPO = Path(__file__).resolve().parent.parent
RC = REPO / "core/skills/review-close/SKILL.md"
WORKFLOW = REPO / "core/companion/docs/WORKFLOW.md"
REFERENCE = REPO / "core/skills/review-close/REFERENCE.md"

FIX_HEADING = "### 4a-fix. Fix the Close's Notes"
POST_HEADING = "### 4a-post. Verify the Merged Tree"
RECHECK = "4. **Re-check the fix commit"
VERDICT = "5. **Act on the verdict.**"


def _rc() -> str:
    return RC.read_text(encoding="utf-8")


def _between(text: str, start: str, end: str, what: str) -> str:
    """The span from the ONE occurrence of `start` to the next `end`, whitespace-tolerant.

    Fails closed on a missing, ambiguous or out-of-order anchor, never falling back to
    end-of-file, which would widen the scope to prose from other steps.
    """
    a = locate(text, start)
    b = anchor(end).search(text, a.end())
    assert b is not None, f"could not locate the end of {what}: {end[:60]!r}"
    return text[a.start():b.start()]


def _flat(span: str) -> str:
    return re.sub(r"\s+", " ", span)


def _live(span: str) -> str:
    """What a reader sees: HTML comments removed, whitespace folded."""
    return _flat(re.sub(r"<!--.*?-->", "", span, flags=re.S))


_FENCE = re.compile(r"^[ \t]*```(?:bash|sh)[ \t]*\n(.*?)^[ \t]*```[ \t]*$", re.M | re.S)


def _fences(span: str) -> list[str]:
    return [textwrap.dedent(m.group(1)) for m in _FENCE.finditer(span)]


def _fence_with(span: str, needle: str, what: str) -> str:
    hits = [f for f in _fences(span) if needle in f]
    assert len(hits) == 1, f"expected exactly one shell fence carrying {what}, found {len(hits)}"
    return hits[0]


def _prompt(text: str) -> str:
    return _between(text, "You are the final convention gate before this branch merges",
                    "The ROUTING block is required", "the 2b convention prompt")


def _step2b(text: str) -> str:
    """Step 2b by its heading LINE; the heading's words also occur in prose elsewhere."""
    heads = [m.start() for m in re.finditer(r"(?m)^### 2b\. Prevention Convention Check$", text)]
    assert len(heads) == 1, f"expected one Step 2b heading line, found {len(heads)}"
    end = re.compile(r"(?m)^### 2c\. ").search(text, heads[0])
    assert end is not None, "could not locate the end of Step 2b"
    return text[heads[0]:end.start()]


_SWEEP = re.compile(r"git worktree list --porcelain \| grep -F '/([A-Za-z0-9_-]+?)' \| sed")


def _notes_para(text: str) -> str:
    return _between(_prompt(text), "A note is something wrong", "Be thorough.",
                    "the prompt's NOTES paragraph")


def _fix(text: str) -> str:
    return _between(text, FIX_HEADING, POST_HEADING, "the 4a-fix step")


def _item(text: str, start: str, end: str, what: str) -> str:
    return _between(_fix(text), start, end, what)


def _post(text: str) -> str:
    return _between(text, POST_HEADING, "### 4b. Close Merged Batches", "the 4a-post step")


def _post_arm(text: str) -> str:
    return _between(_post(text), "**If `4a-fix` kept a fix commit",
                    "The inherited-failure arm fires only when", "4a-post item 4's fix arm")


def _lines(fence: str) -> list[str]:
    """Executable lines: blank lines and whole-line comments dropped, trailing comments cut."""
    out = []
    for ln in fence.splitlines():
        s = ln.split(" #", 1)[0].strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


# --------------------------------------------------------------------------------------
# Predicates
# --------------------------------------------------------------------------------------

def notes_channel_problems(text: str) -> list[str]:
    p: list[str] = []
    prompt = _prompt(text)
    notes = re.search(r"^\s*NOTES:\s*$", prompt, re.M)
    blocked = prompt.find("VERDICT: BLOCKED")
    if notes is None:
        p.append("the 2b prompt has no `NOTES:` block, so a non-blocking finding has no channel")
    elif blocked == -1 or notes.start() < blocked:
        p.append("the `NOTES:` block no longer follows the verdict block")
    if "(or `NOTES: none`)" not in _live(prompt):
        p.append("the prompt no longer names `NOTES: none`, so an empty block is ambiguous")
    if not re.search(r"^\s*Then, whatever the verdict:\s*$", prompt, re.M):
        p.append("notes are no longer requested on BOTH verdicts; an APPROVED target's notes vanish")
    para = _live(_notes_para(text))
    if "Not a preference, not a hypothetical" not in para:
        p.append("the prompt no longer says what is not a note, so noise becomes work")
    if "The close fixes, files or drops each one" not in para:
        p.append("the prompt no longer tells the reviewer every note is acted on")
    item4 = _live(_between(text, "4. Collect all verdicts", "5. **Record outcomes for Step 8.**",
                           "Step 2b item 4"))
    if "Collect all verdicts **and every `NOTES:` line**, **from both fleets**" not in item4:
        p.append("Step 2b item 4 no longer collects the NOTES lines from both fleets")
    if not states(item4, "Step 4 `4a-fix` acts on them once the approved branches have merged, "
                         "and a note on a target that does not merge this run is reported, not acted on."):
        p.append("Step 2b item 4 no longer routes the notes to 4a-fix after the merges")
    twin = _live(_between(text, "The prompt is step 3's, with four substitutions",
                          "Everything else is carried verbatim", "the twin's substitutions"))
    if "NOTES" in twin:
        p.append("the security twin's substitutions now touch the NOTES block")
    return p


def order_problems(text: str) -> list[str]:
    p: list[str] = []
    heads = [m.group(0) for m in re.finditer(r"^### 4a[^\n]*", text, re.M)]
    want = ["### 4a. Merge Approved Feature Branches", FIX_HEADING, POST_HEADING]
    if heads != want:
        p.append("4a-fix must sit between the merges and 4a-post")
    step4a = _live(_between(text, "### 4a. Merge Approved Feature Branches",
                            "For each approved feature branch (oldest first)", "Step 4a's lead"))
    if "go straight to **`4a-fix`**, then **`4a-post`**" not in step4a:
        p.append("Step 4a's PR-reuse pointer skips 4a-fix, so that shape never fixes a note")
    return p


def scope_problems(text: str) -> list[str]:
    p: list[str] = []
    fix = _fix(text)
    live = _live(fix)
    if "**Runs after the merges and before `4a-post`, on the merge target**" not in live:
        p.append("4a-fix's lead no longer places it after the merges on the merge target")
    here = _lines(_fence_with(fix, "git diff --name-only", "4a-fix's merged-diff command"))
    there = _lines(_fence_with(_post(text), "git diff --name-only", "4a-post item 2's command"))
    if here != there:
        p.append("4a-fix's merged-diff command is not 4a-post item 2's; the two scopes can drift")
    if not any("origin/<default branch>...HEAD" in ln for ln in here):
        p.append("the merged-diff command is not three-dot, so it counts upstream work as the close's")
    if not states(live, "`NO_ORIGIN_MAIN` means no note qualifies: file them all;"):
        p.append("an uncomputable merged diff no longer fails closed to filing")
    if "1. **Set aside the notes on a target that did not merge** — rejected, SKIP or 4a-SKIP." not in live:
        p.append("notes on a target that did not merge are no longer all set aside")
    raw = _between(fix, "**Fix it here**", "**File a task**", "the fix-here bullet")
    conds = _between(raw, "**Fix it here**", "Read the code before", "the fix-here conditions")
    subs = re.findall(r"(?m)^ {5}[-*+] ", conds)
    if len(subs) != 4:
        p.append(f"the fix-here bullet carries {len(subs)} conditions, not four")
    bullet = _live(raw)
    for need, why in (
        ("only when all", "the conditions are no longer conjunctive"),
        ("every file the fix edits is in this close's merged diff",
         "the fix is no longer bounded to the merged diff"),
        ("apart from the test that pins a behaviour fix",
         "a behaviour fix's new test is outside the diff and so blocks every behaviour fix"),
        ("it is not a migration, a production write, or auth or payment logic;",
         "the never-list clause is gone or no longer excludes all three"),
        ("no file it edits matches a glob in `.claude/security_map.md` or "
         "`.claude/security_map.project.md`;",
         "the security-map exclusion is gone or lost one of its two maps"),
        ("a fix that changes behaviour adds the test that pins it, in the same commit.",
         "a behaviour fix no longer carries its pinning test"),
    ):
        if need not in bullet:
            p.append(why)
    filing = _live(_between(fix, "**File a task**", "**Drop it**", "the file bullet"))
    if "it came from the security twin" not in filing:
        p.append("a security-twin note may now be fixed with only the convention lens re-checking it")
    if not states(live, "A never-list note is filed whatever the answer"):
        p.append("a never-list note may now be fixed at close on an answer the close cannot record")
    return p


def commit_problems(text: str) -> list[str]:
    p: list[str] = []
    if "**Apply the branch-guard HARD RULE's Rule A assert before each commit below**" not in _live(_fix(text)):
        p.append("4a-fix's commits no longer carry the Rule A branch assert")
    item3 = _item(text, "3. **Make", RECHECK, "item 3")
    live = _live(item3)
    if "3. **Make every fix in ONE commit, and print its SHA.**" not in live:
        p.append("the fixes are no longer one commit, so one drop no longer undoes them")
    if not re.search(r"Skip items 3[–-]5 when nothing qualified\.", live):
        p.append("the skip range no longer stops at the verdict; filing must still run")
    if not states(live, "It is a literal, because no variable survives to the next block."):
        p.append("the SHA is no longer carried as a written-out literal")
    lines = _lines(_fence_with(item3, "git commit", "the fix commit"))
    commit = [i for i, ln in enumerate(lines) if ln.startswith("git commit")]
    rev = [i for i, ln in enumerate(lines) if ln == "git rev-parse HEAD"]
    if not commit or not lines[commit[0]].startswith('git commit -m "docs:'):
        p.append("the fix commit's message no longer starts `docs:`, the only seeded commit rule")
    if commit and lines[commit[0]].count(" -m ") != 1:
        p.append("the fix commit carries a message body: note text in a shell string runs its backticks")
    if len(rev) != 1 or not commit or rev[0] < commit[0]:
        p.append("the SHA printed is not the fix commit's: `git rev-parse HEAD` must follow the commit")
    return p


def recheck_problems(text: str) -> list[str]:
    p: list[str] = []
    item4 = _item(text, RECHECK, VERDICT, "item 4")
    live = _live(item4)
    place = _fence_with(item4, "git worktree add", "the re-check placement")
    pin = re.search(r"^(\w+)=([\"']?)<fix-sha>\2\s*$", place, re.M)
    dirv = re.search(r"^(\w+)=\$\(mktemp -d", place, re.M)
    add = re.search(r'^git worktree add --detach "\$\{?(\w+)\}?" "\$\{?(\w+)\}?"\s*$', place, re.M)
    if pin is None:
        p.append("the re-check's pin is not the fix commit")
    if add is None or pin is None or dirv is None or add.groups() != (dirv.group(1), pin.group(1)):
        p.append("the checkout is not created at the fix commit in the temp directory made for it")
    if "git rev-parse --show-toplevel" not in place:
        p.append("nothing verifies the re-check's checkout is outside the repository")
    made = re.search(r'mktemp -d "\$\{TMPDIR:-/tmp\}/([A-Za-z0-9_-]+?)X{3,}"', place)
    swept = _SWEEP.search(_step2b(text))
    if not made or not swept or not made.group(1).startswith(swept.group(1)):
        p.append("the re-check's temp prefix is not one Step 2b's removal loop sweeps")
    base = live.find("First re-run Step 2b step 2's three baseline lines, verbatim")
    if base == -1 or base > live.find("Then spawn an Agent with:"):
        p.append("the baselines are not re-captured BEFORE the re-check spawns")
    if "<!-- sysop:role=convention-gate -->" not in _flat(item4):
        p.append("the re-check is not on the convention-gate role")
    if not re.search(r'[-*+] `isolation: "worktree"` [-*+] `description:', live):
        p.append("the re-check lost its isolation bullet")
    if "Step 2b step 3's prompt, with these substitutions and nothing else changed:" not in live:
        p.append("the re-check prompt may now drop parts of Step 2b's (its echo, its rules)")
    if not states(live, "The re-check raises no notes, so fixing at close is one pass."):
        p.append("the re-check may raise notes, which makes fixing at close a loop")
    if not states(live, "`## Project conventions` is what Step 2b sent: the same paste, or the "
                        "same `sysop/runtime/2b-conventions.md`."):
        p.append("the re-check no longer routes against the conventions Step 2b sent")
    if "Spawn no security twin." not in live:
        p.append("the re-check may now spawn a security twin the scope rule made unnecessary")
    if "After the verdict, apply Step 2b's HARD RULE: the removal loop, then the five-command assertion." not in live:
        p.append("nothing removes the re-check's checkout or asserts the tree after it")
    return p


_DROP = [r"git rev-parse HEAD", r"git rebase --onto ([\"']?)<fix-sha>~1\1 ([\"']?)<fix-sha>\2"]
_DROP_GATE = "Only when that printed `<fix-sha>`, drop it:"


def verdict_problems(text: str) -> list[str]:
    p: list[str] = []
    item5 = _item(text, VERDICT, "6. **File the notes", "item 5")
    fences = _fences(item5)
    # Two calls, not one: in a single fence the check prints and the drop runs regardless, so
    # the check gates nothing (round 2 dropped a rebased fix and replayed upstream work that way).
    if len(fences) != 2:
        p.append(f"item 5 carries {len(fences)} shell fences, not two; the check must be its own call")
    elif [_lines(f) for f in fences] and not (
            len(_lines(fences[0])) == 1 and re.fullmatch(_DROP[0], _lines(fences[0])[0])
            and len(_lines(fences[1])) == 1 and re.fullmatch(_DROP[1], _lines(fences[1])[0])):
        p.append("item 5's fences are no longer the HEAD check, then the drop of `<fix-sha>`")
    live = _live(item5)
    gate = live.find(_DROP_GATE)
    if gate == -1 or not (live.find("git rev-parse HEAD") < gate < live.find("git rebase --onto")):
        p.append("the drop is no longer gated on the check's output, between the two calls")
    for need, why in (
        ("`APPROVED` keeps the commit.", "something other than APPROVED may now keep the fix"),
        ("`BLOCKED`, a mismatched echo, or no verdict at all drops the whole commit, and every "
         "note it carried goes to item 6.", "a failure shape no longer drops the fix and files its notes"),
        ("If the check printed anything else, or the drop fails, stop: report that the fix commit is "
         "still on the merge target, with the re-check's verdict.",
         "a drop that cannot run has no disposition"),
        ("Do not amend the fix and re-check again.", "a blocked fix may be amended and looped"),
    ):
        if not states(live, need):
            p.append(why)
    return p


def post_failure_problems(text: str) -> list[str]:
    p: list[str] = []
    arm = _live(_post_arm(text))
    for need, why in (
        ("**If `4a-fix` kept a fix commit, test it before anything below**",
         "4a-post item 4 no longer tests a kept fix commit before its other arms"),
        ("on this step's first run only, while `HEAD` is still `<fix-sha>` and "
         "`git diff --quiet HEAD --` succeeds",
         "the arm may now drop a fix that is not HEAD, or over a dirty tree"),
        ("Drop it with `4a-fix` item 5's check and drop, route its notes to item 6's filing, and re-run "
         "this step once from item 1.", "the arm no longer drops, files and re-runs"),
        ("Still failing means the fix was not the failure: restore it with `git cherry-pick <fix-sha>`, "
         "take its notes back from item 6", "an innocent fix is discarded and its notes lost"),
        ("Green now means the fix was the failure", "the arm no longer says what a green re-run means"),
    ):
        if need not in arm:
            p.append(why)
    return p


def filing_problems(text: str) -> list[str]:
    p: list[str] = []
    item6 = _item(text, "6. **File the notes", "7. **Record for Step 8**", "item 6")
    live = _live(item6)
    if "6. **File the notes routed to a task at the start of Step 4d, in one further commit.**" not in live:
        p.append("filing no longer waits for Step 4d, after Step 4c's status flip")
    lines = _lines(_fence_with(item6, "git commit", "the filing commit"))
    v = [i for i, ln in enumerate(lines) if "validate_tasks.py" in ln]
    c = [i for i, ln in enumerate(lines) if ln.startswith("git commit")]
    if not v or not c or v[0] > c[0]:
        p.append("the validator no longer runs before the filing commit")
    if c and not lines[c[0]].startswith('git commit -m "docs:'):
        p.append("the filing commit's message no longer starts `docs:`, the only seeded commit rule")
    if not states(live, "Never commit on a red validator: fix the data and re-run."):
        p.append("a red validator no longer stops the filing commit")
    if "(`[]` for a review-batch branch or the unpushed-main group)" not in live:
        p.append("filed notes no longer say what `surfaced_by:` is for a target with no claimed task")
    lead4d = _live(_between(text, "### 4d. Land on `main`", "#### `direct` policy", "Step 4d's lead"))
    if not lead4d.startswith("### 4d. Land on `main` **First, file the notes `4a-fix` routed to a task**"):
        p.append("Step 4d no longer opens by filing the routed notes; a close whose 4c made no commit "
                 "would never file them")
    return p


def report_problems(text: str) -> list[str]:
    fence = re.sub(r"<!--.*?-->", "", _between(text, "Review Complete.\n", "Documentation written:",
                                               "Step 8's template"), flags=re.S)
    if not re.search(r"^Close notes: ", fence, re.M):
        return ["Step 8 has no `Close notes:` line, so the close's fixes and filings are invisible"]
    if "re-check <APPROVED | BLOCKED — dropped | not run: nothing fixed>" not in fence:
        return ["Step 8 no longer reports the re-check's outcome"]
    live = _flat(fence)
    return [f"Step 8's `Close notes:` line lost {w!r}" for w in (
        "N filed (<ids>)", "N not acted on (target did not merge)",
        "`dropped after 4a-post failed`", "A note listed for the human to file is not filed: say so.")
        if w not in live]


# A licence added BESIDE an intact rule: the rule still reads true and a new sentence carves an
# exception out of it. None of these words appears in the screened text today. The limit,
# stated: a licence phrased without this vocabulary passes, and the hash pins over the same
# text in `test_fix_in_branch_tier.py` are what catch it. Same shape as
# `test_reviewer_placement.py`'s `_PLACEMENT_LICENCES`.
_LICENCES = (
    r"\bwaiv", r"\bunless\b", r"\bexcept\b", r"does not apply", r"need not\b", r"not needed",
    r"may (?:be )?(?:skip|kept|keep)", r"\bkeep\b", r"\boptional", r"\bdiscretion", r"\bexempt",
    r"not required", r"\badvisory\b", r"\banyway\b", r"in practice",
)


def licence_problems(text: str) -> list[str]:
    span = " ".join((_live(_fix(text)), _live(_post_arm(text)), _live(_notes_para(text))))
    return [f"a licence was added beside the 4a-fix rules: {pat!r}"
            for pat in _LICENCES if re.search(pat, span, re.I)]


PREDICATES = {
    "notes": notes_channel_problems,
    "order": order_problems,
    "scope": scope_problems,
    "commit": commit_problems,
    "recheck": recheck_problems,
    "verdict": verdict_problems,
    "post": post_failure_problems,
    "filing": filing_problems,
    "report": report_problems,
    "licence": licence_problems,
}


@pytest.mark.parametrize("name", sorted(PREDICATES))
def test_the_shipped_skill_satisfies(name: str) -> None:
    assert PREDICATES[name](_rc()) == []


def _scoped(start: str, end: str, old: str, new: str):
    """A mutation applied inside one slice only, for text that recurs elsewhere in the file:
    4a-fix's merged-diff fence is 4a-post's verbatim, and the validator line recurs in 4c."""
    def mutate(text: str) -> str:
        a = locate(text, start).start()
        b = anchor(end).search(text, a).start()
        span = text[a:b]
        assert span.count(old) == 1, f"scoped anchor not unique in its slice: {old[:60]!r}"
        return text[:a] + span.replace(old, new) + text[b:]
    return mutate


# One control per check, each changing only what that check reads. An optional fourth field is
# `swap()`'s `after=`. Anchors are short on purpose: a long anchor is stranded by any nearby
# edit, and a stranded anchor reddens the suite for a reason unrelated to the rule.
CONTROLS = [
    ("notes", "     NOTES:\n     - <file>:<line>", "     - <file>:<line>"),
    ("notes", "(or `NOTES: none`)", "(or nothing)"),
    ("notes", "     Then, whatever the verdict:", "     Then, when approved:"),
    ("notes", "Not a preference, not a hypothetical,", "A preference or a hypothetical,"),
    ("notes", "The close fixes, files or drops", "The close may read"),
    ("notes", "**and every `NOTES:` line**, **from both fleets**", "**and every `NOTES:` line**, **from the convention fleet**"),
    ("notes", "Step 4 `4a-fix` acts on them once", "Step 3 acts on them before"),
    ("notes", "   - the violation line becomes", "   - the `NOTES:` block is dropped.\n   - the violation line becomes"),
    ("notes", "     VERDICT: APPROVED\n", "     NOTES:\n     VERDICT: APPROVED\n"),
    ("order", FIX_HEADING + "\n", "### 4b-fix. Fix the Close's Notes\n"),
    ("order", "go straight to **`4a-fix`**, then **`4a-post`**", "go straight to **`4a-post`**"),
    ("order", FIX_HEADING + "\n", "### 4a-note. Routing\n\nGo from the merges directly to `4a-post`.\n\n" + FIX_HEADING + "\n"),
    ("scope", "**Runs after the merges and before `4a-post`, on the merge target**",
     "**Runs before the merges, on each feature branch**"),
    ("scope", _scoped(FIX_HEADING, POST_HEADING, "origin/<default branch>...HEAD", "origin/<default branch>..HEAD")),
    ("scope", _scoped(FIX_HEADING, POST_HEADING, '|| echo "NO_ORIGIN_MAIN"', '|| echo "NO_ORIGIN"')),
    ("scope", "means no note qualifies: file them all;", "means every note qualifies;"),
    ("scope", "It is not the case that", "It is not the case that"),  # placeholder, replaced below
    ("scope", "rejected, SKIP or 4a-SKIP.", "rejected or SKIP."),
    ("scope", "it is not a migration,", "it is a migration,"),
    ("scope", "no file it edits matches a glob", "a file it edits matches a glob"),
    ("scope", "     - a fix that changes behaviour adds the test that pins it, in the same commit.\n",
     "     - a fix that changes behaviour adds the test that pins it, in the same commit.\n     - or the session judges it safe.\n"),
    ("scope", "only when all four hold:", "when any of these hold:"),
    ("scope", "is in this close's merged diff", "is in the repository"),
    ("scope", " — apart from the test that pins a behaviour fix:", ":"),
    ("scope", "it came from the security twin, ", ""),
    ("scope", "A never-list note is filed whatever the answer", "A never-list note is fixed on the answer"),
    ("commit", "**Apply the branch-guard HARD RULE's Rule A assert before each commit below**",
     "**Commit below as usual**"),
    ("commit", "ONE commit, and print its SHA.**", "a commit of its own, and print each SHA.**"),
    ("commit", "Skip items 3–5 when", "Skip items 3–6 when"),
    ("commit", "It is a literal, because", "It may be a variable, because"),
    ("commit", 'git commit -m "docs: review-close fix at close', 'git commit -m "review-close: fix at close'),
    ("commit", "   git add -- <each file the fixes edited>\n", "   git rev-parse HEAD\n   git add -- <each file the fixes edited>\n"),
    ("commit", _scoped("3. **Make", RECHECK,
                       "   git commit -m \"docs: review-close fix at close — <N> note(s)\"\n   git rev-parse HEAD\n",
                       "   git rev-parse HEAD\n   git commit -m \"docs: review-close fix at close — <N> note(s)\"\n")),
    ("commit", 'fix at close — <N> note(s)"\n', 'fix at close — <N> note(s)" -m "<the notes>"\n', "3. **Make"),
    ("recheck", "PIN=", "PIN=$(git rev-parse HEAD~1) # ", RECHECK),
    ("recheck", 'git worktree add --detach "$PINNED" "$PIN"', 'git worktree add --detach "$PINNED" HEAD', RECHECK),
    ("recheck", '"${TMPDIR:-/tmp}/sysop-2b-XXXXXX")', '"${TMPDIR:-/tmp}/sysop-fix-XXXXXX")', RECHECK),
    ("recheck", 'case "$(git -C "$PINNED" rev-parse --show-toplevel 2>/dev/null)" in "$(git rev-parse --show-toplevel)")',
     'case "$(git -C "$PINNED" rev-parse --show-toplevel 2>/dev/null)" in /nowhere)', RECHECK),
    ("recheck", "First re-run Step 2b step 2's", "Later re-run Step 2b step 2's"),
    ("recheck", _scoped(RECHECK, VERDICT, 'git worktree add --detach "$PINNED" "$PIN"', 'git worktree add --detach "$PIN" "$PINNED"')),
    ("recheck", lambda t: _scoped(RECHECK, VERDICT,
                        "After the verdict, apply Step 2b's HARD RULE: the removal loop, then the five-command assertion.",
                        "After the verdict, apply Step 2b's HARD RULE: the removal loop, then the five-command assertion. "
                        "First re-run Step 2b step 2's three baseline lines, verbatim.")(
        _scoped(RECHECK, VERDICT, "First re-run Step 2b step 2's three baseline lines, verbatim: ", "")(t))),
    ("recheck", " <!-- sysop:role=convention-gate -->", "", RECHECK),
    ("recheck", '   - `isolation: "worktree"`\n', "", RECHECK),
    ("recheck", "with these substitutions and nothing else changed:", "without its `## Where you are` block:"),
    ("recheck", "The re-check raises no notes,", "The re-check may raise notes; fix those too,"),
    ("recheck", "is what Step 2b sent:", "is the pinned checkout's `CLAUDE.md`, not what Step 2b sent:"),
    ("recheck", "Spawn no security twin.", "Spawn a security twin."),
    ("recheck", "apply Step 2b's HARD RULE: the removal loop,", "continue; the removal loop is optional,"),
    ("verdict", "   git rebase --onto <fix-sha>~1 <fix-sha>\n", "   git reset --hard <fix-sha>~1\n", VERDICT),
    ("verdict", "   git rev-parse HEAD\n   ```\n", "   git rev-parse HEAD\n   git rebase --onto <fix-sha>~1 <fix-sha>\n   ```\n", VERDICT),
    ("verdict", "   The commit is unpushed and is `HEAD`", "   ```bash\n   git reset --hard HEAD~1\n   ```\n\n   The commit is unpushed and is `HEAD`"),
    ("verdict", "`APPROVED` keeps the commit.", "`APPROVED` or a mismatched echo keeps the commit."),
    ("verdict", "`BLOCKED`, a mismatched echo, or no verdict at all drops", "`BLOCKED` drops"),
    ("verdict", "Only when that printed `<fix-sha>`, drop it:", "Then drop it:"),
    ("verdict", "If the check printed anything else, or the drop fails, stop:", "If the drop fails, carry on:"),
    ("verdict", "   git rebase --onto <fix-sha>~1 <fix-sha>\n", "   git rebase --onto <fix-sha>~1 <fix-sha>\n   git status\n", VERDICT),
    ("verdict", "Do not amend the fix and re-check again.", "Amend the fix and re-check again."),
    ("post", "test it before anything below**", "note it**"),
    ("post", "on this step's first run only, while", "on any run, even when"),
    ("post", "route its notes to item 6's filing,", "drop its notes,"),
    ("post", "Green now means the fix was the failure", "Green now means nothing"),
    ("post", "restore it with `git cherry-pick <fix-sha>`, take its notes back from item 6,", "leave it dropped,"),
    ("filing", "at the start of Step 4d, in one further commit.**", "now, in one further commit.**"),
    ("filing", _scoped("6. **File the notes", "7. **Record for Step 8**", "   python3 sysop/scripts/validate_tasks.py\n", "")),
    ("filing", 'git commit -m "docs: review-close file close notes', 'git commit -m "review-close: file close notes'),
    ("filing", "Never commit on a red validator: fix the data and re-run.", "A red validator is advisory."),
    ("filing", "(`[]` for a review-batch branch or the unpushed-main group)", "(`[]` for a review-batch branch)"),
    ("filing", "**First, file the notes `4a-fix` routed to a task**", "**Where useful, file the notes `4a-fix` routed to a task**"),
    ("filing", _scoped("6. **File the notes", "7. **Record for Step 8**",
                       "   python3 sysop/scripts/validate_tasks.py\n   git add -- tasks/index.yml <each other file those steps wrote>\n   git commit",
                       "   git add -- tasks/index.yml <each other file those steps wrote>\n   git commit")),
    ("report", "Close notes:   <N collected", "Notes seen:    <N collected"),
    ("report", "re-check <APPROVED | BLOCKED — dropped | not run: nothing fixed>", "re-check <APPROVED>"),
    ("report", "Close notes:   <N collected", "<!-- Close notes: --> <N collected"),
    ("report", "N filed (<ids>), ", ""),
    ("report", "A note listed for the human to file is not filed: say so.", "Unfiled notes need no mention."),
]
# The negation arm of `states()`: the pinned phrase kept, the sentence asserting its opposite.
CONTROLS[CONTROLS.index(("scope", "It is not the case that", "It is not the case that"))] = (
    "scope", "`NO_ORIGIN_MAIN` means no note qualifies: file them all;",
    "It is not the case that `NO_ORIGIN_MAIN` means no note qualifies: file them all;")
# One per licence pattern, planted in item 5 where the drop rule lives.
_LICENCE_WORDS = ("waived", "unless", "except", "does not apply", "need not", "not needed",
                  "may be skipped", "keep", "optional", "discretion", "exempt", "not required",
                  "advisory", "anyway", "in practice")
assert len(_LICENCE_WORDS) == len(_LICENCES)
CONTROLS += [("licence", "Do not amend the fix and re-check again.",
              f"Do not amend the fix and re-check again. A doc fix is {w} here.")
             for w in _LICENCE_WORDS]
CONTROLS += [("licence", "and re-run this step once from item 1.",
              "and re-run this step once from item 1, unless the failure looks unrelated.")]


def _apply(control: tuple) -> str:
    if callable(control[1]):
        return control[1](_rc())
    _arm, old, new, *after = control
    return swap(_rc(), old, new, after=after[0] if after else None)


@pytest.mark.parametrize("control", CONTROLS, ids=[f"{c[0]}-{i}" for i, c in enumerate(CONTROLS)])
def test_each_control_reddens_its_own_arm(control: tuple) -> None:
    mutated = _apply(control)
    assert mutated != _rc()
    assert PREDICATES[control[0]](mutated), f"the {control[0]} predicate did not see {control!r}"[:300]


def test_every_licence_pattern_has_a_control() -> None:
    planted = [c[2] for c in CONTROLS if c[0] == "licence" and not callable(c[1])]
    for pat in _LICENCES:
        assert any(re.search(pat, s, re.I) for s in planted), f"no control exercises {pat!r}"


def test_every_arm_has_a_control() -> None:
    assert {c[0] for c in CONTROLS} == set(PREDICATES)


# Legal rewrites that must NOT redden. Regex substitutions from whatever form the file holds,
# each required to match exactly once, so a file already in the other form is not stranded.
LEGAL = [
    (r"(?m)^(\s*PIN=)([\"']?)<fix-sha>\2$", r'\1"<fix-sha>"'),
    (r"(?m)^(\s*PIN=)([\"']?)<fix-sha>\2$", r"\1'<fix-sha>'"),
    (r'(?m)^(\s*git worktree add --detach )"\$PINNED" "\$PIN"$(?=\n\s*```\n\n\s*Then spawn an Agent with:\n\s*- `subagent_type: "general-purpose"`\n\s*- `model: "opus"` \(the \*\*convention-gate\*\* role, as)', r'\1"${PINNED}" "${PIN}"'),
    (r"(?m)^(\s*git rebase --onto )<fix-sha>~1 <fix-sha>$", r'\1"<fix-sha>~1" "<fix-sha>"'),
    (r"only when all (?:four|of these) hold:", "only when all of these hold:"),
    (r"(?m)^( {5})[-*+] (it is not a migration)", r"\1* \2"),
    (r"(?m)^(   )[-*+] (\*\*Fix it here\*\*)", r"\1* \2"),
    (r'mktemp -d "\$\{TMPDIR:-/tmp\}/sysop-2b-XXXXXX"\)\n(   case)', r'mktemp -d "${TMPDIR:-/tmp}/sysop-2b-fix-XXXXXX")\n\1'),
    (r"(?m)^(\s*git rev-parse HEAD)$(?=\n\s*```\n\n\s*Write the printed SHA)", r"\1  # the fix SHA"),
    (r"Skip items 3–5 when", "Skip items 3-5 when"),
    (r"```bash\n(   git rebase --onto)", r"```sh\n\1"),
]


def _legal(pattern: str, repl: str) -> str:
    mutated, n = re.subn(pattern, repl, _rc())
    assert n == 1, f"the legal rewrite's pattern matched {n} sites, not one: {pattern}"
    return mutated


@pytest.mark.parametrize("pattern,repl", LEGAL, ids=[f"legal-{i}" for i in range(len(LEGAL))])
def test_a_legal_rewrite_stays_green(pattern: str, repl: str) -> None:
    mutated = _legal(pattern, repl)
    failures = {n: f(mutated) for n, f in PREDICATES.items() if f(mutated)}
    assert not failures, failures


def test_a_legal_rewrite_that_matches_nothing_is_refused() -> None:
    with pytest.raises(AssertionError, match="matched 0 sites"):
        _legal(r"no such text anywhere in the skill", "x")


def test_a_legal_rewrite_that_matches_twice_is_refused() -> None:
    with pytest.raises(AssertionError, match="matched 2 sites"):
        _legal(r"### 4a-fix\. Fix the Close's Notes|### 4a-post\. Verify the Merged Tree", "x")


def test_a_scoped_mutation_refuses_an_ambiguous_anchor() -> None:
    with pytest.raises(AssertionError, match="not unique in its slice"):
        _scoped(FIX_HEADING, POST_HEADING, "<fix-sha>", "x")(_rc())


def test_the_slicer_fails_closed_on_a_missing_end() -> None:
    with pytest.raises(AssertionError, match="could not locate the end"):
        _between(_rc(), FIX_HEADING, "an end anchor that is nowhere", "a probe")


def test_a_rendering_identical_rewrap_stays_green() -> None:
    """Every paragraph and list body re-wrapped at width 1 renders identically (`Q-495`)."""
    wrapped = rewrapped(_rc())
    assert wrapped != _rc()
    failures = {n: f(wrapped) for n, f in PREDICATES.items() if f(wrapped)}
    assert not failures, failures


def test_workflow_lists_the_step_between_merge_and_merged_tree_pass() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    a = text.find("\n5a. **Fix the close's notes** (`4a-fix`")
    b = text.find("\n5b. **Run verification — the merged-tree pass**")
    assert a != -1 and b != -1 and a < b
    line = _live(text[a:b])
    assert "after the merges" in line and "drops the commit" in line and "at the start of Step 4d" in line


def test_the_role_docs_name_the_second_convention_gate_spawn() -> None:
    """Round 2 reverted each of these to "and nothing else" / "alone" / "only" with every guard
    green. `served_models.yml` is what a consumer reads before overriding the role."""
    served = _flat((REPO / "core/companion/.claude/served_models.yml").read_text(encoding="utf-8"))
    assert "and the Step 4 `4a-fix` # re-check of the close's own fix commit" in served
    wf = _flat(WORKFLOW.read_text(encoding="utf-8"))
    assert "`/review-close` Step 2b's convention agent and its `4a-fix` re-check, nothing else;" in wf
    conf = (REPO / "docs/configuration.md").read_text(encoding="utf-8")
    assert "convention-gate: sonnet   # the 2b convention agent and the 4a-fix re-check" in conf
    assert "`convention-gate` governs two spawns" in conf


def test_the_rationale_lives_in_the_reference() -> None:
    assert "See `REFERENCE.md` § *Step 4a-fix — provenance*." in _fix(_rc())
    assert "\n## Step 4a-fix — provenance\n" in REFERENCE.read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------
# Execution: run the fences the step ships, in a throwaway repository with a local remote.
# --------------------------------------------------------------------------------------

_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def _env(tmpdir: Path | None = None) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(_ENV)
    if tmpdir is not None:
        env["TMPDIR"] = str(tmpdir)
    return env


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, env=_env(), capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout.strip()


def _bash(cwd: Path, script: str, tmpdir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["/bin/bash", "-c", script], cwd=cwd, env=_env(tmpdir),
                          capture_output=True, text=True)


@pytest.fixture()
def closing_repo(tmp_path: Path):
    """A merge target one feature merge past its base, while `origin/main` has moved on.

    `origin/main` carries a commit the merge target does not, so a two-dot diff reports it and
    a three-dot diff does not. Without that commit the two forms agree and the scope test
    cannot tell them apart (the round's two-dot survivor).
    """
    origin, work, tmpdir = tmp_path / "origin.git", tmp_path / "work", tmp_path / "tmp"
    tmpdir.mkdir()
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(tmp_path, "init", "-q", "-b", "main", str(work))
    (work / "doc.md").write_text("see old/path.md\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "base")
    _git(work, "remote", "add", "origin", str(origin))
    (work / "upstream.md").write_text("landed upstream after the branch was cut\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "upstream only")
    _git(work, "push", "-q", "origin", "main")
    _git(work, "checkout", "-q", "-b", "merge/review-close-t", "HEAD~1")
    (work / "feature.md").write_text("new\n")
    (work / "doc.md").write_text("see old/path.md\nmore\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "merged feature")
    return work, tmpdir, _git(work, "rev-parse", "HEAD")


def _commit_fence() -> str:
    return _fence_with(_item(_rc(), "3. **Make", RECHECK, "item 3"), "git commit", "the fix commit")


def _make_fix(work: Path, tmpdir: Path) -> str:
    """Run the shipped commit fence over a real fix; return the SHA it printed."""
    (work / "doc.md").write_text("see new/path.md\nmore\n")
    script = (_commit_fence()
              .replace("<each file the fixes edited>", "doc.md")
              .replace("<N>", "1"))
    r = _bash(work, script, tmpdir)
    assert r.returncode == 0, r.stderr + r.stdout
    return r.stdout.strip().splitlines()[-1]


def test_the_merged_diff_command_is_three_dot_over_the_close(closing_repo) -> None:
    work, tmpdir, _ = closing_repo
    fence = _fence_with(_fix(_rc()), "git diff --name-only", "the merged-diff command")
    r = _bash(work, fence.replace("<default branch>", "main"), tmpdir)
    assert r.returncode == 0, r.stderr
    assert set(r.stdout.split()) == {"doc.md", "feature.md"}, r.stdout


def test_the_merged_diff_command_fails_closed_without_origin(closing_repo) -> None:
    work, tmpdir, _ = closing_repo
    _git(work, "remote", "remove", "origin")
    fence = _fence_with(_fix(_rc()), "git diff --name-only", "the merged-diff command")
    r = _bash(work, fence.replace("<default branch>", "main"), tmpdir)
    assert r.stdout.strip() == "NO_ORIGIN_MAIN", r.stdout


def test_the_commit_fence_prints_the_fix_commit(closing_repo) -> None:
    work, tmpdir, pre = closing_repo
    printed = _make_fix(work, tmpdir)
    assert printed == _git(work, "rev-parse", "HEAD") != pre
    assert _git(work, "log", "-1", "--format=%s").startswith("docs: review-close fix at close")


def test_the_placement_lands_on_the_fix_and_the_2b_sweep_removes_it(closing_repo) -> None:
    work, tmpdir, _ = closing_repo
    fix_sha = _make_fix(work, tmpdir)
    text = _rc()
    place = _fence_with(_item(text, RECHECK, VERDICT, "item 4"), "git worktree add", "the placement")
    r = _bash(work, place.replace("<fix-sha>", fix_sha), tmpdir)
    assert r.returncode == 0, r.stderr + r.stdout
    listed = _git(work, "worktree", "list", "--porcelain")
    pinned = [l.split(" ", 1)[1] for l in listed.splitlines()
              if l.startswith("worktree ") and "/sysop-2b-" in l]
    assert len(pinned) == 1, listed
    assert _git(Path(pinned[0]), "rev-parse", "HEAD") == fix_sha
    assert not Path(pinned[0]).resolve().is_relative_to(work.resolve())
    quoted = _step2b(text)
    sweep = _fence_with("\n".join(l[2:] if l.startswith("> ") else l.lstrip(">")
                                  for l in quoted.splitlines()),
                        "git worktree remove", "Step 2b's removal loop")
    r = _bash(work, sweep, tmpdir)
    assert r.returncode == 0, r.stderr
    assert "/sysop-2b-" not in _git(work, "worktree", "list", "--porcelain")


def test_the_drop_restores_the_merged_tree_and_leaves_no_trace(closing_repo) -> None:
    work, tmpdir, pre = closing_repo
    fix_sha = _make_fix(work, tmpdir)
    check, drop = _fences(_item(_rc(), VERDICT, "6. **File the notes", "item 5"))
    r = _bash(work, check, tmpdir)
    assert r.returncode == 0 and r.stdout.strip() == fix_sha, "the HEAD check did not print the fix"
    r = _bash(work, drop.replace("<fix-sha>", fix_sha), tmpdir)
    assert r.returncode == 0, r.stderr
    assert _git(work, "rev-parse", "HEAD") == pre
    assert _git(work, "rev-parse", "--abbrev-ref", "HEAD") == "merge/review-close-t"
    assert subprocess.run(["git", "merge-base", "--is-ancestor", fix_sha, "HEAD"],
                          cwd=work, env=_env()).returncode == 1, "the fix is still in history"
