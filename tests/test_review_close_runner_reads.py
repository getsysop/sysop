"""Phase 385 (`Q-409` P1, second half): review-close's readers read its runner text.

`tools/RUNNER_CORE_SPLIT_SPEC.md` § 3.2 classes A and B: a test that slices or searches
`review-close/SKILL.md` reads the file alone, so when a step moves into `steps/` it goes red
(the text it wants is gone) or, for an absence check, blind (the text it forbids can come
back unseen). Phase 385 moved each such read to `tests/skill_runner_text.py`'s `text_of`,
which splices the step files back in document order. Wade scoped the repoint to review-close,
the only skill the spec splits (2026-10-15); another skill's readers move when it splits.

Layers:

1. `text_of` itself: a `SKILL.md` is spliced, anything else is read as it is; and
   `runner_key` / `fold_steps`, which key a step file as its skill's `SKILL.md` for the
   per-file censuses that pin which file carries a match;
2. a static guard: no test or tool reads a path that names review-close's `SKILL.md` except
   through the helper, beyond an allowlist that names each reader's count and reason.

The phase's evidence that every in-process read moved is a run, not this module:
`tools/runner_core_split/rc_read_sites.py` over a full suite in a tree holding a committed,
unreferenced step file, and `absence_plant.py` in a tree with every section moved behind
markers (`PHASE_LOG.md` § Phase 385). The static guard keeps the spelled reads from coming
back; its limits are written beside it.
"""
from __future__ import annotations

import ast
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import skill_runner_text as RT

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / "core" / "skills"


# ── 1. text_of ─────────────────────────────────────────────────────────────

def _skill(tmp_path, files):
    d = tmp_path / "demo"
    for rel, text in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return d


def test_text_of_splices_a_skill_md(tmp_path):
    d = _skill(tmp_path, {"SKILL.md": "a\n<!-- sysop:arm=one -->\nb\n", "steps/one.md": "ONE\n"})
    assert RT.text_of(d / "SKILL.md") == "a\nONE\nb\n"
    assert RT.text_of(d / "SKILL.md") == RT.skill_text(d)


def test_text_of_appends_an_unreferenced_step(tmp_path):
    d = _skill(tmp_path, {"SKILL.md": "core\n", "steps/z.md": "STEP\n"})
    assert "STEP" in RT.text_of(d / "SKILL.md")


def test_text_of_reads_any_other_file_as_it_is(tmp_path):
    d = _skill(tmp_path, {"SKILL.md": "core\n", "steps/z.md": "STEP\n",
                          "REFERENCE.md": "why\n"})
    assert RT.text_of(d / "REFERENCE.md") == "why\n"
    assert RT.text_of(d / "steps" / "z.md") == "STEP\n"


def test_text_of_takes_a_string_path(tmp_path):
    d = _skill(tmp_path, {"SKILL.md": "core\n", "steps/z.md": "STEP\n"})
    assert "STEP" in RT.text_of(str(d / "SKILL.md"))


def test_runner_key_folds_a_step_and_nothing_else(tmp_path):
    d = _skill(tmp_path, {"SKILL.md": "core\n", "steps/a.md": "A\n", "steps/deep/b.md": "B\n",
                          "REFERENCE.md": "why\n", "steps/.hidden.md": "h\n",
                          "steps/__pycache__/c.md": "c\n", "steps/notes.txt": "t\n"})
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "o.md").write_text("o\n")
    (d / "steps" / "linked").symlink_to(outside)
    assert RT.runner_key(d / "steps" / "a.md") == d / "SKILL.md"
    assert RT.runner_key(d / "steps" / "deep" / "b.md") == d / "SKILL.md"
    for p in ("SKILL.md", "REFERENCE.md", "steps/.hidden.md", "steps/__pycache__/c.md",
              "steps/notes.txt", "steps/linked/o.md"):
        assert RT.runner_key(d / p) == d / p, p
    # A string path stays a string.
    assert RT.runner_key(str(d / "steps" / "a.md")) == (d / "SKILL.md").as_posix()
    # A `_shared/`-style directory with no SKILL.md folds nothing.
    shared = tmp_path / "_shared" / "sub"
    shared.mkdir(parents=True)
    (shared / "x.md").write_text("x\n")
    assert RT.runner_key(shared / "x.md") == shared / "x.md"


def test_runner_key_folds_exactly_what_step_files_lists(tmp_path):
    """Two rules written to agree are not one measurement: every file `step_files` returns
    folds, and no other `.md` below the skill does."""
    d = _skill(tmp_path, {"SKILL.md": "core\n", "steps/a.md": "A\n", "steps/x/b.md": "B\n",
                          "steps/.dot/c.md": "c\n", "steps/__pycache__/d.md": "d\n",
                          "REFERENCE.md": "r\n"})
    steps = set(RT.step_files(d))
    for p in d.rglob("*.md"):
        assert (RT.runner_key(p) == d / "SKILL.md" and p != d / "SKILL.md") == (p in steps), p


def test_fold_steps_keeps_order_and_reads_once(tmp_path):
    d = _skill(tmp_path, {"SKILL.md": "core\n", "steps/a.md": "A\n", "steps/b.md": "B\n"})
    other = tmp_path / "other.md"
    other.write_text("o\n")
    got = RT.fold_steps([d / "steps" / "a.md", other, d / "SKILL.md", d / "steps" / "b.md"])
    assert got == [d / "SKILL.md", other]
    # The folded `SKILL.md`, read through `text_of`, still carries every step.
    assert all(x in RT.text_of(got[0]) for x in ("A", "B"))


def test_a_folded_list_read_raw_loses_its_steps(tmp_path):
    """Why every reader of a folded list must read through `text_of`: a raw read of the
    folded `SKILL.md` is the core alone, and the step text is gone from the scan."""
    d = _skill(tmp_path, {"SKILL.md": "core\n", "steps/a.md": "PLANT\n"})
    folded = RT.fold_steps(sorted(d.rglob("*.md")))
    assert not any("PLANT" in p.read_text() for p in folded)
    assert any("PLANT" in RT.text_of(p) for p in folded)


def test_today_review_close_reads_as_its_core_plus_its_arms():
    """Phase 388 (`Q-409` P2) moved the first step, `steps/4d-direct.md`, and Phase 390 (P4)
    moved Step 4a's `4a-append` and `4a-fix`, and Phase 393 (P4b) `4d-pr` and the two flag
    sections, and Phase 397 (P5) Step 3b's two exit arms, and Phase 403 (P5) Step 4c's two, and Phase 406 (P5)
    Step 2b's four, and Phase 411 (P5) Step 3c's signal arm, and Phase 415 (P5) Step 4-pre's `pr`
    shapes, and Phase 416 (P5) Step 6's three policy runs, and Phase 429 (P5) Step 4a's published
    arm, and Phase 430 (P5) Step 2a step 3a's answers and 4a-post 3a's pre-scan outcomes, so a repointed reader now reads the
    core with each file spliced at its marker, and nothing else. When another step moves, this
    is the line that changes."""
    rc = SKILLS / "review-close"
    core = (rc / "SKILL.md").read_text(encoding="utf-8")
    want = core
    arms = ("2a-ignored-refs", "2b-large-diff", "2b-leak", "2b-no-conventions", "2b-twin-spawn", "3b-collect-exit",
            "3b-rollback", "3c-signals", "4-pre-pr", "4a-append", "4a-fix", "4a-post-failure", "4a-post-prescan", "4a-published", "4b-batches", "4c-check-exit", "4c-unmerged", "4d-direct", "4d-pr", "6-direct", "6-pr-cleanup", "6-pr-gate", "prepare-resume", "request-review-land")
    for arm in arms:
        marker = f"<!-- sysop:arm={arm} -->\n"
        assert core.count(marker) == 1, arm
        want = want.replace(marker, (rc / "steps" / f"{arm}.md").read_text(encoding="utf-8"))
    assert RT.text_of(rc / "SKILL.md") == want
    assert [p.name for p in RT.step_files(rc)] == [f"{a}.md" for a in arms]


# ── 2. nothing reads review-close's SKILL.md around the helper ─────────────

# A read is `<p>.read_text()`, `<p>.read_bytes()`, `<p>.open()`, `open(<p>)`, `io.open(<p>)`,
# `codecs.open(<p>)` or `Path.read_text(<p>)`, where `<p>` names review-close's `SKILL.md`:
# its leaves, joined by `/`, `.joinpath(...)`, `os.path.join(...)` or a multi-argument
# `Path(...)`, and seen through `.resolve()`, `.absolute()`, `str()` and `os.fspath()`, name
# `review-close` then `SKILL.md`, or one leaf ends in `review-close/SKILL.md`. A leaf may be a
# name bound to the file (`RC = ROOT / _SKILL`), to the string (`_SKILL = "…/SKILL.md"`) or
# to review-close's directory (`rc = SKILLS / "review-close"`, or `RC.parent`); bindings are
# collected file-wide, which over-approximates scope and errs loud. It CANNOT see: a helper
# that takes its path as an argument (`_read(p)`), an f-string or `+` concatenation, a path
# held in a container and read in a loop, a tuple-unpacked or walrus binding, a
# `functools.partial`, an imported constant or attribute (`T.CLOSE`), `PurePosixPath`,
# `.as_posix()`/`.expanduser()`/`.parents[0]`/`.with_name()`, `Path` imported under another
# name, `os.open`, `linecache`, a `SKILL.md` leaf held in a variable, `self.<attr>`, or a
# subprocess; and it reads `tests/*.py` and
# `tools/*.py` only, not `tools/` subdirectories, whose measurement tools read the core on
# purpose. The hand-decided sites read in those shapes
# (`tools/runner_core_split/repoint_385_sites.txt`) and are pinned by function below
# (`UNSEEN_SITES`); a new one is caught only by re-running `rc_read_sites.py` (spec § 8). A
# copy (`shutil.copy`) is not a read.
_READS = {"read_text", "read_bytes", "open"}
_OPENERS = {"io", "codecs", "Path", "pathlib.Path"}   # `io.open(p)`, `Path.read_text(p)`
_SEE_THROUGH = {"resolve", "absolute"}           # `p.resolve()` names p


def _leaves(n):
    if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
        return _leaves(n.left) + _leaves(n.right)
    if isinstance(n, ast.Call):
        f = n.func
        name = getattr(f, "id", None) or getattr(f, "attr", None)
        if name == "Path" or (name == "join" and isinstance(f, ast.Attribute)
                              and ast.unparse(f.value) == "os.path"):
            return [x for a in n.args for x in _leaves(a)]
        if name in ("str", "fspath") and n.args:
            return _leaves(n.args[0])
        if isinstance(f, ast.Attribute) and f.attr in _SEE_THROUGH and not n.args:
            return _leaves(f.value)
        if isinstance(f, ast.Attribute) and f.attr == "joinpath":
            return _leaves(f.value) + [x for a in n.args for x in _leaves(a)]
    if isinstance(n, ast.Attribute) and n.attr == "parent":
        return [ast.Name(id=f"{ast.unparse(n.value)}.parent")]
    return [n]


def _is_dir(expr, dirs, files) -> bool:
    """`expr` names review-close's directory."""
    leaves = _leaves(expr)
    last = leaves[-1]
    if isinstance(last, ast.Name):
        if last.id in dirs:
            return True
        if last.id.endswith(".parent") and last.id[:-len(".parent")] in files:
            return True
    return isinstance(last, ast.Constant) and isinstance(last.value, str) \
        and last.value.rstrip("/").split("/")[-1] == "review-close"


def names_review_close(expr, names=frozenset(), dirs=frozenset()) -> bool:
    """`names` are bound to the file or its path string, `dirs` to review-close's
    directory, so `REPO / _SKILL` and `rc / "SKILL.md"` both count."""
    leaves = _leaves(expr)
    if any(isinstance(x, ast.Name) and x.id in names for x in leaves):
        return True
    vals = [x.value if isinstance(x, ast.Constant) and isinstance(x.value, str) else None
            for x in leaves]
    if any(v and re.fullmatch(r"\S*review-close/SKILL\.md", v) for v in vals):
        return True
    return any(vals[i] == "SKILL.md" and _is_dir(leaves[i - 1], dirs, names)
               for i in range(1, len(leaves)))


def _bindings(tree):
    """Names bound to review-close's file (or path string) and to its directory. One
    breadth-first pass: module-level bindings come before function bodies."""
    files: set[str] = set()
    dirs: set[str] = set()
    for st in ast.walk(tree):
        if not (isinstance(st, (ast.Assign, ast.AnnAssign)) and st.value is not None):
            continue
        targets = st.targets if isinstance(st, ast.Assign) else [st.target]
        ids = {t.id for t in targets if isinstance(t, ast.Name)}
        if names_review_close(st.value, frozenset(files), frozenset(dirs)):
            files |= ids
        elif _is_dir(st.value, dirs, files):
            dirs |= ids
    return files, dirs


def _bound(tree) -> set[str]:
    return _bindings(tree)[0]


def _read_target(n):
    """The path a call reads, or None when it is not a read."""
    f = n.func
    if isinstance(f, ast.Attribute) and f.attr in _READS:
        if ast.unparse(f.value) in _OPENERS:
            return n.args[0] if n.args else None
        return f.value
    if isinstance(f, ast.Name) and f.id == "open":
        if n.args:
            return n.args[0]
        return next((k.value for k in n.keywords if k.arg == "file"), None)
    return None


def raw_reads(src: str) -> list[int]:
    """Line numbers of each read of review-close's `SKILL.md` that bypasses the helper."""
    tree = ast.parse(src)
    files, dirs = _bindings(tree)
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        target = _read_target(n)
        if target is not None and names_review_close(target, frozenset(files), frozenset(dirs)):
            out.append(n.lineno)
    return sorted(out)


def discarded_splices(src: str) -> list[int]:
    """Lines where a `text_of(...)` result is thrown away: a bare expression statement. A
    discarded splice beside a raw read is how a reader looks repointed and is not (round 2,
    lens A: one kept the step-file evidence green and the pin's count right)."""
    return sorted(n.lineno for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                  and (getattr(n.value.func, "id", None) == "text_of"
                       or getattr(n.value.func, "attr", None) == "text_of"))


def test_no_reader_throws_a_splice_away():
    bad = {rel: lines for rel, text in _readers().items() if (lines := discarded_splices(text))}
    assert not bad, f"a `text_of(...)` whose result is discarded: {bad}"


@pytest.mark.parametrize("src,lines", [
    ("text_of(RC)\nt = _read(RC)\n", [1]),
    ("RT.text_of(p)\n", [1]),
    ("t = text_of(RC)\n", []),
    ("f(text_of(RC))\n", []),
])
def test_a_discarded_splice_is_seen(src, lines):
    assert discarded_splices(src) == lines


# Each reader that may read review-close's `SKILL.md` raw: how many reads, and why. A count,
# not a bare file, so a reverted read inside an allowlisted module still goes red.
RAW_READ_ALLOWED = {
    "tests/test_reader_census.py": (
        2, "class E: the census measures the core, in fixture trees built from it"),
    "tests/test_review_close_runner_reads.py": (
        4, "the core alone on purpose: the identity test (the core and the arm it splices), a "
           "marker that must stay in the core, and the moved copy's core size"),
    "tests/test_close_arms.py": (
        6, "class E: a stub and its marker must sit in the core, not arrive by the splice, and "
           "`begin`'s arm list must be the core's own line; Phase 390: 4a-fix's item 6 must be "
           "in the core and not the arm, and the pre-flight line is the core's own; Phase 393: "
           "the frontmatter's argument hint, and the flag sections hold only their stubs"),
    "tests/test_skill_runner_text.py": (
        1, "the plant's marker must sit in the copy's core, not arrive by the splice"),
    "tests/test_review_close_reference_pins.py": (
        1, "the core alone on purpose: Phase 444's step-file test asserts the spliced runner cites "
           "a heading the core alone does not"),
    "tools/phase282_round_survivors.py": (1, "Phase 282's battery record, measured the core then"),
    "tools/phase294_figures.py": (2, "Phase 294's published figures, measured the core then"),
    "tools/phase295_precondition_b.py": (3, "Phase 295's transform-4 measurement of the core"),
    "tools/phase295_split.py": (1, "Phase 295's split tool, which rewrites the core itself"),
    "tools/phase298_lock_rates.py": (1, "Phase 298's lock-rate measurement of the core"),
    "tools/phase406_move.py": (1, "Phase 406's move tool, which rewrites the core itself"),
    "tools/phase411_move.py": (1, "Phase 411's move tool, which rewrites the core itself"),
    "tools/phase415_move.py": (1, "Phase 415's move tool, which rewrites the core itself"),
    "tools/phase416_move.py": (1, "Phase 416's move tool, which rewrites the core itself"),
    "tools/phase418_move.py": (1, "Phase 418's move tool, which rewrites the core itself"),
    "tools/phase419_move.py": (1, "Phase 419's move tool, which rewrites the core itself"),
    "tools/phase429_move.py": (1, "Phase 429's move tool, which rewrites the core itself"),
    "tools/phase430_move.py": (1, "Phase 430's move tool, which rewrites the core itself"),
}

# Author batteries quote the shapes they mutate; they are not readers.
_BATTERY = re.compile(r"(_mutations\d*\.py|mutation_battery\.py)$")


def _readers():
    files = sorted(REPO_ROOT.glob("tests/*.py")) + sorted(
        p for p in REPO_ROOT.glob("tools/*.py") if not _BATTERY.search(p.name))
    return {p.relative_to(REPO_ROOT).as_posix(): p.read_text(encoding="utf-8") for p in files}


def _offenders(readers, allowed):
    out = {rel: ([], n) for rel, (n, _why) in allowed.items() if rel not in readers}
    for rel, text in readers.items():
        lines = raw_reads(text)
        want = allowed.get(rel, (0, ""))[0]
        if len(lines) != want:
            out[rel] = (lines, want)
    return out


def _without_stripped(allowed):
    """The public mirror strips tools/, so its allowlisted readers are absent there by design."""
    if (REPO_ROOT / "tools").is_dir():
        return allowed
    return {k: v for k, v in allowed.items() if not k.startswith("tools/")}


def _skip_without_tools():
    if not (REPO_ROOT / "tools").is_dir():
        pytest.skip("tools/ is mirror-excluded; this runs in the source repo")


def test_no_reader_reads_review_close_around_the_helper():
    offenders = _offenders(_readers(), _without_stripped(RAW_READ_ALLOWED))
    assert not offenders, (
        "these read review-close's SKILL.md alone, which goes blind or red when a step moves "
        "into steps/ — read through tests/skill_runner_text.py's text_of, or allowlist with a "
        f"count and a reason ({{file: (lines found, count allowed)}}): {offenders}")


def test_the_guard_reads_tools_as_well_as_tests():
    _skip_without_tools()
    readers = _readers()
    assert "tools/phase294_figures.py" in readers
    assert "tests/test_review_close_clone_sync.py" in readers
    # The helper modules, not only `test_*.py` (round 2, lens B: narrowing to `test_*`
    # survived, and with it `_section_call_sites.py` left the guard).
    for helper in ("tests/_section_call_sites.py", "tests/_heredoc_population.py",
                   "tests/skill_runner_text.py"):
        assert helper in readers, helper
    assert not any(_BATTERY.search(r) for r in readers if r.startswith("tools/"))


@pytest.mark.parametrize("src", [
    'SKILL = REPO / "core" / "skills" / "review-close" / "SKILL.md"\nt = SKILL.read_text()\n',
    'RC = REPO / "core/skills/review-close/SKILL.md"\nt = RC.read_text(encoding="utf-8")\n',
    't = (REPO / "core/skills/review-close/SKILL.md").read_text()\n',
    't = (SKILLS_DIR / "review-close" / "SKILL.md").read_text()\n',
    't = Path("core/skills/review-close/SKILL.md").read_bytes()\n',
    't = pathlib.Path("core/skills/review-close/SKILL.md").read_text()\n',
    'def f():\n    p = ROOT / "review-close" / "SKILL.md"\n    return open(p).read()\n',
    'def f():\n    with (S / "review-close" / "SKILL.md").open() as h:\n        return h.read()\n',
    '_SKILL = "core/skills/review-close/SKILL.md"\nt = (REPO_ROOT / _SKILL).read_text()\n',
    '_SKILL = "core/skills/review-close/SKILL.md"\nRC = ROOT / _SKILL\nt = RC.read_text()\n',
    # Round 1 (both lenses): the directory-bound spelling, and the see-through forms.
    'rc = SKILLS / "review-close"\nt = (rc / "SKILL.md").read_text()\n',
    't = ROOT.joinpath("core", "skills", "review-close", "SKILL.md").read_text()\n',
    't = open(os.path.join(R, "core/skills/review-close/SKILL.md")).read()\n',
    't = Path(REPO, "core/skills/review-close/SKILL.md").read_text()\n',
    'RC = REPO / "core/skills/review-close/SKILL.md"\nt = RC.resolve().read_text()\n',
    'RC = REPO / "core/skills/review-close/SKILL.md"\nt = open(str(RC)).read()\n',
    'RC = REPO / "core/skills/review-close/SKILL.md"\nt = (RC.parent / "SKILL.md").read_text()\n',
    'RC = REPO / "core/skills/review-close/SKILL.md"\nt = io.open(RC).read()\n',
    'RC = REPO / "core/skills/review-close/SKILL.md"\nt = Path.read_text(RC)\n',
    'RC = REPO / "core/skills/review-close/SKILL.md"\nt = pathlib.Path.read_text(RC)\n',
    'RC = REPO / "core/skills/review-close/SKILL.md"\nt = open(file=RC).read()\n',
    't = (REPO / "core/skills/a/review-close/SKILL.md").read_text()\n',
])
def test_the_guard_sees_each_spelling(src):
    assert raw_reads(src), src


@pytest.mark.parametrize("src", [
    'SKILL = REPO / "core/skills/review-close/SKILL.md"\nt = text_of(SKILL)\n',
    't = skill_text(REPO / "core/skills/review-close")\n',
    'SKILL = REPO / "core/skills/review-close/SKILL.md"\nshutil.copy(SKILL, dest)\n',
    't = (REPO / "core/skills/review-close/REFERENCE.md").read_text()\n',
    't = (REPO / "core/skills/claim-task/SKILL.md").read_text()\n',
    'rc = SKILLS / "review-close"\nt = (rc / "REFERENCE.md").read_text()\n',
    'rc = SKILLS / "review-close"\nt = text_of(rc / "SKILL.md")\n',
    'nd = SKILLS / "not-review-close"\nt = (nd / "SKILL.md").read_text()\n',
    '"""Reads `core/skills/review-close/SKILL.md` and says so."""\n',
])
def test_the_guard_leaves_a_helper_read_alone(src):
    assert not raw_reads(src), src


def test_the_guard_functions_judge_synthetic_readers():
    bad = {"tests/x.py": 'RC = R / "review-close" / "SKILL.md"\nRC.read_text()\n'}
    assert _offenders(bad, {}) == {"tests/x.py": ([2], 0)}
    assert _offenders(bad, {"tests/x.py": (1, "why")}) == {}
    # A second raw read inside an allowlisted module is still an offender.
    two = {"tests/x.py": bad["tests/x.py"] + "RC.read_text()\n"}
    assert _offenders(two, {"tests/x.py": (1, "why")}) == {"tests/x.py": ([2, 3], 1)}
    # An allowlist entry for a file the guard no longer reads is reported too (round 2, B08).
    assert _offenders({}, {"tests/gone.py": (1, "why")}) == {"tests/gone.py": ([], 1)}
    # An allowlist entry whose reads are gone is stale, and reported.
    assert _offenders({"tests/x.py": "pass\n"}, {"tests/x.py": (1, "why")}) == {
        "tests/x.py": ([], 1)}


# ── 2b. the reads the guard cannot see stay on the helper ─────────────────

# Phase 385's sites the static guard cannot see: a read through a helper's argument, a span
# table's path, a loop over a fixed list, an f-string path (`repoint_385_sites.txt`, plus
# the call sites of a raw helper given a named constant). The author battery's two survivors
# were reverts of exactly these (S04 `_read(path)`, S05 `read` back to `read_text`). Running
# them in a moved tree closes them by execution, at ~93 s for the 220 test functions involved, which
# is a full-suite cost for one guard; so each site's FUNCTION is pinned instead: it calls
# `text_of`, and it makes exactly as many raw `read_text`/`read_bytes` calls as it did when
# repointed (some read another file as well). A new site is new code, not covered here.
# The 53 are FUNCTIONS. Since round 1 widened the static guard, it also sees a `text_of` ->
# `.read_text()` revert in 16 of them; in the other 37 only this pin does, and in all 53 only
# this pin sees a revert through a raw helper (S04's shape).
UNSEEN_SITES = {
    ("tests/_heredoc_population.py", "heredoc_containing"): 0,
    ("tests/test_adversarial_review_gate.py", "test_dropping_every_tagged_class_reproduces_the_stripped_rendering"): 0,
    ("tests/test_adversarial_review_gate.py", "test_no_guarded_file_contains_a_tag_marker_of_its_own"): 0,
    ("tests/test_adversarial_review_gate.py", "test_the_guarded_files_carry_no_nesting_the_resolver_cannot_model"): 0,
    ("tests/test_adversarial_review_gate.py", "test_the_indent_floor_is_far_from_the_shipped_files"): 0,
    ("tests/test_adversarial_review_gate.py", "test_the_tagged_population_is_both_guarded_files"): 0,
    ("tests/test_auto_build_test_decision.py", "test_review_close_does_not_call_auto_build_a_non_writer_in_any_wording"): 0,
    ("tests/test_auto_build_test_decision.py", "test_review_close_no_longer_lists_auto_build_as_a_non_writer"): 0,
    ("tests/test_auto_build_test_decision.py", "test_review_close_still_justifies_the_fourth_disposition"): 0,
    ("tests/test_commonmark_code_blocks.py", "test_step_3b_renders_as_its_two_sub_steps"): 0,
    ("tests/test_commonmark_code_blocks.py", "test_the_structure_check_sees_each_revert"): 0,
    ("tests/test_fix_in_branch_tier.py", "read"): 0,
    ("tests/test_ignored_refs.py", "_located"): 0,
    ("tests/test_ignored_refs.py", "_section"): 0,
    ("tests/test_ignored_refs.py", "test_every_site_declares_the_rule_it_runs_under"): 1,
    ("tests/test_ignored_refs.py", "test_every_span_start_anchor_is_unique"): 0,
    ("tests/test_index_writer_class.py", "test_step4c_joins_the_mkstemp_roster_rather_than_standing_apart"): 1,
    ("tests/test_pending_doc_hold.py", "_located"): 0,
    ("tests/test_pending_doc_hold.py", "test_every_span_start_anchor_is_unique"): 0,
    ("tests/test_pending_doc_hold.py", "test_the_clear_command_runs_as_written_from_a_linked_worktree"): 1,
    ("tests/test_pending_doc_integrity.py", "test_no_shipped_file_claims_step4c_deletes_by_glob"): 0,
    ("tests/test_phantom_shell_vars.py", "_skill"): 0,
    ("tests/test_phase128_path_drift.py", "_norm_skill"): 0,
    ("tests/test_phase360_close_paths.py", "_located"): 0,
    ("tests/test_phase360_close_paths.py", "test_every_span_start_anchor_is_unique"): 0,
    ("tests/test_phase379_triage_fixes.py", "test_every_orchestrator_skill_says_to_run_in_the_main_conversation"): 0,
    ("tests/test_pin_normalizer.py", "_read"): 0,
    ("tests/test_pin_normalizer.py", "_structural_mutants"): 0,
    ("tests/test_pin_normalizer.py", "test_a_structural_change_moves_the_pin"): 0,
    ("tests/test_pin_normalizer.py", "test_each_module_test_fails_on_its_subject"): 0,
    ("tests/test_pin_normalizer.py", "test_the_legal_edit_check_sees_a_real_edit"): 0,
    ("tests/test_pin_normalizer.py", "test_the_phase_328_measurements_move_the_pin"): 0,
    ("tests/test_review_close_smoke_decided_text.py", "_located"): 0,
    ("tests/test_review_close_smoke_decided_text.py", "test_every_span_start_anchor_is_unique"): 0,
    ("tests/test_review_close_smoke_gate.py", "test_schema_states_the_user_ops_timing_canonically"): 1,
    ("tests/test_review_close_smoke_held_and_tip.py", "_extract_recorder"): 0,
    ("tests/test_reviewer_scratch_dirs.py", "_recheck_script"): 0,
    ("tests/test_reviewer_scratch_dirs.py", "_step_2b_script"): 0,
    ("tests/test_reviewer_scratch_dirs.py", "test_4a_fix_placement_makes_a_scratch_directory"): 0,
    ("tests/test_reviewer_scratch_dirs.py", "test_a_softened_add_is_caught"): 1,  # Phase 421: the raw read is review_pins.py, not the skill
    ("tests/test_reviewer_scratch_dirs.py", "test_a_softening_is_caught"): 0,
    ("tests/test_reviewer_scratch_dirs.py", "test_every_kept_fixed_name_sits_in_its_stated_context"): 0,
    ("tests/test_reviewer_scratch_dirs.py", "test_step_2b_placement_makes_a_scratch_directory"): 0,
    ("tests/test_reviewer_scratch_dirs.py", "test_step_2b_placement_says_the_scratch_directory_is_per_agent"): 0,
    ("tests/test_reviewer_scratch_dirs.py", "test_step_2b_prompt_names_the_agents_own_scratch_directory"): 0,
    # Phase 425 (`Q-629`): the stage-block test became this one; the notes block's test runs the
    # resolver now and reads no skill text, so it left the census.
    ("tests/test_reviewer_scratch_dirs.py", "test_step_4a_writes_no_stage_extracts"): 0,
    ("tests/test_reviewer_scratch_dirs.py", "test_the_security_twin_gets_its_own_scratch_directory"): 0,
    ("tests/test_skill_positional_substitution.py", "_fenced_block_containing"): 0,
    ("tests/test_squash_provenance.py", "_located"): 0,
    ("tests/test_squash_provenance.py", "test_every_span_start_anchor_is_unique"): 0,
    ("tests/test_step4c_transaction_claims.py", "test_every_primary_worktree_fanout_sends_the_containment_rule"): 0,
    ("tests/test_zsh_path_clobber_guard.py", "test_step_2d_routes_the_silent_read_away_from_missing"): 0,
}


def site_reads(src: str, fn: str) -> tuple[int, int] | None:
    """(`text_of` calls, raw reads) in the module-level function `fn`, or None when it is
    gone. A raw read is any call `_read_target` calls a read, `open` included (round 1,
    lens B: `open(p).read()` beside a dead `text_of(p)` passed the first version)."""
    for node in ast.parse(src).body:
        if isinstance(node, ast.FunctionDef) and node.name == fn:
            calls = [c for c in ast.walk(node) if isinstance(c, ast.Call)]
            helper = sum(1 for c in calls if getattr(c.func, "id", None) == "text_of")
            raw = sum(1 for c in calls if _read_target(c) is not None)
            return helper, raw
    return None


def _text_of_is_the_helper(src: str) -> bool:
    """The module imports `text_of` from `skill_runner_text` and defines none of its own
    (round 1, lens B: a module-local `def text_of` that reads raw de-spliced every site in
    its module while every count stayed right)."""
    tree = ast.parse(src)
    imported = any(isinstance(n, ast.ImportFrom) and n.module == "skill_runner_text"
                   and any(a.name == "text_of" and a.asname is None for a in n.names)
                   for n in tree.body)
    # Any other binding of the name, anywhere (round 2, lens B): another import, a store at
    # any depth (assignment, loop target, `with ... as`), a function or parameter so named.
    other = 0
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            other += sum(1 for a in n.names if (a.asname or a.name.split(".")[0]) == "text_of")
        elif isinstance(n, ast.Name) and n.id == "text_of" and isinstance(n.ctx, ast.Store):
            other += 1
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and n.name == "text_of":
            other += 1
        elif isinstance(n, ast.arg) and n.arg == "text_of":
            other += 1
    return imported and other == 1   # the one import above


def _site_problems(sources, sites):
    bad = []
    for rel in sorted({r for r, _ in sites}):
        if rel in sources and not _text_of_is_the_helper(sources[rel]):
            bad.append(f"{rel}: `text_of` is not tests/skill_runner_text.py's")
    for (rel, fn), raw_allowed in sorted(sites.items()):
        got = site_reads(sources[rel], fn) if rel in sources else None
        if got is None:
            bad.append(f"{rel}::{fn} is gone; drop it here or say where its read went")
        elif got[0] < 1 or got[1] != raw_allowed:
            bad.append(f"{rel}::{fn}: text_of x{got[0]}, raw reads {got[1]} (want >=1, {raw_allowed})")
    return bad


def test_each_unseen_site_still_reads_through_the_helper():
    sources = {rel: (REPO_ROOT / rel).read_text(encoding="utf-8") for rel, _ in UNSEEN_SITES}
    bad = _site_problems(sources, UNSEEN_SITES)
    assert not bad, "\n".join(bad)


def test_the_site_pin_judges_synthetic_sites():
    site = {("t.py", "f"): 0}
    imp = "from skill_runner_text import text_of\n"
    assert _site_problems({"t.py": imp + "def f(p):\n    return text_of(p)\n"}, site) == []
    # Round 1, lens B: `open` beside a dead helper call, and a module-local `text_of`.
    assert _site_problems({"t.py": imp + "def f(p):\n    text_of(p)\n    return open(p).read()\n"}, site)
    assert _site_problems({"t.py": imp + "def text_of(p):\n    return p.read_text()\n"
                                         "def f(p):\n    return text_of(p)\n"}, site)
    assert _site_problems({"t.py": "def f(p):\n    return text_of(p)\n"}, site)
    # Round 2, lens B: an aliased import, a second import, and rebindings at any depth.
    for bad in ("from skill_runner_text import text_of as text_of\n",
                imp + "from other import text_of\n",
                imp + "if True:\n    text_of = str\n",
                imp + "for text_of in []:\n    pass\n",
                imp + "def g(text_of=str):\n    return text_of\n",
                imp + "def g():\n    text_of = str\n"):
        assert _site_problems({"t.py": bad + "def f(p):\n    return text_of(p)\n"}, site), bad
    # S04's revert: the helper call is gone.
    assert _site_problems({"t.py": imp + "def f(p):\n    return _read(p)\n"}, site)
    # A raw read added beside the helper.
    assert _site_problems({"t.py": imp + "def f(p):\n    return text_of(p) + p.read_text()\n"}, site)
    # A recorded raw read of another file is allowed, and only that many.
    two = {("t.py", "f"): 1}
    assert _site_problems({"t.py": imp + "def f(p, q):\n    return text_of(p) + q.read_text()\n"}, two) == []
    assert _site_problems({"t.py": imp + "def f(p, q):\n    return text_of(p)\n"}, two)
    assert _site_problems({}, site)


@pytest.mark.parametrize("src,ok", [
    ("def f(p):\n    return text_of(p)\n", True),
    ("def f(p):\n    return p.read_text()\n", False),          # S05's revert
    ("def f(p):\n    return _read(p)\n", False),               # S04's revert
    ("def f(p):\n    a = text_of(p)\n    return a + q.read_text()\n", False),
])
def test_the_site_pin_judges_a_revert(src, ok):
    got = site_reads(src, "f")
    assert (got[0] >= 1 and got[1] == 0) is ok


# ── 3. a move does not move a census ───────────────────────────────────────

# Phase 385's moved-tree run found per-file censuses that pin WHICH file carries a match (an
# exact population, an allowlist keyed by file, a per-file count). They read every file, so
# they keep coverage when a step moves, but the match changes key and they go red on a move
# that changed nothing a runner reads, so a move phase would have had to edit them. Each now
# folds step files into its skill's `SKILL.md` (`fold_steps`/`runner_key`). The fold is inert
# while no step file exists, so this section is what holds it: every census below runs
# against a copy of the tree whose review-close sections are all moved behind arm markers,
# loaded fresh from its own file so its own import-time code is what runs, and must stay
# green; with the fold switched off it must go red, which shows the move reached it.
_CENSUSES = [
    ("test_fix_in_branch_tier", "test_the_ledger_is_named_only_where_it_is_retired_or_still_read", {}),
    ("test_index_writer_class", "test_the_index_writer_population_is_exactly_the_five_named_here", {}),
    # Review-close's own `safe_dump` (Step 3c's recorder) left it for `smoke_record.py` in
    # Phase 387 (`Q-409` P3), so the per-writer kwargs census has no review-close subject; the
    # exact-population census above still runs over the moved tree and holds it at none.
    ("test_index_writer_class", "test_the_index_naming_universe_is_exactly_the_partition", {}),
    ("test_phase128_path_drift", "test_every_skill_naming_the_log_also_names_the_real_path", {}),
    ("test_phase128_path_drift", "test_the_population_is_exactly_the_declared_set", {}),
    ("test_review_close_diff_basis", "test_no_unpinned_two_dot_git_diff_anywhere_in_the_shipped_tree", {}),
    ("test_mirror_leak_gate", "test_the_carriers_are_scanned_and_not_merely_listed", {"monkeypatch": None}),
    ("test_convention_gate_role", "test_exactly_two_pins_in_the_tree_carry_the_marker", {}),
    ("test_convention_gate_role", "test_the_security_twin_is_governed_by_its_own_role", {}),
    # The resolver fixture: it copies the runner files, so a moved pin is still resolved.
    ("test_convention_gate_role", "test_a_consumer_override_moves_the_convention_pin_and_only_it",
     {"tmp_path": None}),
    ("test_convention_gate_role", "test_both_gates_resolve_to_sonnet_by_default", {"tmp_path": None}),
    ("test_reviewer_scratch_dirs", "test_every_kept_fixed_name_sits_in_its_stated_context", {}),
    ("test_reviewer_scratch_dirs", "test_no_runner_writes_a_fixed_name_under_the_shared_temp_root", {}),
    ("test_zsh_path_clobber_guard", "test_the_site_census_is_exact", {}),
    # Citation registries keyed by `file:line`: the splice is the unsplit file line for line.
    ("test_intra_repo_citations", "test_every_discovered_citation_is_registered", {}),
    ("test_intra_repo_citations", "test_no_registered_citation_has_gone_stale", {}),
    ("test_phase_log_citation_targets", "test_no_new_citation_points_past_the_end_of_its_file", {}),
    # Per file by design (each file renders on its own); its read-is-real sentinel is per skill.
    ("test_commonmark_code_blocks", "test_the_population_is_the_tracked_markdown", {}),
    # Absence scans over the folded zsh population (lens B, round 1: a read reverted to raw
    # left them green over a moved copy, because blind and clean look the same).
    ("test_zsh_path_clobber_guard", "test_no_site_revokes_the_rule_while_appearing_to_state_it", {}),
    ("test_zsh_path_clobber_guard", "test_the_remedy_is_stated_in_full_at_every_site", {}),
    # The section call-site census, which resolves review-close's sections through `text_of`.
    ("_section_call_sites", "audit", {}),
]

# The censuses whose read is NOT `text_of`: they read each file on its own and key it with
# `runner_key`, or take the step files from `step_files`. The splice-only control below does
# not apply to them; the fold-off control does.
_NOT_SPLICED = {
    ("test_mirror_leak_gate", "test_the_carriers_are_scanned_and_not_merely_listed"),
    ("test_reviewer_scratch_dirs", "test_no_runner_writes_a_fixed_name_under_the_shared_temp_root"),
    ("test_commonmark_code_blocks", "test_the_population_is_the_tracked_markdown"),
}


def _move_all(skill_dir: Path) -> int:
    """Every section body from the first `## Step` on goes to `steps/sNNN.md` behind a
    marker, as `tools/runner_core_split/probe_move.py --marker --all` does. Returns how many.

    It must run on a tree where steps have already moved: `steps/` may exist, and a marker
    stays in `SKILL.md`, since a step file's own marker is not spliced and moving it would
    lose that step's text. A body that holds one (an arm cut from inside a step, P5 on) moves
    as the runs between its markers, each to its own file, so the step's text still leaves
    the core (Phase 397: moved whole or not at all, Step 3b stayed, and the population
    census's sentinel with it)."""
    from _prose_guard_helpers import _fence_state
    sk = skill_dir / "SKILL.md"
    lines = sk.read_text(encoding="utf-8").splitlines(keepends=True)
    fenced = dict(_fence_state([ln.rstrip("\n") for ln in lines]))
    heads = [i for i, ln in enumerate(lines) if not fenced[i] and re.match(r"#{2,4} ", ln)]
    first = next(i for i in heads if lines[i].startswith("## Step"))
    bounds = [i for i in heads if i >= first] + [len(lines)]
    out, moved = lines[:first], 0
    (skill_dir / "steps").mkdir(exist_ok=True)
    for n, (h, nxt) in enumerate(zip(bounds, bounds[1:])):
        out.append(lines[h])
        runs, run = [], []
        for ln in lines[h + 1:nxt]:
            if RT._MARKER.match(ln.rstrip("\n")):
                runs += [run, [ln]]
                run = []
            else:
                run.append(ln)
        for k, run in enumerate(runs + [run]):
            if not "".join(run).strip() or RT._MARKER.match(run[0].rstrip("\n")):
                out += run
                continue
            name = f"s{n:03d}" if k == 0 else f"s{n:03d}-{k}"
            (skill_dir / "steps" / f"{name}.md").write_text("".join(run), encoding="utf-8")
            out.append(f"<!-- sysop:arm={name} -->\n")
            moved += 1
    sk.write_text("".join(out), encoding="utf-8")
    return moved


def _unmoved_step_text(skill_dir: Path) -> list[str]:
    """Lines from the first `## Step` on that are neither a heading, a marker nor blank: what
    `_move_all` left in the core. Phase 397's round (lens B) kept a body's first run only, and
    6,498 bytes of Step 3b stayed while every census control stayed green."""
    from _prose_guard_helpers import _fence_state
    lines = (skill_dir / "SKILL.md").read_text(encoding="utf-8").split("\n")
    fenced = dict(_fence_state(lines))
    first = next(i for i, ln in enumerate(lines) if ln.startswith("## Step") and not fenced[i])
    return [ln for i, ln in enumerate(lines[first:], first)
            if ln.strip() and not RT._MARKER.match(ln)
            and (fenced[i] or not re.match(r"#{2,4} ", ln))]


def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t.invalid", *args],
                          cwd=cwd, env=env, check=True, capture_output=True)


def test_move_all_keeps_a_step_that_already_moved(tmp_path):
    """The fixture runs on whatever the tree holds, and P3 on will hold real steps: a body
    already behind a marker stays, an existing `steps/` is no error, and the splice is
    unchanged by the second move (the final probe run of Phase 385 found the first draft
    raising `FileExistsError` on a tree with one step file)."""
    d = tmp_path / "review-close"
    d.mkdir()
    # From the flattened runner text, so the test means the same on a tree already split.
    lines = RT.skill_text(SKILLS / "review-close").split("\n")
    h = lines.index("### 2b. Prevention Convention Check")
    nxt = next(i for i in range(h + 1, len(lines)) if lines[i].startswith(("## ", "### ")))
    (d / "steps").mkdir(exist_ok=True)
    (d / "steps" / "early.md").write_text("\n".join(lines[h + 1:nxt]) + "\n", encoding="utf-8")
    (d / "SKILL.md").write_text("\n".join(lines[:h + 1] + ["<!-- sysop:arm=early -->"] + lines[nxt:]),
                                encoding="utf-8")
    before = RT.skill_text(d)
    assert _move_all(d) > 20
    assert RT.skill_text(d) == before
    assert "<!-- sysop:arm=early -->" in (d / "SKILL.md").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def moved_root(tmp_path_factory):
    """Every tracked file as the working tree has it, review-close moved, committed in a
    repository of its own so a `git ls-files` population sees the step files."""
    root = tmp_path_factory.mktemp("moved") / "repo"
    root.mkdir()
    tracked = _git(REPO_ROOT, "ls-files", "-z").stdout.decode("utf-8").split("\0")
    for rel in filter(None, tracked):
        src, dst = REPO_ROOT / rel, root / rel
        if src.is_symlink() or src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst, follow_symlinks=False)
    rc = root / "core" / "skills" / "review-close"
    _move_all(rc)   # moves nothing on a tree that is already split, which is fine
    assert RT.skill_text(rc) == RT.skill_text(SKILLS / "review-close")
    core = (rc / "SKILL.md").read_text(encoding="utf-8")
    assert len(core) * 4 < len(RT.skill_text(rc)), "the copy's review-close is not moved"
    assert not _unmoved_step_text(rc), "text under a `## Step` heading stayed in the copy's core"
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "moved", "--no-verify")
    return root


def _fresh(name: str, root: Path, monkeypatch):
    """The copy's own `tests/<name>.py` executed as a new module, cwd at `root`, so a root
    derived from `__file__` or from a relative path is the copy's (`_section_call_sites.audit`
    excludes itself by `__file__`). Any module-level path still under the live repo is then
    re-pointed at its twin in `root`. The copy was taken from the working tree, so a mutated
    census is the census that runs."""
    spec = importlib.util.spec_from_file_location(f"_moved_{name}", root / "tests" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.chdir(root)
    monkeypatch.setitem(sys.modules, spec.name, mod)   # a dataclass looks its module up there
    # A census may put its own directory on `sys.path` at import (`_section_call_sites` does).
    # From the copy, that would make every later import in this worker load the copy's
    # modules, which turned 33 of Phase 384's plant tests green-over-a-plant in one run.
    monkeypatch.setattr(sys, "path", list(sys.path))
    before = set(sys.modules)
    spec.loader.exec_module(mod)
    copy = str(root.resolve()) + os.sep
    for name_ in set(sys.modules) - before:
        f = getattr(sys.modules[name_], "__file__", None) or ""
        if os.path.realpath(f).startswith(copy) and name_ != spec.name:
            del sys.modules[name_]

    def repoint(val):
        if isinstance(val, Path):
            try:
                rel = val.relative_to(REPO_ROOT)
            except ValueError:
                return val
            return root / rel
        if type(val) in (list, tuple, set, frozenset):   # not a namedtuple (ParameterSet)
            return type(val)(repoint(v) for v in val)
        if type(val) is dict:
            return {repoint(k): repoint(v) for k, v in val.items()}
        return val

    for k, v in list(vars(mod).items()):
        if not k.startswith("__") and isinstance(v, (Path, list, tuple, set, frozenset, dict)):
            setattr(mod, k, repoint(v))
    return mod


def test_the_populations_are_the_ones_the_record_states():
    """Round 2, lens B: emptying any of these lists left everything green, because pytest
    skips an empty parameter set. A change to a count is a decision, made with the record."""
    # 53 until Phase 425 (`Q-629`): the notes stage block's test runs the resolver, not skill text.
    assert len(UNSEEN_SITES) == 52
    # 22/19/20 until Phase 387 removed the review-close kwargs census, which lost its subject.
    assert len(_CENSUSES) == 21 and len({m for m, _, _ in _CENSUSES}) == 12
    assert len(_SPLICED) == 18 and len(_FOLDED) == 19
    assert _NOT_SPLICED <= {(m, f) for m, f, _ in _CENSUSES}
    assert _FOLD_IRRELEVANT <= {(m, f) for m, f, _ in _CENSUSES}
    assert ("tests/test_fix_in_branch_tier.py", "read") in UNSEEN_SITES            # S05
    assert ("tests/test_reviewer_scratch_dirs.py", "test_a_softening_is_caught") in UNSEEN_SITES
    assert ("test_review_close_diff_basis",
            "test_no_unpinned_two_dot_git_diff_anywhere_in_the_shipped_tree") in {
        (m, f) for m, f, _ in _SPLICED}


def test_a_dangling_marker_is_loud_in_the_index_census(tmp_path, monkeypatch):
    """Round 1 made the index-writer census re-raise a `SKILL.md` it cannot splice; round 2,
    lens B found nothing planted one."""
    import test_index_writer_class as W
    d = _skill(tmp_path, {"SKILL.md": "a\n<!-- sysop:arm=gone -->\n"})
    monkeypatch.setattr(W, "_shipped_files", lambda: [d / "SKILL.md"])
    with pytest.raises(FileNotFoundError):
        W._dump_sites()
    with pytest.raises(FileNotFoundError):
        W._index_naming_files()


def test_a_fresh_census_leaves_no_trace_in_the_worker(moved_root, monkeypatch):
    """Loading a census from the copy must not leave the copy on `sys.path` or in
    `sys.modules`: `_section_call_sites` inserts its own directory at import, and the first
    round-1 fix let that turn 33 of Phase 384's plant tests green over their plants."""
    path_before = list(sys.path)
    copy = str(moved_root.resolve()) + os.sep
    with monkeypatch.context() as m:
        # Not yet imported, so the census's own import of it resolves against the copy.
        m.delitem(sys.modules, "_prose_guard_helpers", raising=False)
        _fresh("_section_call_sites", moved_root, m)
        leaked = [n for n, mod in list(sys.modules.items()) if not n.startswith("_moved_")
                  and os.path.realpath(getattr(mod, "__file__", None) or "").startswith(copy)]
    assert sys.path == path_before
    assert not leaked, leaked


def _call(mod, fn, kwargs, monkeypatch, tmp_path):
    given = {"monkeypatch": monkeypatch, "tmp_path": tmp_path}
    out = getattr(mod, fn)(**{k: given.get(k, v) if v is None else v for k, v in kwargs.items()})
    if fn == "audit":   # `_section_call_sites.audit` returns rows; a row with a problem is a red
        bad = [f"{r.file}:{r.line} {r.problem}" for r in out if r.problem]
        assert not bad, bad


class _Reads(list):
    """The copy's step files a census opened; `.raw_core`, its opens of the copy's
    `review-close/SKILL.md` that did not come through the splice."""

    def __init__(self):
        super().__init__()
        self.raw_core: list[str] = []


def _via_splice_or_copy() -> bool:
    """The open in progress comes from `skill_runner_text` (the splice reading the core) or
    from `shutil` (a fixture copying the runner files)."""
    f = sys._getframe(2)
    while f is not None:
        name = os.path.basename(f.f_code.co_filename)
        if name == "skill_runner_text.py" or f.f_code.co_filename.endswith(
                os.sep + "shutil.py"):
            return True
        f = f.f_back
    return False


def _steps_read(root: Path, monkeypatch) -> "_Reads":
    """Record, from here on, every file opened under the copy's `review-close/steps/`, and
    every open of the copy's core that did not come through the splice.

    Opening a step file is not enough on its own (round 2, lens A): a census that keeps one
    `text_of` call and asserts on a raw read of the core opens the steps and stays blind. So a
    census whose read is the splice must also open the core only through it. The step-file
    evidence is per CALL: one read that opens a step satisfies it for every other read in
    the call, which is why the raw-core half exists (round 2, lens B: a citation check's
    inert target-side read could revert unseen because its citing side opened the steps).

    A census that keeps its fold but reads the folded `SKILL.md` raw reads the core alone;
    an absence-shaped census then stays green, because blind and clean look the same over a
    tree with no defect (lens B, round 1: 8 such reverts survived the first version of this
    section). Whether it opened the step text is what tells them apart."""
    import builtins
    rc = (root / "core" / "skills" / "review-close").resolve()
    steps = str(rc / "steps") + os.sep
    core = str(rc / "SKILL.md")
    seen = _Reads()

    def note(f):
        try:
            real = os.path.realpath(os.fspath(f))
        except TypeError:   # a file descriptor
            return
        if real.startswith(steps):
            seen.append(real)
        elif real == core and not _via_splice_or_copy():
            seen.raw_core.append(real)

    real_open, real_path_open = builtins.open, Path.open

    def open_(file, *a, **k):
        note(file)
        return real_open(file, *a, **k)

    def path_open(self, *a, **k):
        note(self)
        return real_path_open(self, *a, **k)

    monkeypatch.setattr(builtins, "open", open_)
    monkeypatch.setattr(Path, "open", path_open)
    return seen


@pytest.mark.parametrize("name,fn,kwargs", _CENSUSES, ids=[f"{m}::{f}" for m, f, _ in _CENSUSES])
def test_a_census_does_not_change_when_review_close_moves(moved_root, monkeypatch, tmp_path,
                                                          name, fn, kwargs):
    """Green over the moved copy, AND it read the step text: green alone is what a blind
    absence scan also gives."""
    _skip_if_mirror_excluded(name)
    _census_holds(_fresh(name, moved_root, monkeypatch), fn, kwargs, moved_root, monkeypatch,
                  tmp_path, per_file=(name, fn) in _NOT_SPLICED)


# The census modules the public mirror strips. Named, not inferred from a missing file: a
# census module renamed or deleted in the source repo must go red, not skip as "excluded".
_MIRROR_STRIPPED_CENSUSES = frozenset({"test_mirror_leak_gate"})
# Census modules that ship but whose SUBJECT the mirror strips (Phase 432: `PHASE_LOG.md`,
# `Q-716`). The harness calls the census function directly, so the module's own autouse
# skip never runs for it; without this the census raised FileNotFoundError in the
# sterilized tree (Phase 432's step 4, three parametrizations). Named per module, same
# reason as above: a renamed subject in the source repo must go red, not skip.
_MIRROR_STRIPPED_SUBJECTS = {"test_phase_log_citation_targets": "PHASE_LOG.md"}


def _skip_if_mirror_excluded(name):
    # Absent from the moved copy in the mirror, so its census cannot be imported there.
    if name in _MIRROR_STRIPPED_CENSUSES and not (REPO_ROOT / "tools").is_dir():
        pytest.skip(f"tests/{name}.py is mirror-excluded and absent on this tree")
    subject = _MIRROR_STRIPPED_SUBJECTS.get(name)
    if subject and not (REPO_ROOT / "tools").is_dir() and not (REPO_ROOT / subject).is_file():
        pytest.skip(f"{subject}, the subject of tests/{name}.py, is mirror-excluded and absent")


def test_the_mirror_skips_stay_off_in_the_source_repo():
    """The skips above exist for the public mirror. In the source repo they must not fire, or
    this module's guards would skip in CI with nothing red."""
    if not (REPO_ROOT / "tests" / "test_mirror_leak_gate.py").is_file():
        pytest.skip("the public mirror, where these skips are meant to fire")
    assert _without_stripped(RAW_READ_ALLOWED) == RAW_READ_ALLOWED
    try:
        _skip_without_tools()
        for name, _fn, _kwargs in _CENSUSES + _FOLDED:
            _skip_if_mirror_excluded(name)
    except pytest.skip.Exception as e:
        pytest.fail(f"a mirror skip fired in the source repo: {e}")
    missing = sorted({n for n, _f, _k in _CENSUSES + _FOLDED
                      if not (REPO_ROOT / "tests" / f"{n}.py").is_file()})
    assert not missing, f"census modules named in _CENSUSES/_FOLDED that do not exist: {missing}"


def _census_holds(mod, fn, kwargs, moved_root, monkeypatch, tmp_path, per_file=False):
    seen = _steps_read(moved_root, monkeypatch)
    _call(mod, fn, kwargs, monkeypatch, tmp_path)
    assert seen, f"{mod.__name__}::{fn} stayed green over the moved copy without opening a step file"
    assert per_file or not seen.raw_core, (
        f"{mod.__name__}::{fn} read the moved core raw, beside the splice: {seen.raw_core}")


def _synthetic_census(moved_root, read):
    """A census that scans review-close for a word no step holds, reading it with `read`."""
    import types
    mod = types.ModuleType("_synthetic_census")
    rc = moved_root / "core" / "skills" / "review-close" / "SKILL.md"

    def test_census():
        assert "NO-SUCH-WORD-385" not in read(rc)
    mod.test_census = test_census
    return mod


def test_the_evidence_catches_a_blind_census_and_passes_a_spliced_one(moved_root, monkeypatch,
                                                                      tmp_path):
    """The machinery above, on two synthetic censuses: one reads the moved core raw (blind:
    green, and no step opened), one reads it through `text_of`. Without this the evidence
    check is exercised only by a defect in the tree, and today there is none."""
    blind = _synthetic_census(moved_root, lambda p: p.read_text(encoding="utf-8"))
    spliced = _synthetic_census(moved_root, RT.text_of)
    with pytest.raises(AssertionError, match="without opening a step file"):
        _census_holds(blind, "test_census", {}, moved_root, monkeypatch, tmp_path)
    _census_holds(spliced, "test_census", {}, moved_root, monkeypatch, tmp_path)
    assert _evidence_fails(blind, "test_census", {}, moved_root, monkeypatch, tmp_path)
    assert not _evidence_fails(spliced, "test_census", {}, moved_root, monkeypatch, tmp_path)
    # Round 2, lens A: a splice whose result is thrown away, beside a raw read of the core.
    dead = _synthetic_census(moved_root, lambda p: (RT.text_of(p), p.read_text(encoding="utf-8"))[1])
    with pytest.raises(AssertionError, match="read the moved core raw"):
        _census_holds(dead, "test_census", {}, moved_root, monkeypatch, tmp_path)
    assert _evidence_fails(dead, "test_census", {}, moved_root, monkeypatch, tmp_path)
    # A per-file census reads each file on its own, the core included, and that is allowed.
    _census_holds(dead, "test_census", {}, moved_root, monkeypatch, tmp_path, per_file=True)


def _evidence_fails(mod, fn, kwargs, moved_root, monkeypatch, tmp_path, per_file=False) -> bool:
    """True when the positive test's evidence would fail: the census raises, it passes
    without opening a step file, or (for a spliced census) it read the core raw."""
    seen = _steps_read(moved_root, monkeypatch)
    try:
        _call(mod, fn, kwargs, monkeypatch, tmp_path)
    except (AssertionError, KeyError):
        return True
    return not seen or (not per_file and bool(seen.raw_core))


_SPLICED = [c for c in _CENSUSES if (c[0], c[1]) not in _NOT_SPLICED]

# Absence scans that are as correct unfolded as folded: read file by file, the step files are
# scanned anyway. The fold-off control does not apply to them; the splice-only one does.
_FOLD_IRRELEVANT = {
    ("test_zsh_path_clobber_guard", "test_no_site_revokes_the_rule_while_appearing_to_state_it"),
    ("test_zsh_path_clobber_guard", "test_the_remedy_is_stated_in_full_at_every_site"),
}
_FOLDED = [c for c in _CENSUSES if (c[0], c[1]) not in _FOLD_IRRELEVANT]


@pytest.mark.parametrize("name,fn,kwargs", _SPLICED, ids=[f"{m}::{f}" for m, f, _ in _SPLICED])
def test_a_census_that_keeps_its_fold_but_reads_raw_is_seen(moved_root, monkeypatch, tmp_path,
                                                            name, fn, kwargs):
    """The second control (lens B, round 1, HIGH-1): the fold stays and only the splice is
    switched off, the revert that turned eight censuses blind while every test stayed green."""
    _skip_if_mirror_excluded(name)
    mod = _fresh(name, moved_root, monkeypatch)
    raw = lambda p, errors="strict": Path(p).read_text(encoding="utf-8", errors=errors)
    assert hasattr(mod, "text_of"), f"{name} reads through text_of, or belongs in _NOT_SPLICED"
    mod.text_of = raw
    assert _evidence_fails(mod, fn, kwargs, moved_root, monkeypatch, tmp_path)


@pytest.mark.parametrize("name,fn,kwargs", _FOLDED, ids=[f"{m}::{f}" for m, f, _ in _FOLDED])
def test_without_the_fold_the_move_reddens_that_census(moved_root, monkeypatch, tmp_path,
                                                       name, fn, kwargs):
    """The fold-off control: the same census over the same moved copy, with the fold and the
    splice switched off in that module, must fail the positive test's evidence (it raises,
    or it opens no step file). Otherwise the move never reached it."""
    _skip_if_mirror_excluded(name)
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    mod = _fresh(name, moved_root, monkeypatch)
    raw = lambda p, errors="strict": Path(p).read_text(encoding="utf-8", errors=errors)
    for attr, val in (("fold_steps", lambda ps: list(ps)), ("runner_key", lambda p: p),
                      ("text_of", raw)):
        if hasattr(mod, attr):
            setattr(mod, attr, val)
    assert _evidence_fails(mod, fn, kwargs, moved_root, monkeypatch, tmp_path,
                           per_file=(name, fn) in _NOT_SPLICED)
