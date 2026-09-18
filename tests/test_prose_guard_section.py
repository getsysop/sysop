"""`_prose_guard_helpers.section()` — the fence-blind slicer (`Q-543`, Phase 308).

**The defect.** `section()` closed a section at the next line matching `^#{1,N} \\S`, which
matches a **bash comment inside a fenced block**. Its docstring promised *"the next heading
of the SAME OR HIGHER level"*, so this was a defect against contract, not a declared limit.
A guard slicing such a section read a fraction of its subject, and a NEGATIVE assertion over
the invisible remainder passed vacuously. Live instance at the time of the fix: `### 2e.
Claim-Artifact Report` in `review-close/SKILL.md`, **3,210 of 11,628 characters — 28%** —
read by two guards in `test_review_close_claim_artifact_report.py`.

**Phase 238 found the same defect and worked around it locally** rather than fixing the
shared helper (`test_plan_review_config_docs.py::_section_6_1`, still in the tree, and now
folded back onto the fixed helper). One `grep -rn '_prose_guard_helpers.section'` would have
found that record; Phase 307 filed it as novel instead.

**What this module does NOT cover**, stated because Phase 307 shipped three docstrings whose
central claim about their own guard was false when written:

* It does not prove any *caller's* assertions are non-vacuous. Widening a slice cannot
  redden a positive assertion, and both live guards over the truncated section are positive
  — so this fix restored the contract without proving anything about what those two check.
  That is `Q-504`/dimension 10's business, not this module's.
* The call-site gate below reads only calls whose text and heading arguments resolve
  STATICALLY. An unresolvable site sets `problem` and reddens rather than being skipped, so
  the population cannot silently shrink — but a call built at runtime from a computed
  heading would have to be added to the resolution table by hand.
* `section()` still slices on ATX headings only: a setext underline and an indented ATX
  heading do not close a section, and the HEADING search is not itself fence-aware.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _prose_guard_helpers import carries, section  # noqa: E402
from _section_call_sites import audit, fence_aware_slice, fence_blind_slice  # noqa: E402

SKILL = REPO_ROOT / "core/skills/review-close/SKILL.md"
_2E = "### 2e. Claim-Artifact Report (report, never reject — Phase 237, part B leg 1)"
# ONE value, read by both the pin and its non-vacuity control. They held separate copies
# until the author-side battery re-pointed the pin alone and watched the control stay
# green — a phrase moved into the visible 28% would have gone unnoticed, which is the
# two-readers-one-value shape this repo keeps paying for.
#
# Read with `carries()`, not `in`: a raw substring made a rendering-identical SOFT WRAP
# of that sentence redden the pin with "it is truncating again", which is a lie about a
# slice that is fine. That is Phase 292 / `Q-495`'s class, and this repo already ships
# the tolerant reader for it.
_2E_TAIL_PHRASE = "the `Orchestrator artifacts:` line"


# ── the defect, and a control proving the input exercises it ──────────────────────────

_FENCED_COMMENT = (
    "\n## Target\n"
    "intro\n\n"
    "```bash\n"
    "# not a heading — a bash comment\n"
    "run --thing\n"
    "```\n\n"
    "TAIL-MARKER\n\n"
    "## Next\n"
    "SHOULD-NOT-APPEAR\n"
)


def test_a_fenced_hash_comment_does_not_close_the_section():
    body = section(_FENCED_COMMENT, "## Target")
    assert "TAIL-MARKER" in body, (
        "the slice stopped at a `#` line inside a fenced block — the whole defect"
    )
    assert "SHOULD-NOT-APPEAR" not in body, "the slice ran past its real closer"


def test_the_fence_blind_slicer_truncates_that_same_input():
    """Non-vacuity for the test above. Without this, a `section()` that stopped working
    entirely — returning the whole file — would satisfy it."""
    assert "TAIL-MARKER" not in fence_blind_slice(_FENCED_COMMENT, "## Target"), (
        "the control no longer reproduces the defect, so the test above proves nothing"
    )


# ── the contract the fix must not break ───────────────────────────────────────────────

def test_a_same_level_heading_still_closes_the_section():
    t = "\n## A\nkeep\n\n## B\ndrop\n"
    assert "keep" in section(t, "## A") and "drop" not in section(t, "## A")


def test_a_higher_level_heading_still_closes_the_section():
    t = "\n### A\nkeep\n\n## B\ndrop\n"
    assert "keep" in section(t, "### A") and "drop" not in section(t, "### A")


def test_a_deeper_heading_does_not_close_the_section():
    t = "\n## A\nkeep\n\n### A1\nalso-keep\n\n## B\ndrop\n"
    body = section(t, "## A")
    assert "also-keep" in body and "drop" not in body


def test_a_duplicate_heading_is_still_refused():
    with pytest.raises(AssertionError, match="found 2"):
        section("\n## A\nx\n\n## A\ny\n", "## A")


def test_an_absent_heading_is_still_refused():
    with pytest.raises(AssertionError, match="found 0"):
        section("\n## B\nx\n", "## A")


# ── fence pairing: the two shapes a hand-rolled pairing misses (Phase 291's survivors) ─

def test_a_tilde_fence_is_a_fence():
    t = "\n## A\n~~~\n# not a heading\n~~~\nTAIL\n\n## B\ndrop\n"
    body = section(t, "## A")
    assert "TAIL" in body and "drop" not in body


def test_a_three_backtick_line_does_not_close_a_four_backtick_block():
    t = ("\n## A\n````markdown\n```bash\n# not a heading\n```\n````\nTAIL\n\n## B\ndrop\n")
    body = section(t, "## A")
    assert "TAIL" in body and "drop" not in body


def test_a_backtick_opener_whose_info_string_holds_a_backtick_is_not_a_fence():
    """CommonMark's rule, and `_fence_state()` already implements it. If this line is
    wrongly treated as a fence opener, the `#` below it is hidden and the section runs on."""
    t = "\n## A\nkeep\n```a`b\n# H\n```\n\n## B\ndrop\n"
    body = section(t, "## A")
    assert "# H" not in body, "a non-opener was treated as a fence, hiding a real heading"


# ── fail-closed, not fail-open ────────────────────────────────────────────────────────

def test_an_unterminated_fence_raises_rather_than_slicing_to_eof():
    with pytest.raises(AssertionError, match="unterminated fenced"):
        section("\n## A\nx\n\n```bash\n# oops\n", "## A")


def test_a_section_ending_on_a_legal_fence_closer_does_not_raise():
    """`_fence_state()` yields True for a fence's own CLOSING line, so reading the last
    yielded value as the end-of-file state reported every such section as unterminated.
    Caught by running the helper, not by reading it."""
    body = section("\n## A\nintro\n\n```bash\n# c\n```\n", "## A")
    assert body.endswith("```\n")


# ── the live tree ─────────────────────────────────────────────────────────────────────

def test_the_2e_slice_reaches_the_end_of_its_section():
    """A phrase from 2e's LAST paragraph, which sat in the invisible 72%."""
    body = section(SKILL.read_text(encoding="utf-8"), _2E)
    assert carries(body, _2E_TAIL_PHRASE), (
        "the 2e slice no longer reaches its closing paragraph — it is truncating again"
    )
    assert "## Step 3: Run Verification" not in body, "the slice swallowed its neighbour"


def test_the_fence_blind_slicer_would_not_reach_it():
    """Non-vacuity for the pin above: it must lie beyond where the old slicer stopped."""
    assert not carries(fence_blind_slice(
        SKILL.read_text(encoding="utf-8"), _2E), _2E_TAIL_PHRASE), (
        "the pinned phrase moved into the first 28% — pick one from the tail again, or "
        "this pin stops distinguishing a fixed slicer from the broken one"
    )


# ── the population gate ───────────────────────────────────────────────────────────────

def test_every_shared_section_call_site_resolves():
    rows = audit()
    bad = [f"{r.file}:{r.line} — {r.problem}" for r in rows if r.problem]
    assert not bad, "call sites this census cannot measure:\n  " + "\n  ".join(bad)
    over_files = [r for r in rows if not r.synthetic]
    # The LIVE count, not the pre-phase one. This was `>= 11` against 13 actual, so two
    # modules could drop out unnoticed — and a reviewer's battery dropped them, green,
    # by four ordinary edits. A floor set below its subject is slack, not a ratchet.
    assert len(over_files) >= 13, (
        f"only {len(over_files)} file-backed call sites found, against 13 live when this "
        f"was written. Either a module stopped calling the shared helper — in which case "
        f"lower this deliberately — or a binding shape went unrecognised and the "
        f"population shrank silently, which is the failure this floor exists to catch."
    )


# The two path-shaped arms of the cut script's Pass 4 alternation (`^tools/`,
# `^CLAUDE\.md$`). The other arms are test-module filename patterns, which a
# `section()` text argument never resolves to. Kept as a literal because the source of
# truth — `tools/cut_public_release.sh` — is itself stripped in the tree where this
# predicate has to hold; `test_the_mirror_excluded_prefixes_match_the_cut_script` below
# pins the literal against that script wherever the script exists.
_MIRROR_EXCLUDED_PREFIXES = ("tools/", "CLAUDE.md")


def test_every_absent_call_site_path_is_mirror_excluded():
    """Runs in BOTH trees, and is the half that does the work.

    `Row.absent` tolerates a resolved path this tree does not contain, which the public
    snapshot needs because it strips `tools/`. Left at that, the tolerance would also
    absorb a `core/skills/...` path that had genuinely gone missing — invisibly, and
    only in the one tree nobody runs locally. So the tolerance is bounded by WHICH paths
    may be absent, not by which tree is running.
    """
    rogue = [f"{r.file}:{r.line} -> {r.path}" for r in audit()
             if r.absent and not r.path.startswith(_MIRROR_EXCLUDED_PREFIXES)]
    assert not rogue, (
        "a call site resolved to a path that is absent AND is not mirror-excluded:\n  "
        + "\n  ".join(rogue)
        + "\nThat is a broken resolution-table entry, not a stripped snapshot."
    )


def test_the_mirror_excluded_prefixes_match_the_cut_script():
    """Pins the literal above against its source of truth wherever that exists. Skipped
    in a stripped tree, which is the only place the literal is load-bearing and the only
    place the script is gone — stated rather than left as an accident."""
    cut = REPO_ROOT / "tools/cut_public_release.sh"
    if not cut.is_file():  # pragma: no cover - public-snapshot path
        pytest.skip("tools/ is mirror-excluded and absent here")
    alt = cut.read_text(encoding="utf-8")
    # DERIVED, not spot-checked. The first version asserted the script CONTAINS each
    # arm, which is satisfied while the literal above says anything at all — the
    # author-side battery widened the literal to `("",)`, neutering the bound, and
    # watched this stay green. Equality is the assertion; membership was decoration.
    m = re.search(r"""hard "Pass 4 [^"]*"[^|]*\|\s*grep -iE '([^']+)'""", alt)
    assert m, "Pass 4's alternation is no longer where this test reads it from"
    derived = tuple(
        a[1:].replace("\\.", ".").rstrip("$")
        for a in m.group(1).split("|")
        if a.startswith("^")
    )
    assert set(_MIRROR_EXCLUDED_PREFIXES) == set(derived), (
        f"_MIRROR_EXCLUDED_PREFIXES is {_MIRROR_EXCLUDED_PREFIXES}, but Pass 4's "
        f"path-anchored arms derive {derived}. The literal exists only because the cut "
        f"script is stripped in the tree where the bound is load-bearing; it is not a "
        f"place to widen the bound."
    )


def test_no_call_site_path_is_absent_in_the_source_repo():
    """The stricter half, and it only makes sense here.

    In this repo every resolved path exists. Phase 310's cut is why both halves exist:
    `tests/test_prose_guard_section.py` shipped in Phase 308 and no cut ran between, so
    nothing had ever executed this module inside a sterilized tree. It raised
    `FileNotFoundError` there on `tools/CLAIM_TASK_ORCHESTRATOR_SPEC.md` and would have
    reddened the required `pytest` check on the public snapshot PR.
    """
    if not (REPO_ROOT / "tools").is_dir():  # pragma: no cover - public-snapshot path
        pytest.skip("stripped snapshot: tools/ is mirror-excluded, so an absent row is "
                    "expected here and is bounded by the test above instead")
    absent = [f"{r.file}:{r.line} -> {r.path}" for r in audit() if r.absent]
    assert not absent, (
        "a call site resolved to a path this repo does not contain:\n  "
        + "\n  ".join(absent)
        + "\n`Row.absent` exists for the stripped public snapshot, not for this tree. "
          "Here it means the resolution table points at a file that has moved or gone."
    )


def test_no_shared_section_call_site_is_truncated():
    # `not r.absent` here and in the subject control below is DEFENSIVE, not
    # load-bearing, and the author-side battery says so: an absent row carries
    # `live is None` and `fence_aware is None`, so `None != None` already excludes it
    # and removing the clause stays green (battery M5/M6). It is kept against a future
    # `Row` that carries a measurement for an unread file, and it is commented rather
    # than left to read as a working filter.
    rows = audit()
    bad = [f"{r.file}:{r.line} {r.path} {r.heading!r}: live {r.live:,} vs fence-aware "
           f"{r.fence_aware:,}"
           for r in rows if r.problem is None and not r.synthetic and not r.absent
           and r.live != r.fence_aware]
    assert not bad, (
        "the shipped slicer disagrees with an independent fence-aware slicer:\n  "
        + "\n  ".join(bad))


def test_the_corpus_still_contains_a_section_the_old_slicer_would_truncate():
    """The gate above has a SUBJECT only while some call site slices a section holding a
    fenced `#`. If shipped prose changes so none does, the gate goes quietly vacuous —
    Phase 253's "guards that lost their subject" repeated. Red here means re-point it,
    not delete it."""
    rows = [r for r in audit()
            if r.problem is None and not r.synthetic and not r.absent
            and r.current != r.fence_aware]
    assert rows, (
        "no call site slices a section containing a fenced `#` any more, so "
        "`test_no_shared_section_call_site_is_truncated` can no longer fail"
    )


# ── the census's own classification rules, against synthetic modules ──────────────────
#
# Each of these closes a mutation the author-side battery walked through: the rule was
# right and nothing exercised it, because the real corpus contains only shapes that
# happen to agree. `audit(tests_dir=...)` exists for exactly this.

def _synthetic(tmp_path, body: str):
    (tmp_path / "test_synth.py").write_text(body, encoding="utf-8")
    return audit(tests_dir=tmp_path)


def test_an_unresolvable_text_argument_becomes_a_problem_row(tmp_path):
    """A site the census cannot read must REDDEN, not be skipped — the rule the module's
    docstring states, and which was untrue of four call shapes until the round."""
    rows = _synthetic(tmp_path, "from _prose_guard_helpers import section\n"
                                "def t():\n    return section(mystery_text(), '## A')\n")
    assert len(rows) == 1 and rows[0].problem, rows
    assert "resolution table" in rows[0].problem


def test_a_module_that_shadows_section_contributes_no_rows(tmp_path):
    """Import-aware, not name-aware. A local `section(text, start, end)` takes an explicit
    terminator and is immune; counting it is measurement (2)'s error."""
    assert _synthetic(tmp_path,
                      "from _prose_guard_helpers import section\n"
                      "def section(text, start, end=None):\n    return text\n"
                      "def t():\n    return section(open('x').read(), '## A', '## B')\n") == []


def test_a_module_that_does_not_import_the_helper_contributes_no_rows(tmp_path):
    assert _synthetic(tmp_path, "def t():\n    return section(open('x').read(), '## A')\n") == []


def test_a_literal_text_argument_is_RECORDED_as_synthetic_not_dropped(tmp_path):
    """Recorded, because a dropped row is invisible and the population has to stay
    countable. The claim was in the docstring with nothing testing it."""
    rows = _synthetic(tmp_path, "from _prose_guard_helpers import section\n"
                                "def t():\n    x = '\\n## A\\nbody\\n'\n"
                                "    return section(x, '## A')\n")
    assert len(rows) == 1 and rows[0].synthetic and rows[0].problem is None, rows


def test_the_real_corpus_still_contains_a_synthetic_row(tmp_path):
    """Non-vacuity for the classification above, against the live tree."""
    assert any(r.synthetic for r in audit()), (
        "no call site slices a string literal any more — the synthetic arm is dead code"
    )


def test_an_alias_resolves_from_the_INNERMOST_enclosing_function(tmp_path):
    """Two functions binding the same local name to different files: the narrower span
    must win. Module-wide resolution named a different file than the call reads, and a
    wrong resolution is worse than a reported one because it prints a number."""
    # **The CALL sits in the OUTER function.** A first cut put it in the inner one and
    # could not discriminate at all: the innermost span is chosen either way, and its
    # map is identical under both rules — only the OUTER function's map differs between
    # `ast.walk` (polluted by the nested def) and `_own_body` (not). A reviewer's
    # battery reverted `_own_body` to `ast.walk` and watched all 25 tests stay green.
    # So the binding that must differ is the one belonging to the span that WINS.
    rows = _synthetic(tmp_path,
                      "from _prose_guard_helpers import section\n"
                      "def outer():\n"
                      "    body = '\\n## A\\nx\\n'\n"
                      "    def inner():\n"
                      "        body = WORKFLOW.read_text(encoding='utf-8')\n"
                      "        return body\n"
                      "    return section(body, '## A')\n")
    assert len(rows) == 1, rows
    assert rows[0].synthetic and rows[0].problem is None, (
        f"the outer function's own `body` lost to its nested function's: {rows}")


# ── the census's own fence-aware slicer, which is the gate's SECOND OPINION ───────────

def test_the_censuss_independent_slicer_honours_a_tilde_fence():
    """It is only ever exercised on the shapes the corpus holds, and the corpus holds no
    `~~~`. Tested directly so the second opinion is worth having."""
    t = "\n## A\n~~~\n# not a heading\n~~~\nTAIL\n\n## B\ndrop\n"
    body = fence_aware_slice(t, "## A")
    assert "TAIL" in body and "drop" not in body


def test_the_censuss_independent_slicer_honours_a_nested_fence():
    t = "\n## A\n````markdown\n```bash\n# not a heading\n```\n````\nTAIL\n\n## B\ndrop\n"
    body = fence_aware_slice(t, "## A")
    assert "TAIL" in body and "drop" not in body


# ── binding shapes: the census must SEE the call, or say it cannot ────────────────────
#
# Each of these was invisible by construction — zero rows, suite green — until two
# independent batteries walked them through. A census that silently drops what it cannot
# read is the shape that produced "zero truncations", which is this module's whole
# subject, so these are the tests that make its rule-3 claim true rather than stated.

@pytest.mark.parametrize("source,why", [
    ("from _prose_guard_helpers import section as slice_it\n"
     "def t():\n    return slice_it(mystery(), '## A')\n", "aliased name import"),
    ("import _prose_guard_helpers as pgh\n"
     "def t():\n    return pgh.section(mystery(), '## A')\n", "aliased module import"),
    ("import tests._prose_guard_helpers\n"
     "def t():\n    return tests._prose_guard_helpers.section(mystery(), '## A')\n",
     "package-qualified module import"),
    ("from tests._prose_guard_helpers import section\n"
     "def t():\n    return section(mystery(), '## A')\n", "package-qualified name import"),
])
def test_every_binding_shape_is_seen(tmp_path, source, why):
    rows = _synthetic(tmp_path, source)
    assert len(rows) == 1, f"{why}: the call was invisible to the census — {rows}"
    assert rows[0].problem, f"{why}: measured without resolving its text — {rows}"


def test_a_class_method_named_section_does_not_shadow_the_module(tmp_path):
    """It binds no module-level name. Treating it as shadowing deleted every row for a
    real module — 13 file-backed rows to 12, suite green."""
    rows = _synthetic(tmp_path,
                      "from _prose_guard_helpers import section\n"
                      "class _H:\n    def section(self): return None\n"
                      "def t():\n    return section(mystery(), '## A')\n")
    assert len(rows) == 1, f"a class method deleted the module's rows: {rows}"


def test_a_module_level_rebinding_does_shadow(tmp_path):
    """The other direction, so the rule above is not simply 'never shadow'."""
    assert _synthetic(tmp_path,
                      "from _prose_guard_helpers import section\n"
                      "section = something_else\n"
                      "def t():\n    return section(mystery(), '## A')\n") == []


def test_a_function_local_rebinding_is_REPORTED_not_guessed(tmp_path):
    """It rebinds the name for calls in that function only. The census cannot tell which
    callable this is, so it says so rather than printing a number for the wrong one."""
    rows = _synthetic(tmp_path,
                      "from _prose_guard_helpers import section\n"
                      "def t():\n    section = other\n    return section(mystery(), '## A')\n")
    assert len(rows) == 1 and "rebound" in (rows[0].problem or ""), rows


# ── the remaining problem arms, each of which survived a battery ──────────────────────

def test_a_non_literal_heading_becomes_a_problem_row(tmp_path):
    rows = _synthetic(tmp_path, "from _prose_guard_helpers import section\n"
                                "def t():\n    return section(WORKFLOW.read_text(encoding='utf-8'), h)\n")
    assert len(rows) == 1 and "heading argument" in (rows[0].problem or ""), rows


def test_a_non_unique_heading_becomes_a_problem_row(tmp_path):
    rows = _synthetic(tmp_path, "from _prose_guard_helpers import section\n"
                                "def t():\n    return section(WORKFLOW.read_text(encoding='utf-8'), '## A')\n")
    assert len(rows) == 1 and "not unique" in (rows[0].problem or ""), rows


def test_a_generic_text_expression_is_not_resolved_for_another_module(tmp_path):
    """`path.read_text(...)` resolved globally to one file, so any future loop over many
    files would have been measured against it and PRINTED A NUMBER."""
    rows = _synthetic(tmp_path, "from _prose_guard_helpers import section\n"
                                "def t():\n    for path in EVERY:\n"
                                "        return section(path.read_text(encoding='utf-8'), '### Solo')\n")
    assert len(rows) == 1 and rows[0].problem, (
        f"a generic expression resolved to a file this module never reads: {rows}")


def test_the_census_recurses_into_subdirectories(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "test_deep.py").write_text(
        "from _prose_guard_helpers import section\n"
        "def t():\n    return section(mystery(), '## A')\n", encoding="utf-8")
    assert len(audit(tests_dir=tmp_path)) == 1, "a guard in a subdirectory is invisible"


def test_a_section_whose_fence_never_closes_is_a_row_not_a_traceback(tmp_path):
    """`audit()` promises a row. An AssertionError escaping it reddens three tests with
    a traceback instead of naming the site."""
    doc = tmp_path / "doc.md"
    doc.write_text("\n## A\nx\n\n```bash\n# oops\n", encoding="utf-8")
    import _section_call_sites as m
    key = ("test_x.py", "DOC.read_text()")
    m._TEXT_EXPR_BY_MODULE[key] = doc.relative_to(m.REPO_ROOT) if False else None
    m._TEXT_EXPR_TO_PATH["DOC_UNDER_TEST.read_text()"] = str(doc)
    try:
        (tmp_path / "test_x.py").write_text(
            "from _prose_guard_helpers import section\n"
            "def t():\n    return section(DOC_UNDER_TEST.read_text(), '## A')\n", encoding="utf-8")
        rows = audit(tests_dir=tmp_path)
        assert len(rows) == 1 and "slicing refused" in (rows[0].problem or ""), rows
    finally:
        m._TEXT_EXPR_TO_PATH.pop("DOC_UNDER_TEST.read_text()", None)
        m._TEXT_EXPR_BY_MODULE.pop(key, None)


# ── the second opinion must stay a second OPINION ─────────────────────────────────────

def test_the_second_opinion_does_not_delegate_to_the_shipped_helper():
    """Replacing `fence_aware_slice`'s body with `return shipped_section(...)` left all
    tests green: `live == fence_aware` always, so the differential gate could never fail
    while still reading as coverage. Nothing asserted the independence the gate's whole
    value rests on."""
    import ast as _ast
    import inspect
    import _section_call_sites as m
    fn = _ast.parse(inspect.getsource(m.fence_aware_slice)).body[0]
    # The CODE, not the prose about it: its own docstring names `_fence_state()` to say
    # it deliberately does not use it, and a naive source scan flagged that sentence.
    body = [n for n in fn.body if not (isinstance(n, _ast.Expr)
                                       and isinstance(n.value, _ast.Constant)
                                       and isinstance(n.value.value, str))]
    code = "\n".join(_ast.unparse(n) for n in body)
    for forbidden in ("shipped_section", "_fence_state", "_prose_guard_helpers"):
        assert forbidden not in code, (
            f"the independent slicer calls {forbidden!r} — it is now a restatement of "
            f"the code it is supposed to check, not a second opinion")


def test_the_two_slicers_agree_on_the_backtick_info_string_rule():
    """They disagreed, and the gate's message would have accused the SHIPPED one, which
    is the correct implementation."""
    t = "\n## A\nkeep\n```a`b\n# H\n```\nTAIL\n\n## B\ndrop\n"
    assert section(t, "## A") == fence_aware_slice(t, "## A")


# ── the helper's own matching rules, each of which survived a reviewer's battery ──────

def test_a_hash_run_with_no_following_word_does_not_close():
    """The closer requires `\\S` after the space. Without it a bare `## ` line closes."""
    t = "\n## A\nkeep\n## \nmore\n\n## B\ndrop\n"
    body = section(t, "## A")
    assert "more" in body and "drop" not in body


def test_a_deeper_heading_sharing_a_suffix_is_not_the_heading():
    """The marker is newline-anchored, so `### Solo` does not match inside `#### Solo`."""
    t = "\n#### Solo\nnope\n\n### Solo\nkeep\n\n## B\ndrop\n"
    body = section(t, "### Solo")
    assert "keep" in body and "nope" not in body and "drop" not in body


def test_a_longer_closer_closes_a_shorter_fence():
    t = "\n## A\nkeep\n```\n# c\n`````\nTAIL\n\n## B\ndrop\n"
    body = section(t, "## A")
    assert "TAIL" in body and "drop" not in body


def test_a_tilde_line_does_not_close_a_backtick_fence():
    """The property `section()`'s docstring cites as why the fix is correct."""
    t = "\n## A\nkeep\n```\n# c\n~~~\n# d\n```\nTAIL\n\n## B\ndrop\n"
    body = section(t, "## A")
    assert "# d" in body and "TAIL" in body and "drop" not in body


def test_a_would_be_closer_carrying_an_info_string_does_not_close():
    t = "\n## A\nkeep\n```\n# c\n``` extra\n# d\n```\nTAIL\n\n## B\ndrop\n"
    body = section(t, "## A")
    assert "# d" in body and "TAIL" in body and "drop" not in body


# ── the second opinion's OWN pairing rules ───────────────────────────────────────────
#
# Tested directly, because the corpus contains no mixed-character and no longer-closer
# site — so both rules were exercised by nothing, and a reviewer's battery removed each
# and watched the gate stay green. A second opinion nobody checks is not one.

def test_the_second_opinion_requires_a_matching_fence_CHARACTER():
    t = "\n## A\nkeep\n```\n# c\n~~~\n# d\n```\nTAIL\n\n## B\ndrop\n"
    body = fence_aware_slice(t, "## A")
    assert "# d" in body and "TAIL" in body and "drop" not in body


def test_the_second_opinion_accepts_a_LONGER_closer():
    t = "\n## A\nkeep\n```\n# c\n`````\nTAIL\n\n## B\ndrop\n"
    body = fence_aware_slice(t, "## A")
    assert "TAIL" in body and "drop" not in body


def test_the_innermost_span_wins_when_the_call_is_in_the_INNER_function():
    """The companion to the test above, and both are needed.

    That one puts the call in the OUTER function, which is the only shape that can see
    `_own_body`'s nested-function exclusion — but it makes the span sort irrelevant,
    because only one span contains the call. This one puts the call in the INNER
    function, where two spans contain it and `spans.sort` decides. Reversing that sort
    survived every other test in this module.
    """
    import tempfile
    d = Path(tempfile.mkdtemp())
    (d / "test_synth.py").write_text(
        "from _prose_guard_helpers import section\n"
        "def outer():\n"
        "    body = WORKFLOW.read_text(encoding='utf-8')\n"
        "    def inner():\n"
        "        body = '\\n## A\\nx\\n'\n"
        "        return section(body, '## A')\n"
        "    return inner\n", encoding="utf-8")
    rows = audit(tests_dir=d)
    assert len(rows) == 1, rows
    assert rows[0].synthetic and rows[0].problem is None, (
        f"the outer span won over the inner one: {rows}")
