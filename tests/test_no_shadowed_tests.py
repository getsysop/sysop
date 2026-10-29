"""No test module defines the same top-level test function twice.

Python keeps the LAST definition of a name, so an earlier `def test_x` with the same
name never runs, and nothing reports it. Phase 323 met this in its own rewrite of
`tests/test_fix_in_branch_tier.py`: three new guards were shadowed by old copies kept
further down the file, and the author-side battery's A16 survived because the guard it
should have met was the shadowed one. Ruff's F811 would catch this; this repo does not
run ruff over `tests/`, so the check lives here.
"""
from __future__ import annotations

import ast
import collections
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def _target_names(node) -> list[str]:
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, (ast.Tuple, ast.List)):
        return [n for e in node.elts for n in _target_names(e)]
    if isinstance(node, ast.Starred):
        return _target_names(node.value)
    return []


def _bound_names(body) -> list[str]:
    """Every name a scope binds, including inside `if`/`for`/`while`/`try`/`with` blocks.

    Round 2 (Phase 323) disabled the pin tests five ways this detector's first version could
    not see: `del test_x`, a re-def under `if True:`, `from os import sep as test_x`, a tuple
    assignment, and a `for` target. A binding in a nested block binds the enclosing scope.
    """
    out = []
    for n in body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append(n.name)
        elif isinstance(n, ast.Assign):
            out += [x for t in n.targets for x in _target_names(t)]
        elif isinstance(n, (ast.AnnAssign, ast.AugAssign)):
            out += _target_names(n.target)
        elif isinstance(n, ast.Delete):
            out += [x for t in n.targets for x in _target_names(t)]
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            out += [(a.asname or a.name).split(".")[0] for a in n.names]
        if isinstance(n, (ast.For, ast.AsyncFor)):
            out += _target_names(n.target)
        if isinstance(n, (ast.With, ast.AsyncWith)):
            out += [x for i in n.items if i.optional_vars is not None for x in _target_names(i.optional_vars)]
        for field in ("body", "orelse", "finalbody"):
            if isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith)):
                out += _bound_names(getattr(n, field, []) or [])
        if isinstance(n, ast.Try):
            for h in n.handlers:
                out += _bound_names(h.body)
    return out


def _shadowed(src: str) -> list[str]:
    """Test names bound twice in the module scope or in any class body."""
    tree = ast.parse(src)
    bad = set()
    scopes = [("", tree.body)] + [(c.name + ".", c.body) for c in ast.walk(tree) if isinstance(c, ast.ClassDef)]
    for prefix, body in scopes:
        names = collections.Counter(n for n in _bound_names(body) if n.startswith(("test_", "Test")))
        bad |= {prefix + k for k, v in names.items() if v > 1}
    return sorted(bad)


def test_no_module_shadows_its_own_tests() -> None:
    modules = sorted(TESTS.glob("test_*.py"))
    assert len(modules) > 50, f"found only {len(modules)} test modules -- the glob is wrong"
    bad = {m.name: _shadowed(m.read_text(encoding="utf-8")) for m in modules}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, f"test functions defined twice, so the earlier copy never runs: {bad}"


def test_the_detector_sees_a_shadowed_test() -> None:
    """Non-vacuity: the detector must fire on the shape it exists for."""
    assert _shadowed("def test_a():\n    pass\n\ndef test_a():\n    pass\n") == ["test_a"]
    assert _shadowed("def test_a():\n    pass\n\ndef test_b():\n    pass\n") == []
    assert _shadowed("class TestX:\n    def test_a(self):\n        pass\n    def test_a(self):\n        pass\n") == ["TestX.test_a"]
    assert _shadowed("def test_a():\n    pass\ntest_a = None\n") == ["test_a"]
    for rebind in ("del test_a", "if True:\n    def test_a():\n        pass", "from os import sep as test_a",
                   "test_a, _x = 1, 2", "for test_a in [None]:\n    pass"):
        assert _shadowed("def test_a():\n    pass\n" + rebind + "\n") == ["test_a"], rebind
