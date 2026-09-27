"""Controls for the hash pins' shared normalizer, run over every real pinned span.

Three modules pin decided text by hash through the same three functions in
`test_fix_in_branch_tier.py`: `_pin_norm` (what is hashed), `_pin_span` (the context a
slice drops) and `_pin_liveness` (a wrapper a hash cannot see). A pin is only as good as
that normalizer, in both directions:

* **A legal edit keeps every pin.** A re-wrap (paragraphs, list bodies, blockquotes), a
  list-marker swap, and four leading spaces written as a tab change no rendering, so each
  must leave all spans' hashes -- and their slices -- unchanged.
* **A structural change moves the pin or fails liveness.** Tab indentation that makes a
  code block, a fence closer moved out of its list item, the line that opens the span's
  block indented into a code block, and an HTML comment or a fence wrapped around the whole span.
  **Not seen here:** a fence *body* line above the span dedented out of its list item, which
  closes the fence early and turns what follows into code with the pin unmoved. The pin reads
  fences by marker, as `_fence_state` does. `tests/test_substep_line_breaks.py` refuses that
  line in any shipped file instead.

Each control is applied in memory to the real file, and each blind-spot control asserts
it applied to at least one span, so none passes vacuously.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from _prose_guard_helpers import _fence_state, rewrapped
from _reversal import slice_between
import test_fix_in_branch_tier as T
import test_review_close_smoke_decided_text as S
import test_review_loop_decided_text as L
from test_fix_in_branch_tier import _pin_hash, _pin_lines, _pin_liveness, _pin_norm, _pin_span

# (module id, label) -> (path, start, end, fenced)
SPANS: dict[tuple[str, str], tuple[Path, object, object, bool]] = {}
for _label, (_path, _start, _end, _maint) in T.PINNED_SPANS.items():
    SPANS["T", _label] = (_path, _start, _end, _label in T.FENCED_PINS)
for _mod, _spans in (("L", L.SPANS), ("S", S.SPANS)):
    for _label, _cfg in _spans.items():
        SPANS[_mod, _label] = _cfg
MODULES = {"T": T, "L": L, "S": S}
FILES = sorted({cfg[0] for cfg in SPANS.values()})


def _pin(key, text: str) -> str:
    """The hash a pin takes over *text* standing in for its file."""
    path, start, end, _ = SPANS[key]
    span = slice_between(text, start, end, key[1])
    return _pin_hash(_pin_span(path, text, text.index(span), span))


def _read(path: Path) -> str:
    if not path.is_file():
        pytest.skip(f"{path.name} is absent here (maintainer-side, mirror-excluded)")
    return path.read_text(encoding="utf-8")


def _keys_in(path: Path):
    return [k for k, cfg in SPANS.items() if cfg[0] == path]


# ---------------------------------------------------------------------------------------
# The wiring: every module hashes through the shared context
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(SPANS), ids=lambda k: f"{k[0]}:{k[1]}")
def test_every_module_span_goes_through_pin_span(key) -> None:
    """Each module's own `_span` must equal `_pin_span` over its slice: a module that
    dropped the first-line restore (as Phase 329's loop module once had) is caught."""
    path, start, end, _ = SPANS[key]
    text = _read(path)
    span = slice_between(text, start, end, key[1])
    assert MODULES[key[0]]._span(key[1]) == _pin_span(path, text, text.index(span), span)


# ---------------------------------------------------------------------------------------
# Legal edits keep every pin
# ---------------------------------------------------------------------------------------


def _swap_markers(text: str) -> str:
    """`N.` to `N)` and `-` to `*` on every list item outside a fence."""
    lines = text.split("\n")
    out = []
    for (_, fenced), line in zip(_fence_state(lines), lines):
        if not fenced:
            line = re.sub(r"^(\s*(?:>\s*)*)(\d{1,9})\.(?=[ \t])", r"\1\2)", line)
            line = re.sub(r"^(\s*(?:>\s*)*)-(?=[ \t])", r"\1*", line)
        out.append(line)
    return "\n".join(out)


def _tabs_for_fours(text: str) -> str:
    """Each leading run of four spaces written as one tab (CommonMark's tab stop)."""
    return "\n".join(re.sub(r"^((?:    )+)", lambda m: "\t" * (len(m.group(1)) // 4), line)
                     for line in text.split("\n"))


def _rewrap_quotes(text: str, width: int) -> str:
    """Every blockquote re-wrapped inside its `> ` prefix; `rewrapped()` leaves quotes alone."""
    lines = text.split("\n")
    fenced = [f for _, f in _fence_state(lines)]
    quoted = re.compile(r"^( {0,3})> ?")
    out, i = [], 0
    while i < len(lines):
        m = quoted.match(lines[i])
        if fenced[i] or not m:
            out.append(lines[i])
            i += 1
            continue
        block = []
        while (i < len(lines) and not fenced[i] and quoted.match(lines[i])
               and quoted.match(lines[i]).group(1) == m.group(1)):
            block.append(quoted.sub("", lines[i]))
            i += 1
        out.extend(m.group(1) + ("> " + row if row else ">")
                   for row in rewrapped("\n".join(block), width).split("\n"))
    return "\n".join(out)


def _drop_quote_space(text: str) -> str:
    """`> x` written `>x`: CommonMark consumes one optional space after the marker."""
    lines = text.split("\n")
    return "\n".join(line if fenced else re.sub(r"^((?: {0,3}>)+) (?=\S)", r"\1", line)
                     for (_, fenced), line in zip(_fence_state(lines), lines))


LEGAL = {
    "re-wrap width 1": lambda t: rewrapped(t, 1),
    "re-wrap width 40": lambda t: rewrapped(t, 40),
    "re-wrap width 80": lambda t: rewrapped(t, 80),
    "list-marker swap": _swap_markers,
    "tab for four spaces": _tabs_for_fours,
    "blockquote re-wrap width 1": lambda t: _rewrap_quotes(t, 1),
    "blockquote re-wrap width 40": lambda t: _rewrap_quotes(t, 40),
    "quote marker space dropped": _drop_quote_space,
}


def _moved(path: Path, text: str, edited: str) -> list[str]:
    """The spans in *path* whose pin *edited* moves, or whose slice it breaks."""
    moved = []
    for key in _keys_in(path):
        try:
            if _pin(key, edited) != _pin(key, text):
                moved.append(key[1])
        except AssertionError as err:          # an anchor the edit broke
            moved.append(f"{key[1]} ({str(err)[:80]})")
    return moved


@pytest.mark.parametrize("edit", sorted(LEGAL))
@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(T.REPO_ROOT)))
def test_a_legal_edit_keeps_every_pin(path: Path, edit: str) -> None:
    text = _read(path)
    moved = _moved(path, text, LEGAL[edit](text))
    assert not moved, f"{edit} of {path.name} rendered the same and moved: {moved}"


def test_the_legal_edit_check_sees_a_real_edit() -> None:
    """Non-vacuity: a one-word rewording inside a pinned span is reported as moved."""
    text = T.CLOSE.read_text(encoding="utf-8")
    word = "it is the *only* thing that verifies the tree the PR will squash"
    assert text.count(word) == 1
    moved = _moved(T.CLOSE, text, text.replace(word, word.replace("*only*", "*first*")))
    assert moved == ["review-close 4a PR-reuse lead"], moved


def test_the_width_one_step_ref_rewrap_keeps_the_pin() -> None:
    """Phase 329's false kill: `(Step 8),` wrapped to a line start is prose, and a bare
    `8)` alone on a line is too -- neither is a list item, so neither is rewritten."""
    one = "The backstop (written in Step 8), keyed per candidate, and Step 8) again."
    assert _pin_norm(one) == _pin_norm("\n".join(one.split()))
    assert _pin_norm(one) != _pin_norm(one.replace("Step 8),", "Step 8.,"))


def test_a_marker_swap_keeps_the_pin() -> None:
    base = "1. **Fix it** — whatever module.\n2. **File a task** only when it cannot.\n- a\n- b"
    assert _pin_norm(base) == _pin_norm(
        "1) **Fix it** — whatever\n   module.\n2) **File a task** only when it cannot.\n* a\n+ b")


# ---------------------------------------------------------------------------------------
# Structural changes move the pin, or fail liveness
# ---------------------------------------------------------------------------------------


def _span_lines(path: Path, text: str, key):
    """(file line index, kind) for each line of the span, classified in file context."""
    _, start, end, _ = SPANS[key]
    span = slice_between(text, start, end, key[1])
    first = text.count("\n", 0, text.index(span))
    kinds = _pin_lines(text.split("\n"))
    return [(i, kinds[i][0]) for i in range(first, first + span.count("\n") + 1)]


def _mutate_line(text: str, i: int, fn) -> str:
    lines = text.split("\n")
    lines[i] = fn(lines[i])
    return "\n".join(lines)


def _tab_indented(text: str, i: int) -> str:
    """Line *i*'s leading spaces written as as many tabs: three spaces become twelve
    columns, which makes an indented code block of a rule inside a list item."""
    return _mutate_line(text, i, lambda l: "\t" * (len(l) - len(l.lstrip(" "))) + l.lstrip(" "))


def _structural_mutants():
    """(name, key, mutated text) for every structural control that applies to a span."""
    for key in sorted(SPANS):
        path, *_ = SPANS[key]
        if path.suffix != ".md" or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        lines = text.split("\n")
        rows = _span_lines(path, text, key)
        starts = [i for i, kind in rows if kind == "start"
                  and 0 < len(lines[i]) - len(lines[i].lstrip(" ")) < 4]
        if starts:
            yield "tab-indented block start", key, _tab_indented(text, starts[0])
        for i, kind in rows:
            line = lines[i]
            if (kind == "fence" and line.strip().startswith(("```", "~~~"))
                    and line != line.lstrip() and i != rows[0][0]):
                yield f"fence line {i + 1} to column 0", key, _mutate_line(text, i, str.lstrip)
        first = rows[0][0]
        at = text.index(slice_between(text, SPANS[key][1], SPANS[key][2], key[1]))
        at_line_start = not text[text.rfind("\n", 0, at) + 1:at].strip(" >-*+0123456789.)")
        # A span anchored mid-paragraph is inside a paragraph either way; joining that
        # paragraph to the one above changes the text before the span, not the span's block.
        if (at_line_start and first >= 2 and not lines[first - 1].strip()
                and lines[first - 2].strip()):
            joined = "\n".join(lines[:first - 1] + lines[first:])
            # Only where the join is real: the span's first line becomes a continuation of
            # the paragraph above. Under a heading, a table or a fence it renders the same.
            if _pin_lines(joined.split("\n"))[first - 1][0] == "cont" and rows[0][1] == "start":
                yield "blank line above deleted", key, joined
        if not SPANS[key][3]:
            # the line that opened the block the span starts in: the span's own first line,
            # or the paragraph start above it when the anchor sits mid-paragraph
            kinds = _pin_lines(lines)
            j = rows[0][0]
            while j > 0 and kinds[j][0] == "cont":
                j -= 1
            yield "opening line indented into code", key, _mutate_line(text, j, lambda l: "    " + l)


MUTANTS = list(_structural_mutants())


@pytest.mark.parametrize("name,key,mutated", MUTANTS,
                         ids=[f"{k[0]}:{k[1]}:{n}" for n, k, _ in MUTANTS])
def test_a_structural_change_moves_the_pin(name: str, key, mutated: str) -> None:
    text = SPANS[key][0].read_text(encoding="utf-8")
    assert _pin(key, mutated) != _pin(key, text), f"{name} kept the {key[1]!r} pin"


@pytest.mark.parametrize("control", ["tab-indented block start", "fence line", "opening line indented into code",
                                     "blank line above deleted"])
def test_every_structural_control_applies_somewhere(control: str) -> None:
    assert any(n.startswith(control) for n, _, _ in MUTANTS), f"{control} applied to no span"


def test_the_join_control_covers_many_spans() -> None:
    """16 spans on 2026-09-24. A floor well above 1, so a control that stopped after its
    first span is seen; not the exact count, which moves whenever a span is added."""
    joined = [k for n, k, _ in MUTANTS if n == "blank line above deleted"]
    assert len(joined) >= 12, joined


def test_the_quote_space_edit_applies_somewhere() -> None:
    assert any(_drop_quote_space(_read(path)) != _read(path) for path in FILES)


def _wrapped(text: str, key, opener: str, closer: str) -> str:
    """The whole lines holding the span, from its first line through the line its end
    anchor starts on, wrapped in *opener* / *closer*."""
    _, start, end, _ = SPANS[key]
    span = slice_between(text, start, end, key[1])
    at = text.index(span)
    k = at + len(span)
    while k < len(text) and text[k] == "\n":
        k += 1
    first = text.rfind("\n", 0, at) + 1
    last = text.find("\n", k)
    last = len(text) if last == -1 else last + 1
    return text[:first] + opener + text[first:last] + closer + text[last:]


def _wrapper_keys(fence: bool):
    return [k for k, cfg in sorted(SPANS.items())
            if not (fence and (cfg[3] or cfg[0].suffix != ".md"))]


@pytest.mark.parametrize("key", _wrapper_keys(False), ids=lambda k: f"{k[0]}:{k[1]}")
def test_a_comment_wrapper_fails_liveness(key) -> None:
    path = SPANS[key][0]
    mutated = _wrapped(_read(path), key, "<!--\n", "-->\n")
    span = slice_between(mutated, SPANS[key][1], SPANS[key][2], key[1])
    assert _pin_liveness(path, mutated, mutated.index(span), SPANS[key][3]) is not None


@pytest.mark.parametrize("key", _wrapper_keys(True), ids=lambda k: f"{k[0]}:{k[1]}")
def test_a_fence_wrapper_fails_liveness_and_moves_the_pin(key) -> None:
    path = SPANS[key][0]
    text = _read(path)
    mutated = _wrapped(text, key, "~~~~~~~~\n", "~~~~~~~~\n")
    span = slice_between(mutated, SPANS[key][1], SPANS[key][2], key[1])
    assert _pin_liveness(path, mutated, mutated.index(span), False) is not None
    assert _pin(key, mutated) != _pin(key, text)


def test_liveness_flags_a_stale_fenced_mark() -> None:
    """The fenced mark is checked both ways: a live span marked fenced fails too."""
    text = "intro\n\n**Rule.** body\n"
    assert _pin_liveness(Path("x.md"), text, text.index("**Rule"), True) is not None
    assert _pin_liveness(Path("x.md"), text, text.index("**Rule"), False) is None
    assert _pin_liveness(Path("x.html"), "<p>\n**Rule**", 4, False) is None


def test_the_phase_328_measurements_move_the_pin() -> None:
    """The lens's two measured survivors, on the spans it measured them on."""
    text = T.CLOSE.read_text(encoding="utf-8")
    arm = ("T", "review-close 4a-post fix arm")
    needle = "\n   **If `4a-fix` kept a fix commit"
    assert text.count(needle) == 1
    assert _pin(arm, text.replace(needle, "\n\t\t\t" + needle[4:])) != _pin(arm, text)
    step = ("T", "review-close 4a-fix step")
    closer = "   git rebase --onto <fix-sha>~1 <fix-sha>\n   ```\n"
    assert text.count(closer) == 1
    assert _pin(step, text.replace(closer, closer.replace("\n   ```", "\n```"))) != _pin(step, text)


@pytest.mark.parametrize("before,after", [
    # a list item whose content opens with five spaces is an indented code block
    ("- **Never** merge a red branch.", "-     **Never** merge a red branch."),
    # after a heading, four spaces open a code block (a heading is not a paragraph)
    ("### Rule\n**Never** merge a red branch.", "### Rule\n    **Never** merge a red branch."),
    # a line that deepens a quote opens a nested quote
    ("> **Never** merge\n> a red branch.", "> **Never** merge\n> > a red branch."),
    # a quote's own content indented four more spaces is code
    ("> **Never** merge a red branch.", ">     **Never** merge a red branch."),
    # a narrower marker gap moves the item's content column, and its child becomes code
    ("-  **Item.**\n\n      **Never** merge a red branch.", "- **Item.**\n\n      **Never** merge a red branch."),
    # a bare `>` ends the quoted paragraph, so the next line's indentation is structure
    ("> Intro.\n>\n> **Never** merge a red branch.", "> Intro.\n>\n>     **Never** merge a red branch."),
    # a same-length word change inside a fenced template is a change to the template
    ("```\ngit merge --ff-only\n```", "```\ngit merge --no-edit\n```"),
    # quoting a rule changes what it is
    ("**Never** merge a red branch.", "> **Never** merge a red branch."),
    # an ordered rule list turned into bullets
    ("1. **Fix it.**\n2. **File it.**", "- **Fix it.**\n- **File it.**"),
    # two table rows merged onto one line are one broken row
    ("| a | b |\n| c | d |", "| a | b | | c | d |"),
])
def test_pin_norm_sees_code_and_quote_structure(before: str, after: str) -> None:
    assert _pin_norm(before) != _pin_norm(after)


# ---------------------------------------------------------------------------------------
# Each module's own tests fail on what they exist to catch
# ---------------------------------------------------------------------------------------

_MODULE_TESTS = {
    "T": ("review-close 4a PR-reuse lead", "test_the_decided_text_is_pinned", "test_every_pinned_span_is_live"),
    "L": ("WORKFLOW 8.2c fail-closed", "test_the_decided_review_loop_text_is_pinned", "test_every_span_is_live"),
    "S": ("3c options", "test_the_decided_smoke_gate_text_is_pinned", "test_every_span_is_live"),
}


@pytest.mark.parametrize("which", ["pin", "liveness"])
@pytest.mark.parametrize("mod", sorted(_MODULE_TESTS))
def test_each_module_test_fails_on_its_subject(mod: str, which: str, monkeypatch) -> None:
    """A module's pin test fails on a reworded span, and its liveness test on a span
    wrapped in a comment -- so neither can be neutered with the controls above green."""
    label, pin_test, live_test = _MODULE_TESTS[mod]
    path, start, end, _ = SPANS[mod, label]
    text = path.read_text(encoding="utf-8")
    if which == "pin":
        span = slice_between(text, start, end, label)
        words = span.split()
        edited = text.replace(span, span.replace(words[-1], words[-1] + " not", 1), 1)
    else:
        edited = _wrapped(text, (mod, label), "<!--\n", "-->\n")
    real = Path.read_text
    monkeypatch.setattr(Path, "read_text",
                        lambda self, *a, **k: edited if self == path else real(self, *a, **k))
    with pytest.raises(AssertionError):
        getattr(MODULES[mod], pin_test if which == "pin" else live_test)(label)
