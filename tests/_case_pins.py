"""Content pins over `pytest.mark.parametrize` case lists — `Q-518`, Phase 301.

**Why this is a module and not a third copy.** TWO test modules in this suite guarded their own
parametrize lists before Phase 301 — `tests/test_reader_census.py` and
`tests/test_thinning_transforms.py` — and each did it by COUNT — `len(cases.elts) >= 2`. Against
lists of 5, 6, 9 and 10 rows that licenses deleting 3, 4, 7 and 8 rows invisibly, and
`tests/test_reader_census.py`'s guard enumerated three working bypasses in its own docstring
while closing none of them. Confirmed by execution at Phase 301's open: deleting two ratchet
rows and widening one operator gave `7211 passed, 201 skipped` — the whole repo, zero failures
— while permitting `review-close/SKILL.md`'s `editor`+`mixed` mass to grow 105,968 → 317,904
silently.

The fix is to pin row CONTENT. Putting the machinery here rather than copying it is the same
call `tests/_prose_guard_helpers.py` records: this repo already carries
`test_every_copy_of_the_campaign_section_map_agrees` because a map got forked across three
files, and a fourth fork of a guard is a guard that will disagree with itself.

The pin DATA stays with each module, because which row is load-bearing is a fact about that
module's predicates and nothing else.
"""
from __future__ import annotations

import ast
from typing import NamedTuple


class CaseList(NamedTuple):
    """One test's inline parametrize rows, plus how many argnames the decorator declares.

    `argnames` decides whether a list row and a tuple row are the same case — see
    `parametrized_cases` — so the two travel together rather than the count being re-derived at
    each comparison site, which is how they get out of step.
    """

    argnames: int
    rows: list


#: A row the extractor could parse structurally but not evaluate — a name, a call, an f-string.
#: Distinct from every legal row value, so a pin can never accidentally match one.
_UNEVALUATABLE = object()


def parametrized_cases(source: str) -> dict[str, list]:
    """`{test name: [case row, …]}` for every INLINE parametrize list in a module source.

    Keyed by the test the decorator sits on, which is the property `Q-518` needed and the
    predecessor did not have: it walked bare `ast.Call` nodes, so it knew a case list existed
    somewhere at some line number and could not say which control it belonged to. A pin has to
    name its test or its failure message cannot tell a maintainer what to restore.

    Rows are `ast.literal_eval`ed. Every inline row in `tests/test_reader_census.py` evaluates —
    measured at Phase 301's close, 43 of 43 — but a row carrying a name or a call is recorded as
    `_UNEVALUATABLE` rather than dropped, so a pinned row that someone converts to a computed
    expression reports as missing instead of silently ceasing to be checked.

    Stacked decorators accumulate: a test with two `parametrize` decorators contributes both
    lists, because either one going empty is the defect this exists to see.

    **`argnames` is carried, and it is not bookkeeping.** `@parametrize("a,b", [(1, 2)])` unpacks
    the row, so `[1, 2]` and `(1, 2)` are the same two cases; `@parametrize("x", [(1, 2)])` passes
    the row through verbatim, so they are a tuple and a list and the test can tell. A comparison
    that ignores the difference is wrong in the second case, and Phase 301's round measured
    exactly that against the first cut of this module. `CaseList.argnames` is how
    `case_pin_problems` knows which rule applies.
    """
    tree = ast.parse(source)
    found: dict[str, list] = {}
    # MODULE-LEVEL functions only, and `ast.walk` is the wrong tool for that.
    #
    # `Q-518`, Phase 301's round, finding CX7 — and it defeated the whole mechanism. `ast.walk`
    # descends into nested functions and class bodies, which pytest never collects. So a DECOY
    # could hold the pinned rows while the real control was gutted, and the pin reported clean
    # with the entire suite green:
    #
    #     def _holder():                       # never collected
    #         @pytest.mark.parametrize(...)    # ... but walked, and keyed as `t`
    #         def t(a, b): pass
    #     @pytest.mark.parametrize("a,b", [])  # the real one, emptied
    #     def t(a, b): pass
    #
    # The docstring above calls the key "the test the decorator sits on". A bare `node.name` is
    # not a test identity — a collectable test is a module-level function, so that is the
    # population.
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            fn = getattr(dec, "func", None)
            if not (isinstance(dec, ast.Call) and isinstance(fn, ast.Attribute)
                    and fn.attr == "parametrize"):
                continue
            cases = _argvalues(dec)
            if not isinstance(cases, (ast.List, ast.Tuple)):
                continue
            argnames = _argnames_count(dec)
            rows = []
            for elt in _row_nodes(cases):
                try:
                    rows.append(ast.literal_eval(elt))
                except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
                    rows.append(_UNEVALUATABLE)
            prev = found.get(node.name)
            if prev is None:
                found[node.name] = CaseList(argnames, list(rows))
            else:
                # Stacked decorators can declare different argnames. Keep the SMALLER, because
                # the tuple/list equivalence below is only sound at 2+ and the conservative
                # reading is the one that cannot silence a real difference.
                found[node.name] = CaseList(min(prev.argnames, argnames), prev.rows + rows)
    return found


def _argvalues(dec: ast.Call):
    """The case list, positional or `argvalues=`. Both spellings are legal."""
    if len(dec.args) >= 2:
        return dec.args[1]
    for kw in dec.keywords:
        if kw.arg == "argvalues":
            return kw.value
    return None


def _row_nodes(cases) -> list:
    """The AST nodes that are the rows, with `pytest.param(...)` wrappers unwrapped.

    `Q-518`, Phase 301's round — over-strictness in the very class the phase was hunting.
    `pytest.param(1, 2, id="first")` is the same CASE as `(1, 2)`: the id and the marks change the
    test's label, not its values. The first cut compared the wrapper call against the pinned
    tuple, could not evaluate it, and reported the row missing — a false FAIL on the commonest
    non-bare spelling there is, and commoner by far than the list/tuple reformat `_norm` was
    written for. Same `Q-514` shape, same reason it matters: a guard that cries on correct commits
    gets edited to stop crying.

    Positional args only. `id=` and `marks=` are dropped deliberately — two rows differing only by
    id carry the same values, and values are what a pin is about.
    """
    out = []
    for elt in cases.elts:
        fn = getattr(elt, "func", None)
        if isinstance(elt, ast.Call) and (
                (isinstance(fn, ast.Attribute) and fn.attr == "param")
                or (isinstance(fn, ast.Name) and fn.id == "param")):
            out.append(ast.Tuple(elts=list(elt.args), ctx=ast.Load()))
        else:
            out.append(elt)
    return out


def _argnames_count(dec: ast.Call) -> int:
    """How many parameters the decorator's first argument declares.

    `parametrize` accepts `"a,b"` or `["a", "b"]`. A non-literal first argument is unreadable, and
    the answer there is **1** — the conservative value, because 1 is the case where a list row and
    a tuple row are genuinely different and must not be equated.
    """
    node = dec.args[0] if dec.args else next(
        (kw.value for kw in dec.keywords if kw.arg == "argnames"), None)
    if node is None:
        return 1
    try:
        names = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return 1
    if isinstance(names, str):
        return len([n for n in names.replace(" ", "").split(",") if n])
    if isinstance(names, (list, tuple)):
        return len(names)
    return 1


def _norm(value, argnames: int):
    """Canonicalise a row for comparison, and ONLY where pytest makes the two forms the same.

    Found by Phase 301's own author-side pass, under *"over-strictness, the direction that
    hides"*: a row reformatted from `(1, 2)` to `[1, 2]` reported as missing, which is a false
    FAIL on a legal edit — `Q-514`'s shape, and a guard that cries on correct commits is a guard
    that gets edited to stop crying.

    **The first fix for that was wrong, and the round measured it.** It coerced every sequence,
    recursively, on every row. But the equivalence is conditional:

        @parametrize("a,b", [(1, 2)])   ->  a=1, b=2      # the row is UNPACKED
        @parametrize("a,b", [[1, 2]])   ->  a=1, b=2      # ... identically
        @parametrize("x",   [(1, 2)])   ->  x=(1, 2)      # the row is PASSED THROUGH
        @parametrize("x",   [[1, 2]])   ->  x=[1, 2]      # ... and the test can tell

    Run against pytest, not reasoned about. So at one argname the two forms are different values
    and equating them silences a real difference — and the live target points the next consumer at
    `@parametrize("state", ["mixed", "runner", "none"])`, which is exactly that shape. That target is
    `REVIEW_CHECKLIST.md` § *Notes*' 2026-09-16 `tests/test_thinning_transforms.py` line, NOT a `Q-NNN`:
    Phase 301 filed one, its own round un-filed it under the Phase-278 bar, and the id was reissued.

    Hence: coerce the TOP LEVEL only, and only at 2+ argnames. No recursion, because a row's
    MEMBERS are handed to the test verbatim whatever the argname count, so `(1, [2])` and
    `(1, (2,))` are genuinely different cases.
    """
    if argnames >= 2 and isinstance(value, (list, tuple)):
        return tuple(value)
    return value


def case_pin_problems(source: str, pins: dict) -> list[str]:
    """Every pinned case row must still be present in its test's parametrize list.

    SUBSET presence, not equality, and the asymmetry is the design. Adding a row is always the
    good direction and three of these lists have taken one in the last four phases; an equality
    pin would redden on every such commit and be edited to pass, which is the failure mode
    `test_a_wrong_published_digit_is_reported`'s docstring records from the other side. A subset
    pin never fires on an addition and always fires on a deletion or an in-place inversion.

    Presence is tested with `==` over evaluated values, so a row's formatting, its comment, its
    spacing and the order of the list are all free to change. What cannot change is the row.

    `columns` selects what of each row is compared: `None` pins the whole row, an `int` pins that
    one column as a bare value, and a tuple of ints pins those columns as a tuple. The `int` form
    exists because the one list needing a projection needs a single column, and a pin written
    `('…',)` differs from `'…'` by a comma that a reader does not see — this function's first cut
    had exactly that defect and its own guard caught it on the first run.
    """
    found = parametrized_cases(source)
    problems = []
    for test, (columns, required) in sorted(pins.items()):
        if test not in found:
            problems.append(
                f"{test}: pinned, but no inline parametrize list was found on it. Either the "
                f"test was deleted, renamed, or its cases moved to a module constant — all "
                f"three want the pin updated in the same commit, deliberately.")
            continue
        argnames, all_rows = found[test]
        rows = [r for r in all_rows if r is not _UNEVALUATABLE]

        # A column projection over a row that is not a sequence would index INTO the value:
        # `"mixed"[0]` is `"m"`, which reports CLEAN against a pin of first letters, and an int
        # row raises `TypeError` instead of reporting. Both found by Phase 301's round, both
        # latent here and both live for that note's target, which is a single-argname string list.
        # Refuse the pin rather than answer it wrongly.
        if columns is not None:
            scalar = [r for r in rows if not isinstance(r, (list, tuple))]
            if scalar:
                problems.append(
                    f"{test}: pinned with a column projection ({columns!r}), but "
                    f"{len(scalar)} of its rows are not sequences (e.g. {scalar[0]!r}). "
                    f"Indexing those would compare a CHARACTER or raise — pin the whole row "
                    f"instead by passing `None` for the columns.")
                continue

        def project(row, _c=columns):
            if _c is None:
                return row
            return row[_c] if isinstance(_c, int) else tuple(row[i] for i in _c)

        # A projection is not the row pytest unpacks, so the tuple/list equivalence does not
        # apply to it — normalise the whole row only, and compare projections verbatim.
        seen = [project(row) if columns is not None else _norm(row, argnames) for row in rows]
        for row in required:
            if (row if columns is not None else _norm(row, argnames)) not in seen:
                problems.append(
                    f"{test}: the pinned case {row!r} is no longer in its parametrize list. "
                    f"Each pinned row is the ONLY row that kills a specific mutation of the "
                    f"predicate it drives — deleting it leaves the arm uncontrolled and the "
                    f"suite green, which is `Q-518`. If the row is genuinely obsolete, remove "
                    f"it from `_CASE_PINS` in the same commit and say why.\n"
                    f"  present: {seen!r}")
    return problems


def parametrize_shape_problems(source: str, expected_count: int,
                               module_globals: dict) -> list[str]:
    """The emptying bar and the decorator-count ratchet, as a PREDICATE a control can drive.

    `Q-518`, Phase 301, added by its round. Both bars lived as inline `assert`s inside the guard
    test, so nothing could feed them a tampered source — and the round's battery duly showed both
    surviving neutering with the whole suite green (`>= 2` -> `>= 0`, and the count bar -> `>= 0`).
    That is the same defect one level up from the entry itself: a check with no control.

    This module's own rule, stated by `editor_mass_problems` in the consumer and now obeyed here:
    *a function rather than an inline assert, with every input an argument, because a control that
    re-does the arithmetic in its own body passes over a neutered predicate.*

    `module_globals` is passed in rather than closed over so a control can drive the `ast.Name`
    arm against a namespace it constructs.
    """
    tree = ast.parse(source)
    problems = []
    checked = 0
    for node in ast.walk(tree):
        fn = getattr(node, "func", None)
        if not (isinstance(node, ast.Call) and isinstance(fn, ast.Attribute)
                and fn.attr == "parametrize"):
            continue
        cases = _argvalues(node)
        if cases is None:
            problems.append(f"parametrize at line {node.lineno} has no case list")
            continue
        if isinstance(cases, ast.Name):
            if not module_globals.get(cases.id):
                problems.append(
                    f"parametrize at line {node.lineno} names {cases.id!r}, which is empty "
                    f"or absent")
        elif isinstance(cases, (ast.List, ast.Tuple)):
            if len(cases.elts) < 2:
                problems.append(
                    f"the inline case list at line {node.lineno} has {len(cases.elts)} case(s). "
                    f"Emptying an inline list is invisible to every guard that reads module "
                    f"constants, and every control in this module is an inline list.")
        else:
            problems.append(
                f"parametrize at line {node.lineno} takes a {type(cases).__name__} this guard "
                f"cannot size; name it at module level instead")
        checked += 1
    if checked != expected_count:
        problems.append(
            f"this module has {checked} parametrized control(s) against a pinned "
            f"{expected_count}. ADDING one is good and wants the constant raised in the same "
            f"commit; REMOVING one is the case this exists to make visible, because the "
            f"`ast.Name`-driven controls are pinned by nothing else — a content pin covers the "
            f"inline lists only.")
    return problems
