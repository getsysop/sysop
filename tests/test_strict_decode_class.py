"""`Q-550` — one stray byte must cost one file, not the whole run.

`UnicodeDecodeError` is a `ValueError`, not an `OSError`. So a text read with a
strict decode (no `errors=`) under an `except OSError` arm — or a
`yaml.YAMLError` arm, or no arm at all — lets one undecodable byte in a task
body, a lock, an index or a security report escape the per-file handler that
was written for exactly that file, and the run dies with it. Phase 313 measured
13 such reads across 5 shipped scripts plus one with no handler at all;
Phase 319 fixed one of them (`parse_subagent_envelope.py`) in passing.

The fix routes the decode failure into each site's EXISTING per-file error path
— the skip, default or message that site already gives an unreadable file —
and never `errors="replace"`, which silently misparses. **A site that absorbs
an unreadable input also names it** (Wade, Phase 333 round 1: "absorb, but say
so"): the round found the rule landing on silent defaults — an index read as
`{}` made /sitrep say "idle" over a live claim. So /sitrep reports each one as
an `input unreadable` discrepancy, the other scripts warn on stderr naming the
file, and an explicit `--scope-file` that cannot be read is refused (exit 1)
rather than read as "no scoping". Sites that differ:

* `clear_user_action.py` had no handler, so it now exits 1 with an `ERROR:`
  line in the script's own convention.
* `ingest_security_report.py`'s findings loader returned `[]` for an
  unreadable file, which the ingest then counted as a report with zero
  findings. Its caller already caught the decode error and skipped the report
  loudly, so routing that error into `[]` would have turned a loud skip into a
  silent empty report. Both failures now mark the report skipped instead —
  which is what `/security-audit` Step 3c says an unreadable report gets.

Two `git` readers decode path lists that git prints raw (`-z`), where a tracked
file named in a non-UTF-8 encoding kills the run the same way:
`ingest_security_report._commit_changed_files` and `run_checks/semgrep.py`'s
`_git_lines`. Both route into their existing "git could not answer" path.
`sitrep_survey._worktree_dirty` reads `git status`, which prints such a name
raw only under a consumer's `core.quotePath=false`; there the existing path
("" = clean) would be false, so it forces the quoted form instead.
`security_partition.py` names such a file and assesses nothing (status
`undecodable-path`, exit 0): a partial partition would silently drop it.

THE CLASS GUARD below is an AST sweep over every shipped script — core's and
each pack's `companion/scripts/`, which `install.sh` ships beside them. It
covers file reads (`open`, `io.open`, `codecs.open`, `Path.open`, `os.fdopen`,
`read_text`, `bytes.decode`, `codecs.decode`, `fileinput.input`) and text stdin
(`sys.stdin.read*()`, iterating `sys.stdin`, `sys.stdin` handed to a reader,
`input()`), with or without `encoding=` — a read with no `encoding=` is the
locale default and just as strict, and so is `errors=None`. `sys.stdin` handed
to a reader counts whether passed positionally or by keyword. A handler named by
a module-level constant (`except LOAD_ERRORS:`) is resolved to its members only
when that unconditional top-level assignment is the name's ONLY binding in the
module; any other binding (a second assignment, one under `if`/`try`, a
function-local shadow, a `global` rebinding) leaves it unresolved and flagged.

KNOWN LIMITS — shapes the guard does not see (none occurs in a shipped script at
Phase 333): a decode reached through bytes (`json.loads(p.read_bytes())`,
`json.load(open(p, "rb"))`, `str(b, "utf-8")`), a wrapper that decodes
(`io.TextIOWrapper(sys.stdin.buffer)`, `fileinput.FileInput(...)`), and
`sys.stdin` reached through an alias (`inp = sys.stdin; inp.read()`). The
population floor below catches a recognized read being SWAPPED for one of these
(the count drops); it cannot catch one being ADDED (the count does not move). It does NOT cover `subprocess ...
text=True`: whether that output can carry raw bytes depends on the command
(`git ls-files` without `-z` quotes non-ASCII paths; with `-z` it does not),
so those sites are judged one at a time, not by a predicate.

The guard reads handlers up to the enclosing function only. A read whose
caller catches `ValueError` still fails it: the protection is then invisible
at the read, and the next caller does not inherit it. Declared scope, not
chased: a handler that catches and re-raises (`except UnicodeDecodeError:
raise`) passes the guard; a handler constant imported from another module is
not resolved, so the guard flags it (a false kill, fixed by catching inline).
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import clear_user_action  # noqa: E402,F401  (import proves the module loads)
import ingest_security_report as ing  # noqa: E402
import next_task as nt  # noqa: E402
import run_checks.semgrep as semgrep  # noqa: E402
import scope_overlap as so  # noqa: E402
import sitrep_survey as ss  # noqa: E402
from test_next_task import (  # noqa: E402
    _BASE_BODIES,
    _BASE_INDEX,
    _build_repo,
    _patch_repo,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"

BAD = b"\xff\xfe not utf-8 \xe9\n"


def _unreadable(path: Path) -> None:
    """Make ``path`` raise OSError on open — the pre-existing per-file arm."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root reads a mode-000 file; the OSError control needs a user")
    path.chmod(0)


# ---------------------------------------------------------------------------
# The class guard
# ---------------------------------------------------------------------------
_CATCHES_VALUE_ERROR = {
    None, "Exception", "BaseException", "ValueError", "UnicodeError",
    "UnicodeDecodeError",
}
# Receivers whose `.open` is not a text read of a file.
_NOT_TEXT_OPEN = {"os", "gzip", "bz2", "lzma", "tarfile", "zipfile", "webbrowser"}
_TRY_TYPES = tuple(t for t in (getattr(ast, "Try", None), getattr(ast, "TryStar", None)) if t)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _arg(call: ast.Call, kw: str, pos: int | None):
    for k in call.keywords:
        if k.arg == kw:
            return k.value
    if pos is not None and len(call.args) > pos:
        return call.args[pos]
    return None


def _read_kind(call: ast.Call) -> tuple[str, ast.AST | None, ast.AST | None] | None:
    """(kind, mode node, errors node) for a text read, or None when not one."""
    f = call.func
    if isinstance(f, ast.Name) and f.id == "open":
        return "open", _arg(call, "mode", 1), _arg(call, "errors", 4)
    if not isinstance(f, ast.Attribute):
        return None
    recv = ast.unparse(f.value)
    if f.attr == "open":
        if recv in _NOT_TEXT_OPEN:
            return None
        if recv == "io":
            return "open", _arg(call, "mode", 1), _arg(call, "errors", 4)
        if recv == "codecs":
            return "open", _arg(call, "mode", 1), _arg(call, "errors", 3)
        return "Path.open", _arg(call, "mode", 0), _arg(call, "errors", 3)
    if f.attr == "fdopen":
        return "fdopen", _arg(call, "mode", 1), _arg(call, "errors", 4)
    if f.attr == "read_text":
        return "read_text", None, _arg(call, "errors", 1)
    if f.attr == "decode":
        # `codecs.decode(obj, encoding, errors)` — positional 1 is the ENCODING.
        return "decode", None, _arg(call, "errors", 2 if recv == "codecs" else 1)
    if f.attr in ("read", "readline", "readlines") and recv == "sys.stdin":
        return "stdin", None, None
    if f.attr == "input" and recv == "fileinput":
        return "fileinput", None, _arg(call, "errors", None)
    return None


def _stdin_reads(node: ast.AST) -> list[tuple[str, ast.AST]]:
    """Reads of text stdin that are not a `sys.stdin.<method>()` call: `input()`,
    `for ln in sys.stdin` (and comprehensions), and `sys.stdin` handed to a reader
    such as `json.load(sys.stdin)`. Returns (kind, node to locate the read at)."""
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "input":
            return [("input", node)]
        handed = list(node.args) + [k.value for k in node.keywords]
        if any(ast.unparse(a) == "sys.stdin" for a in handed):
            return [("stdin-arg", node)]
    if isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
        if ast.unparse(node.iter) == "sys.stdin":
            return [("stdin-iter", node.iter)]
    return []


def _is_text_read(mode: ast.AST | None) -> bool:
    if mode is None:
        return True  # default mode is "r"
    if isinstance(mode, ast.Constant) and isinstance(mode.value, str):
        return not any(c in mode.value for c in "bwax")
    return True  # a computed mode might read; flag it and let a human look


def _is_strict(errors: ast.AST | None) -> bool:
    if errors is None:
        return True
    if isinstance(errors, ast.Constant) and errors.value is None:
        return True  # `errors=None` is the default, i.e. strict
    return isinstance(errors, ast.Constant) and errors.value == "strict"


def _binding_counts(tree: ast.Module) -> dict[str, int]:
    """How many times each name is bound ANYWHERE in the module — assignments at
    any depth, loop/`with`/`except` targets, parameters, imports, defs — with a
    `global NAME` counted as a rebinding in itself."""
    counts: dict[str, int] = {}

    def bump(name):
        counts[name] = counts.get(name, 0) + 1
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            bump(n.id)
        elif isinstance(n, ast.arg):
            bump(n.arg)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            for name in n.names:
                bump(name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                bump((a.asname or a.name).split(".")[0])
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bump(n.name)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bump(n.name)
    return counts


def _module_constants(tree: ast.Module) -> dict[str, list]:
    """Module-level ``NAME = (A, B)`` / ``NAME = A`` bindings, for handlers that
    name an exception tuple by a constant (``except LOAD_ERRORS:``).

    Fail closed: a name is resolved only when that unconditional top-level
    assignment is its ONLY binding in the module. A second module-level
    assignment, one under `if`/`try`, a function-local shadow or a `global`
    rebinding leaves it unresolved, so the handler reads as a bare name and the
    read is flagged — the guard cannot know which binding a handler sees."""
    counts = _binding_counts(tree)
    out: dict[str, list] = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
            target, value = stmt.targets[0], stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None:
            target, value = stmt.target, stmt.value
        else:
            continue
        if isinstance(target, ast.Name) and isinstance(value, (ast.Tuple, ast.Name, ast.Attribute)) \
                and counts.get(target.id) == 1:
            elts = value.elts if isinstance(value, ast.Tuple) else [value]
            out[target.id] = [ast.unparse(e) for e in elts]
    return out


def _handler_names(h: ast.ExceptHandler, consts: dict | None = None) -> list:
    if h.type is None:
        return [None]
    elts = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
    names, todo, seen = [], [ast.unparse(e) for e in elts], set()
    while todo:
        n = todo.pop(0)
        if consts and n in consts and n not in seen:
            seen.add(n)
            todo.extend(consts[n])
        else:
            names.append(n)
    return names


def _guarded(node: ast.AST, parents: dict, consts: dict | None = None) -> tuple[bool, list]:
    """Whether an enclosing try within the same function can catch ValueError.

    Returns (guarded, handler names seen) — the names are for the failure text.
    """
    seen: list = []
    cur = node
    while cur in parents:
        par = parents[cur]
        if isinstance(par, _TRY_TYPES) and any(cur is b for b in par.body):
            names = [n for h in par.handlers for n in _handler_names(h, consts)]
            seen.append(names)
            if any(n in _CATCHES_VALUE_ERROR for n in names):
                return True, seen
        if isinstance(par, _SCOPES):
            break
        cur = par
    return False, seen


def strict_reads(source: str) -> list[tuple[int, str, str, bool, list]]:
    """Every strict text read in ``source``: (line, kind, call, guarded, handlers)."""
    tree = ast.parse(source)
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    consts = _module_constants(tree)
    out = []
    for node in ast.walk(tree):
        hits = [(kind, node) for kind, node in _stdin_reads(node)]
        k = _read_kind(node) if isinstance(node, ast.Call) else None
        if k is not None:
            kind, mode, errors = k
            if _is_text_read(mode) and _is_strict(errors):
                hits.append((kind, node))
        for kind, at in hits:
            guarded, seen = _guarded(at, parents, consts)
            out.append((at.lineno, kind, ast.unparse(at)[:80], guarded, seen))
    return sorted(out)


def unguarded(source: str) -> list:
    return [r for r in strict_reads(source) if not r[3]]


def _shipped_scripts() -> list[Path]:
    """Every script the installer ships into `sysop/scripts/`: core's, and each
    pack's `companion/scripts/` (`install.sh` copies those alongside)."""
    packs = sorted(REPO_ROOT.glob("packs/*/companion/scripts/**/*.py"))
    return sorted(SCRIPTS.rglob("*.py")) + packs


def test_no_shipped_script_reads_text_strictly_under_a_handler_that_misses_value_error():
    bad = []
    for p in _shipped_scripts():
        for line, kind, call, _, seen in unguarded(p.read_text(encoding="utf-8")):
            bad.append(f"{p.relative_to(REPO_ROOT)}:{line} [{kind}] {call} — handlers {seen or 'none'}")
    assert not bad, (
        "strict text read(s) whose enclosing handlers cannot catch UnicodeDecodeError "
        "(a ValueError). Catch UnicodeDecodeError beside the site's OSError arm, route "
        "it into that arm's per-file outcome, and never use errors='replace':\n  "
        + "\n  ".join(bad)
    )


def test_the_sweep_walks_the_population_it_claims():
    """A sweep that recognizes nothing passes vacuously. Pin that it sees reads."""
    scripts = _shipped_scripts()
    names = {p.name for p in scripts}
    assert {"clear_user_action.py", "sitrep_survey.py", "semgrep.py", "shared_cli.py"} <= names
    total = sum(len(strict_reads(p.read_text(encoding="utf-8"))) for p in scripts)
    # 29 strict reads across 32 shipped scripts at Phase 333's round-1 fix
    # (measured by this function over `_shipped_scripts()`), every one guarded.
    # A predicate that stops recognizing a read shape shows up here as a drop,
    # not as a quiet pass.
    assert total >= 29, total
    # And the one site that had no handler at all is now seen as guarded.
    cua = strict_reads((SCRIPTS / "clear_user_action.py").read_text(encoding="utf-8"))
    assert [r for r in cua if r[1] == "open" and "index_path" in r[2] and r[3]], cua


# A module whose one read is guarded through a single, unconditional constant.
_CONST_OK = (
    'LOAD_ERRORS = (OSError, UnicodeDecodeError)\n'
    'def f(p):\n    try:\n        return open(p).read()\n    except LOAD_ERRORS:\n        return ""\n'
)

# One control per arm: each flagged source differs from its clean twin only in
# what that arm reads.
_ARM_CONTROLS = {
    "unguarded": (
        'def f(p):\n    return open(p, encoding="utf-8").read()\n',
        'def f(p):\n    try:\n        return open(p, encoding="utf-8").read()\n'
        '    except (OSError, UnicodeDecodeError):\n        return ""\n',
    ),
    "oserror_only": (
        'def f(p):\n    try:\n        return p.read_text(encoding="utf-8")\n'
        '    except OSError:\n        return ""\n',
        'def f(p):\n    try:\n        return p.read_text(encoding="utf-8")\n'
        '    except (OSError, ValueError):\n        return ""\n',
    ),
    "yamlerror_only": (
        'def f(p):\n    try:\n        with p.open(encoding="utf-8") as fh:\n'
        '            return yaml.safe_load(fh)\n    except yaml.YAMLError:\n        return {}\n',
        'def f(p):\n    try:\n        with p.open(encoding="utf-8") as fh:\n'
        '            return yaml.safe_load(fh)\n    except (yaml.YAMLError, UnicodeDecodeError):\n'
        '        return {}\n',
    ),
    "write_mode_is_skipped": (
        'def f(p):\n    with open(p, "r", encoding="utf-8") as fh:\n        return fh.read()\n',
        'def f(p):\n    with open(p, "w", encoding="utf-8") as fh:\n        fh.write("x")\n',
    ),
    "path_open_mode_is_args0": (
        'def f(p):\n    with p.open("r", encoding="utf-8") as fh:\n        return fh.read()\n',
        'def f(p):\n    with p.open("a", encoding="utf-8") as fh:\n        fh.write("x")\n',
    ),
    "binary_mode_is_skipped": (
        'def f(p):\n    with open(p, "r") as fh:\n        return fh.read()\n',
        'def f(p):\n    with open(p, "rb") as fh:\n        return fh.read()\n',
    ),
    "fdopen_mode_is_args1": (
        'import os\ndef f(fd):\n    return os.fdopen(fd, "r", encoding="utf-8").read()\n',
        'import os\ndef f(fd):\n    return os.fdopen(fd, "rb").read()\n',
    ),
    "io_open_mode_is_args1": (
        'import io\ndef f(p):\n    return io.open(p, "r").read()\n',
        'import io\ndef f(p):\n    return io.open(p, "rb").read()\n',
    ),
    "codecs_open_mode_is_args1": (
        'import codecs\ndef f(p):\n    return codecs.open(p, "r", "utf-8").read()\n',
        'import codecs\ndef f(p):\n    return codecs.open(p, "rb", "utf-8").read()\n',
    ),
    "codecs_open_errors_is_args3": (
        'import codecs\ndef f(p):\n    return codecs.open(p, "r", "utf-8").read()\n',
        'import codecs\ndef f(p):\n    return codecs.open(p, "r", "utf-8", "replace").read()\n',
    ),
    "non_file_open_receiver_is_skipped": (
        'def f(p):\n    return archive.open(p).read()\n',
        'import gzip\ndef f(p):\n    return gzip.open(p).read()\n',
    ),
    "codecs_decode_errors_is_args2": (
        'import codecs\ndef f(b):\n    return codecs.decode(b, "utf-8")\n',
        'import codecs\ndef f(b):\n    return codecs.decode(b, "utf-8", "replace")\n',
    ),
    "errors_none_is_strict": (
        'def f(p):\n    return open(p, errors=None).read()\n',
        'def f(p):\n    return open(p, errors="ignore").read()\n',
    ),
    "stdin_iteration": (
        'import sys\ndef f():\n    for ln in sys.stdin:\n        print(ln)\n',
        'import sys\ndef f():\n    for ln in sys.stdin.buffer:\n        print(ln)\n',
    ),
    "stdin_comprehension": (
        'import sys\ndef f():\n    return [ln for ln in sys.stdin]\n',
        'import sys\ndef f():\n    try:\n        return [ln for ln in sys.stdin]\n'
        '    except ValueError:\n        return []\n',
    ),
    "stdin_handed_to_a_reader": (
        'import json, sys\ndef f():\n    return json.load(sys.stdin)\n',
        'import json, sys\ndef f():\n    return json.load(sys.stdin.buffer)\n',
    ),
    "input_builtin": (
        'def f():\n    try:\n        return input("? ")\n    except EOFError:\n        return ""\n',
        'def f():\n    try:\n        return input("? ")\n    except (EOFError, UnicodeDecodeError):\n'
        '        return ""\n',
    ),
    "fileinput_input": (
        'import fileinput\ndef f():\n    return list(fileinput.input())\n',
        'import fileinput\ndef f():\n    return list(fileinput.input(errors="replace"))\n',
    ),
    "handler_tuple_constant_is_resolved": (
        'LOAD_ERRORS = (OSError, KeyError)\ndef f(p):\n    try:\n        return open(p).read()\n'
        '    except LOAD_ERRORS:\n        return ""\n',
        'LOAD_ERRORS = (OSError, UnicodeDecodeError)\ndef f(p):\n    try:\n        return open(p).read()\n'
        '    except LOAD_ERRORS:\n        return ""\n',
    ),
    "stdin_handed_by_keyword": (
        'import json, sys\ndef f():\n    return json.load(fp=sys.stdin)\n',
        'import json, sys\ndef f():\n    return json.load(fp=sys.stdin.buffer)\n',
    ),
    "handler_constant_shadowed_in_a_function_is_unresolved": (
        _CONST_OK + 'def g():\n    LOAD_ERRORS = (OSError,)\n    return LOAD_ERRORS\n',
        _CONST_OK,
    ),
    "handler_constant_rebound_by_global_is_unresolved": (
        _CONST_OK + 'def g():\n    global LOAD_ERRORS\n',
        _CONST_OK,
    ),
    "handler_constant_assigned_twice_is_unresolved": (
        'LOAD_ERRORS = (OSError,)\n' + _CONST_OK,
        _CONST_OK,
    ),
    "handler_constant_under_if_is_unresolved": (
        'import sys\nif sys.platform:\n    LOAD_ERRORS = (OSError, UnicodeDecodeError)\n'
        + _CONST_OK.split("\n", 1)[1],
        _CONST_OK,
    ),
    "handler_constant_under_try_is_unresolved": (
        'try:\n    LOAD_ERRORS = (OSError, UnicodeDecodeError)\nexcept NameError:\n    pass\n'
        + _CONST_OK.split("\n", 1)[1],
        _CONST_OK,
    ),
    "handler_constant_inside_a_tuple_is_resolved": (
        'DECODE = KeyError\ndef f(p):\n    try:\n        return open(p).read()\n'
        '    except (OSError, DECODE):\n        return ""\n',
        'DECODE = UnicodeDecodeError\ndef f(p):\n    try:\n        return open(p).read()\n'
        '    except (OSError, DECODE):\n        return ""\n',
    ),
    "errors_kw_is_skipped": (
        'def f(p):\n    return open(p, encoding="utf-8", errors="strict").read()\n',
        'def f(p):\n    return open(p, encoding="utf-8", errors="replace").read()\n',
    ),
    "errors_positional_is_skipped": (
        'def f(p):\n    return p.read_text("utf-8")\n',
        'def f(p):\n    return p.read_text("utf-8", "surrogateescape")\n',
    ),
    "no_encoding_is_still_strict": (
        'def f(p):\n    return open(p).read()\n',
        'def f(p):\n    return open(p, errors="replace").read()\n',
    ),
    "bytes_decode": (
        'def f(b):\n    return b.decode("utf-8")\n',
        'def f(b):\n    return b.decode("utf-8", "replace")\n',
    ),
    "stdin": (
        'import sys\ndef f():\n    return sys.stdin.read()\n',
        'import sys\ndef f():\n    try:\n        return sys.stdin.read()\n'
        '    except Exception:\n        return ""\n',
    ),
    "bare_except_guards": (
        'def f(p):\n    try:\n        return open(p).read()\n    except KeyError:\n        return ""\n',
        'def f(p):\n    try:\n        return open(p).read()\n    except:\n        return ""\n',
    ),
    "outer_try_guards": (
        'def f(p):\n    try:\n        try:\n            return open(p).read()\n'
        '        except OSError:\n            return ""\n    except KeyError:\n        return ""\n',
        'def f(p):\n    try:\n        try:\n            return open(p).read()\n'
        '        except OSError:\n            return ""\n    except UnicodeError:\n        return ""\n',
    ),
    "handler_body_is_not_protected_by_its_own_try": (
        'def f(p):\n    try:\n        pass\n    except ValueError:\n        return open(p).read()\n',
        'def f(p):\n    try:\n        return open(p).read()\n    except ValueError:\n        pass\n',
    ),
    "caller_try_does_not_count": (
        'def g(p):\n    try:\n        def f():\n            return open(p).read()\n'
        '        return f()\n    except ValueError:\n        return ""\n',
        'def g(p):\n    def f():\n        try:\n            return open(p).read()\n'
        '        except ValueError:\n            return ""\n    return f()\n',
    ),
}


@pytest.mark.parametrize("arm", sorted(_ARM_CONTROLS))
def test_each_arm_of_the_guard_is_seen(arm):
    flagged, clean = _ARM_CONTROLS[arm]
    assert len(unguarded(flagged)) == 1, (arm, strict_reads(flagged))
    assert unguarded(clean) == [], (arm, strict_reads(clean))


# ---------------------------------------------------------------------------
# Behaviour, per script: the bad byte takes the unreadable-file path
# ---------------------------------------------------------------------------
_CUA_INDEX = "schema_version: 1\ntasks:\n  - id: DATA-0001\n    status: open\n    user_action: true\n"


@pytest.fixture
def cua_repo(tmp_path):
    root = tmp_path / "proj"
    (root / "tasks").mkdir(parents=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    return root


@pytest.mark.parametrize("breakage", ["bad_byte", "unreadable", "bad_yaml"])
def test_clear_user_action_exits_1_cleanly_on_an_index_it_cannot_load(cua_repo, breakage):
    idx = cua_repo / "tasks" / "index.yml"
    if breakage == "bad_byte":
        idx.write_bytes(_CUA_INDEX.encode() + BAD)
    elif breakage == "unreadable":
        idx.write_text(_CUA_INDEX, encoding="utf-8")
        _unreadable(idx)
    else:
        idx.write_text("tasks: [\n", encoding="utf-8")
    before = idx.stat().st_mtime_ns
    r = subprocess.run([sys.executable, str(SCRIPTS / "clear_user_action.py"), "DATA-0001"],
                       cwd=str(cua_repo), capture_output=True, text=True)
    assert r.returncode == 1, (r.returncode, r.stderr)
    assert "Traceback" not in r.stderr, r.stderr
    assert "ERROR: could not load" in r.stderr and "Nothing was changed" in r.stderr, r.stderr
    assert idx.stat().st_mtime_ns == before


def test_clear_user_action_still_clears_a_clean_index(cua_repo):
    idx = cua_repo / "tasks" / "index.yml"
    idx.write_text(_CUA_INDEX, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPTS / "clear_user_action.py"), "DATA-0001"],
                       cwd=str(cua_repo), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "user_action: false" in idx.read_text(encoding="utf-8")


# -- ingest_security_report ------------------------------------------------
def _ing_finding(fid, file):
    return {"id": fid, "title": "t", "impact": "i", "file": file, "line": 1,
            "description": "d", "exploit_scenario": "e", "preconditions": [],
            "category": "c", "severity": "HIGH", "confidence": "high",
            "recommendation": "r"}


def _ing_report(root: Path, ts: str, payload: bytes) -> Path:
    d = root / f"CLAUDE-SECURITY-{ts}"
    d.mkdir(parents=True)
    (d / ing.RESULTS_JSONL).write_bytes(payload)
    return d


def _good_jsonl(fid, file) -> bytes:
    return (json.dumps(_ing_finding(fid, file)) + "\n").encode()


@pytest.mark.parametrize("breakage", ["bad_byte", "unreadable"])
def test_ingest_skips_a_findings_file_it_cannot_read_and_keeps_the_rest(tmp_path, breakage):
    good = _ing_report(tmp_path, "20260901-000000", _good_jsonl("F1", "app/a.py"))
    bad = _ing_report(tmp_path, "20260902-000000",
                      _good_jsonl("F2", "app/b.py") + (BAD if breakage == "bad_byte" else b""))
    if breakage == "unreadable":
        _unreadable(bad / ing.RESULTS_JSONL)
    # The loader itself no longer raises, and says "unreadable" as None, not [].
    assert ing._load_jsonl(bad / ing.RESULTS_JSONL) is None
    rep = ing.parse_report(bad)
    assert rep.skipped_reason and "not UTF-8" in rep.skipped_reason, rep
    r = ing.ingest(tmp_path, scope=None, include_ingested=True)
    assert [s["report"] for s in r["skipped"]] == [bad.name], r["skipped"]
    assert [f["file"] for f in r["findings"]] == ["app/a.py"], r["findings"]
    assert [m["report"] for m in r["reports"]] == [good.name]


@pytest.mark.parametrize("breakage", ["bad_byte", "unreadable"])
def test_ingest_unreadable_marker_reads_as_empty_and_says_so(tmp_path, capsys, breakage):
    marker = tmp_path / ing.MARKER_REL
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(b"CLAUDE-SECURITY-20260901-000000\n" + (BAD if breakage == "bad_byte" else b""))
    if breakage == "unreadable":
        _unreadable(marker)
    assert ing.read_marker(tmp_path) == set()
    err = capsys.readouterr().err
    assert "WARN: could not read the ingested marker" in err and str(marker) in err, err
    assert "offered again" in err, err


def test_ingest_missing_marker_is_the_silent_first_run(tmp_path, capsys):
    """Control: no marker yet is ordinary, not an unreadable input."""
    assert ing.read_marker(tmp_path) == set()
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("breakage", ["bad_byte", "unreadable", "missing"])
def test_ingest_refuses_an_explicit_scope_file_it_cannot_read(tmp_path, capsys, breakage):
    """`None` from the loader means "no scoping", which on a non-full round files a
    whole-repo report as this round's delta. A named file that cannot be read is
    refused instead: exit 1, the file named, nothing on stdout."""
    _ing_report(tmp_path, "20260901-000000", _good_jsonl("F1", "app/a.py"))
    scope = tmp_path / "scope.txt"
    if breakage != "missing":
        scope.write_bytes(b"app/a.py\n" + (BAD if breakage == "bad_byte" else b""))
    if breakage == "unreadable":
        _unreadable(scope)
    with pytest.raises(ing.ScopeFileUnreadable):
        ing._load_scope(str(scope))
    rc = ing.main(["--root", str(tmp_path), "--scope-file", str(scope), "--json"])
    cap = capsys.readouterr()
    assert rc == 1, (rc, cap.out, cap.err)
    assert "ERROR: --scope-file" in cap.err and str(scope) in cap.err, cap.err
    assert cap.out == "", cap.out


def test_ingest_readable_scope_file_and_no_scope_file_still_run(tmp_path, capsys):
    """Controls: a readable scope file scopes; no flag at all is the unscoped run."""
    _ing_report(tmp_path, "20260901-000000", _good_jsonl("F1", "app/a.py"))
    scope = tmp_path / "scope.txt"
    scope.write_text("app/other.py\n", encoding="utf-8")
    assert ing.main(["--root", str(tmp_path), "--scope-file", str(scope), "--json",
                     "--include-ingested"]) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["out_of_scope"] == 1
    assert ing.main(["--root", str(tmp_path), "--json", "--include-ingested"]) == 0
    assert json.loads(capsys.readouterr().out)["counts"]["in_scope"] == 1


def _git(repo: Path, *args, **kw):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True, **kw)


def _repo_with_non_utf8_path(tmp_path: Path) -> tuple[Path, str]:
    """A repo whose first commit tracks a Latin-1 file name (a test removes it if it needs to).

    Built through the index (`--cacheinfo`) because macOS will not create such a
    file on disk. Returns (repo, first commit).
    """
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    blob = _git(repo, "hash-object", "-w", "--stdin", input=b"x\n").stdout.decode().strip()
    subprocess.run([b"git", b"-C", os.fsencode(repo), b"update-index", b"--add", b"--cacheinfo",
                    b"100644," + blob.encode() + b",caf\xe9.py"], check=True, capture_output=True)
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-qm", "A")
    first = _git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    return repo, first


def test_ingest_staleness_is_unknown_when_git_names_a_non_utf8_path(tmp_path):
    repo, first = _repo_with_non_utf8_path(tmp_path)
    subprocess.run([b"git", b"-C", os.fsencode(repo), b"rm", b"-q", b"--cached", b"caf\xe9.py"],
                   check=True, capture_output=True)
    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    _git(repo, "add", "b.txt")
    _git(repo, "commit", "-qm", "B")
    files, why = ing._commit_changed_files(repo, first)
    assert files is None and "not UTF-8" in why and "not in local history" not in why, why
    # The per-finding note says the true reason, not "not in local history".
    state, note = ing._StalenessResolver(repo).assess({"commit": first}, "a.txt")
    assert (state, note) == ("unknown", why), (state, note)
    # Control: the same call on an all-ASCII change set answers.
    second = _git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    (repo / "b.txt").write_text("c\n", encoding="utf-8")
    assert ing._commit_changed_files(repo, second) == ({"b.txt"}, "")
    assert "not in local history" in ing._commit_changed_files(repo, "0" * 40)[1]


# -- run_checks/semgrep.py ---------------------------------------------------
def test_semgrep_recovery_reports_failure_when_git_lists_a_non_utf8_path(tmp_path):
    repo, _ = _repo_with_non_utf8_path(tmp_path)
    assert semgrep._git_lines(str(repo), ["ls-files", "-z"]) is None
    assert semgrep._default_ignored_targets(str(repo), "fixtures") == ([], 0, True)


def test_semgrep_untracked_read_failing_degrades_like_the_tracked_one(tmp_path, monkeypatch):
    """`or []` dropped the untracked test files while the stage read `executed`.
    macOS cannot create a non-UTF-8 file on disk, so git's answer is stubbed."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("x = 1\n", encoding="utf-8")

    def fake(repo_root, args):
        return None if "--others" in args else ["tests/test_a.py"]
    monkeypatch.setattr(semgrep, "_git_lines", fake)
    assert semgrep._default_ignored_targets(str(tmp_path), "fixtures") == ([], 0, True)
    # Control: the same tree with the untracked half answering recovers the file.
    monkeypatch.setattr(semgrep, "_git_lines", lambda r, a: [] if "--others" in a else ["tests/test_a.py"])
    targets, dropped, failed = semgrep._default_ignored_targets(str(tmp_path), "fixtures")
    assert (dropped, failed) == (0, False) and targets == [os.path.join(str(tmp_path), "tests/test_a.py")]


def test_semgrep_git_lines_control_all_ascii(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    assert semgrep._git_lines(str(repo), ["ls-files", "-z"]) == ["a.txt"]


# -- next_task.py ------------------------------------------------------------
@pytest.mark.parametrize("breakage", ["bad_byte", "unreadable"])
def test_next_task_load_index_exits_1_saying_cannot_read(tmp_path, capsys, breakage):
    idx = tmp_path / "index.yml"
    if breakage == "bad_byte":
        idx.write_bytes(b"schema_version: 2\n" + BAD)
    else:
        idx.write_text("schema_version: 2\n", encoding="utf-8")
        _unreadable(idx)
    with pytest.raises(SystemExit) as exc:
        nt.load_index(idx)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "ERROR: cannot read" in err and "YAML parse error" not in err, err


def test_next_task_load_index_still_names_a_yaml_error(tmp_path, capsys):
    idx = tmp_path / "index.yml"
    idx.write_text("tasks: [\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        nt.load_index(idx)
    assert "ERROR: YAML parse error in" in capsys.readouterr().err


def test_next_task_bad_body_is_omitted_and_the_pick_continues(tmp_path, monkeypatch, capsys):
    repo = _build_repo(tmp_path, _BASE_INDEX, _BASE_BODIES)
    body = repo / "tasks" / "open" / "FEAT-EASY.md"
    body.write_bytes(_BASE_BODIES["FEAT-EASY.md"].encode() + BAD)
    assert nt.extract_body_sections("open/FEAT-EASY.md", repo / "tasks", repo) == {}
    err = capsys.readouterr().err
    assert "WARN: could not read" in err and str(body) in err and "omitted" in err, err
    _patch_repo(monkeypatch, repo)
    assert nt.main([]) == 0
    cap = capsys.readouterr()
    assert "FEAT-EASY" in cap.out and "Easy context." not in cap.out, cap.out
    assert str(body) in cap.err, cap.err


def test_next_task_bad_review_file_warns_and_continues(tmp_path, monkeypatch, capsys):
    repo = _build_repo(tmp_path, _BASE_INDEX, _BASE_BODIES)
    (repo / "review_tasks.md").write_bytes(b"## Review Batch 1\n" + BAD)
    _patch_repo(monkeypatch, repo)
    assert nt.main(["--review"]) == 0
    cap = capsys.readouterr()
    assert "WARN: could not read" in cap.err, cap.err
    assert str(repo / "review_tasks.md") in cap.err, cap.err
    assert cap.out.strip() == "No pending review batches."


# -- scope_overlap.py --------------------------------------------------------
def test_scope_overlap_index_body_and_lock_take_their_soft_defaults(tmp_path, monkeypatch, capsys):
    idx = tmp_path / "tasks" / "index.yml"
    idx.parent.mkdir(parents=True)
    idx.write_bytes(b"tasks: []\n" + BAD)
    assert so._load_index_soft(idx) is None
    err = capsys.readouterr().err
    assert "WARN: scope_overlap: could not read" in err and str(idx) in err, err

    body = tmp_path / "tasks" / "open" / "T-1.md"
    body.parent.mkdir(parents=True)
    body.write_bytes(b"## Key files\n- `a.py`\n" + BAD)
    index = {"tasks": [{"id": "T-1", "body": "open/T-1.md", "blast_radius": "api"}]}
    sc = so._candidate_scope("T-1", index, tmp_path / "tasks", tmp_path)
    assert (sc.paths, sc.source) == ([], "blast_radius_only"), sc
    err = capsys.readouterr().err
    assert str(body) in err and "Key files are unknown" in err, err

    locks = tmp_path / "locks"
    locks.mkdir()
    (locks / "BAD-1.lock").write_bytes(b"task_id: BAD-1\n" + BAD)
    (locks / "OK-2.lock").write_text("task_id: OK-2\nbranch: feat/ok\n", encoding="utf-8")
    assert so._parse_lock_file(locks / "BAD-1.lock") == {}
    monkeypatch.setattr(so, "_resolve_canonical_locks_dir", lambda _root: locks)
    got = {d["task_id"]: d for d in so._read_locks(tmp_path)}
    assert set(got) == {"BAD-1", "OK-2"} and got["OK-2"]["branch"] == "feat/ok", got
    err = capsys.readouterr().err
    assert str(locks / "BAD-1.lock") in err and "OK-2.lock" not in err, err


# -- sitrep_survey.py --------------------------------------------------------
def test_sitrep_lock_index_and_review_reads_take_their_defaults(tmp_path, capsys):
    locks = tmp_path / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    (locks / "BAD-1.lock").write_bytes(b"task_id: BAD-1\n" + BAD)
    (locks / "OK-2.lock").write_text("task_id: OK-2\nbranch: feat/ok\n", encoding="utf-8")
    assert ss._parse_lock_file(locks / "BAD-1.lock") == {}
    got = {lk.task_id: lk for lk in ss._read_locks(tmp_path)}
    assert set(got) == {"BAD-1", "OK-2"} and got["OK-2"].branch == "feat/ok", got

    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "index.yml").write_bytes(b"tasks: []\n" + BAD)
    assert ss._read_index(tmp_path) == {}

    (tmp_path / "review_tasks.md").write_bytes(
        textwrap.dedent("## Review Batch 1 — x\n").encode() + BAD)
    assert ss._read_review_batches(tmp_path) == []
    # Called outside run_survey, each absorbed input is named on stderr.
    err = capsys.readouterr().err
    for name in ("BAD-1.lock", "index.yml", "review_tasks.md"):
        assert f"{name} (UnicodeDecodeError" in err, (name, err)
    assert "OK-2.lock" not in err, err


def _sitrep_survey_over(tmp_path, monkeypatch, default_branch="main", other=()):
    """run_survey over a real tmp tree, git stubbed: the readers are the real ones."""
    monkeypatch.setattr(ss, "_resolve_main_repo_root", lambda: tmp_path)
    monkeypatch.setattr(ss, "_git", lambda *a, **k: "abc1234")
    monkeypatch.setattr(ss, "resolve_default_branch", lambda root: default_branch)
    monkeypatch.setattr(ss, "_read_worktrees", lambda root: [])
    monkeypatch.setattr(ss, "_commits_ahead_of_main", lambda b, r: [])
    monkeypatch.setattr(ss, "_commits_unpushed", lambda b, r: 0)
    monkeypatch.setattr(ss, "_find_discrepancies", lambda *a, **k: list(other))
    return ss.run_survey()


def _all_surfaces(survey) -> str:
    rec = ss._recommended_next(survey)
    return "\n".join([ss.render_text(survey), ss.render_json(survey),
                      rec.command if rec else "", "\n".join(ss._suggested_order(survey))])


def test_sitrep_an_unreadable_lock_is_its_own_state_and_never_routes_to_release(tmp_path, monkeypatch):
    """Round 2, lens 4 MED-1: an undecodable lock parsed to `{}`, its empty branch
    classified `claimed, no branch`, and RECOMMENDED NEXT printed
    `claim_task.sh --release <ID>` — a teardown of a possibly-live claim."""
    locks = tmp_path / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    lock = locks / "FEAT-1.lock"
    lock.write_bytes(b"task_id: FEAT-1\nbranch: feat/one\n" + BAD)
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "index.yml").write_text(
        "tasks:\n  - id: FEAT-1\n    status: in_progress\n", encoding="utf-8")
    survey = _sitrep_survey_over(tmp_path, monkeypatch)
    [ts] = survey.tasks
    assert ts.state == "lock unreadable" and ts.has_lock, ts
    assert str(lock) in ts.next_action and "do NOT release" in ts.next_action, ts.next_action
    everything = _all_surfaces(survey)
    assert "--release" not in everything.replace("do NOT release", ""), everything
    assert "claimed, no branch" not in everything
    assert json.loads(ss.render_json(survey))["tasks"][0]["state"] == "lock unreadable"
    assert any("FEAT-1: repair" in x for x in ss._suggested_order(survey))
    rec = ss._recommended_next(survey)
    assert rec is not None and "repair" in rec.command and str(lock) in rec.command, rec


def test_sitrep_the_state_arm_routes_even_without_the_input_list(tmp_path):
    """The state has its own cascade arm, so a survey built without
    `unreadable_inputs` (e.g. `/roadmap`'s consumer, or a fixture) still repairs."""
    ts = ss.TaskState(task_id="FEAT-1", state=ss._LOCK_UNREADABLE_STATE, next_action="repair x")
    rb = ss.ReviewBatchState(
        batch_number=3, title="B", md_status="Pending", branch="review/b3", has_lock=True,
        has_branch=True, has_flag=False, flag_reason="", total_tasks=1, doc_worked_tasks=0,
        state=ss._LOCK_UNREADABLE_STATE, next_action="repair y")
    base = dict(timestamp=datetime.now(timezone.utc), main_root=tmp_path, head_short="a",
                discrepancies=[], stale_days=7, open_roadmap_ids=["OPEN-1"])
    assert ss._recommended_next(ss.Survey(tasks=[ts], review_batches=[], **base)).command == "repair x"
    assert ss._recommended_next(ss.Survey(tasks=[], review_batches=[rb], **base)).command == "repair y"
    assert "batch 3: repair y" in ss._suggested_order(ss.Survey(tasks=[], review_batches=[rb], **base))


def test_sitrep_an_unreadable_batch_lock_is_not_offered_to_a_drainer(tmp_path, monkeypatch):
    """A `BATCH-<N>.lock` that cannot be read matched no branch and read as
    `pending (not claimed)` — offered to /auto-fix while someone holds it."""
    locks = tmp_path / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    lock = locks / "BATCH-3.lock"
    lock.write_bytes(b"task_id: BATCH-3\nbranch: review/b3\n" + BAD)
    (tmp_path / "review_tasks.md").write_text(
        "### Batch 3 — Helpers `Pending`\n> **Branch:** `review/b3`\n"
        "> **Triaged:** 2026-09-01 auto\n\n- [ ] **TASK-001**: one\n", encoding="utf-8")
    survey = _sitrep_survey_over(tmp_path, monkeypatch)
    [rb] = survey.review_batches
    assert rb.state == "lock unreadable" and rb.has_lock, rb
    assert str(lock) in rb.next_action and "do NOT release" in rb.next_action
    everything = _all_surfaces(survey)
    assert "/auto-fix" not in everything and "pending (not claimed)" not in everything, everything
    assert "batch_work.sh --release" not in everything
    assert not survey.tasks, survey.tasks  # the batch path owns it, not ACTIVE WORK


def test_sitrep_an_unreadable_batch_lock_with_no_open_batch_stays_visible(tmp_path, monkeypatch):
    """Its batch path keys on `BATCH-<N>`; with no open batch to own it, it
    would vanish. It reports in ACTIVE WORK instead."""
    locks = tmp_path / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    (locks / "BATCH-9.lock").write_bytes(b"task_id: BATCH-9\n" + BAD)
    survey = _sitrep_survey_over(tmp_path, monkeypatch)
    assert [(t.task_id, t.state) for t in survey.tasks] == [("BATCH-9", "lock unreadable")]


def test_sitrep_a_readable_batch_lock_stays_on_the_batch_path(tmp_path, monkeypatch):
    """Control: the carve-out is for unreadable locks only."""
    locks = tmp_path / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    (locks / "BATCH-9.lock").write_text("task_id: BATCH-9\nbranch: review/b9\n", encoding="utf-8")
    assert _sitrep_survey_over(tmp_path, monkeypatch).tasks == []


def test_sitrep_orphan_removal_advice_waits_for_the_unreadable_lock(tmp_path):
    """An unreadable lock's branch is unknown, so a worktree matching "no lock"
    may be its claim: the removal advice names the lock repair first."""
    bad = ss.Lock(task_id="FEAT-1", path=tmp_path / "FEAT-1.lock", unreadable="UnicodeDecodeError: x")
    wt = ss.Worktree(path=tmp_path / "wt", branch="feat/one", head="abc", is_main=False)
    import unittest.mock as um
    with um.patch.object(ss, "_git", lambda *a, **k: ""):
        out = ss._find_discrepancies([bad], [wt], {}, tmp_path)
    orphan = [d for d in out if d.kind == "orphan worktree"]
    assert orphan and orphan[0].suggestion.startswith("first repair the unreadable input(s)"), out
    assert str(tmp_path / "FEAT-1.lock") in orphan[0].suggestion
    with um.patch.object(ss, "_git", lambda *a, **k: ""):
        clean = ss._find_discrepancies([], [wt], {}, tmp_path)
    assert not clean[0].suggestion.startswith("first repair"), clean


def test_sitrep_an_unreadable_index_never_ends_idle(tmp_path, monkeypatch):
    """Round 2, lens 4 LOW-MED-2: the survey said `(idle — …)` beside the discrepancy."""
    (tmp_path / "tasks").mkdir()
    idx = tmp_path / "tasks" / "index.yml"
    idx.write_bytes(b"tasks: []\n" + BAD)
    survey = _sitrep_survey_over(tmp_path, monkeypatch)
    text = ss.render_text(survey)
    assert "(idle" not in text, text
    rec = ss._recommended_next(survey)
    assert rec is not None and rec.command.startswith(f"repair {idx}"), rec
    assert "re-run /sitrep" in rec.command


def test_sitrep_a_clean_empty_tree_is_still_idle(tmp_path, monkeypatch):
    """Control for the arm above."""
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "index.yml").write_text("tasks: []\n", encoding="utf-8")
    assert "(idle" in ss.render_text(_sitrep_survey_over(tmp_path, monkeypatch))


@pytest.mark.parametrize("breakage,remedy", [
    ("bad_byte", "re-save it as UTF-8"),
    ("unreadable", "restore read access"),
    ("bad_yaml", "repair its YAML"),
])
def test_sitrep_the_remedy_matches_the_failure(tmp_path, monkeypatch, breakage, remedy):
    """Round 2, lens 4 LOW-3: "re-save as UTF-8, or repair its YAML" was shown
    for a PermissionError and for markdown."""
    (tmp_path / "tasks").mkdir()
    idx = tmp_path / "tasks" / "index.yml"
    if breakage == "bad_byte":
        idx.write_bytes(b"tasks: []\n" + BAD)
    elif breakage == "unreadable":
        idx.write_text("tasks: []\n", encoding="utf-8")
        _unreadable(idx)
    else:
        idx.write_text("tasks: [\n", encoding="utf-8")
    survey = _sitrep_survey_over(tmp_path, monkeypatch)
    [d] = [d for d in survey.discrepancies if d.kind == "input unreadable"]
    assert d.suggestion.startswith(remedy), d
    assert "in this report" in d.detail and "below" not in d.detail, d.detail
    for other in {"re-save it as UTF-8", "restore read access", "repair its YAML"} - {remedy}:
        assert other not in d.suggestion, d


def test_sitrep_markdown_is_never_told_to_repair_yaml(tmp_path, monkeypatch):
    (tmp_path / "review_tasks.md").write_bytes(b"### Batch 1 \xe2\x80\x94 x `Pending`\n" + BAD)
    survey = _sitrep_survey_over(tmp_path, monkeypatch)
    [d] = [d for d in survey.discrepancies if d.kind == "input unreadable"]
    assert "review_tasks.md" in d.detail and "YAML" not in d.suggestion, d


@pytest.mark.parametrize("default_branch", ["main", ""])
def test_sitrep_unreadable_inputs_sit_next_to_the_default_branch_line(tmp_path, monkeypatch,
                                                                       default_branch):
    """The documented placement (round 2 survivor M16): directly after the
    default-branch line when there is one, else first — before every other
    discrepancy."""
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "index.yml").write_bytes(b"tasks: []\n" + BAD)
    other = [ss.Discrepancy(kind="orphan branch", detail="d", suggestion="s")]
    survey = _sitrep_survey_over(tmp_path, monkeypatch, default_branch, other)
    kinds = [d.kind for d in survey.discrepancies]
    expected = (["default branch unresolved"] if not default_branch else []) + [
        "input unreadable", "orphan branch"]
    assert kinds == expected, kinds


def test_sitrep_an_unreadable_round_receipt_is_named_and_does_not_gate(tmp_path, monkeypatch):
    """Round 2 named it; round 3 (LOW-MED-1) found it took RECOMMENDED NEXT from a
    ready /review-close. Only the round-coverage check reads a receipt, so it is
    a plain discrepancy with a delete-or-restore remedy, and routing is kept."""
    d = tmp_path / "sysop" / "runtime" / "round-receipts"
    d.mkdir(parents=True)
    (d / "bad.json").write_text("{not json", encoding="utf-8")
    (d / "list.json").write_text("[1, 2]", encoding="utf-8")
    (d / "bytes.json").write_bytes(b'{"skill": "\xff"}')
    out = ss._round_coverage_discrepancies(tmp_path)
    by = {pathlib_name(x.detail.split(" could not be read")[0]): x for x in out}
    assert set(by) == {"bad.json", "list.json", "bytes.json"}, out
    assert all(x.kind == "round receipt unreadable" for x in out), out
    assert all(x.suggestion.startswith("delete it, or restore it") for x in out), out
    assert "not a JSON object" in by["list.json"].detail
    # Routing: the survey still recommends the ready close, not a repair.
    ready = ss.TaskState(task_id="FEAT-1", state="ready for /review-close", next_action="x")
    monkeypatch.setattr(ss, "_resolve_main_repo_root", lambda: tmp_path)
    monkeypatch.setattr(ss, "_git", lambda *a, **k: "")
    monkeypatch.setattr(ss, "resolve_default_branch", lambda root: "main")
    monkeypatch.setattr(ss, "_read_worktrees", lambda root: [])
    survey = ss.run_survey()
    assert survey.unreadable_inputs == [], survey.unreadable_inputs
    assert [x.kind for x in survey.discrepancies] == ["round receipt unreadable"] * 3
    survey.tasks = [ready]
    rec = ss._recommended_next(survey)
    assert rec is not None and rec.command.startswith("/review-close FEAT-1"), rec


def pathlib_name(p: str) -> str:
    return Path(p).name


def test_sitrep_reports_every_unreadable_input_as_a_discrepancy(tmp_path, monkeypatch, capsys):
    """An unreadable index read as `{}` made /sitrep say "idle" over a live claim.
    The survey now names each absorbed input in its own DISCREPANCIES block."""
    locks = tmp_path / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    (locks / "BAD-1.lock").write_bytes(b"task_id: BAD-1\n" + BAD)
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "index.yml").write_bytes(b"tasks: []\n" + BAD)
    (tmp_path / "review_tasks.md").write_bytes(b"## Review Batch 1\n" + BAD)
    survey = _sitrep_survey_over(tmp_path, monkeypatch)
    unreadable = [d for d in survey.discrepancies if d.kind == "input unreadable"]
    named = sorted(Path(d.detail.split(" could not be read")[0]).name for d in unreadable)
    assert named == ["BAD-1.lock", "index.yml", "review_tasks.md"], survey.discrepancies
    assert any("EMPTY" in d.detail for d in unreadable), unreadable
    text = ss.render_text(survey)
    assert "⚠ input unreadable:" in text and str(tmp_path / "tasks" / "index.yml") in text, text
    assert "triage 3 discrepancies" in text, text


def test_sitrep_clean_inputs_report_no_unreadable_discrepancy(tmp_path, monkeypatch):
    """Control: the same tree, readable, adds nothing."""
    locks = tmp_path / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    (locks / "OK-1.lock").write_text("task_id: OK-1\n", encoding="utf-8")
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "index.yml").write_text("tasks: []\n", encoding="utf-8")
    (tmp_path / "review_tasks.md").write_text("## Review Batch 1\n", encoding="utf-8")
    survey = _sitrep_survey_over(tmp_path, monkeypatch)
    assert not [d for d in survey.discrepancies if d.kind == "input unreadable"]


def test_sitrep_dirty_check_survives_a_consumer_quotepath_false(tmp_path):
    """`git status` prints a non-UTF-8 name raw when the consumer has set
    `core.quotePath=false`, and `_git` decodes strictly. Only emptiness matters
    to the dirty check, so it forces the quoted form rather than catching —
    catching would return "" and report a dirty worktree clean."""
    repo, _ = _repo_with_non_utf8_path(tmp_path)
    _git(repo, "config", "core.quotePath", "false")
    subprocess.run([b"git", b"-C", os.fsencode(repo), b"rm", b"-q", b"--cached", b"caf\xe9.py"],
                   check=True, capture_output=True)
    assert ss._worktree_dirty(repo) is True


# -- the two input() prompts: an answer that is not text declines ------------------
def test_shared_cli_prompt_declines_an_undecodable_answer(monkeypatch, capsys):
    shared_cli = _load_pack_shared_cli()
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)

    def boom(*_a):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")
    monkeypatch.setattr("builtins.input", boom)
    with pytest.raises(SystemExit) as exc:
        shared_cli.confirm_production("prod")
    assert exc.value.code == 0 and "Aborted: no readable answer." in capsys.readouterr().out


def _load_pack_shared_cli():
    import importlib.util
    path = REPO_ROOT / "packs" / "python" / "companion" / "scripts" / "shared_cli.py"
    spec = importlib.util.spec_from_file_location("shared_cli_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("stdin_errors, message", [
    ("strict", "Aborted: the answer was not readable text."),
    # Linux under the C/POSIX locale decodes stdin with surrogateescape (PEP 540), so
    # `input()` returns '\udcff' instead of raising: not "y", so the plain decline. CI
    # showed it; the stdin mode is pinned per case so neither depends on the host.
    ("surrogateescape", "Aborted."),
])
def test_archive_prompt_declines_an_undecodable_answer_through_a_real_pipe(
        tmp_path, stdin_errors, message):
    """`printf '\\xff\\n' | … input()`. Driven through the real stdin of an installed
    copy, the way `test_archive_review_tasks` drives it. Either stdin mode declines."""
    from test_archive_review_tasks import _ARCHIVABLE_WITH_FAILURE, _installed_script
    script = _installed_script(tmp_path)
    (tmp_path / "review_tasks.md").write_text(_ARCHIVABLE_WITH_FAILURE, encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING=f"utf-8:{stdin_errors}")
    r = subprocess.run([sys.executable, str(script)], input=b"\xff\n", capture_output=True,
                       env=env)
    out, err = r.stdout.decode("utf-8", "replace"), r.stderr.decode("utf-8", "replace")
    assert "Traceback" not in err, err
    assert r.returncode == 0 and message in out, (out, err)
    assert (tmp_path / "review_tasks.md").read_text(encoding="utf-8") == _ARCHIVABLE_WITH_FAILURE


# -- security_partition.py: a non-UTF-8 tracked name is named, not dropped ------
def test_security_partition_names_a_non_utf8_tracked_name(tmp_path):
    """The partition promises every tracked file an owner, so dropping the file would
    be a silent coverage hole. It names the file and assesses nothing, exit 0, the same
    shape as every other "could not assess" path; never the last-resort net (exit 2)."""
    repo, _ = _repo_with_non_utf8_path(tmp_path)
    (repo / ".claude").mkdir()
    (repo / ".claude" / "security_map.md").write_text(
        "## A01 Broken Access Control\n\n**Globs:** `**/*.py`\n\n", encoding="utf-8")
    base = [sys.executable, str(SCRIPTS / "security_partition.py"), "--root", str(repo)]
    r = subprocess.run(base + ["--json"], capture_output=True, text=True)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    report = json.loads(r.stdout)
    assert report["status"] == "undecodable-path" and report["assignments"] == [], report
    note = next(n for n in report["notes"] if "git mv" in n)
    assert "$'caf\\xe9.py'" in note, note
    operand = note.split("git mv -- ", 1)[1].split(" <new", 1)[0]
    # The operand, evaluated by bash, names the tracked file's exact bytes ...
    shown = subprocess.run(["bash", "-c", f"printf %s {operand}"], capture_output=True)
    assert shown.stdout == b"caf\xe9.py", shown
    # ... and git agrees it is a tracked path.
    listed = subprocess.run(["bash", "-c", f"git -C \"$1\" ls-files -z -- {operand}", "_",
                             str(repo)], capture_output=True)
    assert listed.stdout == b"caf\xe9.py\0", listed
    h = subprocess.run(base, capture_output=True, text=True)
    assert h.returncode == 0 and "$'caf\\xe9.py'" in h.stdout, (h.stdout, h.stderr)
    assert "unexpected error" not in r.stderr + h.stderr and "Traceback" not in r.stderr + h.stderr


@pytest.mark.parametrize("name", [
    b"caf\xe9.py", b"it's.py", b"back\\slash.py", b"sp ace.py", b"nl\nx.py",
    b"\xe9a1.py", b"\x01a.py", b"-dash.py", b"\xc3\xa9t\xe9.py",
])
def test_security_partition_operand_round_trips_through_bash(name):
    """Every byte the note can carry comes back from bash unchanged — a quote, a
    backslash, a newline, and a low byte followed by a hex digit (`\\x01a` would
    be misread as `\\x1a` by a one-digit escape)."""
    import security_partition as sp
    operand = sp._bash_operand(name)
    got = subprocess.run(["bash", "-c", f"printf %s {operand}"], capture_output=True).stdout
    assert got == name, (name, operand, got)


def test_security_partition_still_partitions_a_utf8_non_ascii_name(tmp_path):
    """Control: a VALID UTF-8 non-ASCII name is not the refused case."""
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "café.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "café.py")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init")
    (repo / ".claude").mkdir()
    (repo / ".claude" / "security_map.md").write_text(
        "## A01 Broken Access Control\n\n**Globs:** `**/*.py`\n\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPTS / "security_partition.py"), "--root",
                        str(repo), "--json"], capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout)["status"] != "undecodable-path", r.stdout


# -- round 2: the remaining absorbing arms --------------------------------------
@pytest.mark.parametrize("payload,expect", [
    (b'{"managed_paths": ["\xff"]}', "UnicodeDecodeError"),
    (b"not json", "JSONDecodeError"),
    (b"[1, 2]", "not a JSON object"),
])
def test_security_partition_names_an_unreadable_vendor_lock(tmp_path, payload, expect):
    """Round 2, lens 4 LOW-4: a lock that could not be read returned `set()` and
    counted Sysop's own files as the consumer's, silently."""
    import security_partition as sp
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "sysop.lock").write_bytes(payload)
    notes: list = []
    assert sp.read_vendor_paths(str(tmp_path), notes) == set()
    assert len(notes) == 1 and "sysop.lock" in notes[0] and expect in notes[0], notes
    assert "counted as the consumer's own" in notes[0]


def test_security_partition_no_vendor_lock_is_silent(tmp_path):
    """Control: an uninstalled tree has no lock, and that is not a failure."""
    import security_partition as sp
    notes: list = []
    assert sp.read_vendor_paths(str(tmp_path), notes) == set() and notes == []


def test_security_partition_vendor_lock_note_reaches_the_report(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    (repo / ".claude").mkdir()
    (repo / ".claude" / "security_map.md").write_text(
        "## A01 Broken Access Control\n\n**Globs:** `**/*.py`\n\n", encoding="utf-8")
    (repo / ".claude" / "sysop.lock").write_bytes(b'{"managed_paths": ["\xff"]}')
    _git(repo, "add", "a.py")
    _git(repo, "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-qm", "i")
    r = subprocess.run([sys.executable, str(SCRIPTS / "security_partition.py"), "--root",
                        str(repo), "--json"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert any("sysop.lock" in n for n in json.loads(r.stdout)["notes"]), r.stdout


def test_scope_overlap_names_each_unreadable_file_once_and_in_notes(tmp_path, monkeypatch, capsys):
    """Round 2, lens 4 LOW-9: the lock warning printed once per candidate (6 lines
    for 6 candidates), and neither the lock nor the body case reached `notes`."""
    tasks = tmp_path / "tasks"
    (tasks / "open").mkdir(parents=True)
    (tasks / "index.yml").write_text(
        "tasks:\n  - id: CAND-1\n    body: open/CAND-1.md\n    blast_radius: api\n"
        "  - id: CAND-2\n    body: open/CAND-2.md\n", encoding="utf-8")
    body = tasks / "open" / "CAND-1.md"
    body.write_bytes(b"## Key files\n- `a.py`\n" + BAD)
    (tasks / "open" / "CAND-2.md").write_text("## Key files\n- `b.py`\n", encoding="utf-8")
    locks = tmp_path / "locks"
    locks.mkdir()
    lock = locks / "OTHER-9.lock"
    lock.write_bytes(b"task_id: OTHER-9\n" + BAD)
    monkeypatch.setattr(so, "_resolve_canonical_locks_dir", lambda _r: locks)
    monkeypatch.setattr(so, "_resolve_default_branch_for", lambda c: "main")
    kw = dict(index_path=tasks / "index.yml", base_tasks_dir=tasks, project_root=tmp_path,
              worktree_reader=lambda ws: [])
    a1 = so.assess("CAND-1", **kw)
    a2 = so.assess("CAND-2", **kw)
    a3 = so.assess("CAND-2", **kw)
    err = capsys.readouterr().err
    assert err.count(str(lock)) == 1 and err.count(str(body)) == 1, err
    j1 = json.loads(so.render_json(a1))["notes"]
    assert any(str(lock) in n for n in j1) and any(str(body) in n for n in j1), j1
    for a in (a2, a3):  # every assessment still carries the lock note
        assert any(str(lock) in n for n in a.notes), a.notes
        assert not any(str(body) in n for n in a.notes), a.notes


@pytest.mark.parametrize("breakage", ["unwritable_marker", "unwritable_dir"])
def test_ingest_mark_reports_a_marker_it_could_not_write(tmp_path, capsys, breakage):
    """Round 2, lens 4 LOW-10: `--mark` printed `{"marked": [...]}` at exit 0 while
    `append_marker` swallowed the OSError and wrote nothing."""
    marker = tmp_path / ing.MARKER_REL
    marker.parent.mkdir(parents=True, exist_ok=True)
    if breakage == "unwritable_marker":
        marker.write_text("", encoding="utf-8")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root writes a mode-000 file")
        marker.chmod(0o444)
    else:
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root writes into a mode-000 directory")
        marker.parent.chmod(0o555)
    (tmp_path / "CLAUDE-SECURITY-20260901-000000").mkdir()   # a mark names a real report dir
    try:
        rc = ing.main(["--root", str(tmp_path), "--mark", "CLAUDE-SECURITY-20260901-000000", "--full", "--json"])
    finally:
        marker.parent.chmod(0o755)
    cap = capsys.readouterr()
    assert rc == 1, (rc, cap.out, cap.err)
    assert "ERROR: could not record the mark" in cap.err and str(marker) in cap.err, cap.err
    assert cap.out == "", cap.out


def test_ingest_mark_still_marks(tmp_path, capsys):
    """Control."""
    (tmp_path / "CLAUDE-SECURITY-20260901-000001").mkdir()
    assert ing.main(["--root", str(tmp_path), "--mark", "CLAUDE-SECURITY-20260901-000001", "--full", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"marked": ["CLAUDE-SECURITY-20260901-000001"], "deferred": {}}
    assert ing.read_marker(tmp_path) == {"CLAUDE-SECURITY-20260901-000001"}


def test_grep_position_check_names_a_file_it_could_not_read(tmp_path, capsys):
    import run_checks.grep as grep_mod
    src = tmp_path / "src"
    src.mkdir()
    bad = src / "locked.py"
    bad.write_text("b\na\n", encoding="utf-8")
    _unreadable(bad)
    check = {"id": "pos-c", "severity": "medium", "description": "d", "paths": ["src"],
             "include": ["*.py"], "position_check": {"earlier": "^a", "later": "^b"}}
    grep_mod.run_check(check, str(tmp_path))
    err = capsys.readouterr().err
    assert "warn: check pos-c: could not read" in err and "locked.py" in err, err


def test_grep_invert_check_names_a_file_it_could_not_reread(tmp_path, capsys, monkeypatch):
    """grep read the file; the re-read then failed. Only reachable in a race, so
    the re-read is made to fail directly."""
    import builtins
    import run_checks.grep as grep_mod
    src = tmp_path / "src"
    src.mkdir()
    (src / "bad.py").write_text("requests.get(url)\n", encoding="utf-8")
    real_open = builtins.open

    def failing_open(path, *a, **k):
        if str(path).endswith("bad.py"):
            raise PermissionError(13, "Permission denied", str(path))
        return real_open(path, *a, **k)
    monkeypatch.setattr(grep_mod, "open", failing_open, raising=False)
    check = {"id": "inv-c", "severity": "medium", "description": "d", "pattern": r"requests\.get",
             "paths": ["src"], "include": ["*.py"], "negative_pattern": "timeout",
             "invert_file_check": True}
    assert grep_mod.run_check(check, str(tmp_path)) == []
    err = capsys.readouterr().err
    assert "warn: check inv-c: could not read" in err and "bad.py" in err, err


# -- round 3 ---------------------------------------------------------------------
@pytest.mark.parametrize("content", [b"", b"- a\n- b\n", b"just a scalar\n"])
def test_sitrep_a_lock_that_parses_to_no_fields_is_unreadable(tmp_path, monkeypatch, content):
    """Round 3 LOW-2: `safe_load` of an empty file or a YAML list/scalar is not a
    mapping, and `{}` took the release route round 2 closed for unreadable locks."""
    locks = tmp_path / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    (locks / "FEAT-1.lock").write_bytes(content)
    survey = _sitrep_survey_over(tmp_path, monkeypatch)
    [ts] = survey.tasks
    assert ts.state == "lock unreadable", ts
    assert "parsed to no fields" in ts.next_action, ts.next_action
    assert "--release" not in _all_surfaces(survey).replace("do NOT release", "")


def test_sitrep_an_empty_batch_lock_is_not_offered_to_a_drainer(tmp_path, monkeypatch):
    locks = tmp_path / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    (locks / "BATCH-3.lock").write_bytes(b"")
    (tmp_path / "review_tasks.md").write_text(
        "### Batch 3 — Helpers `Pending`\n> **Branch:** `review/b3`\n"
        "> **Triaged:** 2026-09-01 auto\n\n- [ ] **TASK-001**: one\n", encoding="utf-8")
    survey = _sitrep_survey_over(tmp_path, monkeypatch)
    [rb] = survey.review_batches
    assert rb.state == "lock unreadable", rb
    assert "/auto-fix" not in _all_surfaces(survey)


def test_sitrep_a_mapping_lock_without_a_branch_is_still_claimed_no_branch(tmp_path, monkeypatch):
    """Control: a readable mapping lacking `branch:` keeps its documented meaning."""
    locks = tmp_path / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True)
    (locks / "FEAT-1.lock").write_text("task_id: FEAT-1\nstatus: claimed\n", encoding="utf-8")
    [ts] = _sitrep_survey_over(tmp_path, monkeypatch).tasks
    assert ts.state == "claimed, no branch", ts


def test_ingest_mark_refuses_a_marker_it_cannot_read_back(tmp_path, capsys):
    """Round 3 LOW-6: over an undecodable marker the append landed but could never
    be read back, and `--mark` said `{"marked": …}` at exit 0."""
    marker = tmp_path / ing.MARKER_REL
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(b"CLAUDE-SECURITY-old\n" + BAD)
    before = marker.read_bytes()
    (tmp_path / "CLAUDE-SECURITY-20260901-000002").mkdir()
    rc = ing.main(["--root", str(tmp_path), "--mark", "CLAUDE-SECURITY-20260901-000002", "--full", "--json"])
    cap = capsys.readouterr()
    assert rc == 1 and cap.out == "", (rc, cap.out, cap.err)
    assert "the marker cannot be read" in cap.err and "UnicodeDecodeError" in cap.err, cap.err
    assert marker.read_bytes() == before  # nothing appended to a file nobody can read


def test_ingest_mark_checks_the_mark_reads_back_after_the_append(tmp_path, capsys, monkeypatch):
    """The after-arm: a marker readable before the append but not after it."""
    calls = {"n": 0}
    real = ing._marker_entries

    def flaky(p):
        calls["n"] += 1
        return real(p) if calls["n"] == 1 else (None, "UnicodeDecodeError: injected")
    monkeypatch.setattr(ing, "_marker_entries", flaky)
    (tmp_path / "CLAUDE-SECURITY-20260901-000002").mkdir()
    rc = ing.main(["--root", str(tmp_path), "--mark", "CLAUDE-SECURITY-20260901-000002", "--full", "--json"])
    cap = capsys.readouterr()
    assert rc == 1 and "does not read back" in cap.err and cap.out == "", (rc, cap.err)


def test_sitrep_orphan_advice_waits_for_an_unreadable_index(tmp_path):
    """Round 3 LOW-7: with the index unread, "no matching lock or index entry" is
    unknown — the removal advice must say so first."""
    import unittest.mock as um
    wt = ss.Worktree(path=tmp_path / "wt", branch="feat/one", head="abc", is_main=False)
    idx = str(tmp_path / "tasks" / "index.yml")
    unread = [(idx, "UnicodeDecodeError: x", "c", "r")]
    with um.patch.object(ss, "_git", lambda *a, **k: "feat/one\nreview/other"):
        out = ss._find_discrepancies([], [wt], {}, tmp_path, unread)
        clean = ss._find_discrepancies([], [wt], {}, tmp_path, [])
    for kind in ("orphan worktree", "orphan branch"):
        got = [d for d in out if d.kind == kind]
        assert got and got[0].suggestion.startswith("first repair the unreadable input(s)"), out
        assert idx in got[0].suggestion
    assert not any(d.suggestion.startswith("first repair") for d in clean), clean
