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
import subprocess
import sys
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

#: The sentinel for the source-repo-only check at the bottom of this module.
#: Deliberately NOT the file that check asserts about — see its docstring.
_PIN_SENTINEL = REPO_ROOT / "REVIEW_CHECKLIST.md"

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


def test_a_skip_sentinel_names_a_file_the_source_repo_actually_has():
    """The over-skip direction, which the rule above cannot see.

    `test_a_module_reading_an_excluded_path_skips_when_it_is_absent` asks whether a
    skip EXISTS. It cannot ask whether the skip's condition is the right one, and
    the two failure directions are not symmetric. Under-skipping reddens the public
    snapshot loudly, at a cut, in front of a required check. **Over-skipping is
    silent**: point a sentinel at a path that exists in neither tree and the guarded
    module skips everywhere, reports green, and checks nothing — in the source repo,
    which is the only place it was ever meant to run.

    Found by Phase 246's author-side battery against its own fix. Mutating
    `tests/test_phase_log_citation_targets.py`'s sentinel from `CLAUDE.md` to a
    nonexistent path left every other guard in this repo green, including the rule
    above: the module still contains `pytest.skip`, so it still passes.

    **Two independent sentinels, which is the whole mechanism.** This test keys on
    `REVIEW_CHECKLIST.md` and asserts about `CLAUDE.md`. Both are mirror-excluded, so
    the assertion is correctly inert on the snapshot; and a mutation of the SUBJECT's
    sentinel is caught by a test keyed on the other.

    **The symmetric direction needed a second mechanism, and did not have one until the
    round said so.** Retargeting `_PIN_SENTINEL` itself at a path in neither tree
    skipped this test in both trees, with zero new failures on a full suite — the exact
    defect described above, sitting in the thing written to catch it. The membership
    assertion below closes that, and is checked BEFORE the skip for that reason. Keying
    both sentinels on the same file is the other direction, and is what the inequality
    assertion is for.
    """
    # Imported first, and MEMBERSHIP is checked before the skip. Both orderings are
    # load-bearing, and the round found out why: with the skip first, retargeting
    # `_PIN_SENTINEL` at a path in neither tree made this test skip in BOTH of them,
    # silently, with zero new failures on a full suite.
    #
    # The import is inside the test so that deleting the subject module raises here
    # rather than silently losing an assertion (the Q-351 class, in the one instance
    # this phase can pin without inventing a repo-wide roster).
    from tests import test_phase_log_citation_targets as citations

    excluded = _excluded_paths()
    for label, path in (("_PIN_SENTINEL", _PIN_SENTINEL),
                        ("the citation guards' sentinel", citations.CLAUDE_MD)):
        assert path.name in excluded, (
            f"{label} names {path.name!r}, which the mirror does not strip (it strips "
            f"{sorted(excluded)}). A skip sentinel that is not mirror-excluded is "
            "either always-present — the skip never fires and the snapshot goes red — "
            "or always-absent, and then the guard checks nothing anywhere. Derived "
            "from the builder rather than hand-listed, so it cannot drift away from "
            "what actually ships."
        )

    if not _PIN_SENTINEL.is_file():
        pytest.skip(
            f"{_PIN_SENTINEL.name} is absent, so this is the sterilized mirror; the "
            "source-repo sentinel check only applies in the source repo"
        )

    # Set cardinality, not `!=`, and the round is the reason. `citations.CLAUDE_MD
    # != _PIN_SENTINEL` reads correctly and dies to a one-token slip: `is not` on two
    # Path objects for the same path is ALWAYS true, because they are never the same
    # object. The guards lens ran that compound — collapse both sentinels, then soften
    # `!=` to `is not` — and the whole mechanism went inert with the suite green.
    # `is`/`!=` confusion is among the most ordinary Python slips there is, and a
    # cardinality check has no comparison operator to soften.
    assert len({_PIN_SENTINEL.name, citations.CLAUDE_MD.name}) == 2, (
        "this test and the module it checks now key on the SAME file, so it skips in "
        "exactly the trees where its subject skips and can never catch a retarget. "
        "The two sentinels must be different mirror-excluded files — that "
        "independence is the entire mechanism, and collapsing it makes this test "
        "agree with the bug."
    )
    assert citations.CLAUDE_MD.is_file(), (
        f"the citation-target guards key their skip on {citations.CLAUDE_MD.name}, "
        "which does not exist in the source repo — so the whole module skips HERE, "
        "where it is the only thing checking that PHASE_LOG.md's citations resolve. "
        "A skip sentinel must name a file the source repo has and the mirror strips."
    )


def test_the_citation_guards_actually_RUN_in_the_source_repo():
    """The over-skip direction again, and this time against the CONDITION.

    The sibling test above pins the *sentinel constant*. The round showed that is
    half the surface: three separate one-token edits to the fixture's **condition**
    — ``if True:``, ``is_file`` → ``is_dir``, ``CLAUDE_MD`` → ``CLAUDE_MD.parent``
    — leave the constant untouched, make the module skip in the SOURCE repo as well
    as the mirror, and were missed by every column an automated run performs. Eleven
    gates go inert in the only repo where they were meant to run, and the suite
    reports green with a skip count nobody reads.

    None of the three is adversarial. ``is_file``/``is_dir`` is a one-word slip;
    ``.parent`` is a refactor slip; ``if True:`` is the ordinary "disable this while
    I debug" that never came back out.

    **No textual check reaches this**, which is why this one is behavioural: it runs
    the module and asserts the tests actually ran. A guard that can be satisfied by
    skipping is not a guard, and skipping is exactly how the failure presents.

    ``-n0`` because the repo's ``addopts`` carries ``-n auto``; a nested xdist run
    is slow and its summary line is no easier to parse.
    """
    if not _PIN_SENTINEL.is_file():
        pytest.skip(
            f"{_PIN_SENTINEL.name} is absent, so this is the sterilized mirror, where "
            "these gates are SUPPOSED to skip; the run-check only applies in the source repo"
        )
    subject = TESTS / "test_phase_log_citation_targets.py"
    assert subject.is_file(), f"{subject.name} is gone — the gates it holds are gone with it"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(subject),
         "-q", "--no-header", "--tb=no", "-n0", "-p", "no:cacheprovider"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    summary = [ln for ln in proc.stdout.splitlines() if " passed" in ln or " skipped" in ln]
    tail = summary[-1] if summary else proc.stdout.strip()[-300:]
    assert proc.returncode == 0, (
        f"{subject.name} does not pass in the source repo:\n{tail}"
    )
    assert "skipped" not in tail, (
        f"{subject.name} SKIPPED in the source repo — its summary reads {tail!r}. That "
        "module's whole job is checking PHASE_LOG.md's citations here; if it skips here "
        "it checks nothing anywhere, because the mirror is where it is supposed to skip. "
        "Look at its skip condition, not just its sentinel constant: the round reached "
        "this state three ways (`if True:`, `.is_dir()`, `.parent.is_file()`), none of "
        "which touches the sentinel and none of which any text-matching guard can see."
    )
