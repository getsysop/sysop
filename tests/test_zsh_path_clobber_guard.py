"""The `path=` clobber class (Phase 287, `Q-486`).

In zsh -- the default login shell on macOS, and therefore the shell that
executes a great many of the bash blocks these skills ship -- `path` is tied to
`$PATH`.  A bare `path=…` empties the command search path, and every later
command in that block dies with `command not found`.

Two shapes carry the hazard, and they differ in how the damage surfaces:

  * a skill that PRESCRIBES per-item shell work without shipping the loop, so
    the agent writes one and picks the variable name itself; and
  * a skill that hands a sub-agent a command TEMPLATE carrying a `<path>`
    placeholder, which reads as a suggested variable name.

Both were unguarded before this file existed.  `/review-close` carried the
remedy at two sites and lacked it at two more -- the sweep that found them ran
only because a triage found one of them by hand.

The sharp part is the FAILURE SIGNATURE, which is why a bare "don't do that" is
not enough and the remedy text has to survive:  under the ordinary
`out=$(git show "$rev:$entry" 2>/dev/null)` idiom the clobber yields EMPTY
STDOUT with the only evidence on the stderr that idiom discards.

It is NOT byte-identical to a body that genuinely lacks the heading -- that one
returns its content -- and an earlier draft of this docstring said it was.  The
collision is one level up and survives the correction: Step 2d's step 1 asks
whether the output holds a `test decision` heading, and neither a clobbered read
nor a body without one has it, so BOTH classify `missing`.  A good body is then
reported as a missing record, the halt fires, and an approved branch is demoted
-- on a shell bug.  Guarding the remedy text is guarding against that.
"""
import re
import sys
from pathlib import Path as _P

sys.path.insert(0, str(_P(__file__).resolve().parent))

from _prose_guard_helpers import carries, locate  # noqa: E402
import pathlib

import pytest

SKILLS = sorted(pathlib.Path("core/skills").rglob("*.md"))

# A command template an agent runs once per item, over a path-shaped placeholder.
TEMPLATE = re.compile(r"`(git\s+(?:show|-C)\s[^`]*)`")

# LOWERCASE placeholder only.  `<WORKTREE_PATH>` in a one-shot `git -C … rev-parse`
# is plainly a value to substitute; `<path>` in a template the agent will loop over
# reads as a suggested variable name.  That difference is the whole hazard, and an
# earlier draft of this guard ignored it and produced 13 false positives -- every
# one a one-shot command or a sentence *about* the trap.
PATHISH = re.compile(r"<(?=[a-z…])[a-z0-9 …\-]*(?:path|body|file|dir|doc)[a-z0-9 …\-]*>")

# ARM A -- the site prescribes iteration in prose and ships no loop.  Without this
# the guard fires on every `git show` in the tree, which is not the class.
ITER = re.compile(r"\bfor each\b|\bfor every\b", re.I)

# ARM B -- the template sits in a PROMPT handed to a sub-agent.  A reviewer reads
# across many files by definition, so it will write a loop whether or not the
# surrounding prose contains the words "for each".  Keying arm B on ITER was this
# guard's fourth wrong cut: it excused `/codebase-review` and `/security-audit`,
# which carry the same reviewer sentence as `/review-close` verbatim.
PROMPT_INTRO = re.compile(r"`?prompt`?\s*:|You are (?:the|a|an)\b|Do NOT mutate repository state")

# Something that BINDS the name for the agent, so it does not invent one.
BINDER = re.compile(
    # SHELL loops only.  A Python `for name in SECTIONS:` ends in a colon and binds
    # nothing for a shell template -- yet one, 170 lines away in a different fenced
    # block, silently excluded a real site once the window went bidirectional.
    r"(?:^|\|\s*)\s*(?:for\s+[a-z_]+\s+in\b(?![^\n]*:\s*$)"
    r"|while\s+[^|]*read\s+(?:-r\s+)?[a-z_]+)"
)

# The remedy, as shipped.  Stated in full at each site on purpose: `/review-close`
# Step 2d records that a rule held only by pointing at another skill's code moves
# when that code does, and this rule has no single home to point at.
# `\s+` spans newlines (a wrapped remedy is still the remedy); the `\**` on both
# sides allows ordinary emphasis -- `**never**`, `never **`path`**` -- which an
# independent control set showed the first version false-redding on.
REMEDY = re.compile(r"never\**\s+\**`path`", re.I)

# A substring test cannot tell the rule from its negation.  An independent battery
# replaced a site's rule with "An older draft said to name it `entry` and never
# `path`; in zsh that was over-cautious, so name the loop variable `path` if you
# prefer" -- which satisfies REMEDY, satisfies the states-it-in-full test (it
# contains `entry` and `zsh`), and revokes the rule.  REVOCATION catches the shape
# that mutation used: a permission to use `path` anywhere near the remedy.
REVOCATION = re.compile(
    r"(name\s+(the\s+)?(loop\s+)?variable\s+`path`"          # "name the variable `path`"
    r"|use\s+`path`"                                          # "use `path`"
    r"|`path`\s+(is\s+)?(fine|ok|okay|acceptable|safe)"        # "`path` is fine"
    r"|over-?cautious"                                         # the hedge that sells it
    r"|if\s+you\s+prefer)",
    re.I,
)

LOOKBACK = 40    # how far above a template the prescribing "for each" may sit
BIND_REACH = 60  # how far BELOW a template its own shipped loop may sit

# Reach for a binder or the remedy is the ENCLOSING SECTION, not a line count.
# A line count is a number tuned until the tree passes; the section is the unit a
# reader actually works in, and it is where "this step says so" has to be true.
# Step 1a's own binder sits 47 lines below its prose and its remedy 84 -- both in
# the same step, and both invisible to any window small enough to be meaningful.
HEADING = re.compile(r"^\s{0,3}(#{1,6})\s")

# A `# comment` inside a fenced bash block matches HEADING exactly.  An earlier
# draft of this guard had no fence model and truncated Step 1a's section at the
# first shell comment, 3 lines in -- so the guard reported the step unprotected
# while its binder and its remedy both sat further down the same step.
FENCE = re.compile(r"^\s{0,5}(`{3,}|~{3,})(.*)$")


def _fenced(lines):
    """Line indices inside a fenced block.  An opener may carry an info string;
    a closer may not, and must use the same character, at least as long."""
    out, open_i, mark = set(), None, None
    for i, ln in enumerate(lines):
        m = FENCE.match(ln)
        if not m:
            continue
        ch, rest = m.group(1), m.group(2).strip()
        if open_i is None:
            open_i, mark = i, ch
        elif ch[0] == mark[0] and len(ch) >= len(mark) and rest == "":
            out.update(range(open_i, i + 1))
            open_i = mark = None
    if open_i is not None:
        out.update(range(open_i, len(lines)))
    return out


def _section_start(lines, i, fenced):
    """Start of the section containing line `i` -- the nearest heading at or above it.

    The window must look BACKWARD as well as forward.  Phase 287's own round found
    the reason: the right place for the naming rule is the command block the agent
    copies from, which sits ABOVE the templates further down the step.  A
    forward-only window penalised exactly the placement the round asked for.
    """
    for j in range(i, -1, -1):
        if HEADING.match(lines[j]) and j not in fenced:
            return j
    return 0


def _section_end(lines, i, fenced):
    """End of the section containing line `i`: the next heading at the same or a
    shallower depth than the nearest heading above it, else EOF.  Headings inside
    a fence are shell comments, not headings."""
    depth = None
    for j in range(i, -1, -1):
        m = HEADING.match(lines[j])
        if m and j not in fenced:
            depth = len(m.group(1))
            break
    if depth is None:
        return len(lines)
    for j in range(i + 1, len(lines)):
        m = HEADING.match(lines[j])
        if m and j not in fenced and len(m.group(1)) <= depth:
            return j
    return len(lines)


def _sites():
    """Every (file, line, template) where an agent is told to iterate, handed a
    per-item path template, and given no loop variable bound for it."""
    out = []
    for f in SKILLS:
        lines = f.read_text().split("\n")
        fenced = _fenced(lines)
        for i, ln in enumerate(lines):
            for tmpl in TEMPLATE.findall(ln):
                if not PATHISH.search(tmpl):
                    continue
                back = lines[max(0, i - LOOKBACK) : i + 1]
                arm_a = any(ITER.search(w) for w in back)
                arm_b = i in fenced and any(PROMPT_INTRO.search(w) for w in back)
                if not (arm_a or arm_b):
                    continue  # a one-shot command, not per-item work
                # TWO windows, because the two lookups mean different things.
                # A BINDER answers "does the skill ship the loop for THIS template"
                # -- that loop is local and below it, so the window is the next
                # fenced block.  A REMEDY answers "does this step warn the reader"
                # -- a step-wide question, and the right placement is ABOVE the
                # template, at the command block the agent copies from.
                bind_end = min(i + BIND_REACH, _section_end(lines, i, fenced))
                if any(BINDER.search(w) for w in lines[i:bind_end]):
                    continue  # the skill ships the loop and names the variable
                window = lines[
                    _section_start(lines, i, fenced) : _section_end(lines, i, fenced)
                ]
                out.append((f, i + 1, tmpl, window))
    return out


# The census, per file.  A bare "is the list non-empty" sentinel is satisfied by
# ONE site anywhere in the tree: an independent battery hid all seven real sites
# behind uppercase placeholders, deleted every remedy, appended a single decoy
# section to an unrelated skill, and the suite stayed green at exit 0 -- real
# coverage zero.  A per-file census is what makes that visible, because the decoy
# lands in a file that is not supposed to have sites and the losses land in files
# that are.
EXPECTED_SITES = {
    "core/skills/codebase-review/SKILL.md": 1,
    "core/skills/review-close/SKILL.md": 5,
    "core/skills/security-audit/SKILL.md": 1,
}


def test_the_site_census_is_exact():
    """G4/G5. Pin WHERE the sites are, not just that some exist.

    Every survivor of the independent battery's detector attacks worked the same
    way -- a cosmetic edit (`<path>` -> `<PATH>`, `<path>` -> `<path_to_file>`,
    `git show` -> `git cat-file -p`) made a site invisible AND deleted its remedy,
    and the parametrised run simply reported one fewer passing case.  Nothing
    noticed, because nothing counted.

    A change to this dict is a real decision: either a site was legitimately added
    or removed, or the detector just went blind.  Say which in the commit.
    """
    got = {}
    for f, _line, _tmpl, _w in _sites():
        got[str(f)] = got.get(str(f), 0) + 1
    assert got == EXPECTED_SITES, (
        "the per-item path-template census changed.\n"
        f"  expected: {EXPECTED_SITES}\n"
        f"  actual  : {got}\n"
        "A file that LOST sites means either the template was reworded past the "
        "detector (`<PATH>`, `<path_to_file>`, `git cat-file`) or the site was "
        "removed. A file that GAINED them means a new unguarded template, or a "
        "decoy. Neither is a thing to re-baseline without reading."
    )


def test_the_class_is_not_empty():
    """If this ever goes to zero the detector has broken, not the tree.

    Kept alongside the census as the cheaper, louder signal: a total detector
    break trips this with an error a reader understands immediately.
    """
    assert _sites(), (
        "the per-item path-template detector matched nothing in core/skills/**; "
        "the detector is broken, not the tree -- a zero here is not a pass"
    )


@pytest.mark.parametrize(
    "site", _sites(), ids=lambda s: f"{s[0].parent.name}:{s[1]}" if isinstance(s, tuple) else ""
)
def test_every_unbound_path_template_carries_the_naming_rule(site):
    f, line, tmpl, window = site
    # Joined, not per-line: a line wrap between `never` and `path` is a legal
    # reflow, and matching per line made three ordinary copy-edits fail.
    assert REMEDY.search("\n".join(window)), (
        f"{f}:{line} hands an agent the per-item template `{tmpl}` with no loop "
        f"variable bound for it and no `never `path`` rule in its section.\n"
        f"The agent writes the loop, names it `path`, and in zsh that empties "
        f"$PATH. Under `2>/dev/null` the result is EMPTY STDOUT, so a reader "
        f"looking for a heading finds none -- the same answer a file without "
        f"one gives, which is how a failed read is classified as a real absence."
    )


def test_no_site_revokes_the_rule_while_appearing_to_state_it():
    """G6. `REMEDY` is a substring test; this is the semantic half.

    A site can satisfy every other assertion in this file and still tell the
    reader to do the one thing the rule forbids.  Measured: a mutation doing
    exactly that survived the whole suite.
    """
    bad = []
    for f in SKILLS:
        lines = f.read_text().split("\n")
        for i, ln in enumerate(lines):
            if not REMEDY.search("\n".join(lines[i : i + 3])):
                continue
            ctx = "\n".join(lines[max(0, i - 2) : i + 8])
            if REVOCATION.search(ctx):
                bad.append(f"{f}:{i + 1}")
    assert not bad, (
        "these sites carry the naming rule and, within a few lines, language that "
        f"licenses `path` anyway -- the rule is revoked where it is stated: {bad}"
    )


def test_the_remedy_is_stated_in_full_at_every_site():
    """Each copy must be self-contained -- not a pointer to another line.

    `entry`, `path` and the zsh mechanism all have to be present, so a later
    edit cannot shrink a site to "see :205" and leave the reader to go looking.
    """
    thin = []
    for f in SKILLS:
        lines = f.read_text().split("\n")
        for i in range(len(lines)):
            # match over a small joined span so a wrapped remedy is still found
            span = "\n".join(lines[i : i + 3])
            if not REMEDY.search(span):
                continue
            if i and REMEDY.search("\n".join(lines[i - 1 : i + 3])) and not REMEDY.search(lines[i]):
                continue  # already counted at the previous line
            ctx = "\n".join(lines[max(0, i - 3) : i + 12])
            if not (re.search(r"`entry`", ctx) and re.search(r"zsh", ctx, re.I)):
                thin.append(f"{f}:{i + 1}")
    assert not thin, (
        "these copies of the naming rule do not state the mechanism -- each site "
        f"must name `entry` and zsh within its own context: {thin}"
    )


def test_step_2d_routes_the_silent_read_away_from_missing():
    """The clobber's signature IS `missing`'s signature. Step 2d must say so.

    Without this, the four enumerated `unreadable` outcomes are each identified
    by a distinct git fatal, the fifth produces no message at all, and the
    classification it falls through to is the one the list exists to refuse.
    """
    body = pathlib.Path("core/skills/review-close/SKILL.md").read_text()
    i = body.find("### 2d. Test-Decision Verification")
    assert i > 0, "### 2d. is gone -- this guard has lost its subject"
    j = body.find("\n### ", i + 10)
    step = body[i : j if j > 0 else len(body)]

    assert "command not found" in step, (
        "Step 2d does not name the `command not found` outcome; a clobbered "
        "$PATH then has no arm and falls through to `missing`"
    )
    assert re.search(r"None\s+of\s+the\s+five\s+is\s+`missing`", step), (
        "Step 2d's summary still counts four outcomes -- the fifth was added "
        "without updating the count that tells the reader how many to expect"
    )
    assert re.search(r"[Ee]mpty\s+output\s+is\s+not\s+evidence", step), (
        "Step 2d's `missing` definition does not rule out a silent failed read, "
        "so empty stdout still classifies as an absent heading"
    )

    # The three below were SURVIVORS of this phase's own second mutation battery.
    # Each is a one-token edit that reverts the fix while every other assertion
    # here stays green -- which is what "the guards were weaker than their author
    # said" means in practice.
    i5 = locate(step, "command not found").start()
    disposition = step[i5 : step.index("\n\n", i5)]
    assert re.search(r"as\s+`unreadable`", disposition), (
        "the fifth outcome no longer DISPOSES to `unreadable`. Routing it to "
        "`missing` is the defect the whole arm exists to prevent, and it is a "
        "one-word edit that leaves the outcome enumerated and every count correct"
    )
    assert carries(disposition, "empty stdout"), (
        "the fifth outcome no longer states the empty-stdout mechanism -- which is "
        "the entire reason it belongs on the `unreadable` list rather than being "
        "treated as a shell error the reader will obviously notice"
    )
    # A8/A9 -- survivors of the second battery's re-run. Both clauses state a
    # CORRECTION: the first draft of this bullet claimed the clobber's output was
    # byte-identical to a body lacking the heading, and the author-side rule-4
    # corpus refuted it (a real body returns its content). A correction with no
    # guard is the shape this project keeps re-deleting and then re-discovering.
    # The first version of these two assertions pinned DIGITS as string literals --
    # `"49 bytes against 0"` and the exact `127 / 0 / 128` sentence. An independent
    # battery showed what that buys: re-measuring 49 to a correct 52 was KILLED,
    # while inverting the surrounding claim to "the outputs ARE byte-identical"
    # SURVIVED. It punished a correction and was blind to a falsehood -- a
    # spell-check wearing a guard's error message. The `49` is now gone from the
    # skill entirely (no fixture in the tree produces it, and real bodies measure
    # 45-113 bytes), and what is pinned here is the RELATION the measurement was
    # evidence for, in the section that now carries it.
    assert re.search(r"[Tt]hree\s+different\s+states\s+produce\s+zero\s+bytes", step), (
        "Step 2d no longer says that empty output is produced by more than one "
        "state. That is the whole reason silence cannot identify an outcome, and "
        "without it a reader treats zero bytes as a diagnosis"
    )
    assert re.search(r"\*\*127\*\*.*\*\*128\*\*.*\*\*0\*\*", step, re.S), (
        "the exit-status discriminator is gone. It is the one signal that DOES "
        "separate the outcomes that share a silent stdout"
    )
    assert re.search(r'"did the command run\?" check passes', step), (
        "Step 2d no longer warns that outcome 4's quiet sub-case PASSES a "
        "did-it-run check -- it exits 0. Without this the prescribed check reads "
        "as sufficient, and it is not"
    )

    assert re.search(r"\*\*Five\s+distinct\s+outcomes\s+land\s+here", step), (
        "the `unreadable` lead-in still counts four. The count is stated twice -- "
        "at the lead-in and at the summary -- and an edit that reverts one and not "
        "the other tells the reader to stop looking after the fourth"
    )
