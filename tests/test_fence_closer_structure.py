"""The fence closer decision is structural, not a substring — Phase 281's round, HIGH 1+2.

**Why this module exists, in the round's own words.** Phase 281 moved the info-string rule
out of two inline caller conditions into a `fence_closes` predicate, and re-pointed
`tests/test_intra_repo_citations.py`'s two anchors from the CALLERS onto the DEFINITION.
The phase's record claimed that was "a re-point, not a softening". The guard-strength lens
refuted it by measurement:

* **HIGH 1** — reverting the *caller* at Step 7f back to an inline
  `mark[0] == fence[0] and mark[1] >= fence[1]` survived the whole suite, and executing the
  shipped block then destroyed **six lines of a task body's `## Plan`** with
  `unbalanced=False`, so the refuse-to-write backstop never fired. `strip_sections` is, by
  the orchestrator guard's own comment, *"the ONLY prescribed block in this skill that
  rewrites a TRACKED file."* Applying the identical defect to the pre-phase tree WAS caught,
  because the anchor then pinned the caller line that carried the clause inline. So the
  re-point genuinely moved coverage off the caller.
* **HIGH 2** — appending `or bool(mark) and mark[1] >= open_mark[1]` to the definition
  neuters the rule while leaving the registered anchor byte-exact on its line, because
  `_staleness` is `anchor not in window` over a single line.

Both defeat a substring pin, and neither can defeat a parse. This module reads the shipped
heredocs, parses them, and asserts the SHAPE: one predicate, a pure conjunction, no caller
re-implementing it.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS = (
    REPO_ROOT / "core" / "skills" / "claim-task" / "SKILL.md",
    REPO_ROOT / "core" / "skills" / "auto-build" / "SKILL.md",
)
EXPECTED_BLOCKS = 3  # Step 7f's writer, Step 8's verifier, /auto-build item 1-record


def _fence_payloads() -> list[tuple[str, int, str]]:
    """Every shipped python heredoc that defines `fence_closes`, as (file, line, source)."""
    found = []
    for path in SKILLS:
        lines = path.read_text(encoding="utf-8").split("\n")
        for i, ln in enumerate(lines):
            m = re.match(r"python3 - <<'([A-Z_0-9]+)'", ln)
            if not m:
                continue
            end = next((k for k in range(i + 1, len(lines)) if lines[k] == m.group(1)), None)
            if end is None:
                continue
            body = "\n".join(lines[i + 1:end])
            if "def fence_closes" in body:
                found.append((path.name + f" ({path.parent.name})", i + 1, body))
    return found


def test_the_population_is_the_three_shipped_blocks():
    """Vacuity control. Every assertion below iterates this list; an extractor that
    silently returns fewer makes the whole module green over an unmeasured tree."""
    found = _fence_payloads()
    assert len(found) == EXPECTED_BLOCKS, (
        f"expected {EXPECTED_BLOCKS} shipped blocks defining `fence_closes`, found "
        f"{len(found)}: {[(f, l) for f, l, _ in found]}. Either a copy was added without "
        "updating this guard, or the extractor has stopped matching the heredoc shape — "
        "and in the second case every other row here is passing over nothing."
    )


@pytest.mark.parametrize("where,line,src", [(w, l, s) for w, l, s in _fence_payloads()],
                         ids=lambda v: str(v)[:40] if isinstance(v, (str, int)) else "src")
def test_fence_closes_is_a_pure_conjunction_of_its_three_properties(where, line, src):
    """HIGH 2. The docstring shipped in all three copies says *"Three properties, not two."*
    A substring pin cannot tell a conjunction from a disjunction that contains it."""
    tree = ast.parse(src)
    fns = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "fence_closes"]
    assert len(fns) == 1, f"{where}:{line} — expected one `fence_closes`, found {len(fns)}"
    fn = fns[0]
    ors = [n for n in ast.walk(fn) if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or)]
    assert not ors, (
        f"{where}:{line} — `fence_closes` contains a disjunction: "
        f"{[ast.unparse(o) for o in ors]}. Any `or` short-circuits the conjunction and "
        "neuters at least one of the three properties while leaving every registered "
        "substring anchor byte-exact on its line. Measured by the round: appending "
        "`or bool(mark) and mark[1] >= open_mark[1]` survived the entire suite."
    )
    ret = fn.body[-1]
    assert isinstance(ret, ast.Return) and isinstance(ret.value, ast.BoolOp) \
        and isinstance(ret.value.op, ast.And), (
        f"{where}:{line} — `fence_closes` must END in a single `return <a and b and c>`; "
        f"got {ast.unparse(ret)}")
    clauses = [ast.unparse(v) for v in ret.value.values]
    for prop, pat in (("same character", r"mark\[0\] == open_mark\[0\]"),
                      ("at least as long", r"mark\[1\] >= open_mark\[1\]"),
                      ("no info string", r"not line\.strip\(\)\.strip\(mark\[0\]\)")):
        assert any(re.search(pat, c) for c in clauses), (
            f"{where}:{line} — `fence_closes` lost its **{prop}** clause. Clauses present: "
            f"{clauses}. All three are load-bearing and this block has shipped missing a "
            "different one twice.")


@pytest.mark.parametrize("where,line,src", [(w, l, s) for w, l, s in _fence_payloads()],
                         ids=lambda v: str(v)[:40] if isinstance(v, (str, int)) else "src")
def test_no_caller_re_implements_the_closer_test(where, line, src):
    """HIGH 1, and it is a data-loss guard, not a style guard.

    The only `>=` comparison anywhere in these blocks is the length half of the closer
    rule, and it belongs inside `fence_closes`. A caller that compares lengths itself has
    re-implemented the decision — which is exactly the revert that survived the suite and
    then ate six lines of a tracked task body.
    """
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "fence_closes")
    inside = {id(n) for n in ast.walk(fn)}
    stray = [ast.unparse(n) for n in ast.walk(tree)
             if isinstance(n, ast.Compare) and any(isinstance(o, ast.GtE) for o in n.ops)
             and id(n) not in inside]
    assert not stray, (
        f"{where}:{line} — a caller compares fence lengths itself: {stray}. The closer "
        "decision has one home per block on purpose; a second copy is how the info-string "
        "half went missing from one of two loops in the first place."
    )


@pytest.mark.parametrize("where,line,src", [(w, l, s) for w, l, s in _fence_payloads()],
                         ids=lambda v: str(v)[:40] if isinstance(v, (str, int)) else "src")
def test_every_fence_close_is_delegated(where, line, src):
    """The positive half of the rule above: each `<fence> = None` must be guarded by a
    `fence_closes(...)` call. Catches a caller that drops the test rather than replacing it."""
    tree = ast.parse(src)
    closes = [n for n in ast.walk(tree)
              if isinstance(n, ast.If) and len(n.body) == 1
              and isinstance(n.body[0], ast.Assign)
              and isinstance(n.body[0].value, ast.Constant) and n.body[0].value.value is None]
    assert closes, f"{where}:{line} — found no `<fence-var> = None` branch at all; re-point this guard"
    for node in closes:
        calls = [c for c in ast.walk(node.test)
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                 and c.func.id == "fence_closes"]
        assert calls, (
            f"{where}:{line} — a fence is closed by `{ast.unparse(node.test)}` rather than "
            "by `fence_closes(...)`. That is the HIGH-1 revert.")


@pytest.mark.parametrize("where,line,src", [(w, l, s) for w, l, s in _fence_payloads()],
                         ids=lambda v: str(v)[:40] if isinstance(v, (str, int)) else "src")
def test_the_bom_strip_survives(where, line, src):
    """Round lens 1, LOW T6, scoped by measurement rather than assumption.

    Removing the BOM strip from the READER copies was green. Scoped to the blocks that
    read a revision -- the ones that print a `MISSING` verdict. Step 7f's writer is
    excluded deliberately: it rewrites a local body it was handed, never decodes
    `git show` output, and has never carried the strip. A first cut of this row asserted
    all three and went red on the writer, which is the over-strict direction this same
    lens flagged elsewhere. The block's own comment says a leading BOM *"would report a
    false MISSING, which BLOCKS"* -- a refusal against a compliant branch.

    Pre-existing at Step 8, but Phase 281 copied it into a second shipped skill, which is
    when an unguarded behaviour stops being one site's problem. The block's own comment
    says a leading BOM *"would report a false MISSING, which BLOCKS"* -- a refusal against
    a compliant branch, which is the direction this repo treats as most expensive.
    """
    if "MISSING --" not in src:
        pytest.skip("writer block: reads no revision, so no decoded bytes carry a BOM")
    assert "ufeff" in src, (
        f"{where}:{line} -- the BOM strip is gone. A body saved with a UTF-8 BOM then "
        "reports a false MISSING and blocks the close.")
