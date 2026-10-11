"""Phase 348 — `Q-621` + `Q-605`: a YAML parse fails in more ways than `YAMLError`, and a
branch name YAML reads as a number never matches its own doc.

`Q-621`. `yaml.safe_load` raises `ValueError` for an impossible date (`date: 2026-09-31`),
`KeyError` for `!!bool abc`, `AttributeError` for `!!timestamp abc`, and `RecursionError` for
deep nesting — none of them a `yaml.YAMLError`. The entry named three `/review-close` Step 3b
handlers; the AST sweep below found 24 `try` blocks in shipped code that handled `YAMLError`
and missed at least one of these, five of them already widened by hand to `ValueError` and
still missing `KeyError`. Each now takes its existing unreadable-input arm for ANY exception
the parse raises (Wade's answer: `except Exception`, since the failure set is open-ended —
PyYAML's constructors call `int()`, `float()`, `datetime()`, dict lookups). A handler chain
that tells a read failure from a parse failure keeps its narrow arms first and ends with the
broad one.

`Q-605`. The pending-doc templates emitted `branch: <branch-name>` bare, so `1234` read as
an int and `2026-09-01` as a date; `branch_of()` answers None for a non-string and the collect
refused the doc as a collision naming `None`. Reader coercion is lossy (`0123` reads as 83,
`true` as True), so the writers quote, and the collect says WHY a doc has no branch.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _heredoc_population import heredoc_containing, shipped_heredocs  # noqa: E402
from test_pending_doc_integrity import (  # noqa: E402
    _checkout, _live, _pending_doc_template_files, _run, _task_lock, scripts,  # noqa: F401
)
from test_review_close_smoke_gate import SMOKE_SRC  # noqa: E402
from test_strict_decode_class import (  # noqa: E402
    _SCOPES, _handler_names, _module_constants, _shipped_scripts,
)
from test_strict_decode_heredocs import (  # noqa: E402
    SKILLS, _doc_work, _install_case, _repo, _run_body,
)

REPO = Path(__file__).resolve().parents[1]
CLAIM_SH = REPO / "core" / "companion" / "scripts" / "claim_task.sh"

# Each one raises something that is not a `YAMLError` (measured on PyYAML 6.0.2).
BAD_YAML = {
    "impossible date": ("date: 2026-09-31\n", ValueError),
    "bad !!bool": ("x: !!bool abc\n", KeyError),
    "bad !!timestamp": ("x: !!timestamp abc\n", AttributeError),
    "bad !!int": ("x: !!int abc\n", ValueError),
}


@pytest.mark.parametrize("label", sorted(BAD_YAML))
def test_the_premise_pyyaml_raises_more_than_yamlerror(label):
    """If a PyYAML release starts wrapping these in `YAMLError`, this fails — and the broad
    handlers are still right, but this module's reason for existing should be re-read."""
    text, exc = BAD_YAML[label]
    with pytest.raises(exc) as info:
        yaml.safe_load(text)
    assert not isinstance(info.value, yaml.YAMLError)


def test_the_premise_deep_nesting_is_a_recursion_error():
    with pytest.raises(RecursionError):
        yaml.safe_load("a: " + "[" * 20000 + "]" * 20000)


# ── the class guard ──────────────────────────────────────────────────────────

_BROAD = {None, "Exception", "BaseException"}   # None is a bare `except:`
_TRY = tuple(t for t in (ast.Try, getattr(ast, "TryStar", None)) if t)   # `except*` too
# Every PyYAML entry point that parses (round 1, lens 1: `yaml.load(…, Loader=…)` and
# `safe_load_all` walked the first guard), and the two lock loaders that wrap one.
_YAML_LOADERS = {"load", "safe_load", "full_load", "unsafe_load",
                 "load_all", "safe_load_all", "full_load_all", "unsafe_load_all"}
_WRAPPERS = {"load_lock_text", "_load_lock_yaml"}


def _yaml_names(tree: ast.AST) -> tuple[set, set]:
    """(names bound to the yaml module, names bound to a yaml loader) by this source's
    imports: `import yaml as y`, `from yaml import safe_load as sl` (round 2, lens A)."""
    mods, loaders = {"yaml"}, set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.asname or a.name for a in n.names if a.name == "yaml"}
        elif isinstance(n, ast.ImportFrom) and n.module == "yaml":
            loaders |= {a.asname or a.name for a in n.names
                        if a.name in _YAML_LOADERS or a.name.endswith("Loader")}
    return mods, loaders


def _is_loader(func: ast.AST, names: tuple[set, set] = ({"yaml"}, set())) -> bool:
    """A yaml loader (`load`, `safe_load`, … or a `*Loader` class) reached through the module
    or an alias of it, through `getattr(yaml, "<loader>")`, or imported by name; or a lock
    wrapper."""
    mods, loaders = names
    if isinstance(func, ast.Attribute):
        return func.attr in _WRAPPERS or (
            (func.attr in _YAML_LOADERS or func.attr.endswith("Loader"))
            and ast.unparse(func.value).split(".")[-1] in mods)
    if isinstance(func, ast.Name):
        return func.id in _WRAPPERS or func.id in loaders
    if (isinstance(func, ast.Call) and isinstance(func.func, ast.Name) and func.func.id == "getattr"
            and len(func.args) >= 2 and isinstance(func.args[1], ast.Constant)):
        return (ast.unparse(func.args[0]) in mods
                and str(func.args[1].value) in _YAML_LOADERS)
    return False


def _reraises(h: ast.ExceptHandler) -> bool:
    """The handler hands the caught exception on unchanged somewhere in its body: a bare
    `raise`, or `raise <the bound name>`. Raising a different type (`raise ConfigShapeError(…)
    from e`) is a conversion three shipped sites make on purpose; whether the caller catches
    that type is a judgement this predicate does not make."""
    for n in ast.walk(ast.Module(body=h.body, type_ignores=[])):
        if isinstance(n, ast.Raise) and (
                n.exc is None or (h.name and isinstance(n.exc, ast.Name) and n.exc.id == h.name)):
            return True
    return False


def _covers(h: ast.ExceptHandler, consts: dict) -> bool:
    """A broad handler that does not hand the failure on (round 1 H01; round 2 widened it from
    a lone bare `raise` to any re-raise of the caught exception)."""
    return not _reraises(h) and any(n in _BROAD for n in _handler_names(h, consts))


def _in_scope_body(child: ast.AST, scope: ast.AST) -> bool:
    """Whether `child` runs inside `scope`. A default argument or a decorator is evaluated by
    the enclosing scope, so the walk must continue past it (round 2, lens A)."""
    if isinstance(scope, ast.Lambda):
        return child is scope.body
    return any(child is s for s in getattr(scope, "body", []))


def yaml_handler_problems(source: str) -> list[str]:
    """Every `try` that handles `YAMLError` must also handle everything else a parse
    raises, and no handler may follow the broad one (it could never run)."""
    tree = ast.parse(source)
    consts = _module_constants(tree)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, _TRY):
            continue
        per = [_handler_names(h, consts) for h in node.handlers]
        if not any(n and n.split(".")[-1] == "YAMLError" for names in per for n in names):
            continue
        broad = [i for i, names in enumerate(per) if any(n in _BROAD for n in names)]
        if not broad:
            out.append(f"line {node.lineno}: handles YAMLError but not Exception — {per}")
        elif broad[0] != len(per) - 1:
            out.append(f"line {node.lineno}: a handler follows the broad one and never runs — {per}")
    return out


def broad_parse_sites(source: str) -> int:
    """`try` blocks whose body calls a YAML loader and whose handlers catch Exception."""
    tree = ast.parse(source)
    consts = _module_constants(tree)
    n = 0
    names = _yaml_names(tree)
    for node in ast.walk(tree):
        if not isinstance(node, _TRY):
            continue
        calls = [c for stmt in node.body for c in ast.walk(stmt) if isinstance(c, ast.Call)]
        if not any(_is_loader(c.func, names) for c in calls):
            continue
        if any(_covers(h, consts) for h in node.handlers):
            n += 1
    return n


def _population():
    for p in _shipped_scripts():
        yield str(p.relative_to(REPO)), p.read_text(encoding="utf-8")
    for p, line, _, body in shipped_heredocs():
        yield f"{p.relative_to(REPO)} (heredoc at line {line})", body


def test_no_shipped_handler_catches_yamlerror_and_misses_the_rest():
    bad = []
    for where, src in _population():
        try:
            bad += [f"{where}: {p}" for p in yaml_handler_problems(src)]
        except SyntaxError:
            continue          # `test_every_shipped_heredoc_parses` owns that failure
    assert not bad, (
        "a handler catches yaml.YAMLError but not the ValueError / KeyError / "
        "AttributeError / RecursionError yaml.safe_load also raises (`Q-621`). Catch "
        "Exception in the arm that already handles an unreadable input:\n  " + "\n  ".join(bad)
    )


# 36 `try` blocks around a YAML loader catch Exception and do not re-raise: one that already
# did (`claim_task.sh`'s heredoc at line 312), plus the 24 YAMLError handlers, 12 read-error-only
# handlers and one bare parse Phase 348 converted, less the two lock loaders' first parses, whose
# handlers re-raise by design (the retry allowance above).
FLOOR = 36


def floor_problem(total: int) -> str:
    return "" if total >= FLOOR else (
        f"only {total} broad YAML-parse handlers found (floor {FLOOR}); the sweep went blind")


# The two lock loaders parse, and on a failure retry with their `: `-bearing values quoted
# inside the handler, and re-raise; every caller of both catches Exception. Keyed by function,
# and `test_the_retry_allowance_names_live_functions` holds each to exactly its two calls, so a
# third in either still fails.
RETRY_IN_HANDLER = {("core/companion/scripts/sitrep_survey.py", "load_lock_text"),
                    ("core/companion/scripts/validate_tasks.py", "_load_lock_yaml")}

# A loader held in a variable is refused, because no AST walk can follow its calls. This one
# was read by hand: `for _loader in (json.loads, yaml.safe_load)`, called only inside
# `try: … except Exception: continue`.
ALIAS_READ_BY_HAND = {("core/companion/scripts/sitrep_survey.py", "<alias in _classification_verdict>")}


def exposed_loader_calls(source: str) -> list[tuple[int, str, bool]]:
    """(line, enclosing scope, inside an except body) for each YAML loader call that no
    enclosing `try` in its scope can catch a parse failure for — and for each loader held in
    a variable (`_p = yaml.safe_load`), whose calls no AST walk can follow, as `<alias>`."""
    tree = ast.parse(source)
    consts = _module_constants(tree)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    names = _yaml_names(tree)
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, (ast.Attribute, ast.Name)) and isinstance(getattr(node, "ctx", None), ast.Load)
                and _is_loader(node, names)
                and not (isinstance(parents.get(node), ast.Call) and parents[node].func is node)):
            scope = node
            while scope in parents and not isinstance(scope, _SCOPES):
                scope = parents[scope]
            if not isinstance(scope, _SCOPES):
                scope = None
            out.append((node.lineno, f"<alias in {getattr(scope, 'name', '<module>')}>", False))
            continue
        if not (isinstance(node, ast.Call) and _is_loader(node.func, names)):
            continue
        cur, covered, func, in_handler = node, False, "<module>", False
        while cur in parents:
            par = parents[cur]
            if isinstance(par, ast.ExceptHandler):
                in_handler = True
            if isinstance(par, _TRY) and any(cur is b for b in par.body) and any(
                    _covers(h, consts) for h in par.handlers):
                covered = True
                break
            if isinstance(par, _SCOPES) and _in_scope_body(cur, par):   # lambda, class too (H02)
                func = getattr(par, "name", "<lambda>")
                break
            cur = par
        if not covered:
            out.append((node.lineno, func, in_handler))
    return out


def escape_problems(where: str, source: str) -> list[str]:
    """`exposed_loader_calls`, less the retry allowance: a call inside an `except` body of an
    allowed function in an allowed file."""
    path = where.split(" (heredoc")[0]
    return [f"{where}: line {line} in {func}()"
            for line, func, in_handler in exposed_loader_calls(source)
            if (path, func) not in RETRY_IN_HANDLER
            and (path, func) not in ALIAS_READ_BY_HAND]


_RETRY_SRC = "def load_lock_text(t):\n    try:\n        a()\n    except Exception:\n        yaml.safe_load(t)\n"


@pytest.mark.parametrize("where,src,flagged", [
    ("core/companion/scripts/sitrep_survey.py", _RETRY_SRC, False),
    ("core/companion/scripts/other.py", _RETRY_SRC, True),
    ("core/companion/scripts/sitrep_survey.py", _RETRY_SRC.replace("load_lock_text", "other"), True),
    ("core/companion/scripts/other.py",
     "def load_lock_text(t):\n    yaml.safe_load(t)\n", True),
])
def test_the_retry_allowance_is_exactly_that(where, src, flagged):
    assert bool(escape_problems(where, src)) is flagged


def test_no_yaml_loader_call_escapes_a_broad_handler():
    """The stronger half. Handling `YAMLError` is not the only way to miss the rest: 13 more sites,
    12 catching only read errors (`OSError`, `UnicodeDecodeError`) around the parse and one
    parsing with no handler at all, so even a YAML syntax error was a traceback where each step's
    contract has an unreadable-input exit."""
    bad = []
    for where, src in _population():
        try:
            bad += escape_problems(where, src)
        except SyntaxError:
            continue
    assert not bad, ("a YAML loader call no enclosing handler can catch a parse failure for "
                     "(`Q-621`):\n  " + "\n  ".join(bad))


def retry_shape_problem(src: str, func: str) -> str:
    """The allowed function parses once and retries once inside its handler, and no more."""
    calls = [h for _, f, h in exposed_loader_calls(src) if f == func]
    return "" if sorted(calls) == [False, True] else (
        f"{func} should parse once and retry once inside its handler; it now has {calls}. "
        f"Re-read it and update the allowance")


def test_the_retry_shape_check_refuses_a_third_call():
    src = ("def load_lock_text(t):\n    try:\n        return yaml.safe_load(t)\n"
           "    except Exception:\n        yaml.safe_load(t)\n        raise\n")
    assert not retry_shape_problem(src, "load_lock_text")
    assert retry_shape_problem(src + "    yaml.safe_load(t)\n", "load_lock_text")


def test_the_retry_allowance_names_live_functions():
    for rel, func in RETRY_IN_HANDLER:
        problem = retry_shape_problem((REPO / rel).read_text(encoding="utf-8"), func)
        assert not problem, f"{rel}: {problem}"
    for rel, func in ALIAS_READ_BY_HAND:
        src = (REPO / rel).read_text(encoding="utf-8")
        assert [f for _, f, _ in exposed_loader_calls(src)].count(func) == 1, (
            f"{rel}: {func} is gone or has a second alias; re-read it and update the allowance")


@pytest.mark.parametrize("src,flagged", [
    ("try:\n    yaml.safe_load(t)\nexcept (OSError, UnicodeDecodeError):\n    pass\n", True),
    ("yaml.safe_load(t)\n", True),
    ("def f():\n    try:\n        x()\n    except Exception:\n        yaml.safe_load(t)\n", True),
    ("try:\n    yaml.safe_load(t)\nexcept Exception:\n    pass\n", False),
    ("yaml.load(t, Loader=yaml.SafeLoader)\n", True),
    ("next(yaml.safe_load_all(t))\n", True),
    ("from yaml import safe_load\nsafe_load(t)\n", True),
    ("_p = yaml.safe_load\ntry:\n    _p(t)\nexcept Exception:\n    pass\n", True),
    ("try:\n    yaml.safe_load(t)\nexcept Exception:\n    raise\n", True),
    ("try:\n    f = lambda: yaml.safe_load(t)\nexcept Exception:\n    pass\nf()\n", True),
    ("json.load(f)\n", False),
    ("import yaml as y\ny.safe_load(t)\n", True),
    ("from yaml import safe_load as sl\nsl(t)\n", True),
    ("from yaml import load\nload(t)\n", True),
    ("getattr(yaml, 'safe_load')(t)\n", True),
    ("yaml.SafeLoader(t).get_single_data()\n", True),
    ("try:\n    yaml.safe_load(t)\nexcept Exception as e:\n    raise e\n", True),
    ("try:\n    yaml.safe_load(t)\nexcept Exception as e:\n    log(e)\n    raise\n", True),
    ("try:\n    yaml.safe_load(t)\nexcept Exception as e:\n    if x:\n        raise\n", True),
    ("try:\n    yaml.safe_load(t)\nexcept Exception as e:\n    raise ValueError(str(e)) from e\n", False),
    ("def f(d=yaml.safe_load(t)):\n    pass\n", True),
    ("try:\n    def f(d=yaml.safe_load(t)):\n        pass\nexcept Exception:\n    pass\n", False),
    ("from yaml import load as l\nimport json\njson.load(f)\n", False),
    ("try:\n    yaml.safe_load(t)\nexcept* Exception:\n    pass\n", False),
])
def test_each_arm_of_the_escape_guard_is_seen(src, flagged):
    assert bool(exposed_loader_calls(src)) is flagged


def test_the_sweep_sees_the_sites_it_fixed():
    """Vacuity floor: the guard above passes over a tree with no handler at all."""
    total = 0
    for _, src in _population():
        try:
            total += broad_parse_sites(src)
        except SyntaxError:
            continue
    assert not floor_problem(total), floor_problem(total)


def test_the_floor_refuses_one_short():
    """Literal, not `FLOOR - 1`: a control relative to the constant moves with it (the
    battery's G05 walked `FLOOR = 0` through that form)."""
    assert floor_problem(35) and not floor_problem(36)


@pytest.mark.parametrize("src,flagged", [
    ("try:\n    yaml.safe_load(t)\nexcept yaml.YAMLError:\n    pass\n", True),
    ("try:\n    yaml.safe_load(t)\nexcept (yaml.YAMLError, ValueError, RecursionError):\n    pass\n", True),
    ("E = (yaml.YAMLError, ValueError)\ntry:\n    yaml.safe_load(t)\nexcept E:\n    pass\n", True),
    ("try:\n    yaml.safe_load(t)\nexcept yaml.YAMLError:\n    a()\nexcept Exception:\n    b()\n", False),
    ("try:\n    yaml.safe_load(t)\nexcept Exception:\n    a()\nexcept yaml.YAMLError:\n    b()\n", True),
    ("try:\n    yaml.safe_load(t)\nexcept Exception:\n    pass\n", False),
    ("from yaml import YAMLError\ntry:\n    safe_load(t)\nexcept YAMLError:\n    pass\n", True),
    ("try:\n    yaml.safe_load(t)\nexcept (OSError, yaml.YAMLError):\n    pass\nexcept:\n    pass\n", False),
])
def test_each_arm_of_the_guard_is_seen(src, flagged):
    assert bool(yaml_handler_problems(src)) is flagged


# ── /review-close Step 3b: the collect and the rollback ──────────────────────

def _bad_doc(path: Path, branch: str, bad: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'---\nbranch: "{branch}"\n{bad}summary: "S"\n---\n', encoding="utf-8")


@pytest.mark.parametrize("label", sorted(BAD_YAML))
def test_the_collect_refuses_an_unparseable_doc_and_says_why(scripts, tmp_path, label):
    """Exit 3 with the reason, where the base exited 1 with a traceback on the half that
    decides what to delete."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _live(main).mkdir(parents=True)
    _bad_doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", BAD_YAML[label][0])

    r = _run(collect, main, wt)

    assert "Traceback" not in r.stderr, r.stderr
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
    assert f"its frontmatter does not parse ({BAD_YAML[label][1].__name__}" in r.stdout, r.stdout
    assert not (_live(main) / "feat-x.md").exists(), "an unparseable doc was collected"


def test_an_unparseable_main_copy_is_refused_with_its_own_reason(scripts, tmp_path):
    """The main-copy collision names why MAIN's copy has no branch, not the worktree's."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _bad_doc(_live(main) / "feat-x.md", "feat/x", "x: !!bool abc\n")
    _bad_doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "")

    r = _run(collect, main, wt)

    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
    line = next(ln for ln in r.stdout.splitlines() if "main copy belongs to" in ln)
    assert "does not parse (KeyError" in line, line
    assert "abc" in (_live(main) / "feat-x.md").read_text(encoding="utf-8")


def test_a_neighbour_on_main_with_an_impossible_date_does_not_stop_the_collect(scripts, tmp_path):
    """The collect reads EVERY doc on main to find this branch's; one bad neighbour used to
    kill it for everybody."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _bad_doc(_live(main) / "feat-other.md", "feat/other", "date: 2026-09-31\n")
    _bad_doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "")

    r = _run(collect, main, wt)

    assert "Traceback" not in r.stderr, r.stderr
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert (_live(main) / "feat-x.md").exists()
    assert "2026-09-31" in (_live(main) / "feat-other.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("value,kind", [("1234", "int"), ("2026-09-01", "date"), ("true", "bool")])
def test_an_unquoted_branch_yaml_reads_as_a_non_string_is_named_with_its_remedy(
    scripts, tmp_path, value, kind
):
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _live(main).mkdir(parents=True)
    doc = wt / "sysop/runtime/pending-docs" / f"{value}.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(f'---\nbranch: {value}\nsummary: "S"\n---\n', encoding="utf-8")

    r = _run(collect, main, wt, branch=value)

    assert r.returncode == 3, (r.returncode, r.stdout)
    assert f"`branch:` is a YAML {kind}: quote it" in r.stdout, r.stdout


@pytest.mark.parametrize("value", ["1234", "2026-09-01", "true"])
def test_the_quoted_branch_the_templates_now_emit_is_collected(scripts, tmp_path, value):
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _live(main).mkdir(parents=True)
    _bad_doc(wt / "sysop/runtime/pending-docs" / f"{value}.md", value, "")

    r = _run(collect, main, wt, branch=value)

    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert (_live(main) / f"{value}.md").exists()


def test_a_branch_holding_a_double_quote_collects_when_escaped(scripts, tmp_path):
    """Git accepts `feat/a"b`. Bare, it parsed; inside the quoted template it does not, so
    the template says to escape it, and the escaped form must be the one that collects."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _live(main).mkdir(parents=True)
    doc = wt / "sysop/runtime/pending-docs/feat-a-b.md"
    doc.parent.mkdir(parents=True)
    doc.write_text('---\nbranch: "feat/a\\"b"\nsummary: "S"\n---\n', encoding="utf-8")

    r = _run(collect, main, wt, branch='feat/a"b')

    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert (_live(main) / "feat-a-b.md").exists()


def test_the_rollback_leaves_an_unparseable_main_copy_and_says_why(scripts, tmp_path):
    _, rollback = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _bad_doc(_live(main) / "feat-x.md", "feat/x", "date: 2026-09-31\n")
    _bad_doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "")

    r = _run(rollback, main, wt)

    assert "Traceback" not in r.stderr, r.stderr
    assert "2026-09-31" in (_live(main) / "feat-x.md").read_text(encoding="utf-8")
    assert "LEFT ALONE" in r.stdout and "does not parse (ValueError" in r.stdout, r.stdout


# ── the writers: every pending-doc template quotes `branch:` ─────────────────

_DOUBLE_QUOTED = re.compile(r'"(?:[^"\\]|\\.)+"')
_KEY = re.compile(r'\s*["\']?([A-Za-z_]+)["\']?\s*:(.*)')


def template_branch_problems(text: str) -> tuple[list[int], list[str]]:
    """(lines of pending-doc `branch:` fields, problems) for one file. A pending-doc template
    is a `---`-delimited block holding both `branch:` and `branch_tip:`, in either order
    (round 1, lens 1, T01: a next-line test lost a template whose `date:` moved up). The
    value must be one non-empty double-quoted scalar: single quotes contradict the `\\"`
    rule the same step gives (T02), and an unterminated or empty value passed a first-
    character test (T03)."""
    lines = text.splitlines()
    seen, bad = [], []
    # Round 2, lens A: an indented or tab-indented block, `branch : x`, a quoted key and a
    # fenced block with no `---` all slipped past a column-0 `---` / `branch:` reading.
    opens = [i for i, ln in enumerate(lines) if ln.strip() == "---" or ln.strip().startswith("```")]
    for a, b in zip(opens, opens[1:]):
        block = lines[a + 1:b]
        fields = [(i, _KEY.match(ln)) for i, ln in enumerate(block, a + 2)]
        keys = {m.group(1) for _, m in fields if m}
        if not {"branch", "branch_tip"} <= keys:
            continue
        for i, m in fields:
            if m and m.group(1) == "branch":
                seen.append(i)
                if not _DOUBLE_QUOTED.fullmatch(m.group(2).strip()):
                    bad.append(f"line {i}: {lines[i - 1]}")
    return seen, bad


@pytest.mark.parametrize("text,flagged", [
    ('---\nbranch: "<branch-name>"\nbranch_tip: x\n---\n', False),
    ('---\nbranch: "feat/a\\"b"\nbranch_tip: x\n---\n', False),
    ("---\nbranch: <branch-name>\nbranch_tip: x\n---\n", True),
    ("---\nbranch: <branch-name>\ndate: d\nbranch_tip: x\n---\n", True),
    ("---\nbranch_tip: x\nbranch: <branch-name>\n---\n", True),
    ("---\nbranch: '<branch-name>'\nbranch_tip: x\n---\n", True),
    ('---\nbranch: "<branch-name>\nbranch_tip: x\n---\n', True),
    ('---\nbranch: ""\nbranch_tip: x\n---\n', True),
    ("---\nbranch: \nbranch_tip: x\n---\n", True),
    ("   ---\n   branch: <x>\n   branch_tip: y\n   ---\n", True),
    ("---\n\tbranch: <x>\n\tbranch_tip: y\n---\n", True),
    ("---\nbranch : <x>\nbranch_tip: y\n---\n", True),
    ("---\n\"branch\": <x>\nbranch_tip: y\n---\n", True),
    ("```yaml\nbranch: <x>\nbranch_tip: y\n```\n", True),
    ("```yaml\nbranch: \"<x>\"\nbranch_tip: y\n```\n", False),
])
def test_each_arm_of_the_template_guard_is_seen(text, flagged):
    seen, bad = template_branch_problems(text)
    assert seen and bool(bad) is flagged, (seen, bad)


def test_no_shipped_template_emits_an_unquoted_branch():
    """The `summary:` guard's twin. A template value is a placeholder (`<branch-name>`) or a
    worked example; either way it is what an agent copies."""
    offenders, names = [], set()
    for f in _pending_doc_template_files():
        seen, bad = template_branch_problems(f.read_text(encoding="utf-8"))
        if seen:
            names.add(str(f.relative_to(REPO)))
        offenders += [f"{f.relative_to(REPO)} {b}" for b in bad]
    assert not offenders, "a pending-doc template's branch: is not one double-quoted value:\n" + "\n".join(offenders)
    for required in ("core/skills/document-work/SKILL.md", "core/skills/auto-fix/SKILL.md",
                     "core/skills/auto-judge/SKILL.md", "core/companion/docs/WORKFLOW.md",
                     "core/companion/docs/WORKFLOW_GUIDE.md"):
        assert required in names, f"{required} carries no pending-doc template — sweep is blind"


# ── the scripts ──────────────────────────────────────────────────────────────

LABELS = ["impossible date", "bad !!bool"]


def _index(tmp_path: Path, label: str) -> Path:
    p = tmp_path / "tasks" / "index.yml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("schema_version: 2\ntasks:\n  - id: FEAT-1\n    status: done\n    "
                 + BAD_YAML[label][0].replace("date:", "completed_date:"), encoding="utf-8")
    return p


@pytest.mark.parametrize("label", LABELS)
def test_next_task_names_a_parse_failure_as_one(tmp_path, capsys, label):
    import next_task
    with pytest.raises(SystemExit) as e:
        next_task.load_index(_index(tmp_path, label))
    assert e.value.code == 1
    assert "YAML parse error in" in capsys.readouterr().err


@pytest.mark.parametrize("label", LABELS)
def test_clear_user_action_exits_1(tmp_path, label):
    import clear_user_action
    _index(tmp_path, label)
    assert clear_user_action.run("FEAT-1", root=tmp_path) == 1


@pytest.mark.parametrize("label", LABELS)
def test_sitrep_reads_the_index_as_unreadable(tmp_path, label):
    import sitrep_survey
    _index(tmp_path, label)
    unreadable: list = []
    assert sitrep_survey._read_index(tmp_path, unreadable) == {}
    assert unreadable


@pytest.mark.parametrize("label", LABELS)
def test_sitrep_and_scope_overlap_read_the_lock_as_unreadable(tmp_path, label):
    import scope_overlap
    import sitrep_survey
    lock = tmp_path / "FEAT-1.lock"
    lock.write_text("task_id: FEAT-1\nbranch: feat/x\nexpires: " + BAD_YAML[label][0].split(": ", 1)[1],
                    encoding="utf-8")
    fields, exc = sitrep_survey._load_lock_file(lock)
    assert fields == {} and exc is not None
    assert scope_overlap._parse_lock_file(lock).unreadable


@pytest.mark.parametrize("label", LABELS)
def test_scope_overlap_reads_the_index_as_absent(tmp_path, label):
    import scope_overlap
    assert scope_overlap._load_index_soft(_index(tmp_path, label)) is None


@pytest.mark.parametrize("label", LABELS)
def test_the_sitrep_staleness_read_is_unknown(tmp_path, label):
    import sitrep_survey
    doc = tmp_path / "feat-x.md"
    _bad_doc(doc, "feat/x", BAD_YAML[label][0])
    assert sitrep_survey._pending_doc_drift(doc, "feat/x").commits is None


@pytest.mark.parametrize("label", LABELS)
def test_validate_tasks_reports_it_as_an_error(tmp_path, label):
    import validate_tasks
    _index(tmp_path, label)
    report = validate_tasks.validate(tmp_path / "tasks")
    assert [f for f in report.errors if "index.yml" in f.location]


@pytest.mark.parametrize("label", LABELS)
def test_validate_tasks_lock_warning_skips_it(tmp_path, label):
    """The loader re-raises; `_check_expired_placeholder_lock` absorbs, warning nothing."""
    import validate_tasks
    lock = tmp_path / "FEAT-1.lock"
    lock.write_text("task_id: FEAT-1\nexpires: " + BAD_YAML[label][0].split(": ", 1)[1],
                    encoding="utf-8")
    report = validate_tasks.Report()
    validate_tasks._check_expired_placeholder_lock(lock, "FEAT-1", report)
    assert not report.errors and not report.warnings


@pytest.mark.parametrize("label", LABELS)
def test_backfill_exits_1(tmp_path, label):
    import backfill_completed_dates
    assert backfill_completed_dates.main(["--index", str(_index(tmp_path, label)), "--dry-run"]) == 1


@pytest.mark.parametrize("label", LABELS)
def test_run_checks_raises_its_parse_error(tmp_path, label):
    from run_checks import config
    p = tmp_path / "checks.yml"
    p.write_text("checks:\n  - id: a\n    " + BAD_YAML[label][0], encoding="utf-8")
    with pytest.raises(ValueError, match="checks.yml YAML parse error"):
        config.parse_checks_yml(p)


@pytest.mark.parametrize("label", LABELS)
def test_model_roles_raises_its_shape_error(tmp_path, label):
    import _model_roles
    p = tmp_path / "served_models.yml"
    p.write_text(BAD_YAML[label][0], encoding="utf-8")
    with pytest.raises(_model_roles.ConfigShapeError, match="not valid YAML"):
        _model_roles._load_yaml_mapping(p)


@pytest.mark.parametrize("label", LABELS)
def test_claim_task_release_probe_refuses_naming_the_error(tmp_path, label):
    body = heredoc_containing(CLAIM_SH, "except Exception as e:  # not only YAMLError")
    r = subprocess.run([sys.executable, "-c", body], capture_output=True, text=True,
                       env={"INDEX_PATH": str(_index(tmp_path, label)), "PATH": "/usr/bin:/bin"},
                       timeout=30)
    assert r.returncode == 1 and "Traceback" not in r.stderr, (r.stdout, r.stderr)
    assert BAD_YAML[label][1].__name__ in r.stdout


# ── the read-only handlers: each step's unreadable-input exit, not a traceback ──

def _bad_index(root: Path, label: str) -> Path:
    return _repo(root, index=("schema_version: 2\ntasks:\n  - id: FEAT-1\n    status: open\n    "
                              + BAD_YAML[label][0]).encode())


def _names_it(r, code: int, stream: str, exc: type) -> None:
    out = getattr(r, stream)
    assert r.returncode == code, (r.returncode, r.stdout, r.stderr)
    assert f"could not be read ({exc.__name__}" in out, (r.stdout, r.stderr)
    assert "Traceback" not in r.stdout + r.stderr, r.stderr


@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize("skill,needle,args,code,stream", [
    ("auto-build", "subset = set(sys.argv[1].split())", [""], 2, "stdout"),
    ("auto-build", 't["status"] = "in_progress"', ["FEAT-1"], 1, "stderr"),
    ("claim-task", "print(f\"id={match['id']}\")", ["FEAT-1"], 2, "stderr"),
    ("claim-task", "resumed = False", ["FEAT-1"], 1, "stderr"),
    ("review-close", 'ids = ["<ROADMAP_ID_1>"', [], 1, "stderr"),
])
def test_an_unparseable_index_takes_the_steps_unreadable_exit(
        tmp_path, label, skill, needle, args, code, stream):
    repo = _bad_index(tmp_path / "r", label)
    before = (repo / "tasks/index.yml").read_bytes()
    r = _run_body(heredoc_containing(SKILLS / f"{skill}/SKILL.md", needle), args, repo)
    _names_it(r, code, stream, BAD_YAML[label][1])
    assert (repo / "tasks/index.yml").read_bytes() == before


@pytest.mark.parametrize("label", LABELS)
def test_document_work_3b_an_unparseable_index_is_exit_2_not_missing_stubs(tmp_path, label):
    index = ("tasks:\n  - id: FEAT-1\n    " + BAD_YAML[label][0]).encode()
    r = _doc_work(tmp_path, b'---\nbranch: "feat/x"\n---\nbody\n', index)
    _names_it(r, 2, "stderr", BAD_YAML[label][1])


@pytest.mark.parametrize("label", LABELS)
def test_document_work_3b_an_unparseable_pending_doc_is_exit_2_not_missing_stubs(tmp_path, label):
    r = _doc_work(tmp_path, ('---\nbranch: "feat/x"\n' + BAD_YAML[label][0] + "---\nbody\n").encode(),
                  b"tasks: []\n")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert f"could not be parsed ({BAD_YAML[label][1].__name__}" in r.stderr, r.stderr
    assert "Traceback" not in r.stderr


@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize("needle", [
    "top-level 'substitutions:' mapping missing or empty",
    "PATHS_KEY = re.compile",
])
def test_install_names_an_unparseable_substitutions_file(tmp_path, label, needle):
    argv = ["OK:substitutions:\n  " + BAD_YAML[label][0]] + (["OK:x\n"] if "PATHS" in needle else [])
    r, _ = _install_case(tmp_path, needle, argv)
    assert r.returncode != 0 and "Traceback" not in r.stderr, (r.returncode, r.stderr)
    assert f"could not be read ({BAD_YAML[label][1].__name__}" in r.stderr, r.stderr


# ── round 1's findings ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("index", [
    "schema_version: 2\ntasks:\n  - id: FEAT-1\n    completed_date: 2026-09-31\n",
    "schema_version: 2\ntasks:\n  - id: FEAT-1\n    x: !!bool abc\n",
    "- just\n- a list\n",
    "tasks:\n  a: b\n",
    "tasks: just a string\n",
    "tasks: 5\n",
])
def test_the_smoke_gate_stops_on_an_index_it_cannot_score(tmp_path, index):
    """Round 1, lens 3, F1. Reading the index as empty scores no task `manual_smoke`, so the
    gate printed NO_SMOKE_REQUIRED and the close merged without asking. The gate's other
    failure modes stop the close; this one now does too."""
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks/index.yml").write_text(index, encoding="utf-8")
    (tmp_path / "sysop/runtime/pending-docs").mkdir(parents=True)
    r = subprocess.run([sys.executable, "-c", SMOKE_SRC, "", "", "main"], capture_output=True,
                       text=True, cwd=tmp_path, timeout=30)
    assert r.returncode != 0 and "NO_SMOKE_REQUIRED" not in r.stdout, (r.returncode, r.stdout)
    assert "tasks/index.yml" in r.stderr and "Traceback" not in r.stderr, r.stderr


def test_the_exit_8_refusal_names_the_doc_it_could_not_read(scripts, tmp_path):
    """Round 1, lens 3, F6. With no `src_dir`, main's doc for the branch that will not parse
    counts as absent, and exit 8 said only that no doc claims the branch."""
    collect, _ = scripts
    main, wt = tmp_path / "main", _checkout(tmp_path / "wt")
    _bad_doc(_live(main) / "feat-x.md", "feat/x", "date: 2026-09-31\n")
    _task_lock(main, "TASK-0042", "feat/x")

    r = _run(collect, main, wt)

    assert r.returncode == 8, (r.returncode, r.stdout, r.stderr)
    line = next(ln for ln in r.stdout.splitlines() if ln.startswith("PENDING-DOC MISSING:"))
    assert "Unreadable: feat-x.md — its frontmatter does not parse (ValueError" in line, line


def test_document_work_3b_a_prose_frontmatter_is_exit_2_not_missing_stubs(tmp_path):
    """Round 1, lens 3, F8. `or {}` passes a prose line through as a str, and `.get` then
    raised AttributeError: exit 1, which the step reads as missing stubs."""
    r = _doc_work(tmp_path, b"---\nwork in progress\n---\nbody\n", b"tasks: []\n")
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert "not a mapping" in r.stderr and "Traceback" not in r.stderr, r.stderr


# ── round 1, lens 1: sites no behaviour test reached, and the reasons branch_of gives ──

@pytest.mark.parametrize("label", LABELS)
def test_claim_task_release_flip_names_the_parse_failure(tmp_path, label):
    body = heredoc_containing(CLAIM_SH, "found = False\nfor t in data.get(\"tasks\", []):")
    index = _index(tmp_path, label)
    before = index.read_bytes()
    r = subprocess.run([sys.executable, "-c", body], capture_output=True, text=True, timeout=30,
                       env={"TASK_ID": "FEAT-1", "INDEX_PATH": str(index), "PATH": "/usr/bin:/bin"})
    _names_it(r, 1, "stdout", BAD_YAML[label][1])
    assert index.read_bytes() == before


@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize("needle,bad_first", [
    ("seen_in_proj, dupes = set(), []", True), ("seen_in_proj, dupes = set(), []", False),
    ("base['checks'] = base_checks", True), ("base['checks'] = base_checks", False),
])
def test_install_names_an_unparseable_checks_file(tmp_path, label, needle, bad_first):
    bad, ok = "OK:checks:\n  - id: a\n    " + BAD_YAML[label][0], "OK:checks:\n  - id: b\n"
    r, _ = _install_case(tmp_path, needle, [bad, ok] if bad_first else [ok, bad])
    assert r.returncode != 0 and "Traceback" not in r.stderr, (r.returncode, r.stderr)
    assert f"could not be read ({BAD_YAML[label][1].__name__}" in r.stderr, r.stderr


def test_the_smoke_gate_stops_on_a_doc_it_cannot_parse(tmp_path):
    """Round 2, lens A: `read_fm` skipped a doc it could not parse, so a `manual_smoke` doc with
    a bad date scored NO_SMOKE_REQUIRED and the close merged unasked (before Phase 348 the same
    doc crashed the gate). On Wade's answer it stops, naming the doc."""
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks/index.yml").write_text("tasks: []\n", encoding="utf-8")
    pd = tmp_path / "sysop/runtime/pending-docs"
    pd.mkdir(parents=True)
    (pd / "feat-x.md").write_text('---\nbranch: "feat/x"\nmanual_smoke: true\ndate: 2026-09-31\n---\n',
                                  encoding="utf-8")
    r = subprocess.run([sys.executable, "-c", SMOKE_SRC, "", "", "main"], capture_output=True,
                       text=True, cwd=tmp_path, timeout=30)
    assert r.returncode != 0 and "NO_SMOKE_REQUIRED" not in r.stdout, (r.returncode, r.stdout)
    assert "feat-x.md does not parse (ValueError" in r.stderr and "Traceback" not in r.stderr, r.stderr


def test_the_smoke_recorder_refuses_an_unparseable_doc(tmp_path):
    """Round 2, lens B: the first version wrote the doc outside `pending-docs/`, so the
    recorder refused at its path check before parsing, and the test passed on the base tree."""
    from test_review_close_smoke_held_and_tip import RECORDER_SRC
    doc = tmp_path / "sysop/runtime/pending-docs/feat-x.md"
    doc.parent.mkdir(parents=True)
    doc.write_text('---\nbranch: "feat/x"\ndate: 2026-09-31\n---\n', encoding="utf-8")
    before = doc.read_bytes()
    r = subprocess.run([sys.executable, "-c", RECORDER_SRC, str(doc), "0" * 16, "confirmed"],
                       capture_output=True, text=True, cwd=tmp_path, timeout=30)
    assert r.returncode != 0 and "Traceback" not in r.stderr, r.stderr
    assert "has no frontmatter mapping" in r.stderr, r.stderr
    assert doc.read_bytes() == before


def test_document_work_3b_a_list_index_is_exit_2_not_missing_stubs(tmp_path):
    r = _doc_work(tmp_path, b'---\nbranch: "feat/x"\n---\nbody\n', b"- id: FEAT-1\n")
    assert r.returncode == 2 and "not a mapping" in r.stderr, (r.returncode, r.stderr)
    assert "Traceback" not in r.stderr


@pytest.mark.parametrize("frontmatter,reason", [
    ("summary: \"S\"\n", "it has no `branch:` value"),
    ("branch: null\n", "it has no `branch:` value"),
    ("branch: \"\"\n", "it has no `branch:` value"),
    ("- a\n- b\n", "its frontmatter is a list, not a mapping"),
])
def test_every_cause_of_no_branch_is_named(scripts, tmp_path, frontmatter, reason):
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _live(main).mkdir(parents=True)
    doc = wt / "sysop/runtime/pending-docs/feat-x.md"
    doc.parent.mkdir(parents=True)
    doc.write_text(f"---\n{frontmatter}---\n", encoding="utf-8")
    r = _run(collect, main, wt)
    assert r.returncode == 3 and reason in r.stdout, (r.returncode, r.stdout)


def test_a_missing_frontmatter_block_is_named(scripts, tmp_path):
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _live(main).mkdir(parents=True)
    doc = wt / "sysop/runtime/pending-docs/feat-x.md"
    doc.parent.mkdir(parents=True)
    doc.write_text("no frontmatter here\n", encoding="utf-8")
    r = _run(collect, main, wt)
    assert r.returncode == 3 and "it has no frontmatter block at the top" in r.stdout, r.stdout


def test_a_bom_prefixed_doc_is_collected_as_step_3c_reads_it(scripts, tmp_path):
    """Round 1, lens 1, LOW-5: Step 3c's reader accepted a BOM and Step 3b's refused the doc
    as a collision, so the two steps disagreed about one file. Step 3b now accepts it too."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _live(main).mkdir(parents=True)
    doc = wt / "sysop/runtime/pending-docs/feat-x.md"
    doc.parent.mkdir(parents=True)
    doc.write_text('﻿---\nbranch: "feat/x"\nsummary: "S"\n---\n', encoding="utf-8")
    r = _run(collect, main, wt)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert (_live(main) / "feat-x.md").exists()


def test_validate_tasks_names_a_syntax_error_as_one(tmp_path):
    """Round 1, lens 1, LOW-7: the `YAMLError` arm could be deleted with every test green,
    because the broad arm after it still refused the file, under the wrong name."""
    import validate_tasks
    p = tmp_path / "tasks" / "index.yml"
    p.parent.mkdir()
    p.write_text("tasks: [unclosed\n", encoding="utf-8")
    report = validate_tasks.validate(tmp_path / "tasks")
    assert any("YAML parse error" in f.message for f in report.errors), report.errors


_ALIAS_SRC = ("def _classification_verdict(m):\n    for _loader in (json.loads, yaml.safe_load):\n"
              "        try:\n            return _loader(m)\n        except Exception:\n            continue\n")


@pytest.mark.parametrize("where,src,flagged", [
    ("core/companion/scripts/sitrep_survey.py", _ALIAS_SRC, False),
    ("core/companion/scripts/sitrep_survey.py", _ALIAS_SRC.replace("_classification_verdict", "other"), True),
    ("core/companion/scripts/other.py", _ALIAS_SRC, True),
])
def test_the_alias_allowance_is_exactly_that(where, src, flagged):
    """The battery's K05: an allowance that excused every alias walked the escape guard."""
    assert bool(escape_problems(where, src)) is flagged


def test_the_smoke_gate_skips_a_task_whose_id_is_not_a_string(tmp_path):
    """Round 2, lens A: `- id: [a]` raised a raw TypeError out of the gate."""
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks/index.yml").write_text("tasks:\n  - id: [a]\n", encoding="utf-8")
    (tmp_path / "sysop/runtime/pending-docs").mkdir(parents=True)
    r = subprocess.run([sys.executable, "-c", SMOKE_SRC, "", "", "main"], capture_output=True,
                       text=True, cwd=tmp_path, timeout=30)
    assert r.returncode == 0 and "Traceback" not in r.stderr, (r.returncode, r.stderr)


def test_the_rollback_reads_a_bom_doc_as_the_collect_does(scripts, tmp_path):
    """Round 2, lens A: the rollback's BOM acceptance and reasons had no behaviour test. A BOM
    main copy of this branch's doc, with a worktree copy beside it, is this branch's to unlink."""
    _, rollback = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _live(main).mkdir(parents=True)
    (_live(main) / "feat-x.md").write_text('﻿---\nbranch: "feat/x"\nsummary: "S"\n---\n', encoding="utf-8")
    _bad_doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "")
    r = _run(rollback, main, wt)
    assert "Traceback" not in r.stderr and "ROLLED BACK: feat-x.md" in r.stdout, (r.stdout, r.stderr)
    assert not (_live(main) / "feat-x.md").exists(), r.stdout


@pytest.mark.parametrize("content,reason", [
    ('---\nbranch: 1234\nsummary: "S"\n---\n', "`branch:` is a YAML int"),
    ("---\n- a\n---\n", "its frontmatter is a list, not a mapping"),
    ("no frontmatter\n", "it has no frontmatter block at the top"),
])
def test_the_rollback_names_why_it_left_a_doc(scripts, tmp_path, content, reason):
    _, rollback = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _live(main).mkdir(parents=True)
    (_live(main) / "feat-x.md").write_text(content, encoding="utf-8")
    _bad_doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "")
    r = _run(rollback, main, wt)
    line = next(ln for ln in r.stdout.splitlines() if "LEFT ALONE" in ln or "feat-x.md (main copy" in ln)
    assert reason in r.stdout, (line, r.stdout)
    assert (_live(main) / "feat-x.md").read_text(encoding="utf-8") == content


@pytest.mark.parametrize("pending", [
    b'\xef\xbb\xbf---\nbranch: "feat/x"\nwhitelist: [FEAT-0099]\n---\nSee FEAT-0099.\n',
    b'---\nbranch: "feat/x"\nwhitelist: [FEAT-0099]\n---',
])
def test_document_work_3b_reads_a_bom_or_eof_frontmatter(tmp_path, pending):
    """Round 2, lens A: `raw.startswith("---\\n")` read a BOM doc as having no frontmatter (its
    `whitelist:` dropped, a false block), and missed a frontmatter closed at end of file. The
    index carries FEAT-1 so the FEAT prefix is live and an unwhitelisted FEAT-0099 would block;
    the first version used an empty index, and then `FEAT-9`, which the token pattern (two or
    more characters after the dash) never matches, so nothing could block (P06/P07)."""
    r = _doc_work(tmp_path, pending, b"tasks:\n  - id: FEAT-1\n    status: open\n")
    assert r.returncode == 0 and "Traceback" not in r.stderr, (r.returncode, r.stdout, r.stderr)


@pytest.mark.parametrize("index", [b"tasks:\n  a: b\n", b"tasks: a string\n"])
def test_document_work_3b_an_index_whose_tasks_is_not_a_list_is_exit_2(tmp_path, index):
    """Round 2, lens A: it printed "0 task IDs named" and passed, so the stub check never ran."""
    r = _doc_work(tmp_path, b'---\nbranch: "feat/x"\n---\nbody\n', index)
    assert r.returncode == 2 and "tasks: is a list" in r.stderr, (r.returncode, r.stderr)


def test_a_doc_that_is_not_a_regular_file_is_named(scripts, tmp_path):
    """The battery's P04: the reason for a non-file had no test."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _live(main).mkdir(parents=True)
    (wt / "sysop/runtime/pending-docs/feat-x.md").mkdir(parents=True)
    r = _run(collect, main, wt)
    assert r.returncode == 3 and "it is not a regular file" in r.stdout, (r.returncode, r.stdout)


def test_an_unreadable_doc_is_named(scripts, tmp_path):
    """The battery's P05: the reason for an OSError had no test."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _live(main).mkdir(parents=True)
    doc = wt / "sysop/runtime/pending-docs/feat-x.md"
    _bad_doc(doc, "feat/x", "")
    doc.chmod(0)
    try:
        r = _run(collect, main, wt)
    finally:
        doc.chmod(0o600)
    assert r.returncode == 3 and "it could not be read (PermissionError)" in r.stdout, (r.returncode, r.stdout)
