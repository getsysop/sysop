"""The `Q-286` predicate, tested on built venvs instead of on prose (Phase 226).

**This module exists because the thing it replaces was disqualified by its own
round.** Phase 226 first shipped `tests/test_venv_probe_discipline.py`, a guard
over the *idiom*: "a venv path's existence is never a truth test, only its
interpreter is." An independent lens ran 77 mutations against it; **48 survived
(62%)**, including the `Q-286` defect itself rewritten two ordinary ways inside
the very function the phase had just fixed — once with the venv name coming from
a `for`-loop target (the binding resolver reads only assignments, so the
extractor yielded zero sites), and once with no existence probe at all
(`_usable_venv_dir() or (REPO_ROOT / ".venv")`). It also produced a genuine
**false positive** on a behaviour-preserving `assert` -> `if not: raise` refactor
of a real site — which was the bar it had to clear and did not.

The deeper finding is the one this module answers. The idiom guard could not
reach the phase's own stated acceptance criteria: **deleting any single
condition from `_usable_venv_dir` — the file test, the executability test, or
the yaml import — left the whole suite green**, because nothing anywhere
executed that function against a venv it could inspect. Four shapes were
described in the record as "built and run", and not one of them was pinned.

So the mechanism moved from *what the code looks like* to *what the predicate
answers*. A shape is built on disk and the predicate is asked about it. Renaming
a variable, hoisting a path, or switching to `os.path` cannot change the result,
because the result is a behaviour rather than a spelling.

**What this does NOT cover, so the coverage is not over-read.** It pins the
*test-side* predicate against the contract `claim_task.sh` documents; it does not
execute `resolve_yaml_python()` and diff the two. The shipped script's own
behaviour on these shapes is covered separately and hermetically by
`tests/test_claim_task_venv_python.py`, which builds yaml-less and absent
interpreters and runs the real script. Making the two agree *by execution* over
one shared corpus is the honest next step, and it is filed rather than faked.
"""
import os
import stat
import sys
from pathlib import Path

import pytest

from tests.test_claim_clone_and_flag_order import (  # noqa: E402
    _a_pyyaml_interpreter_is_reachable,
    _imports_yaml,
    _usable_venv_dir,
)


def _shim(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _capable_py3(bin_dir: Path) -> Path:
    """A real interpreter that CAN import yaml — the positive controls' engine.

    Not a stub: a fix that deleted the resolution and returned a constant would
    pass against a stub, and fails against this.
    """
    return _shim(bin_dir / "python3", f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')


def _yamlless_py3(bin_dir: Path, blocker: Path) -> Path:
    """A real interpreter that CANNOT import yaml.

    Shadows `yaml` with a raising stub via PYTHONPATH, searched before
    site-packages. The distinction is load-bearing and is borrowed from
    `test_claim_task_venv_python.py`: against a shim that simply `exit 1`s, a fix
    that dropped the probe rather than resolving an interpreter still looks green.
    """
    blocker.mkdir(parents=True, exist_ok=True)
    (blocker / "yaml.py").write_text("raise ImportError(\"No module named 'yaml'\")\n")
    return _shim(bin_dir / "python3",
                 f'#!/bin/sh\nPYTHONPATH="{blocker}" exec "{sys.executable}" "$@"\n')


@pytest.fixture(scope="module", autouse=True)
def _the_runner_can_import_yaml():
    """Non-negotiable precondition for the POSITIVE controls below.

    Skipped rather than failed, and the reason is this module's own subject: a
    test whose precondition is an ambient interpreter must skip when it is
    absent, not fail. That is `Q-286`.
    """
    if not _imports_yaml(Path(sys.executable)):
        pytest.skip("the interpreter running pytest cannot import yaml, so the "
                    "positive controls cannot be built")


# ── the four shapes the record claimed were "built and run" ──────────────────

def test_an_empty_venv_directory_is_not_a_usable_venv(tmp_path):
    """Phase 225's predicate returned True here. `resolve_yaml_python()` does
    not: `[[ -x .../python3 ]]` fails and it falls through to the PATH probe."""
    (tmp_path / ".venv").mkdir()
    assert _usable_venv_dir(tmp_path) is None


def test_a_non_executable_python3_is_not_a_usable_venv(tmp_path):
    """A botched copy, or a tree restored from an archive. Deleting the
    `os.access(..., X_OK)` term makes this the one test in the suite that
    reddens — before this module, that deletion was invisible."""
    py = tmp_path / ".venv/bin/python3"
    py.parent.mkdir(parents=True)
    py.write_text("#!/bin/sh\nexit 0\n")
    py.chmod(0o644)
    assert _usable_venv_dir(tmp_path) is None


def test_a_windows_layout_venv_is_not_a_usable_venv(tmp_path):
    """`Scripts/`, no `bin/`. Pins the `bin` segment of the probed path."""
    _shim(tmp_path / ".venv/Scripts/python3", f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    assert _usable_venv_dir(tmp_path) is None


def test_a_yamlless_interpreter_is_not_a_usable_venv(tmp_path):
    """The sharpest of the four: everything present and executable, and the only
    thing wrong is the one thing `claim_task.sh` actually needs."""
    _yamlless_py3(tmp_path / ".venv/bin", tmp_path / "blocker")
    assert _usable_venv_dir(tmp_path) is None


# ── positive controls: without these, `return None` passes every test above ──

def test_a_working_dot_venv_IS_resolved(tmp_path):
    _capable_py3(tmp_path / ".venv/bin")
    assert _usable_venv_dir(tmp_path) == tmp_path / ".venv"


def test_a_working_plain_venv_IS_resolved(tmp_path):
    """`resolve_yaml_python()` probes `.venv/bin` then `venv/bin`. Dropping the
    second candidate is invisible without this."""
    _capable_py3(tmp_path / "venv/bin")
    assert _usable_venv_dir(tmp_path) == tmp_path / "venv"


def test_dot_venv_wins_over_plain_venv(tmp_path):
    """Pins the ORDER, which is unobservable whenever both candidates work."""
    _capable_py3(tmp_path / ".venv/bin")
    _capable_py3(tmp_path / "venv/bin")
    assert _usable_venv_dir(tmp_path) == tmp_path / ".venv"


def test_a_broken_dot_venv_falls_through_to_a_working_plain_venv(tmp_path):
    """`continue`, not `break` — the script skips a bad candidate rather than
    abandoning the loop. A predicate returning None at the first failure passes
    every negative test above and fails here."""
    (tmp_path / ".venv").mkdir()
    _capable_py3(tmp_path / "venv/bin")
    assert _usable_venv_dir(tmp_path) == tmp_path / "venv"


# ── the skip decision itself, which is what Q-286 was actually about ─────────

def test_the_skip_predicate_is_true_when_the_venv_is_usable(tmp_path):
    _capable_py3(tmp_path / ".venv/bin")
    assert _a_pyyaml_interpreter_is_reachable(tmp_path) is True


def test_the_skip_predicate_falls_through_to_PATH_when_the_venv_is_unusable(
        tmp_path, monkeypatch):
    """The fall-through is what makes the whole thing safe: an unusable venv must
    not be the final answer, or one broken `.venv` silently disables the tests.

    **The PATH is CONTROLLED here, and that is the whole point of the fixture.**
    An earlier version asserted agreement with whatever ambient `python3` could
    do — which on a developer machine with a yaml-less Homebrew python3 is
    `False`, the same answer a predicate with the fall-through *deleted* returns.
    So the test was inert exactly where it was written and live only on CI.
    Mutation found it: deleting the fall-through survived. A capable interpreter
    is now put on PATH so the two answers differ.
    """
    (tmp_path / ".venv").mkdir()                       # present and unusable
    bin_dir = tmp_path / "pathbin"
    _capable_py3(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    assert _a_pyyaml_interpreter_is_reachable(tmp_path) is True


def test_the_skip_predicate_is_false_when_nothing_anywhere_has_yaml(
        tmp_path, monkeypatch):
    """The refusal half, also on a controlled PATH: no usable venv AND no capable
    `python3` is the one environment in which a skip is the honest answer. This
    is the precondition `Q-286` was filed for, built rather than waited for."""
    (tmp_path / ".venv").mkdir()
    bin_dir = tmp_path / "pathbin"
    _yamlless_py3(bin_dir, tmp_path / "blocker2")
    monkeypatch.setenv("PATH", str(bin_dir))
    assert _a_pyyaml_interpreter_is_reachable(tmp_path) is False


def test_the_predicate_defaults_to_this_repo(tmp_path):
    """The `root` parameter must not have changed the shipped call's meaning."""
    assert _usable_venv_dir() == _usable_venv_dir(Path(__file__).resolve().parents[1])


def test_a_directory_where_python3_should_be_is_not_a_usable_venv(tmp_path):
    """`is_file()` is load-bearing against a CRASH, not just a wrong answer.

    Found by mutation: dropping `is_file()` left every other shape here green,
    because `os.access()` is False for a path that does not exist. A *directory*
    is the case that separates them — `os.access(dir, X_OK)` is True for a
    traversable directory, and `subprocess.run([<dir>, ...])` then raises rather
    than returning non-zero, so the predicate would die instead of falling
    through. `claim_task.sh` survives the same shape because its
    `"${candidate}/python3" -c ...` merely fails and hits `continue`.
    """
    (tmp_path / ".venv/bin/python3").mkdir(parents=True)
    assert _usable_venv_dir(tmp_path) is None
