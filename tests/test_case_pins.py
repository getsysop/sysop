"""The case-pin machinery's own tests — `Q-518`, Phase 301.

**Its own module, and not a section of `tests/test_reader_census.py`, for one reason.** That
module carries `pytestmark = pytest.mark.skipif(not SCRIPT.exists(), …)` because
`tools/reader_census.py` is mirror-excluded — so every test in it stands down in the sterilized
tree and in the public repo's CI. `tests/_case_pins.py` ships and runs there, and a helper whose
only tests are in a module that skips is a helper nobody tests where it actually runs.

**What is here vs. what is in the consumer module.** This file tests the PREDICATE: what it
reports, what it stays silent on, and which escape routes it closes. Whether a particular row is
load-bearing for a particular arm is a fact about that arm, so those pins and their tamper control
stay with the module that owns them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _case_pins import (  # noqa: E402
    case_pin_problems,
    parametrize_shape_problems,
    parametrized_cases,
)

#: One pinned row, so each case below differs only in how the SOURCE is written.
_PINS = {"t": (None, ((1, 2),))}

_BASELINE = """
import pytest
@pytest.mark.parametrize("a,b", [(1, 2), (3, 4)])
def t(a, b): pass
"""


@pytest.mark.parametrize("src,reports,why", [
    # The honest tree: the pinned row is present and nothing is reported.
    (_BASELINE, False, "the pinned row is present"),
    # `from pytest import mark` — a different spelling of the same decorator, still seen.
    ('\nfrom pytest import mark\n@mark.parametrize("a,b", [(1, 2), (3, 4)])\ndef t(a, b): pass\n',
     False, "`mark.parametrize` is the same decorator under another import"),
    # A tuple/list reformat parametrizes identically, so it must NOT redden. Found by this
    # phase's own author-side pass under "over-strictness, the direction that hides": a guard
    # that cries on a correct commit is a guard that gets edited to stop crying.
    ('\nimport pytest\n@pytest.mark.parametrize("a,b", [[1, 2], [3, 4]])\ndef t(a, b): pass\n',
     False, "a list row and a tuple row parametrize identically"),
    # The case LIST written as a tuple is legal pytest too. Phase 327 (`Q-592` line 26): no
    # list in the suite was spelled this way, so dropping the extractor's `ast.Tuple` arm was
    # green; this row is what reads it.
    ('\nimport pytest\n@pytest.mark.parametrize("a,b", ((1, 2), (3, 4)))\ndef t(a, b): pass\n',
     False, "a case list written as a tuple rather than a list"),
    # ── the escape routes, each of which must report ────────────────────────────────────────
    ('\nimport pytest\n@parametrize("a,b", [(1, 2), (3, 4)])\ndef t(a, b): pass\n',
     True, "the decorator aliased to a bare name, which the Attribute walk cannot see"),
    ('\nimport pytest\nROWS = [(1, 2), (3, 4)]\n@pytest.mark.parametrize("a,b", ROWS)\n'
     'def t(a, b): pass\n',
     True, "the cases moved to a module constant, out of the inline walk"),
    ('\nimport pytest\n@pytest.mark.parametrize("a,b", [(1, 2), (3, 4)])\ndef other(a, b): pass\n'
     '@pytest.mark.parametrize("a,b", [(9, 9), (8, 8)])\ndef t(a, b): pass\n',
     True, "the pinned row present, but under a DIFFERENT test than the one pinned"),
    ('\nimport pytest\n@pytest.mark.parametrize("a,b", [(3, 4), (5, 6)])\ndef t(a, b): pass\n',
     True, "the pinned row deleted, leaving two others — invisible to any count"),
    ('\nimport pytest\n@pytest.mark.parametrize("a,b", [(1, 1 + 1), (3, 4)])\ndef t(a, b): pass\n',
     True, "the pinned row rewritten as an expression `literal_eval` cannot read"),
])
def test_the_predicate_reports_exactly_the_escape_routes(src, reports, why):
    """Both directions in one control, because only one of them is usually tested.

    A guard measured on positive cases alone cannot tell "catches the defect" from "reports
    everything", and the three `reports=False` rows are what make the other five mean something.
    Two of those three are legal spellings the naive implementation of this predicate reddened on.
    """
    problems = case_pin_problems(src, _PINS)
    assert bool(problems) is reports, (
        f"{why}: expected {'a report' if reports else 'silence'}, got {problems!r}")


def test_the_extractor_keys_by_test_and_accumulates_stacked_decorators():
    """The property the predecessor did not have, asserted rather than assumed.

    `Q-518`'s guard walked bare `ast.Call` nodes, so it knew a case list existed at some line
    number without knowing which control owned it — and a pin that cannot name its test cannot
    tell a maintainer what to restore. Stacking accumulates because either list going empty is
    the defect, not just the last one parsed.
    """
    src = (
        '\nimport pytest\n'
        '@pytest.mark.parametrize("a", [1, 2])\n'
        '@pytest.mark.parametrize("b", [3, 4])\n'
        'def t(a, b): pass\n'
        '@pytest.mark.parametrize("c", [5, 6])\n'
        'def u(c): pass\n'
    )
    found = parametrized_cases(src)
    assert set(found) == {"t", "u"}, found
    assert sorted(found["t"].rows) == [1, 2, 3, 4], found["t"]
    assert sorted(found["u"].rows) == [5, 6], found["u"]
    # Stacked decorators each declare one argname here, so the conservative minimum is 1.
    assert found["t"].argnames == 1 and found["u"].argnames == 1, found


def test_a_pinned_test_that_no_longer_exists_is_reported_not_skipped():
    """The arm that makes a rename visible — `Q-518`'s deletion case at whole-test granularity.

    A `pins` entry naming a test the source does not contain must REPORT. Returning clean for an
    absent test is the same defect one level up: the pin would silently stop covering anything
    the moment someone renamed the control, which is the shape
    `tests/test_reader_census.py::test_the_case_pin_actually_bites` exercises end to end.
    """
    problems = case_pin_problems(_BASELINE, {"nonexistent_test": (None, ((1, 2),))})
    assert problems and "no inline parametrize list" in problems[0], problems


@pytest.mark.parametrize("decorator,reports,why", [
    # TWO argnames: pytest unpacks the row, so list and tuple are the same two cases.
    ('@pytest.mark.parametrize("a,b", [[1, 2], [3, 4]])', False,
     "2 argnames: the row is unpacked, so [1,2] and (1,2) are one case"),
    # ONE argname: the row is passed through, so they are a list and a tuple and differ.
    ('@pytest.mark.parametrize("x", [[1, 2], [3, 4]])', True,
     "1 argname: the row is passed through verbatim, so the forms are different values"),
    # The list spelling of argnames counts the same way.
    ('@pytest.mark.parametrize(["a", "b"], [[1, 2], [3, 4]])', False,
     "argnames given as a list, not a comma string"),
])
def test_the_tuple_list_equivalence_applies_only_where_pytest_unpacks(decorator, reports, why):
    """The conditional the first cut of `_norm` got wrong, driven against the real predicate.

    Phase 301's round measured this: `_norm` coerced every sequence on every row, which is right
    at 2+ argnames and WRONG at one, where pytest hands the row to the test verbatim and a list
    and a tuple are genuinely different values. `tests/test_thinning_transforms.py` pins a
    single-argname list (Phase 327), so this is not hypothetical.

    Each row below pins the TUPLE form `(1, 2)` against a source written with the LIST form. It
    must be silent where pytest makes them the same case and must report where it does not.
    """
    src = f'\nimport pytest\n{decorator}\ndef t(*a): pass\n'
    problems = case_pin_problems(src, {"t": (None, ((1, 2),))})
    assert bool(problems) is reports, (
        f"{why}: expected {'a report' if reports else 'silence'}, got {problems!r}")


def test_a_column_pin_over_scalar_rows_is_refused_rather_than_answered_wrongly():
    """`row[0]` on `"mixed"` is `"m"`, and on `1` it raises. Neither is an answer.

    Found by Phase 301's round. A column projection assumes each row is a sequence of columns; a
    single-argname list of strings is a sequence of CHARACTERS, so a pin of first letters reported
    CLEAN — a false pass — and an int row raised `TypeError` out of the guard instead of reporting.
    `tests/test_thinning_transforms.py::test_transform_1_refuses_every_state_that_is_not_editor`
    is exactly that shape, and Phase 327 pins it with a whole-row pin, the remedy below.

    The predicate now refuses the pin and says what to do instead.
    """
    src = '\nimport pytest\n@pytest.mark.parametrize("state", ["mixed", "runner"])\ndef t(state): pass\n'
    problems = case_pin_problems(src, {"t": (0, ("m", "r"))})
    assert problems and "not sequences" in problems[0], problems

    ints = '\nimport pytest\n@pytest.mark.parametrize("n", [1, 2])\ndef t(n): pass\n'
    problems = case_pin_problems(ints, {"t": (0, (1,))})
    assert problems and "not sequences" in problems[0], problems

    # And the whole-row pin over the same scalar rows still works, which is the documented remedy.
    assert not case_pin_problems(src, {"t": (None, ("mixed",))})


def test_an_int_projection_reads_the_column_it_names():
    """Phase 327 (`Q-592` line 26). Every `int` projection in the suite was column 0, so
    hard-coding `row[0]` in `project()` survived everywhere. Column 1 tells them apart."""
    src = ('\nimport pytest\n@pytest.mark.parametrize("key, why", [("k1", "first"), ("k2", "second")])'
           '\ndef t(key, why): pass\n')
    assert not case_pin_problems(src, {"t": (1, ("second",))})
    problems = case_pin_problems(src, {"t": (1, ("k2",))})
    assert problems, "a column-1 pin matched a value that only column 0 holds"


def test_an_overflowing_row_is_counted_not_raised():
    """Phase 327's round. `literal_eval` computes `int + complex` itself, and a 400-digit int
    overflows the float conversion. The row is unevaluatable like any other; the guard must
    count it and go on, not crash the module that imports it."""
    big = "1" + "0" * 400
    src = (f'\nimport pytest\n@pytest.mark.parametrize("a,b", [({big} + 1j, 2), (3, 4)])\n'
           'def t(a, b): pass\n')
    found = parametrized_cases(src)["t"]
    assert found.unevaluated == 1 and found.rows == [(3, 4)], found
    argnames_src = f'\nimport pytest\n@pytest.mark.parametrize({big} + 1j, [(1, 2)])\ndef t(*a): pass\n'
    assert parametrized_cases(argnames_src)["t"].argnames == 1


def test_stacked_decorators_sum_their_unevaluated_rows():
    """Each stacked list contributes its own count; dropping either side of the sum was green."""
    src = ('\nimport pytest\n'
           '@pytest.mark.parametrize("a", [x, 1])\n'
           '@pytest.mark.parametrize("b", [y, z, 2])\n'
           'def t(a, b): pass\n')
    assert parametrized_cases(src)["t"].unevaluated == 3


@pytest.mark.parametrize("site", ["rows", "argnames"])
def test_an_unexpected_error_is_not_swallowed(monkeypatch, site):
    """The other side of the tuple, at EACH of its two sites. A bug in `literal_eval` itself —
    anything outside the errors it documents — must surface, not be counted as unreadable.
    Round 2 broadened one site at a time and each survived, because one patch that raised at
    both sites was caught by whichever site was still narrow."""
    import ast as _ast
    import _case_pins
    real = _ast.literal_eval

    def boom(node):
        argnames = isinstance(node, _ast.Constant) and isinstance(node.value, str)
        if (site == "argnames") == argnames:
            raise AttributeError("not a literal_eval error")
        return real(node)
    monkeypatch.setattr(_case_pins.ast, "literal_eval", boom)
    with pytest.raises(AttributeError):
        parametrized_cases(_BASELINE)


def test_an_unhashable_row_is_counted_not_raised():
    """`literal_eval` raises `TypeError` on a dict keyed by a list; round 2 removed `TypeError`
    from the tuple with every module green."""
    src = '\nimport pytest\n@pytest.mark.parametrize("a,b", [({[1]: 2}, 3), (3, 4)])\ndef t(a, b): pass\n'
    found = parametrized_cases(src)["t"]
    assert found.unevaluated == 1 and found.rows == [(3, 4)], found


def test_a_row_that_cannot_be_evaluated_is_named_as_the_likely_cause():
    """Phase 327 (`Q-592` line 25). A pinned row rewritten as an expression reads as missing
    either way; what the extractor adds is the count that lets the report say so. Without it the
    maintainer is told a row was deleted when it was rewritten."""
    rewritten = ('\nimport pytest\n@pytest.mark.parametrize("a,b", [(1, 1 + 1), (3, 4)])\n'
                 'def t(a, b): pass\n')
    problems = case_pin_problems(rewritten, _PINS)
    assert problems and "1 row(s) in this list are not literals" in problems[0], problems
    assert parametrized_cases(rewritten)["t"].unevaluated == 1
    assert parametrized_cases(rewritten)["t"].rows == [(3, 4)], "a non-literal row entered `rows`"

    deleted = '\nimport pytest\n@pytest.mark.parametrize("a,b", [(3, 4), (5, 6)])\ndef t(a, b): pass\n'
    problems = case_pin_problems(deleted, _PINS)
    assert problems and "not literals" not in problems[0], (
        "a plain deletion was blamed on an unevaluatable row it does not have")


@pytest.mark.parametrize("argnames_src,expect", [
    ('"a,b"', 2), ('"a, b"', 2), ('"x"', 1), ('["a", "b"]', 2), ('("a", "b", "c")', 3),
    ("SOME_NAME", 1),
])
def test_argnames_are_counted_conservatively(argnames_src, expect):
    """Both spellings, and the unreadable case, which must answer 1 rather than guess.

    1 is the conservative value: it is the reading under which `_norm` does NOT equate a list row
    with a tuple row, so an unreadable decorator cannot silence a real difference.
    """
    src = f'\nimport pytest\n@pytest.mark.parametrize({argnames_src}, [(1, 2)])\ndef t(*a): pass\n'
    assert parametrized_cases(src)["t"].argnames == expect


#: This module's own controls, pinned by the predicate they test.
#:
#: `Q-518`, Phase 301, added by its round. The phase shipped two NEW parametrized controls — this
#: module's escape-route table and `test_each_provenance_pointer_arm_is_not_vacuous` in
#: `tests/test_review_close_reference_pins.py` — into modules with no emptying guard and no pin.
#: The round then ran the compound shape the filing describes (delete the rows that would notice,
#: then neuter the arm) and the whole suite stayed green. That is `Q-518`'s class, minted in the
#: commit that closes `Q-518`.
#:
#: Rows are pinned by their SOURCE text (column 0) and expectation (column 1); the `why` prose is
#: free to be reworded.
_SELF_PINS = {
    # The first row of that table passes `_BASELINE`, a module NAME, so `literal_eval` cannot
    # read it and the extractor counts it as unevaluated — correctly, and it is therefore
    # unpinnable by content. Said out loud rather than papered over: that one row is covered by
    # the count check, not by this pin. The other two `False` rows hold the silent direction.
    "test_the_predicate_reports_exactly_the_escape_routes": ((0, 1), (
        ('\nimport pytest\n@pytest.mark.parametrize("a,b", [[1, 2], [3, 4]])\ndef t(a, b): pass\n',
         False),
        ('\nfrom pytest import mark\n@mark.parametrize("a,b", [(1, 2), (3, 4)])\n'
         'def t(a, b): pass\n', False),
        ('\nimport pytest\n@pytest.mark.parametrize("a,b", [(1, 2), (3, 4)])\n'
         'def other(a, b): pass\n@pytest.mark.parametrize("a,b", [(9, 9), (8, 8)])\n'
         'def t(a, b): pass\n', True),
        ('\nimport pytest\n@parametrize("a,b", [(1, 2), (3, 4)])\ndef t(a, b): pass\n', True),
        ('\nimport pytest\nROWS = [(1, 2), (3, 4)]\n@pytest.mark.parametrize("a,b", ROWS)\n'
         'def t(a, b): pass\n', True),
        ('\nimport pytest\n@pytest.mark.parametrize("a,b", [(3, 4), (5, 6)])\ndef t(a, b): pass\n',
         True),
        ('\nimport pytest\n@pytest.mark.parametrize("a,b", [(1, 1 + 1), (3, 4)])\n'
         'def t(a, b): pass\n', True),
        ('\nimport pytest\n@pytest.mark.parametrize("a,b", ((1, 2), (3, 4)))\ndef t(a, b): pass\n',
         False),
    )),
    "test_the_tuple_list_equivalence_applies_only_where_pytest_unpacks": ((0, 1), (
        ('@pytest.mark.parametrize("a,b", [[1, 2], [3, 4]])', False),
        ('@pytest.mark.parametrize("x", [[1, 2], [3, 4]])', True),
    )),
    "test_argnames_are_counted_conservatively": (None, (
        ('"a,b"', 2), ('"x"', 1), ('["a", "b"]', 2), ("SOME_NAME", 1),
    )),
}


def test_this_modules_own_controls_are_pinned():
    """The predicate turned on the module that tests it.

    `Q-518`'s shape is a control whose rows can be deleted with the suite green, and Phase 301
    shipped two fresh instances of it while closing the entry. The one in this file is closed
    here; the one in `tests/test_review_close_reference_pins.py` is closed there, by the same
    predicate, because the pin DATA belongs with the module that owns the arm.

    **Where the regress stops**, stated rather than left implicit: these rows are pinned by
    `case_pin_problems`, and `case_pin_problems` is tested by these rows. Breaking both is two
    edits in one diff, which is where a mechanism ends and a reviewer begins. Every layer below
    it was a single-token edit with the suite green.
    """
    problems = case_pin_problems(Path(__file__).read_text(encoding="utf-8"), _SELF_PINS)
    assert not problems, "\n\n".join(problems)


_SHAPE_SRC = """
import pytest
ROWS = [(1, 2), (3, 4)]
@pytest.mark.parametrize("a,b", [(1, 2), (3, 4)])
def t(a, b): pass
@pytest.mark.parametrize("a,b", ROWS)
def u(a, b): pass
"""


@pytest.mark.parametrize("mutate,expect,why", [
    (lambda s: s, False, "the honest shape: two controls, both populated"),
    (lambda s: s.replace('[(1, 2), (3, 4)])\ndef t', '[(1, 2)])\ndef t'), True,
     "an inline list emptied to ONE row — the `>= 2` bar"),
    (lambda s: s.replace("ROWS = [(1, 2), (3, 4)]", "ROWS = []"), True,
     "a NAMED list emptied — the `ast.Name` arm"),
    (lambda s: s.replace('@pytest.mark.parametrize("a,b", ROWS)\ndef u(a, b): pass\n', ""), True,
     "a whole control DELETED — the count ratchet, which no content pin can see"),
    (lambda s: s + '@pytest.mark.parametrize("a,b", ROWS)\ndef v(a, b): pass\n', True,
     "a control ADDED without raising the pin — the ratchet is exact in both directions"),
    (lambda s: s.replace('@pytest.mark.parametrize("a,b", [(1, 2), (3, 4)])\ndef t(a, b): pass\n',
                         '@pytest.mark.parametrize("a,b", (x for x in []))\ndef t(a, b): pass\n'),
     True, "a case list of a shape the guard cannot size"),
])
def test_the_shape_bars_are_driven_rather_than_asserted_inline(mutate, expect, why):
    """The control both bars shipped without, and the round measured them vacuous for it.

    `Q-518`, Phase 301. `len(cases.elts) >= 2` and the decorator-count bar were inline `assert`s
    inside the guard test, so no control could feed them a tampered source. The round neutered
    each to `>= 0` and the whole suite stayed green — the entry's own shape, in the fix for the
    entry. Extracting `parametrize_shape_problems` is what makes them drivable; this is what
    drives them.

    The honest row first, because a control made only of failures cannot tell "catches the
    defect" from "reports everything".
    """
    src = mutate(_SHAPE_SRC)
    problems = parametrize_shape_problems(src, 2, {"ROWS": [(1, 2), (3, 4)] if "ROWS = []" not in src else []})
    assert bool(problems) is expect, (
        f"{why}: expected {'a report' if expect else 'silence'}, got {problems!r}")


@pytest.mark.parametrize("cases_src,reports,why", [
    ('[pytest.param(1, 2, id="first"), (3, 4)]', False,
     "pytest.param with an id is the same CASE as the bare tuple"),
    ('[pytest.param(1, 2, marks=pytest.mark.xfail), (3, 4)]', False,
     "pytest.param with marks, likewise"),
    ('[pytest.param(9, 9, id="first"), (3, 4)]', True,
     "a pytest.param whose VALUES differ is still reported"),
])
def test_pytest_param_wrappers_are_unwrapped_not_reported_missing(cases_src, reports, why):
    """`Q-518`, Phase 301's round. The commonest non-bare row spelling was a false FAIL.

    `pytest.param(...)` carries an id or marks, which change the test's label and not its values,
    so it is the same case as the bare tuple and a pin must not report it missing. The third row
    is the other direction: unwrapping must not make every `pytest.param` match.
    """
    src = f'\nimport pytest\n@pytest.mark.parametrize("a,b", {cases_src})\ndef t(a, b): pass\n'
    problems = case_pin_problems(src, {"t": (None, ((1, 2),))})
    assert bool(problems) is reports, (
        f"{why}: expected {'a report' if reports else 'silence'}, got {problems!r}")


def test_the_keyword_spelling_of_parametrize_is_read():
    """`argnames=`/`argvalues=` are legal and were a false FAIL until the round found them."""
    src = ('\nimport pytest\n@pytest.mark.parametrize(argnames="a,b", argvalues=[(1, 2), (3, 4)])'
           '\ndef t(a, b): pass\n')
    assert not case_pin_problems(src, {"t": (None, ((1, 2),))})
    assert parametrized_cases(src)["t"].argnames == 2


def test_a_decoy_definition_cannot_supply_a_pinned_row():
    """`Q-518`, Phase 301's round, finding CX7 — the one that defeated the whole mechanism.

    `ast.walk` descends into nested functions and class bodies, which pytest never collects, so a
    decoy holding the pinned rows let the real control be gutted with the suite green. Measured at
    the time: `7236 passed, 202 skipped`, zero failures. Only module-level functions are the
    population now, because only those are tests.
    """
    for shape, src in [
        ("nested function", '\nimport pytest\ndef _holder():\n'
                            '    @pytest.mark.parametrize("a,b", [(1, 2), (3, 4)])\n'
                            '    def t(a, b): pass\n'
                            '@pytest.mark.parametrize("a,b", [(9, 9), (8, 8)])\n'
                            'def t(a, b): pass\n'),
        ("class method", '\nimport pytest\nclass _Holder:\n'
                         '    @pytest.mark.parametrize("a,b", [(1, 2), (3, 4)])\n'
                         '    def t(self, a, b): pass\n'
                         '@pytest.mark.parametrize("a,b", [(9, 9), (8, 8)])\n'
                         'def t(a, b): pass\n'),
    ]:
        problems = case_pin_problems(src, {"t": (None, ((1, 2),))})
        assert problems, f"a {shape} decoy supplied the pinned row — CX7 is open again"
