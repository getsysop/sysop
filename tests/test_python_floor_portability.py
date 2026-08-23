"""The interpreter floor, verified against real interpreters — not against one.

`Q-263`. Five shipped scripts carry a PyYAML resolution block inside
`except ImportError:`, so it runs **only** on an interpreter that has no
PyYAML — which is exactly the stock-macOS / PEP-668 case Phase 182 added it
for. That block used to slice `Path(__file__).resolve().parents[:3]`, and
slicing `PurePath.parents` is Python 3.10+ (bpo-35498). On stock macOS
`/usr/bin/python3` (3.9.6) it raised `TypeError` from inside the rescue path,
*before* `validate_tasks.py`'s `sys.exit(2)` environment-failure arm could be
reached — so the exit-2 contract that `/review-close` Step 4a routes on was
unreachable by construction, and a missing dependency arrived at the close as
a schema error (`1`), which aborts the branch.

**Why this module exists rather than an assertion in the drift guard.** Phase
218 shipped a merge gate that did not parse under bash 3.2 and had it sit
green, because the one pre-existing test that executed that bash resolved its
shell through `PATH` — homebrew 5.3 on the author's machine. The coverage was
version-blind, not absent. A single-interpreter test of a compatibility
mechanism is evidence about one interpreter; this module parametrises over
every interpreter it can find, and refuses to be quietly green when the
population contains nothing below the floor.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"

# The declared floor. Single-sourced: README states it, and a test below
# asserts the two agree, so raising or lowering the floor is one edit that
# fails loudly until the documentation follows.
FLOOR = (3, 9)
FLOOR_STR = "3.9"

# The bootstrap population, from the same split the drift guard uses.
FATAL = [
    "validate_tasks.py",
    "sitrep_survey.py",
    "next_task.py",
    "backfill_completed_dates.py",
]
SOFT = "scope_overlap.py"
BOOTSTRAP_SCRIPTS = [*FATAL, SOFT]


# ── interpreter discovery ───────────────────────────────────────────────────

def _version_of(exe: str) -> tuple[int, int] | None:
    try:
        r = subprocess.run(
            [exe, "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        major, minor = r.stdout.strip().split(".")
        return int(major), int(minor)
    except ValueError:
        return None


def _discover() -> list[tuple[str, tuple[int, int]]]:
    """Every python3 this machine can offer, de-duplicated by real path.

    `/usr/bin/python3` is named EXPLICITLY rather than trusted to `PATH`: on
    macOS a Homebrew or venv python shadows it, and the shadowed one is the
    whole point — it is the interpreter a consumer without PyYAML actually
    runs. `SYSOP_FLOOR_PYTHONS` (colon-separated) is how CI hands in an
    interpreter that is deliberately NOT on `PATH`.
    """
    candidates: list[str] = []
    candidates += [p for p in os.environ.get("SYSOP_FLOOR_PYTHONS", "").split(":") if p]
    candidates.append("/usr/bin/python3")
    names = ["python3"] + [f"python3.{minor}" for minor in range(8, 15)]
    for name in names:
        found = shutil.which(name)
        if found:
            candidates.append(found)
    candidates.append(sys.executable)

    seen: set[str] = set()
    out: list[tuple[str, tuple[int, int]]] = []
    for c in candidates:
        if not c or not os.path.exists(c):
            continue
        real = os.path.realpath(c)
        if real in seen:
            continue
        seen.add(real)
        v = _version_of(c)
        if v is not None:
            out.append((c, v))
    return out


INTERPRETERS = _discover()
BELOW_FLOOR_PLUS_ONE = [(p, v) for p, v in INTERPRETERS if v < (3, 10)]

_IDS = [f"{p}@{v[0]}.{v[1]}" for p, v in INTERPRETERS]


@pytest.fixture(scope="session")
def yamlless(tmp_path_factory) -> Path:
    """A directory that shadows `yaml` for any interpreter, via PYTHONPATH.

    Shadowing rather than uninstalling: the interpreter is otherwise intact,
    so a "fix" that merely deleted the resolution probe would still be caught
    by the exit-code assertions below.
    """
    d = tmp_path_factory.mktemp("yamlless")
    (d / "yaml.py").write_text(
        "raise ImportError(\"No module named 'yaml'\")\n", encoding="utf-8"
    )
    return d


@pytest.fixture(scope="session")
def consumer(tmp_path_factory) -> Path:
    """A consumer-shaped tree — `<root>/sysop/scripts/` — with NO venv.

    No venv is the point: the resolution block must run all the way through
    and fall out of its bottom into the designed error, which is the path the
    slice used to crash on.
    """
    root = tmp_path_factory.mktemp("floor-consumer") / "proj"
    (root / "sysop" / "scripts").mkdir(parents=True)
    (root / "tasks").mkdir()
    for name in [*BOOTSTRAP_SCRIPTS, "_log.py"]:
        (root / "sysop" / "scripts" / name).write_bytes((SCRIPTS / name).read_bytes())
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
        check=True, capture_output=True,
    )
    return root


def _run(py: str, script: Path, *args, cwd: Path, yamlless: Path):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(yamlless)
    return subprocess.run(
        [py, str(script), *args], cwd=str(cwd),
        capture_output=True, text=True, env=env, timeout=120,
    )


# ── the floor, executed ─────────────────────────────────────────────────────

@pytest.mark.parametrize("py,version", INTERPRETERS, ids=_IDS)
@pytest.mark.parametrize("name", BOOTSTRAP_SCRIPTS)
def test_the_bootstrap_survives_every_interpreter(name, py, version, consumer, yamlless):
    """The resolution block must not raise on any interpreter it can run on.

    Asserted on the traceback rather than on the exit code, because four of
    these five exit non-zero by design once the resolution fails — the
    distinction that matters is *designed refusal* versus *crash inside the
    rescue*.
    """
    r = _run(py, consumer / "sysop" / "scripts" / name, cwd=consumer, yamlless=yamlless)
    assert "Traceback (most recent call last)" not in r.stderr, (
        f"{name} crashed under {py} ({version[0]}.{version[1]}) inside its own "
        f"PyYAML rescue path:\n{r.stderr}"
    )
    assert "TypeError" not in r.stderr, (
        f"{name} raised TypeError under {py} ({version[0]}.{version[1]}):\n{r.stderr}"
    )


@pytest.mark.parametrize("py,version", INTERPRETERS, ids=_IDS)
def test_the_environment_failure_arm_is_reachable(py, version, consumer, yamlless):
    """`validate_tasks.py` must exit **2**, not 1, when PyYAML is missing.

    This is the assertion `Q-263` asked for by name. `/review-close` Step 4a
    routes the two apart in terms — `1` means "your resolution is wrong: fix
    it, or abort and 4a-SKIP the branch", `2` means "environment failure, do
    NOT abort on it". The crash made every 3.9 host report `1`, converting a
    must-not-abort into a must-abort and downgrading an approved branch over
    a missing dependency. A green "no traceback" is not enough: the exit code
    is the contract.
    """
    r = _run(py, consumer / "sysop" / "scripts" / "validate_tasks.py", "--quiet",
             cwd=consumer, yamlless=yamlless)
    assert r.returncode == 2, (
        f"validate_tasks.py exited {r.returncode} under {py} "
        f"({version[0]}.{version[1]}); the environment-failure contract is 2.\n"
        f"stdout={r.stdout}\nstderr={r.stderr}"
    )
    assert "requires PyYAML" in r.stderr, r.stderr


@pytest.mark.parametrize("py,version", INTERPRETERS, ids=_IDS)
def test_every_shipped_script_compiles_on_every_interpreter(py, version):
    """Syntax-level floor sweep, so the next 3.10-only construct is caught.

    `parents[:3]` was a *runtime* break and this check would not have caught
    it — which is why the execution tests above exist. This one covers the
    other half of the class (match statements, `X | Y` annotations at runtime,
    parenthesised context managers) across every shipped `.py`, not just the
    five with a bootstrap.
    """
    shipped = sorted((REPO_ROOT / "core").rglob("*.py")) + sorted(
        (REPO_ROOT / "packs").rglob("*.py")
    )
    assert shipped, "no shipped Python found — the glob is wrong, not the tree"
    # `compile()` rather than `py_compile`: py_compile writes `__pycache__`
    # into the source tree, and a test that dirties the tree it is measuring
    # is how Phase 218 lost a suite run to contamination.
    prog = (
        "import sys\n"
        "for f in sys.argv[1:]:\n"
        "    src = open(f, 'rb').read()\n"
        "    try:\n"
        "        compile(src, f, 'exec')\n"
        "    except SyntaxError as e:\n"
        "        print('%s: %s' % (f, e), file=sys.stderr); sys.exit(1)\n"
    )
    r = subprocess.run(
        [py, "-c", prog, *[str(p) for p in shipped]],
        capture_output=True, text=True, timeout=300,
    )
    assert r.returncode == 0, (
        f"shipped Python does not compile under {py} "
        f"({version[0]}.{version[1]}):\n{r.stderr}"
    )


# ── the class, swept ────────────────────────────────────────────────────────

def test_no_shipped_script_slices_path_parents():
    """The class, not the five instances.

    Indexing (`parents[2]`) is fine on 3.9 and is used in several scripts;
    only *slicing* breaks. This asserts the slice form is absent everywhere
    under `core/` and `packs/`, so the next author who reaches for it in a
    sixth script is caught by the suite rather than by a consumer on macOS.
    """
    pattern = re.compile(r"\.parents\[[^\]]*:")
    offenders = []
    for p in [*(REPO_ROOT / "core").rglob("*.py"), *(REPO_ROOT / "packs").rglob("*.py")]:
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{p.relative_to(REPO_ROOT)}:{i}: {line.strip()}")
    assert not offenders, (
        "slicing `PurePath.parents` is Python 3.10+ (bpo-35498) and these sites "
        "would raise TypeError on the interpreter floor. Use "
        "`list(path.parents)[:N]`:\n" + "\n".join(offenders)
    )


# ── the population itself is the thing that goes quietly wrong ──────────────

def test_a_sub_floor_interpreter_was_actually_exercised():
    """Loud about being unable to test the floor, rather than green.

    Every test above is parametrised over whatever this machine has. On a
    machine with only 3.13 they all pass and prove nothing about 3.9. This
    test states that outcome instead of letting the green suite imply
    coverage it does not have.
    """
    if not BELOW_FLOOR_PLUS_ONE:
        pytest.skip(
            "NO INTERPRETER BELOW 3.10 ON THIS MACHINE — the floor guard ran "
            f"against {[f'{v[0]}.{v[1]}' for _, v in INTERPRETERS]} and is "
            "therefore evidence about nothing below 3.10. Install one "
            "(`brew install python@3.9`, or point SYSOP_FLOOR_PYTHONS at it) "
            "before trusting this module's green."
        )
    assert BELOW_FLOOR_PLUS_ONE


@pytest.mark.skipif(
    not os.environ.get("CI"),
    reason="local machines may legitimately lack a sub-3.10 interpreter; CI may not",
)
def test_ci_supplies_the_floor_interpreter():
    """In CI the skip above is not acceptable — it would be version-blindness
    with a receipt.

    The workflow installs 3.9 alongside the suite's own interpreter and hands
    its path in through `SYSOP_FLOOR_PYTHONS`. If that step is removed or
    renamed, this fails rather than the module quietly narrowing to one
    modern interpreter — which is exactly how Phase 218's bash-3.2 parse
    error survived a green suite.
    """
    assert BELOW_FLOOR_PLUS_ONE, (
        "CI provided no interpreter below 3.10. Discovered: "
        f"{[(p, f'{v[0]}.{v[1]}') for p, v in INTERPRETERS]}. "
        "Check the 'Install the floor interpreter' step in "
        ".github/workflows/tests.yml and SYSOP_FLOOR_PYTHONS."
    )


def test_the_readme_states_the_floor_this_module_enforces():
    """A floor nobody documents is not a floor a consumer can meet."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", readme)
    assert f"Python {FLOOR_STR}+" in flat, (
        f"README.md does not state the interpreter floor as 'Python {FLOOR_STR}+'. "
        "This module enforces it by execution; the prerequisites line has to say it."
    )


# ── the half the `.py` sweep cannot see ─────────────────────────────────────
#
# Round lens 3, finding I2: a 3.10+ construct inside a *skill heredoc* is invisible to
# every check above — they glob `*.py`. Those heredocs are shipped Python that runs on
# the consumer's bare `python3`, which on stock macOS is 3.9, and they are among the
# most-executed programs Sysop has (the close's consolidation, the claim's schema gate).
# Demonstrated by mutation: `parents[:3]` inside Step 3c's program survived the whole
# suite.

_HEREDOC = re.compile(r"^([ \t]*)(?:\.venv/bin/)?python3\s+-\s*<<\s*'?(\w+)'?[^\n]*$", re.M)


def _skill_heredocs() -> list[tuple[str, str]]:
    """(label, source) for every `python3 - <<PY … PY` block under core/skills/."""
    out: list[tuple[str, str]] = []
    for f in sorted((REPO_ROOT / "core" / "skills").rglob("*.md")):
        body = f.read_text(encoding="utf-8")
        for m in _HEREDOC.finditer(body):
            term = m.group(2)
            rest = body[m.end():]
            end = re.search(r"^[ \t]*%s[ \t]*$" % re.escape(term), rest, re.M)
            if not end:
                continue
            block = rest[:end.start()]
            # Strip the common leading indentation the fenced block carries.
            lines = [ln for ln in block.split("\n")]
            pads = [len(ln) - len(ln.lstrip()) for ln in lines if ln.strip()]
            pad = min(pads) if pads else 0
            src = "\n".join(ln[pad:] if len(ln) >= pad else ln for ln in lines)
            line_no = body.count("\n", 0, m.start()) + 1
            out.append((f"{f.relative_to(REPO_ROOT)}:{line_no}", src))
    return out


HEREDOCS = _skill_heredocs()


def test_the_heredoc_population_is_not_empty():
    """A zero-length population would make every test below vacuously green — which is
    how the class hid in the first place."""
    assert len(HEREDOCS) >= 10, (
        f"only {len(HEREDOCS)} skill heredocs extracted; the regex has drifted away from "
        "the shipped invocation shape and the floor checks below are testing nothing"
    )


@pytest.mark.parametrize("py,version", INTERPRETERS, ids=_IDS)
def test_no_skill_heredoc_needs_more_than_the_floor(py, version, tmp_path):
    """Differential, not absolute: a heredoc that compiles on a modern interpreter and
    NOT on this one is using something above the floor. Comparing the two sidesteps the
    unsubstituted `<placeholder>` text some blocks legitimately carry."""
    prog = (
        "import sys\n"
        "src = open(sys.argv[1], 'rb').read()\n"
        "try:\n"
        "    compile(src, sys.argv[1], 'exec')\n"
        "except SyntaxError as e:\n"
        "    print('SYNTAX %s' % e, file=sys.stderr); sys.exit(2)\n"
    )
    offenders = []
    for label, src in HEREDOCS:
        f = tmp_path / "block.py"
        f.write_text(src, encoding="utf-8")
        here = subprocess.run([py, "-c", prog, str(f)], capture_output=True, text=True, timeout=60)
        modern = subprocess.run([sys.executable, "-c", prog, str(f)],
                                capture_output=True, text=True, timeout=60)
        if here.returncode != 0 and modern.returncode == 0:
            offenders.append(f"{label}: {here.stderr.strip().splitlines()[-1:]}")
    assert not offenders, (
        f"skill heredoc(s) that compile on {sys.version_info[0]}.{sys.version_info[1]} but "
        f"not on {py} ({version[0]}.{version[1]}) — this is shipped Python that runs on a "
        "consumer's bare `python3`:\n" + "\n".join(offenders)
    )


def test_no_skill_heredoc_slices_path_parents():
    """The specific class, swept where the `.py` sweep does not reach. A runtime break
    like `parents[:3]` is invisible to the compile check above, exactly as it was to the
    `py_compile` sweep of the shipped scripts."""
    pattern = re.compile(r"\.parents\[[^\]]*:")
    offenders = [label for label, src in HEREDOCS if pattern.search(src)]
    assert not offenders, (
        "slicing `PurePath.parents` is 3.10+ and these skill heredocs would raise "
        "TypeError on the interpreter floor: " + ", ".join(offenders)
    )
