"""Every call to the shared `_prose_guard_helpers.section()`, and what each one slices.

**Why this is a module and not a number.** `Q-543`'s blast radius was measured five times
before this one and the first four disagreed — three by Phase 307's author, one by a round
lens, and the fourth is the one its entry published. That fourth names two sites, and
neither is a call to the shared helper: `## Step 3c: Manual Smoke Gate` is sliced by nobody
(`test_review_close_merged_tree_gate.py` uses explicit start/end pairs), and `WORKFLOW.md`
§ 6.1 is sliced by `test_plan_review_config_docs.py`'s own local helper, which Phase 238
added *because of this defect* and which is therefore immune. The one real truncation —
`### 2e. Claim-Artifact Report` in `review-close/SKILL.md` — appears in none of the five.

So the population is derived here, by the suite, on every run. A number in prose rots; this
does not.

**The measurement rules, written down so the FORM can be checked and not just the total:**

* **Import-aware, not name-aware.** A module counts only if it imports `section` from
  `_prose_guard_helpers` or reaches it as an attribute, under whatever local name the
  import binds. Measurement (2) matched `section` by bare name and swept in 17 calls in
  a module that shadows the import; measurement (3) then over-corrected, excluding whole
  modules that merely contained the name. (An earlier draft of this sentence said (3)
  was the bare-name one — a misattribution, in the module whose subject is attribution.)
* **Shadowing is checked by AST at any depth.** A module defining its own `section` binds
  that name locally, and the local helpers here take an explicit terminator — they are
  immune. Measurement (1) regexed `section\\(` with no left word boundary and swept those in.
* **An argument this cannot resolve is a PROBLEM, not a skip.** `problem` is set and the
  gate reddens. A census that silently drops what it cannot read is the shape that produced
  "zero truncations" and demoted the entry to § Medium.
"""
from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS = REPO_ROOT / "tests"
HELPER = "_prose_guard_helpers"

sys.path.insert(0, str(TESTS))
from _prose_guard_helpers import section as shipped_section  # noqa: E402

# The text argument is an expression, not a path. Each is resolved by reading the module's
# own constant and recorded here; an expression absent from this table sets `problem`.
_TEXT_EXPR_TO_PATH = {
    "SCHEMA.read_text(encoding='utf-8')": "core/companion/tasks/schema.md",
    "SCHEMA.read_text()": "core/companion/tasks/schema.md",
    "AUTO_BUILD.read_text()": "core/skills/auto-build/SKILL.md",
    "SPEC.read_text()": "tools/CLAIM_TASK_ORCHESTRATOR_SPEC.md",
    "WORKFLOW.read_text(encoding='utf-8')": "core/companion/docs/WORKFLOW.md",
    "(REPO_ROOT / 'core' / 'companion' / 'tasks' / 'schema.md').read_text(encoding='utf-8')":
        "core/companion/tasks/schema.md",
    # NOTE: no entry for a GENERIC expression such as `path.read_text(...)`. It used to
    # map to `schema.md`, which was right for the one module that writes it and wrong
    # for every future one — a loop over many files would have been measured against
    # schema.md and printed a number, which `_alias_spans` below calls worse than a
    # reported failure. Generic expressions are module-scoped in `_TEXT_EXPR_BY_MODULE`.
    # `@module`: the module's own `SKILL` constant names the file — see `_MODULE_SKILL`.
    "SKILL.read_text()": "@module",
    "SKILL.read_text(encoding='utf-8')": "@module",
}
# Expressions too generic to resolve globally: keyed by (module, expression), so the
# resolution says WHICH module it was verified for and any other module gets a problem row.
_TEXT_EXPR_BY_MODULE = {
    # The retired-claim sweep reads every tracked file but calls `section()` only under
    # `if rel == _QUOTING_FILE`, so the one text it ever slices is that constant's file.
    ("tests/test_review_close_smoke_gate.py", "path.read_text(encoding='utf-8')"):
        "core/companion/tasks/schema.md",
    ("tests/test_claim_task_id_vocabulary.py", "skill_text"): "core/skills/claim-task/SKILL.md",
    ("tests/test_claim_task_id_vocabulary.py", "release_text"): "core/skills/release/SKILL.md",
}
_MODULE_SKILL = {
    "tests/test_review_close_claim_artifact_report.py": "core/skills/review-close/SKILL.md",
    "tests/test_prose_guard_section.py": "core/skills/review-close/SKILL.md",
    "tests/test_contribute_convention_sources.py": "core/skills/contribute-convention/SKILL.md",
}
# `test_review_close_smoke_gate.py` was listed here and never consulted — it resolves
# through `path.read_text(...)` instead. Dead configuration reads as coverage.


@dataclass(frozen=True)
class Row:
    file: str
    line: int
    heading: str | None
    path: str | None      # None for a synthetic row: the text came from a literal
    current: int | None       # what the pre-Phase-308, fence-BLIND slicer returned
    fence_aware: int | None   # what an independent fence-aware slicer returns
    live: int | None          # what the shipped helper returns today
    problem: str | None
    synthetic: bool = False   # sliced a string literal, not a file from the tree
    absent: bool = False      # resolved to a path this TREE does not contain
    # `absent` exists for one tree: the public snapshot, which strips `tools/`. A call
    # site that resolves correctly to `tools/CLAIM_TASK_ORCHESTRATOR_SPEC.md` cannot be
    # measured there, and Phase 310's cut found the census raising `FileNotFoundError`
    # over it inside the sterilized tree — a module that ships, reddening the required
    # `pytest` check on the public snapshot PR. It is NOT a softening: an absent row
    # still counts toward the population floor below (so a site that genuinely stops
    # calling the helper is still caught), it is excluded only from the truncation
    # comparison it cannot participate in, and
    # `test_no_call_site_path_is_absent_in_the_source_repo` asserts there are ZERO of
    # them here. In this repo the state is unreachable; if it ever becomes reachable,
    # that control reddens rather than this tolerance absorbing it.


def _module_shadows_section(tree: ast.AST) -> bool:
    """A MODULE-LEVEL `def section` or `section = …` rebinds the imported name.

    Module level only, and that scoping is the finding. The first cut walked the whole
    AST, so a **class method** named `section` — which binds no module-level name — and
    a function-local `section = …` each deleted every row for the module. Measured: one
    appended `class _H:\n    def section(self): …` took the census from 13 file-backed
    rows to 12 with the suite green, which is the silent shrink this module's own rule 3
    forbids. A function-local rebinding is handled per call instead, below: it makes
    that call unreadable, not the module invisible.
    """
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "section":
            return True
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "section" for t in node.targets):
                return True
    return False


def _helper_bindings(tree: ast.AST) -> tuple[set[str], set[str]]:
    """`(names bound to the helper's `section`, names bound to the helper MODULE)`.

    Binding-aware rather than spelling-aware. Three shapes were invisible by
    construction until a reviewer's battery walked all three through: `import section as
    slice_it`, `import _prose_guard_helpers as pgh`, and `import tests._prose_guard_helpers`.
    Each contributed zero rows — a census dropping what it cannot read, which is the
    shape that produced "zero truncations" and the thing rule 3 above claims to prevent.
    """
    call_names: set[str] = set()
    module_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[-1] == HELPER:
            for a in node.names:
                if a.name == "section":
                    call_names.add(a.asname or a.name)
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[-1] != HELPER:
                    continue
                # `import x.y` binds `x`; the call is then spelled `x.y.section(...)`.
                module_names.add(a.asname or a.name)
    return call_names, module_names


def _literal(node: ast.AST) -> str | None:
    try:
        v = ast.literal_eval(node)
    except Exception:
        return None
    return v if isinstance(v, str) else None


def _module_constants(tree: ast.AST) -> dict[str, str]:
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t, v = node.targets[0], _literal(node.value)
            if isinstance(t, ast.Name) and v is not None:
                out[t.id] = v
    return out


def _alias_spans(tree: ast.AST) -> list[tuple[int, int, dict[str, str]]]:
    """Per-FUNCTION alias maps as `(start, end, {name: rhs})`, narrowest first.

    Scoped to the enclosing function deliberately: a module-wide map resolved `body` to the
    FIRST `body = ...` anywhere in the file, which in two modules here names a different
    file than the call actually reads. A wrong resolution is worse than a reported one,
    because it prints a number.
    """
    spans = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        amap = {}
        for node in _own_body(fn):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                t = node.targets[0]
                if isinstance(t, ast.Name):
                    amap[t.id] = ast.unparse(node.value)
        spans.append((fn.lineno, getattr(fn, "end_lineno", fn.lineno), amap))
    spans.sort(key=lambda s: s[1] - s[0])
    return spans


def _own_body(fn: ast.AST):
    """Every node in `fn` EXCEPT those inside a nested function.

    `ast.walk` descends into nested defs, so an outer function's map ended up holding the
    inner function's bindings — and, because the inner ones come later in breadth-first
    order, holding them in preference to its own. Both spans then agreed and the
    innermost-wins sort above was decorative. Found by mutating that sort and watching
    nothing redden; the nested function gets its own span, which is the whole point.
    """
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        stack.extend(ast.iter_child_nodes(node))


def _resolve(spans, consts: dict[str, str], lineno: int, expr: str) -> str:
    """Function-local aliases first, then module-level string constants. Locals win: a
    module constant of the same name is shadowed inside the function, and resolving the
    wrong one prints a number for a file the call never read."""
    for start, end, amap in spans:
        if start <= lineno <= end and expr in amap:
            return amap[expr]
    return repr(consts[expr]) if expr in consts else expr


def fence_blind_slice(text: str, heading: str) -> str:
    """The pre-Phase-308 implementation, kept verbatim as the CONTROL. Without it the gate
    below could not tell a fixed slicer from a corpus that stopped containing the defect."""
    level = len(heading) - len(heading.lstrip("#"))
    marker = "\n" + heading + "\n"
    rest = text[text.index(marker) + len(marker):]
    m = re.compile(r"^#{1,%d} \S" % level, re.MULTILINE).search(rest)
    return heading + "\n" + (rest[: m.start()] if m else rest)


def fence_aware_slice(text: str, heading: str) -> str:
    """An INDEPENDENT fence-aware slicer — deliberately not `_fence_state()`, so the gate
    is a second opinion rather than a restatement of the code it checks."""
    level = len(heading) - len(heading.lstrip("#"))
    marker = "\n" + heading + "\n"
    rest = text[text.index(marker) + len(marker):]
    closer, opener = re.compile(r"^#{1,%d} \S" % level), re.compile(r"^(`{3,}|~{3,})(.*)$")
    out, fence = [], None
    for ln in rest.splitlines(keepends=True):
        s = ln.lstrip()
        m = opener.match(s)
        if m:
            run, info = m.group(1), m.group(2)
            # CommonMark: a BACKTICK opener's info string may not contain a backtick.
            # Without this the second opinion disagreed with the shipped helper on
            # ```a`b — and the gate's message blames the shipped one, which is correct.
            if fence is None and run[0] == "`" and "`" in info:
                if closer.match(ln):
                    break
                out.append(ln)
                continue
            if fence is None:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence) and not s[len(run):].strip():
                fence = None
            out.append(ln)
            continue
        if fence is None and closer.match(ln):
            break
        out.append(ln)
    return heading + "\n" + "".join(out)


def audit(tests_dir: Path | None = None) -> list[Row]:
    """`tests_dir` exists so the classification RULES can be tested against synthetic
    modules. Without it, every rule below is exercised only on whatever shapes the real
    corpus happens to contain today — and five of them were unexercised when this was
    written, which the author-side battery found by mutating each one away and watching
    nothing redden."""
    tests_dir = TESTS if tests_dir is None else tests_dir
    rows: list[Row] = []
    me = Path(__file__).resolve()
    for path in sorted(set(tests_dir.rglob("*.py"))):
        # The instrument does not measure itself. It calls the helper to produce the
        # `live` column, and those calls are infrastructure, not guards over shipped
        # prose. Excluded by IDENTITY rather than by filename, so the exclusion cannot
        # widen to a module that merely shares a name. (Before aliased imports were
        # recognised this module self-excluded by accident, which is not a reason.)
        if path.resolve() == me:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        call_names, module_names = _helper_bindings(tree)
        if not (call_names or module_names):
            continue
        if _module_shadows_section(tree):
            continue
        consts, spans = _module_constants(tree), _alias_spans(tree)
        try:
            rel_mod = path.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel_mod = path.as_posix()      # a synthetic module outside the repo
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            local_rebind = False
            if isinstance(f, ast.Name):
                if f.id not in call_names:
                    continue
                # A function-local `section = …` rebinds the name for calls in that
                # function only. Reported, never guessed: the census cannot tell which
                # callable this is, and a wrong resolution prints a number.
                local_rebind = _resolve(spans, {}, node.lineno, "section") != "section"
            elif isinstance(f, ast.Attribute) and f.attr == "section":
                if ast.unparse(f.value) not in module_names:
                    continue
            else:
                continue

            head = _literal(node.args[1]) if len(node.args) > 1 else None
            if head is None and len(node.args) > 1 and isinstance(node.args[1], ast.Name):
                head = consts.get(node.args[1].id)
            expr = (_resolve(spans, consts, node.lineno, ast.unparse(node.args[0]))
                    if node.args else None)

            def _row(problem, path_=None, cur=None, fa=None, live=None, synthetic=False,
                     absent=False):
                return Row(rel_mod, node.lineno, head, path_, cur, fa, live, problem,
                           synthetic, absent)

            # A call whose text argument folds to a string LITERAL — written inline, or
            # held in a module constant or a local — slices no file in the tree: it is a
            # unit test of the helper, and the helper's behaviour on it is asserted right
            # there. Tested on the ALIAS-RESOLVED expression, because the literal usually
            # arrives through a local `t = "..."`. Recorded, not dropped, so the
            # population stays visible.
            if expr is not None:
                try:
                    if isinstance(ast.literal_eval(expr), str):
                        rows.append(_row(None, synthetic=True))
                        continue
                except (ValueError, SyntaxError):
                    pass

            if local_rebind:
                rows.append(_row("`section` is rebound by a local assignment in the "
                                 "enclosing function — this call may not be the helper"))
                continue

            if head is None:
                rows.append(_row(f"heading argument is not a literal or module constant: "
                                 f"{ast.unparse(node.args[1]) if len(node.args) > 1 else '<none>'}"))
                continue
            rel = _TEXT_EXPR_BY_MODULE.get((rel_mod, expr)) or _TEXT_EXPR_TO_PATH.get(expr)
            if rel == "@module":
                rel = _MODULE_SKILL.get(rel_mod)
            if rel is None:
                rows.append(_row(f"text argument {expr!r} is not in the resolution table — "
                                 f"add it there rather than letting the site go unmeasured"))
                continue
            target = REPO_ROOT / rel
            if not target.is_file():
                # Resolved, but not present in THIS tree. Recorded rather than raised —
                # see Row.absent. The row keeps its path so the floor can count it and a
                # reader can see which site went unmeasured and where.
                rows.append(_row(None, rel, absent=True))
                continue
            text = target.read_text(encoding="utf-8")
            if text.count("\n" + head + "\n") != 1:
                rows.append(_row(f"{head!r} is not unique in {rel}", rel))
                continue
            try:
                measured = (len(fence_blind_slice(text, head)),
                            len(fence_aware_slice(text, head)),
                            len(shipped_section(text, head)))
            except AssertionError as exc:
                # An unterminated fence inside the section. The design promises a row,
                # and an exception escaping `audit()` reddens three tests with a
                # traceback instead of naming the site.
                rows.append(_row(f"slicing refused: {exc}", rel))
                continue
            rows.append(_row(None, rel, *measured))
    return rows
