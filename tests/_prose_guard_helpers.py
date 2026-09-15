"""Shared helpers for prose drift guards (Phase 235's round, guards lens).

**Why this exists.** Phase 235 shipped a set of guards over shipped prose, every one of
them shaped `assert "<literal>" in <whole file>`. An independent reviewer ran 64 mutations
against them and **41 survived (64%)**, against the author's reported 17/17. The survivors
were not exotic. They were four mechanical properties of that shape:

1. **A substring survives inside its own negation.** `assert "gate the WORK, not the merge"
   in mirror` passes on *"It is NOT the case that those steps gate the WORK, not the
   merge."* — which is the retired claim, restored, with the guard green.
2. **A substring is satisfied by an incidental hit elsewhere in the file.** `assert "waive"
   in body` passes with the whole rationale deleted, because `review-close/SKILL.md` uses
   "waive"/"waived"/"waiver" twelve times for unrelated reasons.
3. **A section slice keyed to the next `## ` swallows every deeper heading between.** The
   `### User ops` "section" was 6,382 characters and contained all of `### Solo`, so a
   phrase planted in one satisfied a guard about the other.
4. **A population filtered by suffix silently omits shipped files.** Extensionless git
   hooks, `.fragment` and `.example` files are shipped and were outside the sweep.

`states()` and `section()` close 1–3. The sweep's population fix closes 4 at its call site.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# Markers that turn a statement into its opposite. Checked only within the sentence
# carrying the phrase, so an unrelated "not" elsewhere in the paragraph is not a false kill.
_NEGATORS = (
    "not the case", "is false", "it is false", "no longer", "not true",
    "retired", "ignore any claim", "do not read", "never actually",
    "is wrong", "was wrong", "incorrect", "disregard", "except that",
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n\n")


def _sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def states(haystack: str, phrase: str) -> bool:
    """True when `haystack` ASSERTS `phrase` — present, and not inside a negation.

    The sentence carrying the phrase must not also carry a negator, and must not negate
    the phrase directly ("It is NOT the case that <phrase>"). A file that mentions the
    phrase only to retire it does not count as stating it.
    """
    if phrase not in haystack:
        return False
    for sentence in _sentences(haystack):
        if phrase not in sentence:
            continue
        low = sentence.lower()
        before = low[: low.index(phrase.lower())] if phrase.lower() in low else low
        if any(n in low for n in _NEGATORS):
            continue
        # "is not a restatement" is an assertion; " NOT <phrase>" immediately before is not.
        if re.search(r"\b(?:not|n't|never)\b[^.]{0,40}$", before):
            continue
        return True
    return False


def section(text: str, heading: str) -> str:
    """The body of `heading`, ending at the next heading of the SAME OR HIGHER level.

    `heading` is the full markdown heading line, e.g. `### Solo`. Raises AssertionError
    (never ValueError) with a message naming the problem, and requires the heading to be
    unique — a decoy duplicate earlier in the file silently redirected the original guard.
    """
    level = len(heading) - len(heading.lstrip("#"))
    marker = "\n" + heading + "\n"
    count = text.count(marker)
    assert count == 1, f"expected exactly one {heading!r} heading, found {count}"
    start = text.index(marker)
    rest = text[start + len(marker):]
    # any heading at level <= this one closes the section
    closer = re.compile(r"^#{1,%d} \S" % level, re.MULTILINE)
    m = closer.search(rest)
    return heading + "\n" + (rest[: m.start()] if m else rest)


def normalize(text: str) -> str:
    """Fold the variations a per-line literal regex misses: unicode dashes, `_`/`*`
    emphasis, and hard-wrapped lines. Used by the retired-claim sweep."""
    text = unicodedata.normalize("NFKC", text)
    for dash in ("‐", "‑", "‒", "–", "—", "−"):
        text = text.replace(dash, "-")
    text = re.sub(r"[*_`]+", "", text)
    return re.sub(r"\s+", " ", text)


# --------------------------------------------------------------------------------------
# Whitespace-tolerant anchors (Phase 292, `Q-495`).
#
# Phase 291 ran four rendering-identical reformats of `review-close/SKILL.md` against the
# guards over it. Three went red, and in two of them the failing assertion was a shipped
# test's MUTATION ANCHOR rather than a rule: the row pins the pre-mutation text as a
# literal, so re-wrapping that text staled the anchor while every rule it protects was
# intact. `tools/mutation_battery.py` names the same class as the FIRST of its measured
# requirements -- "Anchors are derived at run time, not retyped", Phase 186's seven
# `SKIPPED` rows -- and it had not reached the shipped guards, only the one-off batteries.
# --------------------------------------------------------------------------------------

# A SOFT break or horizontal whitespace: optional spaces around at most ONE newline, or
# spaces alone. Deliberately not `\s+`. `\s+` also matches a blank line, which would let
# an anchor match across a paragraph boundary and quietly join two unrelated sentences --
# a widening, not a tolerance. A re-wrap never inserts a blank line inside a paragraph,
# because that would split the paragraph and change the rendering, so one newline is the
# whole of what a legitimate reformat can add.
_SOFT_BREAK = r"(?:[^\S\n]*\n[^\S\n]*|[^\S\n]+)"

# The TRAILING boundary matches MINIMALLY: one line break, or one space. The interior form
# above is greedy, which is right between two words -- all the whitespace there belongs to
# the phrase. At the end it does not: a phrase ending `…<default branch>\n` matched
# `…<default branch>\n  `, swallowing the NEXT line's indentation, and `swap()` replacing
# that span then de-indented the fence closer that followed it. Same corruption the
# leading-boundary rule already prevents, arriving from the other end; found by this
# phase's round on a live mutation row.
_TRAILING_BREAK = r"(?:[^\S\n]*\n|[^\S\n])"


@lru_cache(maxsize=None)
def anchor(phrase: str, *, any_bullet: bool = False) -> re.Pattern:
    """`phrase` as a pattern that pins the WORDS and lets the LAYOUT move.

    Each run of whitespace becomes "spaces or one line break", so the same anchor matches
    the sentence re-wrapped across two lines or re-indented with its fenced block -- and
    still fails the moment a word, a backtick or a `**` changes.

    **A blockquote body reflowed across two lines is NOT tolerated**, and that is a
    declared limit rather than a property. Re-wrapping inside a blockquote inserts
    `\n> `, and `>` is outside the whitespace class on purpose (below), so the anchor
    goes red. Tolerating it would mean absorbing a `> ` that follows a line break, and
    that same tolerance lets an anchor match a rule someone has WRAPPED in a blockquote
    -- Phase 167's neutered-rule survivor, reintroduced through the matcher. No measured
    site needs it: `Q-495`'s controls re-wrap prose and list bodies, which leaves
    blockquote bodies alone. A site that needs it should say so at the call site.

    **Why this is not `_flat`.** Eleven modules already flatten the whole file and search the
    flattened copy, which is tolerant in the same way. What flattening destroys is the
    OFFSET: a position in the flattened string no longer corresponds to the file, so a
    guard that has to EDIT the text -- every mutation table in the suite, which must plant
    its mutation in the real file before the checks run -- could not use it and stayed on
    raw `str.replace`. That is why `Q-495`'s two worst sites are mutation anchors rather
    than rules. This returns a match against the ORIGINAL text, so the tolerant read and
    the edit are one operation.

    **What it deliberately does NOT absorb**, because each would be a real edit reported
    as a reflow:

    * `>` -- a rule moved into a blockquote is a change, not a re-wrap. Phase 291 settled
      that a wrapper is a change and `_anchor_is_wrapped` exists to say so; folding `>`
      into the whitespace class here would quietly reverse it.
    * list markers -- `4.` to `*` drops an ordinal from an ordered procedure. An anchor
      that spans a list marker wants NARROWING to the sentence it is really about, not a
      fuzzier marker class; `Q-495`'s third control is that case.
    * a blank line, per `_SOFT_BREAK` above.
    """
    if not phrase.strip():
        raise ValueError("anchor() needs a phrase with at least one non-space character")
    parts = re.split(r"(\s+)", phrase)      # tokens and the whitespace runs between them
    lead = ""
    if any_bullet:
        # The phrase is a LIST ITEM and its marker character is presentational: `-`, `+`
        # and `*` are interchangeable in CommonMark, and a formatter that normalises one
        # to another changes no rendering. Sixteen guards across eight modules pinned
        # `- ` and went red on a uniform swap -- including one about SPAWN PARAMETERS and
        # one about a REQUIRED permission rule, neither of which is about bullets.
        #
        # The marker requirement itself is kept and TIGHTENED: `any_bullet` also pins the
        # item to the start of a line, so `- \`Bash(...)\`` can no longer be satisfied by
        # the same text appearing mid-sentence. Folding which character is not the same
        # as dropping the requirement that this is a list item at all.
        # 2, not 1. `re.split` yields ['', '  ', '-', ' ', …] for an INDENTED item, so the
        # marker is two positions along -- index 1 is the whitespace run itself. At 1 this
        # raised "the phrase opens no list item" for every nested bullet, and these skills
        # are full of them; no fixture caught it because all of them were flush-left.
        i = 2 if parts[0] == "" else 0      # skip a leading-whitespace run
        if i < len(parts) and parts[i] in ("-", "+", "*"):
            # `[""] + ...`, not a bare slice: `re.split` returns token/separator/token/...
            # and the loop below reads that alternation by INDEX PARITY, so dropping the
            # marker token alone shifts every separator into a token slot and the pattern
            # silently stops matching anything. The empty token holds the parity.
            parts = [""] + parts[i + 1:]
            lead = r"(?m)^[^\S\n]*[-+*]"
        else:
            raise ValueError(f"any_bullet=True but the phrase opens no list item: {phrase[:60]!r}")
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 0:                      # a token
            out.append(re.escape(part))
            continue
        # A BOUNDARY run is the phrase's own leading or trailing whitespace -- `re.split`
        # marks it by leaving an empty token on that side. It matches IN KIND: a run with
        # no newline in it matches horizontal whitespace only.
        #
        # This is not a nicety. `"   " + COMMAND` anchors a fenced command by its indent,
        # and a leading `_SOFT_BREAK` there also matches the NEWLINE that ends the fence
        # opener -- so the matched span starts one character early and `swap()` replacing
        # it deletes that newline, joining the command onto the ``` line and corrupting
        # the fence it was anchored to. Measured: it turned two of this module's own
        # legitimate-rewrite controls red, reporting the scope command "missing,
        # corrupted, or not in a bash fence" -- which it then was.
        #
        # An INTERIOR run always takes `_SOFT_BREAK`: a space between two words becoming a
        # line break is precisely the re-wrap this exists to absorb.
        # Only the LEADING boundary matches in kind, and the asymmetry is load-bearing.
        # A leading horizontal run is INDENTATION -- `"   " + COMMAND` -- and the newline
        # it must not eat is the fence opener's, which is outside the phrase. A TRAILING
        # horizontal run is the ordinary space before the next word, and a re-wrap turns
        # exactly that space into a line break: a phrase ending `cause.** ` stopped
        # matching once the sentence after it moved to the next line, which is the defect
        # this file exists to remove, reintroduced by its own boundary rule.
        leading = i == 1 and parts[0] == ""
        trailing = i == len(parts) - 2 and parts[-1] == ""
        if leading and "\n" not in part:
            out.append(r"[^\S\n]+")
        elif trailing:
            out.append(_TRAILING_BREAK)
        else:
            out.append(_SOFT_BREAK)
    return re.compile(lead + "".join(out))


def carries(text: str, phrase: str, *, any_bullet: bool = False) -> bool:
    """True when `text` states `phrase`, up to whitespace. The tolerant `in`.

    `any_bullet=True` reads the phrase as a list item whose marker character is
    presentational — see `anchor`.
    """
    return anchor(phrase, any_bullet=any_bullet).search(text) is not None


def locate(text: str, phrase: str, *, after: str | None = None) -> re.Match:
    """The ONE whitespace-tolerant occurrence of `phrase`, or AssertionError naming it.

    AssertionError, never ValueError: `str.index` raises ValueError with no message beyond
    "substring not found", which is what several of these sites did and what makes a
    staled anchor read as a broken test rather than a stale literal.

    **Exactly one, not the first.** `str.replace(old, new, 1)` silently takes the first of
    however many sites match, and tolerance ENLARGES that set: measured on
    `review-close/SKILL.md`, `"   " + SCOPE_COMMAND` matches one site raw and TWO
    tolerantly, because the three-space indent that had been distinguishing 4a-post's copy
    of the command from Step 3's is exactly the whitespace a re-indent moves. Taking the
    first would have quietly re-pointed a mutation named for one step at another step and
    still reported a kill. So an ambiguous anchor is a defect in the anchor and says so;
    `after=` names the region that disambiguates it.

    `after=` moves where the search BEGINS and nothing else, so it isolates a site that is
    the last match rather than one in the middle. There is no `before=`: no site measured
    by `Q-495` needs one, and the refusal is loud, so the day one does it will ask.
    """
    start = 0 if after is None else locate(text, after).end()
    hits = list(anchor(phrase).finditer(text, start))
    assert hits, (
        f"anchor not found, even allowing any re-wrap: {phrase[:110]!r}"
        + ("" if after is None else f" (searching after {after[:50]!r})")
    )
    assert len(hits) == 1, (
        f"anchor is AMBIGUOUS — {len(hits)} sites match it once whitespace is allowed to "
        f"move, so which one is meant is not stated: {phrase[:110]!r}. Narrow the phrase, "
        f"or pass after=<a phrase that opens the intended region>."
    )
    return hits[0]


def swap(text: str, old: str, new: str, *, after: str | None = None) -> str:
    """Replace the one whitespace-tolerant occurrence of `old` with `new`.

    The drop-in for a mutation table's `text.replace(old, new, 1)` -- same fail-loud
    contract if the source text is gone, but the anchor survives a re-wrap of the shipped
    file, and an anchor matching more than one site is refused rather than resolved by
    position (see `locate`).
    """
    m = locate(text, old, after=after)
    return text[: m.start()] + new + text[m.end():]


# --------------------------------------------------------------------------------------
# The instrument: a rendering-identical re-wrap (Phase 292, `Q-495`).
#
# A guard can only claim "this anchor survives a reformat" if something actually reformats
# the text. `rewrapped()` is that something. It moves whitespace inside prose paragraphs
# and list-item bodies and touches nothing else -- fenced blocks, headings, tables,
# blockquotes, HTML blocks and indented code are left byte-identical -- and it ASSERTS its
# own invariant on every call: collapsing all whitespace must give the same string before
# and after, which is the definition of "only whitespace moved".
# --------------------------------------------------------------------------------------

_FENCE = re.compile(r"^(\s*)(`{3,}|~{3,})(.*)$")
_HEADING = re.compile(r"^\s{0,3}#{1,6}(\s|$)")
_LIST_ITEM = re.compile(r"^(\s*)([-+*]|\d{1,9}[.)])\s+")
# a word that would OPEN a new block if it landed at the head of a line
# `[-=]{2,}$` is a SETEXT UNDERLINE: at width 1 a bare `---` inside a paragraph lands on
# its own line and turns the line above it into an H2. Found by this phase's round.
_OPENS_BLOCK = re.compile(r"^(?:[-=]{2,}$|[-+*]$|[-+*]\s|\d{1,9}[.)]\s|\d{1,9}[.)]$|>|#{1,6}\s|#{1,6}$|\||```|~~~|<)")
# An angle-bracket link destination is the ONE inline construct a whitespace re-wrap can
# split and break: `[text](<a b.md>)` is legal CommonMark and its destination may carry
# spaces, while a line break inside it is not allowed. A bare `](url)` destination and an
# autolink cannot contain whitespace at all, so a whitespace-based re-wrap can never split
# one -- this phase's first cut protected exactly those two and was therefore dead code,
# which its own battery found by mutating the protection away and watching nothing fail.
_UNSPLITTABLE = re.compile(r"\]\(<[^>]*>\)")


def _fence_state(lines):
    """(index, inside_a_fence) per line, by CommonMark's pairing rule: a closer is the
    same character, at least as long, with nothing after it, and a backtick opener's info
    string may not itself contain a backtick. Phase 291's round reached the Phase 167
    survivor through `~~~` and through a 3-backtick line closing a 4-backtick block, so
    neither shortcut is taken here."""
    opener = None
    for i, line in enumerate(lines):
        m = _FENCE.match(line)
        if opener is None:
            if m and not (m.group(2)[0] == "`" and "`" in m.group(3)):
                opener = m.group(2)
                yield i, True
            else:
                yield i, False
        else:
            yield i, True
            if (m and m.group(2)[0] == opener[0]
                    and len(m.group(2)) >= len(opener) and not m.group(3).strip()):
                opener = None


def _kinds(lines):
    """(kind, indent) per line. Only `prose` and `listitem` are ever re-wrapped."""
    out, in_comment, in_html = [], False, False
    for i, fenced in _fence_state(lines):
        line, stripped = lines[i], lines[i].strip()
        if fenced:
            out.append(("fence", ""))
        elif in_comment:
            out.append(("html", ""))
            in_comment = "-->" not in line
        elif stripped.startswith("<!--"):
            out.append(("html", ""))
            in_comment = "-->" not in line
        elif not stripped:
            # BEFORE the html-continuation arm, not after: a blank line is what CLOSES an
            # HTML block, so testing the continuation first leaves `in_html` latched on
            # forever and every paragraph after the first `<details>` stops being prose.
            out.append(("blank", ""))
            in_html = False
        elif in_html or re.match(r"^\s*</?[A-Za-z]", line):
            # An HTML block runs to the next BLANK LINE, not to the end of the tag line
            # (CommonMark block type 6). Marking only the lines that open with `<` left
            # `<details>`/`<summary>` bodies classified as prose and re-wrapped -- the
            # state machine reformatting a region it reports as untouched.
            out.append(("html", ""))
            in_html = True
        elif _HEADING.match(line) or stripped.startswith(("|", ">")):
            out.append(("struct", ""))
        elif len(line) - len(line.lstrip()) >= 4:
            out.append(("struct", ""))          # indented code, or a deep continuation
        elif _LIST_ITEM.match(line):
            out.append(("listitem", _LIST_ITEM.match(line).group(0)))
        else:
            out.append(("prose", line[: len(line) - len(line.lstrip())]))
    return out


def _frontmatter_end(lines: list[str]) -> int:
    """Index just past a leading `---` YAML block, or 0 when there is none."""
    if not lines or lines[0].strip() != "---":
        return 0
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return i + 1
    return 0


def rewrapped(text: str, width: int = 1) -> str:
    """`text` with every prose paragraph and list-item body re-wrapped at `width`.

    The default of 1 -- one word per line -- is deliberate and is what makes this an
    ENUMERATOR rather than a sample. A re-wrap breaks a raw literal anchor only when a
    line break lands inside it, so any single wrap width leaves an arbitrary subset
    intact; at width 1 every gap between two words becomes a line break at once, so every
    raw multi-word anchor over the paragraph text goes stale in one pass. Soft line breaks
    render as spaces, so the rendered document is unchanged.
    """
    lines = text.split("\n")
    kinds = _kinds(lines)
    # YAML FRONTMATTER is not prose and re-wrapping it is not a reformat -- it is
    # corruption. Every one of this repo's 23 shipped skills opens with a `---` block
    # carrying `name:`, `description:` and `model:`, and joining those onto one line makes
    # the document unparseable (`yaml.ScannerError`). This phase's round found it by
    # noticing that the pin `_model_roles.py` "loses" under a re-wrap is the FRONTMATTER
    # pin, destroyed here, rather than an inline pin losing its role marker.
    frontmatter = _frontmatter_end(lines)
    out, i = [], 0
    while i < frontmatter:
        out.append(lines[i])
        i += 1
    while i < len(lines):
        kind, indent = kinds[i]
        if kind not in ("prose", "listitem") or lines[i].endswith("  "):
            # A line ending in two or more spaces is a HARD BREAK; joining it into the
            # paragraph deletes a line break the renderer shows. Left byte-identical.
            out.append(lines[i])
            i += 1
            continue
        base = re.match(r"^(\s*)", indent).group(1) if kind == "listitem" else indent
        block, j = [lines[i]], i + 1
        while j < len(lines) and kinds[j] == ("prose", base):
            block.append(lines[j])
            j += 1
        body = " ".join(l.strip() for l in block)
        if kind == "listitem":
            head, cont = indent, " " * len(indent)
            body = body[len(indent.strip()):].strip()
        else:
            head = cont = indent
        held = []
        body = _UNSPLITTABLE.sub(lambda m: held.append(m.group(0)) or f"\x00{len(held)-1}\x00", body)
        rows, cur = [], []
        for word in body.split():
            if not cur:
                cur = [word]
            elif _OPENS_BLOCK.match(word) or len(cont) + len(" ".join(cur + [word])) <= width:
                cur.append(word)            # never let a word open a block at a line head
            else:
                rows.append(" ".join(cur))
                cur = [word]
        if cur:
            rows.append(" ".join(cur))
        for n, row in enumerate(rows):
            row = re.sub(r"\x00(\d+)\x00", lambda m: held[int(m.group(1))], row)
            out.append((head if n == 0 else cont) + row)
        i = j
    new = "\n".join(out)
    assert re.sub(r"\s+", " ", text) == re.sub(r"\s+", " ", new), (
        "rewrapped() changed more than whitespace — the instrument is broken, not the guard"
    )
    return new
