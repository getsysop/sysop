"""Phase 170 — `/review-close`'s verification gate runs on the tree that merges.

The defect (upstream #242): Step 3 ran the project's build/test/lint commands while `HEAD`
was still `main` and before Step 3b removed a worktree or Step 4a merged anything, so no
approved branch's files were in the tree and its new tests did not exist. Under `pr` policy
it was worse — Step 4-pre cuts the integration branch from *fresh* `origin/<default branch>`, so Step 3's
tree was not even the base. And the `### Ratchet` snippets a consumer authors filter
`git diff --name-only origin/<default branch>...HEAD` themselves, which on a synced `main` is the empty
set: the pass reported green having executed nothing.

The fix keeps Step 3 as a declared **pre-merge** pass and adds `4a-post`, which re-runs the
same resolved list on the **merge target** — placed after 4a but before 4b/4c, because Step 4c
deletes each `sysop/runtime/pending-docs/*.md` after routing it and those files are untracked,
so a gate failing after 4c would strand doc content in a commit the run is about to abandon.

Folded in (upstream #206): each auto-detected command is gated on its own surface appearing
in that pass's changed-file list, skipped-not-failed, with the unclaimed changed code files
reported rather than dropped.

What these guards are FOR, stated so a later edit can tell a rename from a retreat:

  - the ordering is the whole fix. Prose asserting it is not a test of it, so both sides are
    resolved from *executable fenced lines* (Phase 168's rule), and the ordering mutations
    move real commands rather than headings.
  - Step 3's disclaimer is load-bearing on its own: without it the pre-merge pass reads as a
    verdict again, which is the pre-fix state with an extra step bolted on.
  - the Step 3c coupling is here because this phase nearly shipped its own regression. The
    old text skipped the manual-smoke gate whenever Step 3 skipped; after the fix Step 3
    doc-only-skips on nearly every cycle (main's local-only diff is a claim flip and a
    `review_tasks.md` save), so that coupling would have disabled the smoke gate almost
    always — and its miss is a human never being asked.
"""

from __future__ import annotations

import inspect
import pathlib
import re
import sys
from pathlib import Path
from typing import Callable

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from _prose_guard_helpers import locate, rewrapped, states, swap  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"
GUARD = REPO_ROOT / "core" / "skills" / "_shared" / "main-push-guard.md"
WORKFLOW = REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md"
GUIDE = REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW_GUIDE.md"

# The scope command IN FULL, byte-identical in both passes on purpose: one rule, computed
# the same way on two trees, so neither pass can drift into a different notion of "changed".
# The first version pinned only the FIRST physical line, so the round corrupted the second
# one five ways and every mutation lived: a `-- '*.md'` pathspec (4a-post then doc-only-skips
# forever), `origin/<default branch>...origin/<default branch>` (always empty), a `:!tests` exclusion, a two-dot range
# hidden after a continuation, and the range hoisted into a variable.
SCOPE_CMD = (
    'git rev-parse --verify --quiet origin/<default branch> >/dev/null '
    '&& git diff --name-only origin/<default branch>...HEAD '
    '|| echo "NO_ORIGIN_MAIN"'
)

# `4a-post`'s clean-tree probe. Distinct arms from Step 6's gate deliberately — Step 6's
# mutation guards in test_review_close_record_revision.py anchor on ITS arms for that reason.
CLEAN_PROBE = 'git diff --quiet HEAD -- && echo "CLEAN" || echo "DIRTY — verification modified tracked files"'

# Matched as a PREFIX. Pinning the bare three-argument form made a Step 4b that shipped only
# the `--force` invocation go red — the invocation the skill itself mandates under `pr`.
CLOSE_BATCH = "bash sysop/scripts/close_batch.sh"

# Raw shipped forms, for mutation anchoring only (SCOPE_CMD above is the NORMALISED form the
# checks compare against, so it is not a substring of the file).
RAW_SCOPE_STEP3 = (
    "git rev-parse --verify --quiet origin/<default branch> >/dev/null \\\n"
    "  && git diff --name-only origin/<default branch>...HEAD \\\n"
    '  || echo "NO_ORIGIN_MAIN"'
)
RAW_SCOPE_POST = (
    "   git rev-parse --verify --quiet origin/<default branch> >/dev/null \\\n"
    "     && git diff --name-only origin/<default branch>...HEAD \\\n"
    '     || echo "NO_ORIGIN_MAIN"'
)

# `None` end marker means "to end of file". A *named* marker that cannot be found fails
# closed — the same rule test_review_close_record_revision.py adopted after a missing end
# marker silently widened a window 12x.
SECTIONS: dict[str, tuple[str, str | None]] = {
    "step3": ("## Step 3: Run Verification", "## Step 3c: Manual Smoke Gate"),
    "step3c": ("## Step 3c: Manual Smoke Gate", "## Step 3b: Prepare Worktrees for Merge"),
    "step4a": ("### 4a. Merge Approved Feature Branches", "### 4a-post. Verify the Merged Tree"),
    "post": ("### 4a-post. Verify the Merged Tree", "### 4b. Close Merged Batches"),
    "step4b": ("### 4b. Close Merged Batches", "### 4c. Consolidate Pending Documentation"),
    "step8": ("## Step 8: Report", None),
}

# Backticks optional. The round noted the backtick-required form let an extension LIST be
# restated unfenced, which is under-strictness; the >= 3 distinct threshold below is what
# keeps the looser pattern from firing on an incidental mention.
# A STANDALONE extension, not a filename suffix. The original pattern matched the
# `.sh` inside `run_checks.sh` and the `.py` inside `accounting.py`, so any prose
# that cites three differently-suffixed FILENAMES read as a restatement of Step 3's
# extension list. Phase 247 surfaced it by naming `run_checks.sh`,
# `run_checks_impl.py` and `close_batch.sh` in 4a-post.
#
# This is a tightening toward the guard's stated intent, not a softening of it:
# what it exists to catch is 4a-post RESTATING the list (`.py` / `.ts` / `.tsx`),
# and those are standalone tokens. A filename is not a restatement. The
# `(?<![\w/])` lookbehind keeps every real restatement matching -- verified
# against this module's own positive controls, which still go red.
CODE_EXT_RE = re.compile(r"(?<![\w/])`?\.(py|ts|tsx|js|jsx|sql|sh|kt|swift|go|rs)\b`?")


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Whitespace-collapsed, so a pin survives rewrapping and reflowing while any change to
    the words themselves still fails it."""
    return re.sub(r"\s+", " ", text)


def _slice(text: str, key: str) -> str:
    start, end = SECTIONS[key]
    a = text.find(start)
    if a < 0:
        return ""
    if end is None:
        return text[a:]
    b = text.find(end, a)
    if b <= a:
        return ""
    return text[a:b]


def _bash_fence_lines(section: str) -> list[str]:
    """Lines inside a ```bash / ```sh fence — comments, blanks and blockquoted lines dropped.

    The round found the first version accepted ANY info string (`in_fence = stripped != "```"`),
    so re-fencing a command block as ```text or ```console left it counting as executable and
    four mutations walked straight through. An unterminated fence also swallowed the rest of
    the file as executable. Both are closed here: the toggle is anchored on the opening info
    string, so a non-bash fence never opens one.
    """
    out: list[str] = []
    in_bash = False
    for raw in section.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_bash = False if in_bash else stripped[3:].strip().lower() in ("bash", "sh", "shell")
            continue
        if not in_bash or not stripped or stripped.startswith("#") or stripped.startswith(">"):
            continue
        out.append(stripped)
    return out


def _normalize_cmd(cmd: str) -> str:
    """Collapse whitespace and redirection spacing so an equivalent rewrite still matches.

    Over-strictness is the direction that hides. The round showed that joining the scope
    command onto one line, or writing `> /dev/null` for `>/dev/null`, made the guard go red
    on an edit that changes nothing — and a check that fails on a legitimate rewrite trains
    people to weaken it.

    The redirection collapse must not touch the `>` that CLOSES a placeholder (Phase 255,
    `Q-381`). Once the scope command reads `origin/<default branch> >/dev/null`, a blind
    ``>\\s+`` rule eats the space separating the operand from the redirection, the pinned
    form stops matching the shipped one, and the guard reports "missing or corrupted" over
    a file that is correct.

    Placeholders are MASKED rather than matched around. The first cut used a negative
    lookbehind on the word ``branch``, which is a proxy for one placeholder spelling: this
    skill also carries ``<approved branch name>`` and ``<branch>``, and any future
    ``<...>`` token ending in some other word would walk straight through it. Masking is
    keyed to the construct instead of to one of its spellings.
    """
    cmd = re.sub(r"\s+", " ", cmd)
    # Mask `<...>` placeholders so their closing `>` cannot read as a redirection operator.
    holes: list[str] = []

    def _hide(m):
        holes.append(m.group(0))
        return f"\x00{len(holes) - 1}\x00"

    masked = re.sub(r"<[^<>]*>", _hide, cmd)
    masked = re.sub(r">\s+", ">", masked)
    for i, original in enumerate(holes):
        masked = masked.replace(f"\x00{i}\x00", original)
    return masked.strip()


def _exec_commands(section: str) -> list[str]:
    """Whole commands from bash fences, backslash continuations joined, normalised."""
    joined, buf = [], ""
    for line in _bash_fence_lines(section):
        if line.endswith("\\"):
            buf += line[:-1] + " "
            continue
        joined.append(_normalize_cmd(buf + line))
        buf = ""
    if buf:
        joined.append(_normalize_cmd(buf))
    return joined


def _exec_offset(text: str, prefix: str) -> int:
    """Offset of the first EXECUTABLE bash-fenced command starting with `prefix`, or -1.

    Prefix, not equality: the round found the ordering check pinned `close_batch.sh` to its
    bare three-argument form, so a Step 4b shipping only the `--force` invocation — which the
    skill itself mandates under `pr` policy — went red. Still not `text.find`: a commented-out
    or prose copy of a command must never satisfy an ordering assertion.
    """
    offset, in_bash, buf, buf_start = 0, False, "", 0
    want = _normalize_cmd(prefix)
    for raw in text.splitlines(keepends=True):
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_bash = False if in_bash else stripped[3:].strip().lower() in ("bash", "sh", "shell")
        elif in_bash and stripped and not stripped.startswith("#") and not stripped.startswith(">"):
            if not buf:
                buf_start = offset
            if stripped.endswith("\\"):
                buf += stripped[:-1] + " "
            else:
                if _normalize_cmd(buf + stripped).startswith(want):
                    return buf_start
                buf = ""
        offset += len(raw)
    return -1


# --------------------------------------------------------------------------------------
# Pins — load-bearing sentences, verbatim (whitespace-normalised)
# --------------------------------------------------------------------------------------

PINS: list[tuple[str, str, str]] = [
    ("step3",
     "**This is the pre-merge pass, and it can only verify the tree it runs on.**",
     "the disclaimer that stops Step 3 reading as a verdict. Without it the fix is a second "
     "step bolted onto the pre-fix behaviour."),
    ("step3",
     "**It is not a verdict on the work, and nothing here may be reported as having verified a branch**",
     "the prohibition. A round mutation softened the disclaimer to a caveat and left every "
     "other token intact."),
    ("step3",
     "**An empty list is a real outcome here, and it is the one to report rather than pass over.**",
     "the measured amplifier: on a synced `main` the ratchet filters an empty set and passes "
     "having run nothing. Green and ran-nothing must not read the same."),
    ("step3",
     "**gate nothing and skip nothing — run the full resolved list.** A scope you could not compute must never silently narrow the gate.",
     "the fail-safe direction for `NO_ORIGIN_MAIN`. Inverting it (skip everything) turns an "
     "uncomputable scope into a silent full bypass."),
    ("step3",
     "**A surface absent from the changed-file list is `skipped`, not `failed`.**",
     "upstream #206's requested semantics, verbatim. The point is that the skip is "
     "authorized rather than improvised."),
    ("step3",
     "**Then report every changed code file that no detected surface claimed**",
     "the honesty half of #206. Surface-gating narrows the gate, so what it cannot account "
     "for must become visible instead of disappearing."),
    ("step3",
     '**"The diff" is this pass\'s changed-file list, never the run\'s.**',
     "each pass decides its own skip. Collapsing the two lists is how one pass's green gets "
     "read as the other's."),
    ("step3c",
     "**Skip Step 3c only when the whole *run* is doc-only — not when Step 3's pre-merge pass was.**",
     "the regression this phase nearly shipped. Step 3 doc-only-skips on nearly every cycle "
     "after the fix, so the old coupling would have disabled the smoke gate almost always."),
    ("post",
     "**This is the gate whose green means something.**",
     "the thesis. This is the sentence a later edit would soften first."),
    ("post",
     "**Placed here on purpose — after the merges, before `close_batch.sh` and before doc consolidation.**",
     "the placement rationale. Moving the gate after 4c would put a data-loss window under a "
     "failing gate."),
    ("post",
     "those files are **untracked**",
     "why the placement matters at all. Without the untracked fact the placement reads as "
     "arbitrary and gets moved."),
    # Phase 318 split this into a discriminator plus the arm that still stops. The old
    # single pin read "an empty list here means the merges did not land", which is false
    # on a cycle that approved no branches — the shape upstream #686 reported, where the
    # stop fired on a healthy docs-consolidation close. Both halves are pinned because
    # the arm is what a widening would delete: dropping the second sentence leaves a step
    # that treats every empty list as expected, which is the original defect inverted.
    ("post",
     "**An empty list here is not automatically a pass and not automatically a contradiction — the discriminator is how many branches are still approved after Step 3b, so read that count first.**",
     "the discriminator. Whether an empty list is a contradiction depends on whether anything was owed."),
    ("post",
     "**One or more still approved after Step 3b**, including the Step 4-pre PR-reuse shape where the merge target *is* the one approved branch: **stop.**",
     "the arm that still stops. The reuse shape merges zero branches but approves one, so a "
     "merged-branch predicate would widen onto the one shape that needs the stop."),
    ("post",
     "Re-read it rather than carrying Step 3's result forward as a remembered value",
     "the only way this step can silently run something other than what the consumer declared."),
    ("post",
     "**Do not `git reset --hard`**",
     "the `direct`-policy recovery. A reset here discards the claim flips and the merges "
     "together, and neither is recoverable from `origin`."),
    ("post",
     "**Under the Step 4-pre PR-reuse shape this step still runs**",
     "4a is skipped under reuse; this step must not be skipped with it."),
    ("post",
     "**This is the gate `_shared/main-push-guard.md` Rule B re-runs, and Step 3 is not.**",
     "reconciles the third verification site rather than leaving it pointing at the wrong pass."),
    # ---- the three the round found. Each was a site the first version's guards could not
    # see, and the first is the phase's own closing lesson landing inside the phase: the
    # class recurs at CALL-SITE granularity, so pinning the new step's own sentence says
    # nothing about whether anything routes to it.
    ("step4a",
     "go straight to **`4a-post`** — **not** to Step 4b.",
     "Step 4a's forward pointer. It said 'go straight to Step 4b', so under the PR-reuse "
     "shape — where 4a is skipped and nothing else re-verifies — an agent executing "
     "literally routed PAST the new gate and squash-merged an unverified branch to a "
     "protected `main`. Pinning 4a-post's own 'this step still runs' sentence did not "
     "reach it: that sentence is in the section nobody arrives at."),
    ("step3",
     "**The item-5 stop is about the run, not about this pass — resolve before you skip.**",
     "item 4 (doc-only skip) precedes item 5 (stop-and-ask) and fires first on the dominant "
     "path, so a consumer with no declared commands and no detectable surface never got the "
     "free stop — it landed at `4a-post`, after every branch had merged. The phase's own "
     "record claimed the opposite."),
    ("post",
     '**If the surface gate leaves nothing to run while the list still contains a code file, that is "ran nothing", not green**',
     "the surface gate is the one way this step can re-manufacture the defect it removes: "
     "gate every detected command out and the merged-tree pass reports green having "
     "executed zero commands. Step 3 got an explicit empty-set rule; this had none."),
]

FORBIDDEN: list[tuple[str, str, str]] = [
    ("step4a",
     "go straight to Step 4b.",
     "the pre-fix forward pointer. Restoring it re-opens the PR-reuse bypass, and a pin on "
     "the replacement text alone would not catch a version that shipped BOTH sentences."),
    ("step3c",
     "If Step 3 was skipped (doc-only diff), skip Step 3c too",
     "the pre-fix coupling. Restoring it disables the manual-smoke gate on nearly every run."),
    # No terminal punctuation in the banned phrase: Phase 239 changed the shipped
    # sentence's `:` to `.`, and a colon-bearing ban would have gone quietly inert
    # against the period-bearing reversal. Strictly wider, and it cannot false-fire
    # on the shipped text, which carries `and \`4a-post\` reported green,` in between.
    ("step4b",
     "After all branches are merged but **before** doc consolidation",
     "4b's lead-in must name the gate that now precedes it, or the ordering is undocumented "
     "at the one place a reader is standing when they need it."),
]


# --------------------------------------------------------------------------------------
# Checks — each returns a list of failure strings
# --------------------------------------------------------------------------------------

def check_sections_resolve(text: str) -> list[str]:
    return [f"section {key!r} does not resolve" for key in SECTIONS if not _slice(text, key)]


def check_pinned_sentences_are_intact(text: str) -> list[str]:
    bad = []
    for key, span, why in PINS:
        if _flat(span) not in _flat(_slice(text, key)):
            bad.append(f"{key}: pin lost — {span[:70]!r} ({why})")
    return bad


def check_forbidden_phrases_are_absent(text: str) -> list[str]:
    bad = []
    for key, phrase, why in FORBIDDEN:
        if _flat(phrase) in _flat(_slice(text, key)):
            bad.append(f"{key}: forbidden phrase present — {phrase[:70]!r} ({why})")
    return bad


def check_the_gate_runs_after_the_merges_and_before_the_close(text: str) -> list[str]:
    """The ordering, resolved from executable lines on BOTH sides.

    `4a-post`'s clean-tree probe must execute before `close_batch.sh` does. Prose is not
    admissible: a commented-out probe fails this.
    """
    bad = []
    probe = _exec_offset(text, CLEAN_PROBE)
    close = _exec_offset(text, CLOSE_BATCH)
    if probe < 0:
        bad.append("4a-post has no executable clean-tree probe (a prose mention does not count)")
    if close < 0:
        bad.append("no executable close_batch.sh invocation anywhere")
    # Presence is asserted inside the SECTION as well as globally. Step 4b's recovery paths
    # also invoke the script, so a global lookup alone stays satisfied when 4b's own primary
    # invocation is demoted out of a bash fence — the ordering would still read as green
    # while the step a reader executes has no command in it.
    if not any(c.startswith(_normalize_cmd(CLOSE_BATCH)) for c in _exec_commands(_slice(text, "step4b"))):
        bad.append("Step 4b's own close_batch.sh invocation is not an executable bash-fenced command")
    if probe >= 0 and close >= 0 and probe > close:
        bad.append("the merged-tree gate executes AFTER close_batch.sh — the placement is inverted")
    heading_4a = text.find("### 4a. Merge Approved Feature Branches")
    heading_post = text.find("### 4a-post. Verify the Merged Tree")
    heading_4b = text.find("### 4b. Close Merged Batches")
    if not (0 <= heading_4a < heading_post < heading_4b):
        bad.append("4a-post is not between 4a and 4b")
    return bad


ROUTE_RE = re.compile(
    r"(?:go straight to|proceed to|continue to|skip (?:ahead |forward )?to|jump to)\s+"
    r"(?:\*\*)?(?:`)?Step 4b",
    re.IGNORECASE,
)


def check_nothing_routes_past_the_merged_tree_gate(text: str) -> list[str]:
    """Population is the WHOLE file, not the 4a slice.

    The round found Step 4a still saying "go straight to Step 4b" — text this phase never
    touched, which under the PR-reuse shape (where 4a is skipped and nothing else
    re-verifies) routed an agent past the new gate and squash-merged an unverified branch to
    a protected `main`. Pinning 4a-post's own "this step still runs" sentence could not see
    it: that sentence lives in the section nobody arrives at.

    So this asserts the property rather than the one site — any forward pointer anywhere in
    the skill that jumps to Step 4b jumps over the gate.
    """
    hits = ROUTE_RE.findall(text)
    if hits:
        return [f"{len(hits)} forward pointer(s) route past 4a-post straight to Step 4b"]
    return []


def check_the_gate_is_executable_at_all(text: str) -> list[str]:
    """A step made of prose runs nothing. `4a-post` must carry real fenced commands."""
    if not _exec_commands(_slice(text, "post")):
        return ["4a-post carries no executable fenced command — it is prose, not a gate"]
    return []


def check_both_passes_share_one_scope_command(text: str) -> list[str]:
    """One rule, two trees. If the passes drift into different scope commands, the whole
    'computed the same way on its own tree' claim stops holding."""
    bad = []
    for key in ("step3", "post"):
        # Resolved from EXECUTABLE fenced lines, not a substring of the section. An
        # assumption-mutation that fenced the block as ```text and prefixed the command with
        # `#` left the substring intact and survived every check — a commented-out command
        # was marking the pass compliant.
        if SCOPE_CMD not in _exec_commands(_slice(text, key)):
            bad.append(f"{key}: the shared changed-file scope command is missing, corrupted, "
                       "or not in a bash fence")
    # Scoped to `git diff` on purpose. Step 1's `git log --oneline origin/<default branch>..HEAD` is a
    # LEGITIMATE two-dot — for `log`, two dots already mean "commits not on the base", which
    # is what that line wants (the per-command rule in Step 2a's three-dots note). A blanket
    # substring ban here would have gone red on the shipped tree for a correct command.
    # The gap is flags only, never `[^\n]*`: a permissive gap matched a 700-character
    # paragraph that happened to contain `git diff --quiet HEAD --` near its start and
    # `origin/<default branch>..main` (a `git rev-list` range, correctly two-dot) near its end, and
    # went red on the shipped tree for two unrelated correct commands.
    if re.search(r"git diff(?:\s+--?[\w-]+)*\s+origin/<default branch>\.\.(?!\.)", text):
        bad.append("a two-dot `git diff origin/<default branch>..HEAD` shipped — everything the base "
                   "gained since the cut renders as a deletion")
    return bad


def check_no_fourth_code_extension_list(text: str) -> list[str]:
    """`test_review_close_diff_basis.py` pins ONE code-file set across the three doc-only
    skips by comparing them for equality. A fourth list restated in 4a-post would sit
    outside that equality and could drift silently, so 4a-post must defer to Step 3's."""
    # >= 3 distinct = a LIST. One or two backticked extensions in prose is an example, not a
    # competing source of truth; firing on those was over-strictness, the direction that hides.
    found = set(CODE_EXT_RE.findall(_slice(text, "post")))
    if len(found) >= 3:
        return [f"4a-post restates a code-file extension LIST {sorted(found)} — defer to Step 3 item 4"]
    return []


def check_the_report_has_somewhere_to_render(text: str) -> list[str]:
    """Phase 158's precedent: a gate whose skips nobody can see is not a fix. Before this
    phase the Step 8 template had no verification line at all, so every run's verification
    result — right tree or wrong — was recorded nowhere."""
    report = _slice(text, "step8")
    bad = []
    # `"merged-tree (4a-post)"`, not a bare `"4a-post"`: the step8 slice runs to EOF and so
    # includes the `--dry-run` line, which names `4a-post` too. Keyed on the bare token, the
    # whole template block could be deleted and this check would still pass on that mention.
    for token in ("Verification:", "Unverified surfaces:", "merged-tree (4a-post)"):
        if token not in report:
            bad.append(f"Step 8 report has no {token!r} — the gate's result is unrecordable")
    return bad


# Phase 318. Both arms this phase added are CONTINUES on a path that previously always
# stopped, so the pins above only protect their spelling. These two checks protect the
# property: an arm that keeps its pinned sentence while losing a precondition is the
# failure mode, and it is the one a prose pin cannot see.
INHERITED_PRECONDITIONS = (
    # 1 — the close cannot have introduced the failure. The STAGE is load-bearing: Step 2d
    #     demotes and Step 3b downgrades, so the Step 2a count is a different number.
    "**This close has zero branches still approved after Step 3b**",
    # 2 — the failure is present on the base, not manufactured by the merge.
    "fails the same way on `origin/<default branch>`",
    # 3 — and it is the ONE error another step already classifies as self-clearing,
    #     for a task THIS close will flip. Without the second half the arm fires on any
    #     Invariant 9 error, including one for a task no pending-doc will ever close.
    "Invariant 9",
    "will actually flip to `done`",
    # 3, second half — Step 4c has THREE filters, not two. Its step 1c refuses to route a
    #     doc at all when any id it names carries a truthy `user_action`, so a doc 1c holds
    #     yields no flip and the arm's premise is false. The round's execution lens built
    #     the fixture, drove all three preconditions true against a held task, and watched
    #     the arm fire on a doc Step 4c would never route.
    "step 1c's `user_action` hold",
)

#: The two sentences that make a CONTINUE past a failing gate honest. Neither is a
#: precondition, so the loop above cannot reach them — and the round's guard lens deleted
#: both with every check green. The second is the sharper loss: without it the tree that is
#: actually pushed is gated by nothing at all, because `4a-post` failed and the re-run that
#: was supposed to be the real verdict is gone.
INHERITED_SAFETY = (
    "**Never silently:**",
    "Re-run the command after Step 4c's flip and report that result as the gate for the tree actually pushed.",
)

#: Vocabulary that WIDENS an arm rather than stating it. The round's guard lens defeated
#: every precondition by pure addition — a clarifying sentence that waives one, or opens the
#: arm to "any other failure on the same reasoning" — while leaving all fourteen anchors
#: matching. This does not close that class (a class is not a string; see `Q-560`), but it
#: catches the spellings that reach for it, which is what `OPTIONALISING_RE` does one
#: function over for the sibling class.
WIDENING_RE = re.compile(
    r"may be waived|waived where|need not hold|does not gate the arm|never load-bearing|"
    r"qualifies on the same reasoning|the worked example, not the boundary|"
    r"guidance rather than a gate|use judgement where|either spelling is fine|"
    r"disregard that requirement|is open to it|settles it just as well|"
    r"without opening the pending-doc|questions to think about",
    re.I,
)


def _live(text: str) -> str:
    """`text` with HTML comments and fenced blocks removed.

    A rule a runner never reads is not a rule. The round's guard lens wrapped the WHOLE
    empty-list branch — both arms, both pins — in an HTML comment captioned "kept so the
    drift guards keep their subject", replaced it with a blanket pass, and the module
    reported 172 passed. `check_dry_run_disclaimer_is_live_text` in this same file already
    strips comments for exactly this reason (its own round HTML-commented a rule out); the
    two checks below were written beside it and did not, so this is that helper's rule
    generalised rather than a new idea. Fences too: a rule demoted into a ```text block is
    equally unread.
    """
    live = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    out, fenced = [], False
    for line in live.split("\n"):
        if re.match(r"^\s*(```|~~~)", line):
            fenced = not fenced
            continue
        if not fenced:
            out.append(line)
    return "\n".join(out)


def check_the_inherited_failure_arm_keeps_its_preconditions(text: str) -> list[str]:
    """Item 4 is the stop that speaks for the merged tree; Phase 318 gave it one continue.

    A general inherited/introduced test — the shape upstream `#685` proposed — licenses
    continuing past ANY gate-visible defect already on the default branch. The arm shipped
    instead is scoped to one error. The skill states THREE numbered preconditions; this tuple
    carries FIVE phrases because precondition 3 is itself a conjunction (Invariant 9, AND a task
    this close will actually flip, AND step 1c's hold). The counts are not in conflict and the
    round asked — every phrase is load-bearing:
    drop the approved-branch count and a close that merged work can walk past a failure it
    introduced; drop the `origin/<default branch>` reproduction and "inherited" is an
    assertion rather than a measurement; drop either half of the Invariant 9 scoping and
    the arm reaches failures no Step 4c will repair, which is a fail-open gate.
    """
    # LIVE text only, and flattened. Both are round findings: the guard lens hid the rules in
    # an HTML comment and in a fence with every check green, and the re-wrap control showed
    # the first cut going red on an innocent reformat — the fail-closed direction that trains
    # people to weaken a guard (`Q-495`'s thesis).
    post = _flat(_live(_slice(text, "post")))
    bad = []
    # `states()`, not `in` — this module's author-side battery walked the first cut by leaving
    # every required phrase in place inside a sentence that negates it ("It is NOT the case
    # that ... matters here"). A substring check marks that compliant. `states()` is the
    # negation-aware form the repo already ships. It is SENTENCE-scoped, so it does not reach
    # a cancelling sentence placed next to the rule — that residual is `Q-560`.
    if not states(post, _flat("The inherited-failure arm fires only when all three hold")):
        bad.append("4a-post item 4's inherited arm no longer states that its preconditions are conjunctive")
    for phrase in INHERITED_PRECONDITIONS:
        if not states(post, _flat(phrase)):
            bad.append(f"4a-post's inherited-failure arm lost a precondition: {phrase!r}")
    # The two sentences that make the continue honest. Not preconditions, so the loop above
    # never reached them, and the round deleted both with every check green.
    for phrase in INHERITED_SAFETY:
        if not states(post, _flat(phrase)):
            bad.append(f"4a-post's inherited arm lost the rule that keeps its continue honest: {phrase!r}")
    # The arm must fail closed on what it cannot establish.
    if not states(post, _flat("If you cannot name a doc that clears all three, stop.")):
        bad.append("the inherited arm does not fail closed when its Step 4c doc cannot be named")
    if "INHERITED:" not in post:
        bad.append("the inherited arm continues without a report token — a silent walk past a failure")
    # The literal SLOT, in LIVE text: `| WAS-INHERITED: <command>` contains the substring
    # `INHERITED:` and satisfied an earlier form while renaming the slot out from under the
    # arm that writes to it; HTML-commenting the slot out satisfied the form after that.
    # Step 8 is COMMENT-stripped but NOT fence-stripped: the report template legitimately
    # lives inside a fence — `check_the_report_lines_are_in_the_template_fence` requires
    # exactly that — so running `_live()` here deleted the slot it was checking for and
    # reddened the shipped tree plus five negative controls. My bug, caught by the controls.
    step8 = _flat(re.sub(r"<!--.*?-->", "", _slice(text, "step8"), flags=re.S))
    if _flat("| INHERITED: <command>") not in step8:
        bad.append("Step 8 has no live INHERITED slot, so the arm's report has nowhere to render")
    # Widening by pure ADDITION — the round's sharpest finding. Not closed by this, and the
    # residual is filed as `Q-560`; this catches the spellings that reach for it.
    m = WIDENING_RE.search(post)
    if m:
        bad.append(f"4a-post item 4 carries arm-widening language: {m.group(0)!r}")
    # ORDERING. The arm is a test the runner must reach BEFORE the unconditional stop; prose
    # asserting an order is not a test of it. Use the LAST occurrence of the arm and the
    # FIRST of the stop: the round bypassed a first/first comparison by planting a near-copy
    # of the arm sentence earlier in the step.
    arm = post.rfind(_flat("The inherited-failure arm fires only when all three hold"))
    stop = post.find(_flat("**On every other failure, stop.**"))
    if arm < 0 or stop < 0:
        bad.append("4a-post item 4 lost either its inherited arm or its unconditional stop")
    elif stop < arm:
        bad.append(
            "4a-post item 4's unconditional stop now precedes the inherited-failure arm, "
            "so the arm is unreachable — a runner stops before it is ever tested"
        )
    return bad


def check_the_empty_list_arms_are_both_present(text: str) -> list[str]:
    """The empty changed-file list branches; neither arm may be dropped.

    Upstream `#686` reported the stop firing on a healthy zero-branch close. The fix is a
    branch, not a removal — and a branch decays in two directions. Losing the stop arm
    makes every empty list expected, which is the defect this step was built to catch;
    losing the continue arm restores `#686`.
    """
    # LIVE and flattened, for the reasons the sibling check states: the round hid this whole
    # branch — both arms, both pins — inside an HTML comment and replaced it with a blanket
    # pass, and every check stayed green.
    post = _flat(_live(_slice(text, "post")))
    bad = []
    # `states()` for the same reason the sibling check above uses it: a negating sentence
    # keeps every substring and inverts the rule.
    if not states(post, _flat("**Zero still approved after Step 3b**")):
        bad.append("4a-post lost the zero-approved-branch arm — a healthy docs close stops again (#686)")
    if not states(post, _flat("**One or more still approved after Step 3b**")):
        bad.append("4a-post lost the stop arm — every empty list now reads as expected")
    # The STAGE, which the execution lens found missing. Step 2d demotes and Step 3b
    # downgrades, so a Step 2a count is a different number — and on a close where 2a
    # approved one branch and 3b downgraded it, the two readings disagree on exactly the
    # shape #686 reports. Step 4-pre condition 1 already insists on this stage.
    if not states(post, _flat("Take the count after Step 3b, not after Step 2a")):
        bad.append("4a-post's empty-list discriminator no longer names the stage its count is taken at")
    # Widening by addition — a third "also expected" bullet swallows the stop case without
    # touching either pinned arm. Residual filed as `Q-560`.
    m = WIDENING_RE.search(post)
    if m:
        bad.append(f"4a-post's empty-list branch carries widening language: {m.group(0)!r}")
    # The distinction the filing's own proposed remedy got wrong. Plain `in`, NOT `states()`,
    # and the exception is worth stating: the shipped sentence reads "**that note is not `ran
    # nothing`**, which is reserved for a run that executed zero commands" — so `states()`'s
    # within-40-chars negation rule sees "is not" and rejects a sentence that is in fact
    # asserting the distinction. The negation belongs to the quoted TOKEN, not to the clause.
    # Using `states()` here reddened the shipped tree, which is how this was found.
    if "which is reserved for a run that executed zero commands" not in post:
        bad.append("4a-post no longer separates an empty SCOPE from a zero-command RUN")
    return bad


def check_dry_run_does_not_claim_the_merged_gate(text: str) -> list[str]:
    if "**`4a-post` cannot run under `--dry-run`**" not in text:
        return ["--dry-run does not disclaim the merged-tree gate; Step 3's green stands in for it"]
    return []



# `optional(?!-dependencies)` — the bare word matched `[project.optional-dependencies]`, a
# legitimate pyproject key Step 3 names in its pytest auto-detect rule, so the first version
# of this regex went red on the shipped tree. Over-strictness caught by its own negative
# control rather than by a reviewer, which is what the controls are for.
OPTIONALISING_RE = re.compile(
    r"\b(optional(?!-dependencies)|skipped by default|if convenient|may (?:be )?skip|"
    r"no longer applies|historical note|purely advisory|at your discretion|nice to have)\b", re.I)
NON_STOPPING_RE = re.compile(
    r"do not run the list|note it and continue|continue anyway|proceed to Step 4b anyway|"
    r"log it and move on|does not stop the close", re.I)
REORDER_RE = re.compile(
    r"after (?:the )?(?:Step )?4b\b|after Step 4b|Step 4b first|after the close-batch|"
    r"after `close_batch\.sh`|once the close-batch commit lands", re.I)


def check_the_gate_actually_runs_the_list(text: str) -> list[str]:
    """The round's worst finding: NOTHING required 4a-post to run a verification command.

    `check_the_gate_is_executable_at_all` was satisfied by the scope command and the clean
    probe — neither of which verifies anything. Deleting the "Run the list" instruction, or
    softening it to "if convenient", left a step that resolves a list, computes a changed-file
    set, confirms the tree is clean, and verifies nothing. Four mutations lived there,
    including one that rewrote the whole step as OPTIONAL while keeping all eight pins
    verbatim inside a blockquote.
    """
    post = _slice(text, "post")
    bad = []
    if "3. **Run the list**" not in post:
        bad.append("4a-post has no imperative 'Run the list' actuator — the step verifies nothing")
    # Both passes, not just the new one: the round softened STEP 3's failure sentence
    # ("report the failure and stop" → "note it and continue") and that survived a check
    # scoped to 4a-post. A gate whose failure does not stop is not a gate in either pass.
    for key in ("post", "step3"):
        section = _slice(text, key)
        for label, rx in (("optional-ising", OPTIONALISING_RE), ("non-stopping", NON_STOPPING_RE)):
            m = rx.search(section)
            if m:
                bad.append(f"{key} carries {label} language: {m.group(0)!r}")
    m = REORDER_RE.search(post)
    if m:
        bad.append(f"4a-post is told to run after the step it gates: {m.group(0)!r}")
    return bad


def check_the_step3c_coupling_is_gone_from_the_whole_file(text: str) -> list[str]:
    """Whole-file, not section-scoped.

    The section-scoped FORBIDDEN entry was escapable: the round reintroduced the pre-fix
    coupling in Step 3 and in Step 3b — outside the `step3c` slice — and both survived. That
    is the exact regression this phase says it nearly shipped, reachable by moving one
    sentence one section over.
    """
    if "skip Step 3c too" in _flat(text):
        return ["the pre-fix Step 3c coupling is present somewhere in the file"]
    return []


def check_the_report_lines_are_in_the_template_fence(text: str) -> list[str]:
    """Tokens must live INSIDE the report's fenced template.

    Token-presence over the whole Step 8 slice let the round delete the template fence and
    replace it with prose inviting the reader to "mention Verification: … if you feel they
    add value", and to HTML-comment the lines out. Both kept every token and both survived.
    """
    report = _slice(text, "step8")
    fences = re.findall(r"```\n(.*?)```", report, re.S) or re.findall(r"```[a-z]*\n(.*?)```", report, re.S)
    body = "\n".join(fences)
    bad = []
    if not body:
        return ["Step 8 has no fenced report template at all"]
    starts = {ln.strip() for ln in body.splitlines()}
    for token in ("Verification:", "Unverified surfaces:", "merged-tree (4a-post)"):
        # Line-start, not substring: inside a fence `<!--` is literal text, so an
        # HTML-commented line keeps the token present while the rendered report line becomes
        # `<!-- Verification: …`. Presence alone stayed green on exactly that mutation.
        if not any(ln.startswith(token) for ln in starts):
            bad.append(f"Step 8's report TEMPLATE has no line starting {token!r} "
                       "(a prose mention or a commented-out line does not count)")
    return bad


def check_dry_run_disclaimer_is_live_text(text: str) -> list[str]:
    """HTML comments and negation both defeated the first version's `in text` check."""
    live = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    para = ""
    for chunk in live.split("\n\n"):
        if "--dry-run" in chunk and "4a-post" in chunk:
            para = chunk
            break
    if not para:
        return ["no live paragraph ties --dry-run to 4a-post"]
    bad = []
    if "**`4a-post` cannot run under `--dry-run`**" not in para:
        bad.append("--dry-run no longer disclaims the merged-tree gate")
    if re.search(r"myth|is not true|also runs under", para, re.I):
        bad.append("the --dry-run disclaimer is negated in its own paragraph")
    return bad


CHECKS: list[Callable[[str], list[str]]] = [
    check_sections_resolve,
    check_pinned_sentences_are_intact,
    check_forbidden_phrases_are_absent,
    check_the_gate_runs_after_the_merges_and_before_the_close,
    check_nothing_routes_past_the_merged_tree_gate,
    check_the_gate_is_executable_at_all,
    check_the_gate_actually_runs_the_list,
    check_the_step3c_coupling_is_gone_from_the_whole_file,
    check_the_report_lines_are_in_the_template_fence,
    check_dry_run_disclaimer_is_live_text,
    check_both_passes_share_one_scope_command,
    check_no_fourth_code_extension_list,
    check_the_report_has_somewhere_to_render,
    check_dry_run_does_not_claim_the_merged_gate,
    check_the_inherited_failure_arm_keeps_its_preconditions,
    check_the_empty_list_arms_are_both_present,
]


def test_shipped_skill_satisfies_every_check():
    failures = [f for check in CHECKS for f in check(_text())]
    assert not failures, "\n".join(failures)


@pytest.mark.parametrize("check", CHECKS, ids=[c.__name__ for c in CHECKS])
def test_each_check_is_green_on_the_shipped_tree(check):
    assert check(_text()) == []


# --------------------------------------------------------------------------------------
# The three sites outside this skill
# --------------------------------------------------------------------------------------

NEGATION_RE = re.compile(r"no need to|is not required|is a myth|optional|need not|"
                         r"do not\s+(?:re-?run|run)|without re-?verif", re.I)


def test_main_push_guard_reruns_the_merged_tree_gate_not_step_3():
    """Rule B's rebase-first arm is a THIRD execution of the same command list. It named
    Step 3 — the one pass whose tree is not what the rebase moved.

    Pinned as a contiguous span, not as two tokens. The round inverted the whole instruction
    ("There is no need to RE-RUN review-close 4a-post, and NOT Step 3 either … push without
    re-verifying") while keeping both asserted tokens present, and it survived.
    """
    flat = _flat(GUARD.read_text(encoding="utf-8"))
    span = ("# The base changed → RE-RUN review-close 4a-post (the merged-tree gate: the "
            "# project's § Pre-merge verification commands, run on the merge target) against "
            "# the new base before pushing. NOT Step 3 — Step 3's tree is the default branch "
            "# before any merge, which is not the tree this rebase moved.")
    assert _flat(span) in flat, "Rule B's re-run instruction is not intact"
    assert "RE-RUN review-close Step 3" not in flat, "the pre-fix instruction is back"
    i = flat.index("RE-RUN review-close 4a-post")
    window = flat[max(0, i - 200): i + 400]
    m = NEGATION_RE.search(window)
    assert not m, f"Rule B's re-run instruction is negated nearby: {m.group(0) if m else ''!r}"


def test_the_two_specs_state_the_merged_tree_pass():
    """Unlike Phase 167 — where both specs were right and only the skill had drifted — here
    the specs ordered verification before the merge too. They are the root cause, so a fix
    confined to the skill would leave the text that licensed it.

    Each assertion carries its list marker, so a `Do not <sentence>` prefix cannot satisfy it.
    """
    wf = _flat(WORKFLOW.read_text(encoding="utf-8"))
    gd = _flat(GUIDE.read_text(encoding="utf-8"))
    assert "5b. **Run verification — the merged-tree pass**" in wf
    assert "the pre-merge pass** (Step 3)" in wf
    assert "Run **twice**" in wf
    assert "5b. **Run full verification on the merged result" in gd, (
        "the by-hand Merge Process's merged-result step lost its list marker, so a negating "
        "prefix would satisfy a bare-sentence assertion"
    )
    assert "**They run twice, on two different trees:**" in gd


def test_the_worktree_gates_are_not_presented_as_substitutes():
    """`/claim-task` 7b and `/auto-build`'s execution-agent sequence verify a branch in its
    own worktree and are the only thing that ever does. Both told the reader `/review-close`
    covers them 'at merge time' — false before this phase, a division of labour after it."""
    for rel in ("claim-task", "auto-build"):
        text = _flat((REPO_ROOT / "core" / "skills" / rel / "SKILL.md").read_text(encoding="utf-8"))
        assert "its `4a-post` step, on the merged tree" in text, f"{rel}: no longer names the gate"
        # The full clause with its terminator, not the trailing fragment: the round appended
        # ", so 7b is optional" to a bare "cannot substitute for it" and it survived.
        assert "`4a-post` verifies the **assembled** result and cannot substitute for it." in text, (
            f"{rel}: the division-of-labour sentence is altered or extended"
        )
        assert "nothing* verifies the branch in isolation" in text, (
            f"{rel}: the absent-section caveat is gone"
        )


PUBLIC_DOCS = {
    "docs/configuration.md": "twice, as a cheap pre-merge pass on `main` and again on the merged tree",
    "docs/getting-started.md": "`/review-close` runs it on the merged tree on every merge",
    "docs/workflow.html": "run twice on two trees",
}


def test_the_public_docs_carry_the_two_pass_shape():
    """Population derived from what the change touched, not from this module's SECTIONS dict.

    The round reverted all three public-site edits and every one survived — no guard read
    `docs/` at all, and `test_doc_currency.py` carries no `4a-post` reference. A public page
    still describing a single pre-merge gate is the mirror-leak class: it ships to readers
    who cannot see the skill.
    """
    for rel, span in PUBLIC_DOCS.items():
        text = _flat((REPO_ROOT / rel).read_text(encoding="utf-8"))
        assert _flat(span) in text, f"{rel} no longer states the two-pass shape"


# --------------------------------------------------------------------------------------
# Mutations — every one must be caught by at least one check
# --------------------------------------------------------------------------------------

def _at(text: str, phrase: str) -> int:
    """`text.index(phrase)`, whitespace-tolerant — the offset form of `_sub`.

    The rows that slice the file rather than substitute into it used `t.index`, which
    raises a bare `ValueError("substring not found")` when its anchor stales: the row
    reads as a broken test rather than as a stale literal, which is `Q-495`'s reason for
    routing every one of these through an assertion that names the phrase.
    """
    return locate(text, phrase).start()


def _sub(old: str, new: str, after: str | None = None) -> Callable[[str], str]:
    """A mutation that replaces the first WHITESPACE-TOLERANT occurrence of `old`.

    `Q-495`: this was `text.replace(old, new, 1)` over a raw literal, so re-wrapping the
    shipped sentence staled the anchor and the row went red for a reformat while every
    rule it protects was intact. Measured on this module at the phase's OPEN (`1988a9a`,
    before any of this phase's edits): **33 of its 59 rows** stopped applying after a
    rendering-identical re-wrap. `swap()` pins the
    words and lets the layout move; leading whitespace in `old` still requires whitespace,
    so the rows anchored on `"   " + COMMAND` keep targeting the fenced occurrence rather
    than a prose mention of the same command.
    """
    def go(text: str) -> str:
        return swap(text, old, new, after=after)
    return go


# `Q-495`: the scope command appears in Step 3 AND in 4a-post, and the three-space indent
# that used to tell them apart is exactly what a re-indent moves. Every row named for
# 4a-post's copy says so rather than relying on which one comes first in the file.
POST_HEADING = SECTIONS["post"][0]


# Step 4b's actual invocation, pinned WITH its fence closer. The bare three-argument form
# is also a prefix of the recovery path's re-run (`… <N3> 2>&1`), so without the closer the
# anchor names two sites.
_MOVE_PROBE_SOURCE = ""  # set below, once the helper is defined

_STEP_4B_CALL = (
    'bash sysop/scripts/close_batch.sh --merge-target "<merge target>" <N1> <N2> <N3>\n```'
)


def _move_probe_after_close_batch(text: str) -> str:
    """O1: relocate the clean-tree probe to AFTER Step 4b's close-batch call.

    `Q-495`'s own lesson, applied to this row. It used to be two chained `str.replace`
    calls, and the second one -- `"   " + CLOSE_BATCH + "\n"` -- had NEVER matched: the
    shipped line carries `--merge-target` arguments and sits at column 0, so the row was a
    pure DELETION of the probe wearing the name of a move, and the table's only ordering
    mutation tested no ordering. `str.replace` returns the string unchanged when it finds
    nothing, so nothing said so; `swap()` fails loud instead, which is why both halves go
    through it. Found by this phase's round.
    """
    without = swap(text, "   " + CLEAN_PROBE + "\n", "")
    return swap(without, _STEP_4B_CALL, _STEP_4B_CALL + "\n\n   " + CLEAN_PROBE,
                after=SECTIONS["step4b"][0])


_MOVE_PROBE_SOURCE = inspect.getsource(_move_probe_after_close_batch)

MUTATIONS: list[tuple[str, Callable[[str], str]]] = [
    # ---- ordering: the whole fix ----
    ("O1 move the gate after close_batch.sh", lambda t: _move_probe_after_close_batch(t)),
    ("O2 comment the clean-tree probe out, leave the text present", _sub(
        "   " + CLEAN_PROBE, "   # " + CLEAN_PROBE)),
    ("O3 rename the step so it no longer sits between 4a and 4b", _sub(
        "### 4a-post. Verify the Merged Tree", "### 4z. Verify the Merged Tree")),
    ("O4 demote the step to prose (strip its fences)", lambda t: (
        t[:_at(t, "### 4a-post.")]
        + t[_at(t, "### 4a-post."):_at(t, "### 4b. Close Merged Batches")].replace("```bash", "").replace("```", "")
        + t[_at(t, "### 4b. Close Merged Batches"):])),
    # ---- the disclaimers ----
    ("D1 soften Step 3's disclaimer to a caveat", _sub(
        "**This is the pre-merge pass, and it can only verify the tree it runs on.**",
        "This pass runs early and is generally sufficient; the notes below are edge cases.")),
    ("D2 retire the do-not-report prohibition", _sub(
        "**It is not a verdict on the work, and nothing here may be reported as having verified a branch**",
        "It is a reasonable verdict on the work and may be reported as such")),
    ("D3 restore the pre-fix Step 3c coupling", _sub(
        "**Skip Step 3c only when the whole *run* is doc-only — not when Step 3's pre-merge pass was.**",
        "If Step 3 was skipped (doc-only diff), skip Step 3c too.")),
    ("D4 collapse the two changed-file lists into one", _sub(
        '**"The diff" is this pass\'s changed-file list, never the run\'s.**',
        "\"The diff\" is the run's changed-file list, shared by both passes.")),
    # ---- the fail-safe directions ----
    ("F1 invert NO_ORIGIN_MAIN to skip everything", _sub(
        "**gate nothing and skip nothing — run the full resolved list.** A scope you could not compute must never silently narrow the gate.",
        "skip verification entirely — with no list there is nothing to check.")),
    ("F2 make an empty list at 4a-post a pass", _sub(
        "**An empty list here is not automatically a pass and not automatically a contradiction — the discriminator is how many branches are still approved after Step 3b, so read that count first.**",
        "An empty list here is a clean pass — nothing changed, so nothing needs checking.")),
    # Phase 318's own fix is what this row exists to break: the zero-approved-branch arm
    # is a continue, so widening its predicate to the MERGED count silently swallows the
    # Step 4-pre PR-reuse shape, where Step 4a merges zero branches while one approved
    # branch IS the merge target. An empty list there is a real contradiction — a branch
    # that ships nothing — and the widened arm would sail past it.
    ("F2b widen the zero-branch arm from approved count to merged count", _sub(
        "**One or more still approved after Step 3b**, including the Step 4-pre PR-reuse shape where the merge target *is* the one approved branch: **stop.**",
        "**One or more branches merged by Step 4a**: **stop.**")),
    ("F2c drop the zero-approved-branch arm — #686 comes back", _sub(
        "   - **Zero still approved after Step 3b**", "   - **Zero still approved after Step 3b, which cannot happen**")),
    ("F2d collapse an empty SCOPE into a zero-command RUN", _sub(
        "which is reserved for a run that executed zero commands",
        "which means the same thing")),
    # ---- Phase 318's inherited-failure arm. Each row removes exactly one predicate. ----
    ("I1 drop the approved-branch precondition — a merging close may walk past its own failure", _sub(
        "   1. **This close has zero branches still approved after Step 3b**, so it cannot have introduced the failure. One or more — including the Step 4-pre PR-reuse shape — means stop. Same count, same stage, as step 2 above.\n",
        "")),
    ("I2 drop the origin reproduction — 'inherited' becomes an assertion", _sub(
        "**The failing command fails the same way on `origin/<default branch>`.**",
        "**The failing command looks like one that was probably already there.**")),
    ("I3 widen past Invariant 9 to any failure — the #685-as-filed shape", _sub(
        "**The failure is `validate_tasks.py` Invariant 9** (`status=in_progress but lock file missing`) **for a task id this close's Step 4c will actually flip to `done`**",
        "**The failure reproduces on the default branch**")),
    ("I4 keep Invariant 9 but drop the this-close scoping", _sub(
        "**for a task id this close's Step 4c will actually flip to `done`**",
        "**for any task id at all**")),
    ("I5 let the arm fire on what it cannot establish", _sub(
        "**If you cannot name a doc that clears all three, stop.**",
        "If you cannot name that doc, assume it exists.")),
    ("I6 make the arm silent — a walk past a failure that reads as a pass", _sub(
        "**When the arm fires, report it and keep going to item 5** — `INHERITED: <command> — fails on origin/<default branch> too; <TASK-ID> is in this close's Step 4c set` on Step 8's `Verification:` line, **beside** the executed-command count, never instead of it.",
        "**When the arm fires, keep going to item 5.**")),
    ("I7 make the preconditions disjunctive", _sub(
        "**The inherited-failure arm fires only when all three hold.**",
        "**The inherited-failure arm fires when any of these holds.**")),
    # ---- The four the AUTHOR-SIDE battery found walking the first cut of the two checks
    # above. All four left every required phrase in the file, which is why substring checks
    # marked them compliant; three are the "what it accepts" class and one is "when it runs".
    ("I8 keep every precondition but negate the sentence carrying one", _sub(
        "   1. **This close has zero branches still approved after Step 3b**, so it cannot have introduced the failure.",
        "   1. It is NOT the case that **This close has zero branches still approved after Step 3b** matters here; ignore it.")),
    ("I9 keep the fail-closed phrase inside a sentence that cancels it", _sub(
        "**If you cannot name a doc that clears all three, stop.**",
        "It is false that **If you cannot name a doc that clears all three, stop.** — carry on.")),
    # Hoisting by INSERTING the stop ahead of the arm rather than moving it: one tolerant
    # `swap`, and it produces the same defect the check tests for, because the check reads
    # the FIRST occurrence of each. A two-step `.replace()` form was whitespace-fragile and
    # is forbidden by `test_no_mutation_row_edits_the_skill_with_a_SILENT_matcher` besides.
    ("I10 hoist the unconditional stop above the arm, making the arm unreachable", _sub(
        "**The inherited-failure arm fires only when all three hold.**",
        "**On every other failure, stop.** **The inherited-failure arm fires only when all three hold.**")),
    ("I11 rename the Step 8 slot while keeping the INHERITED substring", _sub(
        "| INHERITED: <command> — fails on origin/<default",
        "| WAS-INHERITED: <command> — fails on origin/<default")),
    ("F3 retire the empty-set warning at Step 3", _sub(
        "**An empty list is a real outcome here, and it is the one to report rather than pass over.**",
        "An empty list needs no special handling.")),
    # ---- #206's semantics ----
    ("S1 turn skipped-not-failed into a failure", _sub(
        "**A surface absent from the changed-file list is `skipped`, not `failed`.**",
        "A surface absent from the changed-file list is a failure — stop the close.")),
    ("S2 drop the unclaimed-file reporting (the honesty half)", _sub(
        "**Then report every changed code file that no detected surface claimed**",
        "Changed files no surface claims need no reporting")),
    # ---- placement + recovery ----
    ("P1 retire the placement rationale", _sub(
        "**Placed here on purpose — after the merges, before `close_batch.sh` and before doc consolidation.**",
        "Placement is not significant; run it wherever is convenient after the merges.")),
    ("P2 drop the untracked fact that makes placement load-bearing", _sub(
        "those files are **untracked**", "those files are tracked")),
    ("P3 prescribe the destructive `direct` recovery", _sub(
        "**Do not `git reset --hard`**", "Run `git reset --hard origin/<default branch>`")),
    ("P4 skip the gate under the PR-reuse shape", _sub(
        "**Under the Step 4-pre PR-reuse shape this step still runs**",
        "Skip this step entirely under the Step 4-pre PR-reuse shape")),
    ("P5 let Step 3's resolution be carried forward", _sub(
        "Re-read it rather than carrying Step 3's result forward as a remembered value",
        "Reuse the list Step 3 already resolved")),
    # ---- reporting + scope ----
    ("R1 drop the Step 8 verification line", _sub(
        "Verification:  pre-merge", "Verified:      pre-merge")),
    # Anchored on the Step 8 TEMPLATE's form, not the bare label. `_sub` replaces the first
    # occurrence, and the first is Step 3's prose cross-reference to the line — mutating that
    # left the template intact and the mutation survived every check.
    ("R2 drop the unverified-surfaces line", _sub(
        "Unverified surfaces: <changed code files no detected surface claimed>",
        "Surfaces: <changed code files no detected surface claimed>")),
    ("R3 let --dry-run's green stand in for the merged gate", _sub(
        "**`4a-post` cannot run under `--dry-run`**", "`4a-post` also runs under `--dry-run`")),
    ("R4 drift 4a-post's scope command to two dots", _sub(
        RAW_SCOPE_POST, RAW_SCOPE_POST.replace("origin/<default branch>...HEAD", "origin/<default branch>..HEAD"),
        after=POST_HEADING)),
    ("R4b append a pathspec so 4a-post only ever sees markdown", _sub(
        RAW_SCOPE_POST, RAW_SCOPE_POST.replace("origin/<default branch>...HEAD", "origin/<default branch>...HEAD -- '*.md'"),
        after=POST_HEADING)),
    ("R4c degenerate range — always empty", _sub(
        RAW_SCOPE_POST, RAW_SCOPE_POST.replace("origin/<default branch>...HEAD", "origin/<default branch>...origin/<default branch>"),
        after=POST_HEADING)),
    ("R4d hoist the range into a variable", _sub(
        RAW_SCOPE_POST, '   RANGE=origin/<default branch>..HEAD && git diff --name-only "$RANGE"', after=POST_HEADING)),
    # R5/R5b were written against the pre-Phase-175 sentence, which propagated item 4's
    # doc-only skip into 4a-post. Phase 175 removed that propagation, so both mutations
    # are re-pointed at the sentence that replaced it — the rewrite takes its battery
    # with it (`_shared/adversarial-review.md` § Before you spawn anyone, rule 1).
    ("R5 restate the code-file extension LIST in 4a-post", _sub(
        "3. **Run the list**, applying item 3's surface gate to *this* list.",
        "3. **Run the list**, skipping unless a `.py` / `.ts` / `.tsx` / `.js` / `.sql` / `.go` / `.rs` file is in the list.")),
    ("R5b restate the LIST without backticks (the under-strict form)", _sub(
        "3. **Run the list**, applying item 3's surface gate to *this* list.",
        "3. **Run the list**, skipping unless a .py / .ts / .tsx / .js / .sql / .go / .rs file is in the list.")),
    ("R6 reconcile the Rule B site away", _sub(
        "**This is the gate `_shared/main-push-guard.md` Rule B re-runs, and Step 3 is not.**",
        "Rule B's re-run is a separate concern and is not addressed here.")),
    # Anchored on the clause, NOT the whole sentence: Phase 239 changed this
    # sentence's terminal punctuation (`:` -> `.`, because Step 4b now opens with
    # prose rather than straight into the fence) and broke a full-sentence pin
    # that was only ever asserting the `4a-post` reference. Pin the property.
    ("R7 strip 4b's lead-in reference to the gate", _sub(
        "and `4a-post` reported green, but **before** doc consolidation",
        "but **before** doc consolidation")),
    # ---- the round's findings: each survived the first version's whole battery ----
    ("W1 restore Step 4a's route past the gate", _sub(
        "go straight to **`4a-post`** — **not** to Step 4b.", "go straight to Step 4b.")),
    ("W2 ship both sentences (the pin alone would pass)", _sub(
        "go straight to **`4a-post`** — **not** to Step 4b.",
        "go straight to **`4a-post`** — **not** to Step 4b. On reflection, go straight to Step 4b.")),
    ("W3 add a NEW route past the gate somewhere else entirely", _sub(
        "### 4b. Close Merged Batches\n",
        "### 4b. Close Merged Batches\n\nIf you are in a hurry, proceed to Step 4b directly.\n")),
    ("W4 let item 4's skip swallow the item-5 stop again", _sub(
        "**The item-5 stop is about the run, not about this pass — resolve before you skip.**",
        "Item 4 is evaluated first; if it skips, the rest of the list is moot.")),
    ("W5 let a fully surface-gated 4a-post report green", _sub(
        '**If the surface gate leaves nothing to run while the list still contains a code file, that is "ran nothing", not green**',
        "If the surface gate leaves nothing to run, the pass is green")),
    # ---- assumption mutations (author-side pass rule 1) ----
    # Not reverts of text the checks assert. Each attacks something a CHECK assumes, which
    # is the half a revert-only mutation set reports a kill rate for while saying nothing
    # about.
    ("A1 delete the Step 8 template's verification block outright", lambda t: re.sub(
        r"Verification:  pre-merge.*?Unverified surfaces: <[^\n]*\n", "", t, count=1, flags=re.S)),
    ("A2 keep 4a-post's fence but leave only comments in it", _sub(
        RAW_SCOPE_POST, "   # (see Step 3 for the command)", after=POST_HEADING)),
    ("A3 re-fence Step 3's scope block as ```text", _sub(
        "```bash\n# The changed-file list for THIS pass", "```text\n# The changed-file list for THIS pass")),
    ("A3b re-fence 4a-post's scope block as ```console", lambda t: (
        t[:_at(t, "### 4a-post.")]
        + t[_at(t, "### 4a-post."):_at(t, "### 4b. Close Merged Batches")].replace("```bash", "```console", 1)
        + t[_at(t, "### 4b. Close Merged Batches"):])),
    ("A4 rename the Step 3c heading that bounds two sections", _sub(
        "## Step 3c: Manual Smoke Gate", "## Step 3d: Manual Smoke Gate")),
    # Phase 175 split the 4a-post report arm across two lines to add `ran nothing` — the
    # deletion has to take both, or the check is still satisfied by the remnant.
    ("A5 satisfy the report check from the --dry-run mention alone", _sub(
        "               merged-tree (4a-post) <ran on <merge target>: N commands\n"
        "                                      | ran nothing: why | not reached: why\n"
        "                                      | TIMEOUT: <command> — killed, so it returned no\n"
        "                                        verdict. The tree is UNVERIFIED: neither passed\n"
        "                                        nor failed, and never folded into \"ran N commands\".\n"
        "                                      | INHERITED: <command> — fails on origin/<default\n"
        "                                        branch> too; <TASK-ID> is in this close's Step 4c\n"
        "                                        set. The gate RAN and a command FAILED; the close\n"
        "                                        continued because 4a-post item 4's three\n"
        "                                        preconditions all held. Never folded into \"ran N\n"
        "                                        commands\" either — that would report a failing\n"
        "                                        command as a passing one.>\n",
        "")),
    # ---- the round's survivors. 49 of its 63 mutations lived against the first version;
    # these are the ones that named a distinct bypass rather than a variant of one. ----
    ("H01 delete the run-the-list instruction — the gate verifies nothing", lambda t: (
        t[:_at(t, "3. **Run the list**")]
        + t[_at(t, "4. **On failure, stop — unless"):])),
    ("H02 turn the run into a non-instruction", _sub(
        "3. **Run the list**, applying", "3. **Do not run the list** — each branch's worktree already ran it. Skip, ignoring")),
    ("H04 make the run optional", _sub(
        "3. **Run the list**, applying", "3. **Run the list** if convenient (optional), applying")),
    ("H60 declare the whole step optional while keeping every pin", _sub(
        "### 4a-post. Verify the Merged Tree\n",
        "### 4a-post. Verify the Merged Tree\n\n**This step is OPTIONAL and is skipped by default.**\n")),
    ("H24 tell the gate to run after the step it gates", _sub(
        "3. **Run the list**, applying", "3. **Run the list after Step 4b's close-batch commit lands**, applying")),
    ("H25 reorder by prepending an instruction", _sub(
        "1. **Re-resolve the command list**", "**Run Step 4b first, then come back here.**\n\n1. **Re-resolve the command list**")),
    ("H49 let a failure not stop the close", _sub(
        "4. **On failure, stop — unless the failure is one this close inherited and is about to repair.",
        "4. **On failure, note it and continue.** Unless the failure is one this close inherited and is about to repair.")),
    ("H51 reintroduce the Step 3c coupling in Step 3 instead", _sub(
        "**The item-5 stop is about the run",
        "If Step 3 was skipped (doc-only diff), skip Step 3c too.\n\n**The item-5 stop is about the run")),
    ("H52 reintroduce it in Step 3b instead", _sub(
        "## Step 3b: Prepare Worktrees for Merge\n",
        "## Step 3b: Prepare Worktrees for Merge\n\nIf Step 3 was skipped (doc-only diff), skip Step 3c too.\n")),
    ("H05 delete the report fence, keep the tokens in prose", lambda t: (
        t[:_at(t, "```\nReview Complete.")]
        + "Mention Verification:, Unverified surfaces: and merged-tree (4a-post) if you feel they add value.\n"
        + t[_at(t, "If `$ARGUMENTS` contains `--dry-run`"):])),
    ("H07 HTML-comment the report's verification lines", _sub(
        "Verification:  pre-merge", "<!-- Verification:  pre-merge")),
    ("H42 move the --dry-run disclaimer into an HTML comment", _sub(
        "**`4a-post` cannot run under `--dry-run`**", "<!-- **`4a-post` cannot run under `--dry-run`** -->")),
    ("H43 negate the --dry-run disclaimer in place", _sub(
        "**`4a-post` cannot run under `--dry-run`**",
        "It is a myth that **`4a-post` cannot run under `--dry-run`**")),
    # ---- population ----
    ("Z blank the whole skill", lambda t: ""),
]

# Mutations that must SURVIVE — the over-strictness direction, which is the one that hides.
# A guard that fails on a legitimate rewrite trains people to weaken it, and the round found
# five such edits going red against the first version.
NON_MUTATIONS: list[tuple[str, Callable[[str], str]]] = [
    ("N1 join the scope command onto one line (equivalent)", _sub(
        RAW_SCOPE_POST,
        '   git rev-parse --verify --quiet origin/<default branch> >/dev/null && git diff --name-only origin/<default branch>...HEAD || echo "NO_ORIGIN_MAIN"', after=POST_HEADING)),
    ("N2 space the redirection (equivalent)", _sub(
        RAW_SCOPE_POST, RAW_SCOPE_POST.replace(">/dev/null", "> /dev/null"),
        after=POST_HEADING)),
    # N3/N4 re-pointed by Phase 248: Step 4b's primary invocation gained
    # `--merge-target` (`Q-308`), so the old literal no longer existed and both
    # controls died on `_sub`'s source assert rather than measuring anything.
    # The MUTATIONS are unchanged in kind -- add `--force` to the primary
    # invocation; re-fence a redundant close_batch block -- and N4 now uses the
    # cherry-pick block, which is the redundant one it was always describing.
    ("N3 Step 4b ships only the --force form the skill mandates under pr", _sub(
        'bash sysop/scripts/close_batch.sh --merge-target "<merge target>" <N1> <N2> <N3>\n```',
        'bash sysop/scripts/close_batch.sh --force --merge-target "<merge target>" <N1> <N2> <N3>\n```',
        after=SECTIONS["step4b"][0])),
    ("N4 re-fence ONE redundant close_batch block (invariant intact)", _sub(
        '```bash\nbash sysop/scripts/close_batch.sh --force --merge-target "<merge target>" <N1> <N2> <N3>\n```',
        '```text\nbash sysop/scripts/close_batch.sh --force --merge-target "<merge target>" <N1> <N2> <N3>\n```')),
    ("N5 mention one code extension in 4a-post prose (an example, not a list)", _sub(
        "naming the surfaces gated out and the unclaimed files.",
        "naming the surfaces gated out and the unclaimed files (a stray `.sql` file, say).")),
]


@pytest.mark.parametrize("name,mutate", NON_MUTATIONS, ids=[m[0] for m in NON_MUTATIONS])
def test_legitimate_rewrites_do_not_go_red(name, mutate):
    shipped = _text()
    rewritten = mutate(shipped)
    assert rewritten != shipped, f"{name!r} was a no-op — it no longer matches the shipped text"
    failures = [f for check in CHECKS for f in check(rewritten)]
    assert not failures, f"{name!r} is a legitimate rewrite but went red: {failures}"


def test_no_mutation_row_edits_the_skill_with_a_SILENT_matcher():
    """`Q-495`'s own lesson, turned on this table. A row that half-applies reports nothing.

    `str.replace` returns the string unchanged when it finds nothing and `str.index` at
    least raises, so a row built from chained `.replace` calls can have one half quietly
    match nothing and still look like a working mutation — `mutate(t) != t` is satisfied by
    the other half. That is not hypothetical: `O1`, the table's ONLY ordering mutation,
    had a second `.replace` targeting `"   " + CLOSE_BATCH + "\n"`, a line the file has
    never contained (the shipped call carries `--merge-target` arguments and sits at
    column 0). For as long as it shipped, `O1` was a pure DELETION of the clean-tree probe
    wearing the name of a move, and nothing tested ordering. Found by this phase's round.

    So every edit to the skill text goes through `swap`/`_at`, which fail loud. This is a
    source-level check because the failure is invisible at run time by construction.
    """
    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    start = src.index("MUTATIONS: list[tuple[str")
    # The first `@pytest.mark.parametrize` AFTER the tables, not the first in the file --
    # there is one 150 lines earlier, and taking it produced an inverted slice, so this
    # guard scanned an EMPTY string and passed over anything. Caught by checking that it
    # actually bites on a reintroduced `t.replace(`, which is the only way to see it.
    end = src.index("@pytest.mark.parametrize", start)
    tables = src[start:end]
    assert '("O1 move the gate' in tables and len(tables) > 5000, (
        f"the scanned region is not the mutation tables ({len(tables)} chars) — this "
        "guard is measuring nothing"
    )
    offenders = [
        ln.strip() for ln in (tables + _MOVE_PROBE_SOURCE).splitlines()
        if re.search(r"\bt\.replace\(|\btext\.replace\(|\bt\.index\(|\btext\.index\(", ln)
    ]
    assert not offenders, (
        "a mutation row edits the skill with a matcher that fails silently; use "
        "`swap()`/`_at()` so a stale anchor is loud:\n  " + "\n  ".join(offenders)
    )


@pytest.mark.parametrize("name,mutate", MUTATIONS + NON_MUTATIONS,
                         ids=[m[0] for m in MUTATIONS + NON_MUTATIONS])
def test_every_anchor_survives_a_rendering_identical_rewrap(name, mutate):
    """`Q-495`: a reformat that changes no meaning must not stale a mutation anchor.

    Every row here pins the pre-mutation text. When that text is re-wrapped the row stops
    applying, and the suite goes red for a REFORMAT while every rule the row protects is
    intact — and the fix each time is to re-type a literal in a test, a re-approval with
    no review in it. Phase 291 met this with a single-sentence control and lost one row.
    Measured at this phase's open with a maximal re-wrap, which breaks every raw
    multi-word anchor at once rather than sampling one wrap position: **33 of these 59
    rows** stopped applying. After `_sub`/`_at` were routed through the tolerant matcher,
    zero did.

    This is the guard, not the measurement: it re-wraps the shipped text and requires the
    row to still land. It cannot go vacuous, because `rewrapped()` asserts that it changed
    something and that it changed only whitespace.
    """
    wrapped = rewrapped(_text())
    assert wrapped != _text()
    assert mutate(wrapped) != wrapped, (
        f"{name!r} became a no-op on re-wrapped text — its anchor is whitespace-fragile"
    )


@pytest.mark.parametrize("name,mutate", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_every_mutation_is_caught(name, mutate):
    shipped = _text()
    mutated = mutate(shipped)
    assert mutated != shipped, f"mutation {name!r} was a no-op — it no longer matches the shipped text"
    failures = [f for check in CHECKS for f in check(mutated)]
    assert failures, f"mutation {name!r} survived every check"


def test_the_external_checks_are_not_vacuous():
    """The mutation table only edits the skill file, so it cannot reach the three checks
    whose population is main-push-guard.md, the two specs, and the two sibling skills.
    Prove those directly rather than letting them ride on an untested population."""
    guard = GUARD.read_text(encoding="utf-8")
    assert "RE-RUN review-close 4a-post" in _flat(guard)
    # the pre-fix instruction really is gone, not merely accompanied
    assert "RE-RUN review-close Step 3 (the project's" not in _flat(guard)
    wf = _flat(WORKFLOW.read_text(encoding="utf-8"))
    gd = _flat(GUIDE.read_text(encoding="utf-8"))
    assert "5b. **Run verification — the merged-tree pass**" in wf
    assert "Run full verification on the merged result" in gd


def test_every_pin_and_forbidden_phrase_names_a_resolvable_section():
    for key, _span, _why in PINS:
        assert key in SECTIONS, f"pin references unknown section {key!r}"
    for key, _phrase, _why in FORBIDDEN:
        assert key in SECTIONS, f"forbidden phrase references unknown section {key!r}"


def test_slice_fails_closed_on_a_missing_end_marker():
    text = _text()
    assert _slice(text, "post")
    broken = text.replace("### 4b. Close Merged Batches", "### 4b. Closing Merged Batches")
    assert _slice(broken, "post") == ""


def test_exec_offset_ignores_prose_and_comments():
    """The ordering check's admissibility rule, tested directly — a prose copy of a command
    must not be able to satisfy it."""
    prose = f"Run `{CLEAN_PROBE}` before Step 4b.\n"
    assert _exec_offset(prose, CLEAN_PROBE) == -1
    commented = f"```bash\n# {CLEAN_PROBE}\n```\n"
    assert _exec_offset(commented, CLEAN_PROBE) == -1
    real = f"```bash\n{CLEAN_PROBE}\n```\n"
    assert _exec_offset(real, CLEAN_PROBE) >= 0
