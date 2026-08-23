"""A shipped test may not read a mirror-excluded file without skipping (Phase 221).

**This is the register's rule applied to the register's own commit.**

`tools/make_public_mirror.sh` strips `tools/`, `CLAUDE.md`, `REVIEW_CHECKLIST.md`
and friends from the public snapshot; `tests/` ships. A test module that reads one
of those paths and does not `pytest.skip` turns the public repo's required `pytest`
check red on a tree nobody can fix from the mirror. Worse, when the read happens
inside a `parametrize` decorator it is a COLLECTION error, which aborts the run
rather than failing one test.

The rule has existed since **Phase 160** and its entire enforcement was prose — a
line in `tools/TESTER_MIRROR_RUNBOOK.md` and eleven modules following it by hand.
In Phase 221 it failed again: two new modules read four excluded paths with no
guard, and the phase that shipped them was the phase arguing that written lessons
do not transfer. Its own round caught it by building the mirror and running the
suite.

So the lesson is not written a twelfth time. `tools/AUTHOR_DEFECT_REGISTER.md`
carries the class; this is its enforcement.

**Stated limit.** This matches a module's *textual* references to excluded paths.
A module that reaches an excluded file through a computed path, or through a helper
in another module, is outside what this can see — it is a floor on the class, not a
proof against it.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS = REPO_ROOT / "tests"
MIRROR_SCRIPT = REPO_ROOT / "tools" / "make_public_mirror.sh"

# Paths the mirror removes. Derived from the script where it is available, so this
# cannot drift silently away from what actually ships; the literal fallback keeps
# the guard alive on a tree where `tools/` is already gone (i.e. the mirror itself).
_FALLBACK = ("tools/", "CLAUDE.md", "REVIEW_CHECKLIST.md", "REVIEW_ARCHIVE.md",
             "HANDOVER.md", "PHASE_47_SPEC.md")

# Modules the mirror deletes outright — they never run there, so they owe no skip.
_DELETED_FROM_MIRROR = {
    "test_auto_claim_miner.py", "test_mirror_leak_gate.py", "test_cut_release_gate.py",
}


def _excluded_paths() -> tuple[str, ...]:
    if not MIRROR_SCRIPT.exists():
        return _FALLBACK
    text = MIRROR_SCRIPT.read_text(encoding="utf-8")
    found = set(_FALLBACK) & set(_FALLBACK)  # start from the known floor
    for m in re.finditer(r'"\$TARGET/([A-Za-z0-9_./-]+)"', text):
        p = m.group(1)
        if p.endswith(".md") or p.endswith("/"):
            found.add(p)
    if 'rm -rf "$TARGET/tools"' in text:
        found.add("tools/")
    return tuple(sorted(found))


def _modules():
    return sorted(p for p in TESTS.glob("test_*.py") if p.name not in _DELETED_FROM_MIRROR)


# A module *mentions* excluded paths constantly — in docstrings, in assertion
# strings, in design references. Only a path CONSTRUCTION is a read. The first cut
# matched any textual occurrence and produced 25 false positives, which is the
# over-strict shape that teaches a maintainer to delete a guard.
_PATH_BUILD = re.compile(r'(?:ROOT|parents\[\d\]|Path)\s*(?:/\s*"([^"]+)")+')
_SEGMENT = re.compile(r'/\s*"([^"]+)"')


def _constructed_paths(text: str) -> list[tuple[str, ...]]:
    """Literal path-segment chains, per line. Chains, not a flat set, because
    `ROOT / "tools" / "X.md"` and `ROOT / "tools"` have different consequences."""
    out = []
    for line in text.splitlines():
        if not re.search(r'(?:ROOT|parents\[\d\]|Path\()', line):
            continue
        segs = tuple(_SEGMENT.findall(line))
        if segs:
            out.append(segs)
    return out


def _reads_excluded_file(text: str) -> list[str]:
    """Excluded paths this module builds **a file path to**.

    Only a file read raises. `Path("/gone").rglob("*.py")` returns `[]` silently,
    so a module that sweeps a missing `tools/` degrades its own coverage on the
    mirror but does not redden it — a real concern, and a different one from this
    guard's subject. Flagging it anyway produced this guard's last false positive
    (`test_phantom_shell_vars.py`), so directory-only constructions are exempt and
    the reason is stated rather than left as a silent carve-out.
    """
    excluded = _excluded_paths()
    files = {p for p in excluded if not p.endswith("/")}
    dirs = {p.rstrip("/") for p in excluded if p.endswith("/")}
    hits = set()
    for segs in _constructed_paths(text):
        # A segment may itself be a multi-part path: `ROOT / "tools/X.md"` is one
        # segment, not two. Missing that let this guard pass over the very module
        # whose omission prompted it.
        parts = [q for s in segs for q in s.split("/") if q]
        has_file = any("." in q for q in parts)
        for q in parts:
            if q in files:
                hits.add(q)
            elif q in dirs and has_file:
                hits.add(q + "/")
    return sorted(hits)


@pytest.mark.parametrize("module", _modules(), ids=lambda p: p.name)
def test_a_module_reading_an_excluded_path_skips_when_it_is_absent(module):
    """**The rule.** A shipped test that reads a mirror-excluded FILE must skip
    when it is absent, or the public snapshot's required `pytest` check goes red on
    a tree nobody can fix from the mirror."""
    text = module.read_text(encoding="utf-8")
    touched = _reads_excluded_file(text)
    if not touched:
        pytest.skip("builds no path to a mirror-excluded file")
    assert "pytest.skip" in text, (
        f"{module.name} builds a path to mirror-excluded {touched} but never calls "
        f"pytest.skip. On the public snapshot that file is absent, and this module "
        f"reddens the required `pytest` check — as a collection ERROR if the read "
        f"happens inside a decorator. Guard it, as tests/test_registry_drift.py does."
    )


def test_the_guard_actually_matches_something():
    """Non-vacuity. If the exclusion extraction breaks, every module reports
    "reads no mirror-excluded path" and this suite certifies a rule it stopped
    checking — the exact shape of the defect it exists to prevent."""
    ex = _excluded_paths()
    assert "tools/" in ex and "REVIEW_CHECKLIST.md" in ex, f"exclusion list looks wrong: {ex}"
    hits = [m.name for m in _modules() if _reads_excluded_file(m.read_text(encoding="utf-8"))]
    assert len(hits) >= 3, (
        f"only {len(hits)} modules build a path to an excluded file ({hits}) — the "
        f"construction extraction has broken and this guard is scoring nothing"
    )
