"""The interpreter a check resolves when it is standing in a linked worktree.

WHY THIS MODULE EXISTS. `CLAUDE.md`'s round gate makes it mandatory to create
every reviewer AT the commit under review, and this repo places them with
`git worktree add --detach <sha>`. **A linked worktree has no `.venv` by
construction.** So from Phase 288 onward — the phase that made placement
mandatory — every correctly-placed reviewer ran checks that resolved their own
interpreter from a tree that has none.

`tools/scan_public_history.sh` resolved it as

    PY="$SRC/.venv/bin/python3"; [ -x "$PY" ] || PY=python3

one probe, then a silent degrade to a system interpreter carrying none of the
project's dependencies. Measured at `75d1bc9` in a placed worktree: **25 tests
red on arrival** (24 in `tests/test_public_history_scan.py`, 1 in
`tests/test_cut_release_gate.py`), every one reporting `refusing: cannot import
the leak detectors`, against **115 passed** in the primary checkout at the same
commit with the same interpreter handed to pytest. A reviewer cannot tell 25
pre-existing reds from damage the phase caused, so the gate's own signal is what
degrades.

THE FIX IS RESOLUTION ORDER, NOT A REFUSAL. `--git-common-dir` answers "which
checkout is PRIMARY"; the worktree's own root answers a different question, and
conflating the two is the Phase 234 class. `run_checks.sh:53` and
`self_check.sh:91` already resolve in this order, and `self_check.sh`'s comment
records Phase 182 fixing this same bug there. `scan_public_history.sh` is the
site that never got it.

WHAT THIS DOES NOT COVER, stated because the round gate sanctions TWO
placements and this fixes one. A **linked worktree** resolves the primary
checkout, so it is covered. A **throwaway clone** is not: `--git-common-dir`
returns the clone's own `.git`, so "primary" resolves to the clone itself, which
has no `.venv` either, and the run falls through to the bare interpreter exactly
as before. Measured, not reasoned. The clone path is still covered by the
symlink remedy the same file already states as the only one — this widening does
not replace it, and `test_the_venv_remedy_is_the_symlink_alone` still guards it.

WHY THIS TEST SLICES THE REAL FILE RATHER THAN RESTATING THE SNIPPET. A test
that re-authors the lines under test asserts its own copy, which is the defect
`tests/test_cut_release_gate.py::_publish_block`'s docstring already records a
round walking four mutations through. These tests read the real bytes between
two literal anchors and execute them, so moving or weakening the real block
changes what runs here.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNER = REPO_ROOT / "tools" / "scan_public_history.sh"

# `tools/` is stripped by the public mirror, so on a sterilized tree the script
# this module slices is simply absent. Skip rather than fail: the runbook's
# step 4 rule is that every shipped test reading a mirror-excluded file must
# `pytest.skip` with its reason, and without this the public snapshot's required
# `pytest` check goes red on a tree nobody can fix from the mirror. In the source
# repo the line is an exact no-op. Caught by
# `tests/test_mirror_skip_discipline.py` on this module's first full-suite run —
# the gate reading a brand-new module and refusing it, which is the gate working.
if not SCANNER.is_file():  # pragma: no cover - only true on the public mirror
    pytest.skip(
        "tools/scan_public_history.sh is maintainer-side and excluded from the "
        "public mirror; the reviewer interpreter-resolution guard only applies "
        "in the source repo",
        allow_module_level=True,
    )

_OPEN = 'PY="$SRC/.venv/bin/python3"'
_CLOSE = '[ -x "$PY" ] || PY=python3'


def _resolution_block() -> str:
    """The real resolution lines, sliced from the real script by literal anchors.

    Fails CLOSED: a missing or duplicated anchor raises rather than returning a
    block that happens to be empty, because an empty snippet would `echo` a bare
    `python3` and read as the pre-fix behaviour passing.

    COMMENTS ARE STRIPPED FIRST, and that is not tidiness. The block's own
    comment QUOTES the pre-fix line verbatim to record what changed, so counting
    over the raw file finds the anchor twice and this helper refused — correctly,
    but for the wrong reason. An anchor on prose is not an anchor on code, and a
    guard that a later comment can break by mentioning its own subject is a
    guard that gets deleted. Caught by this module against its own first draft.
    """
    text = "\n".join(
        ln for ln in SCANNER.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )
    assert text.count(_OPEN) == 1, (
        f"expected exactly one {_OPEN!r} in {SCANNER.name}, found "
        f"{text.count(_OPEN)} — the anchor moved and this guard is reading "
        "something other than the resolution block"
    )
    assert text.count(_CLOSE) == 1, (
        f"expected exactly one {_CLOSE!r} in {SCANNER.name}, found "
        f"{text.count(_CLOSE)}"
    )
    start = text.index(_OPEN)
    end = text.index(_CLOSE) + len(_CLOSE)
    assert start < end, (
        "the final fallback precedes the first probe — the block is inverted, "
        "which would resolve a bare python3 before ever looking for a venv"
    )

    # THE SLICE IS NOT THE SCRIPT, and the round proved that gap is exploitable.
    # Everything AFTER the close anchor was invisible here, so appending one line
    # that undoes the fix — scoped to the worktree case, leaving the primary
    # checkout's answer intact — reverted the whole thing with the entire suite
    # green, because the pre-existing execution tests only ever run this script
    # from the primary checkout. A blanket `PY=python3` was caught; the shape of
    # the ORIGINAL defect was not.
    #
    # So the block is no longer merely sliced: every assignment to `PY` anywhere
    # in the file must live inside it. That is the invariant an appended undo
    # breaks, and it is checkable without executing the script.
    # ANY assignment, not one at line-start. The first cut of this check used
    # `^\s*PY=` and BOTH exploit shapes walked straight through it, because an
    # appended undo is written `[ -x … ] || PY=python3` — the assignment is not
    # the first token on its line. A negative lookbehind for `$` and word
    # characters keeps `"$PY"` references and names like `LEGACY_PY=` out.
    assignments = [
        (i, ln) for i, ln in enumerate(text.splitlines(), 1)
        if re.search(r"(?<![$\w])PY=", ln)
    ]
    block_lines = set(range(
        text[:start].count("\n") + 1,
        text[:end].count("\n") + 2,
    ))
    stray = [(i, ln.strip()) for i, ln in assignments if i not in block_lines]
    assert not stray, (
        "an assignment to $PY sits OUTSIDE the resolution block, so this guard "
        "is reading a block the script then overrides. That is exactly how the "
        "fix gets reverted with every test green:\n" +
        "\n".join(f"  line {i}: {ln}" for i, ln in stray)
    )
    return text[start:end]


# Git's discovery variables, and the fixtures MUST NOT inherit them. `tests/
# conftest.py`'s own write-guard message prescribes this and names
# `tests/test_cut_release_gate.py::_hermetic_env` as the pattern; eleven modules
# follow it, including the sibling module over this same script. This module did
# not, and its round measured the consequence: with `GIT_DIR` set the way git
# exports it into every hook, `git init`/`git commit` here wrote a commit onto a
# VICTIM repo's main, registered a stray worktree in it and left its working
# tree dirty — while the fixture reported success. The repo-tree write guard
# cannot see subprocess writes and says so. `GIT_CONFIG_GLOBAL` is pinned too:
# without it these run under the user's real ~/.gitconfig, so a global
# `commit.gpgsign` or `core.hooksPath` reddens every test in the module for a
# reason that has nothing to do with its subject.
_GIT_DISCOVERY_VARS = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CEILING_DIRECTORIES",
)


def _hermetic_git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_DISCOVERY_VARS}
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_AUTHOR_NAME="Fixture", GIT_AUTHOR_EMAIL="f@example.invalid",
        GIT_COMMITTER_NAME="Fixture", GIT_COMMITTER_EMAIL="f@example.invalid",
    )
    return env


def _git(cwd: Path, *args: str) -> None:
    """Every fixture git call goes through here. No exceptions — that is the guard."""
    subprocess.run(args, cwd=cwd, check=True, capture_output=True,
                   encoding="utf-8", env=_hermetic_git_env())


def _fixture_pair(tmp_path: Path) -> tuple[Path, Path]:
    """A primary checkout carrying a marker `.venv`, plus a linked worktree.

    The marker interpreter only ever echoes its own name, so a test asserting on
    it is asserting on WHICH path was chosen, never on what an interpreter can
    import. That keeps these tests independent of whether pytest happens to be
    importable anywhere on the box.
    """
    main = tmp_path / "main dir"
    main.mkdir()
    _git(main, "git", "init", "-q", ".")
    (main / "seed").write_text("seed\n", encoding="utf-8")
    _git(main, "git", "add", "-A")
    _git(main, "git", "commit", "-qm", "seed")

    venv_bin = main / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    marker = venv_bin / "python3"
    marker.write_text("#!/bin/sh\necho PRIMARY_VENV\n", encoding="utf-8")
    marker.chmod(0o755)

    wt = tmp_path / "wt dir"
    _git(main, "git", "worktree", "add", "--detach", str(wt), "HEAD")
    assert not (wt / ".venv").exists(), (
        "the fixture worktree has a .venv, so it cannot exercise the condition "
        "this module exists for"
    )
    return main, wt


def _sealed_env(tmp_path: Path) -> dict[str, str]:
    """A `PATH` carrying `git` and deliberately NOT carrying `python3`.

    The block resolves the primary checkout THROUGH git, so an empty `PATH`
    would make the middle step fail for a reason that has nothing to do with the
    behaviour under test — and the whole module would then pass or fail on the
    wrong cause. `python3` is withheld so the last-resort fallback reports the
    literal string `python3` rather than an absolute path, which is what makes
    "fell through to the fallback" distinguishable from "resolved something".
    """
    gitbin = tmp_path / "gitbin"
    gitbin.mkdir(exist_ok=True)
    real_git = subprocess.run(
        ["/usr/bin/which", "git"], capture_output=True, encoding="utf-8",
    ).stdout.strip()
    assert real_git, "no git on PATH; this module cannot run sealed"
    link = gitbin / "git"
    if not link.exists():
        link.symlink_to(real_git)
    return {"PATH": str(gitbin), "HOME": str(tmp_path)}


def _resolve(src: Path, tmp_path: Path, cwd: Path | None = None,
             env_extra: dict[str, str] | None = None, block: str | None = None) -> str:
    """Run the real block with `$SRC` pointed at `src`; report the chosen `$PY`.

    `SRC` is QUOTED. It was not in the first draft, so a `tmp_path` containing a
    space would have broken the harness rather than the subject — a test that
    fails for its own reasons reports on nothing.
    """
    env = _sealed_env(tmp_path)
    if env_extra:
        env.update(env_extra)
    script = f'SRC="{src!s}"\n{block or _resolution_block()}\nprintf %s "$PY"\n'
    r = subprocess.run(
        ["/bin/bash", "-c", script], capture_output=True, encoding="utf-8",
        env=env, cwd=str(cwd) if cwd else None,
    )
    assert r.returncode == 0, f"the resolution block itself failed:\n{r.stderr}"
    return r.stdout.strip()


def _repo_with_marker_venv(root: Path, marker: str) -> Path:
    """A git repo carrying a marker interpreter, used as a WRONG answer to detect."""
    root.mkdir(parents=True)
    _git(root, "git", "init", "-q", ".")
    (root / "seed").write_text("seed\n", encoding="utf-8")
    _git(root, "git", "add", "-A")
    _git(root, "git", "commit", "-qm", "seed")
    vb = root / ".venv" / "bin"
    vb.mkdir(parents=True)
    (vb / "python3").write_text(f"#!/bin/sh\necho {marker}\n", encoding="utf-8")
    (vb / "python3").chmod(0o755)
    return root


def test_the_primary_is_resolved_relative_to_SRC_not_to_the_process_CWD(tmp_path: Path) -> None:
    """THE `case` LINE. `--git-common-dir` answers `.git` RELATIVE whenever `$SRC` is
    an ordinary checkout, so without absolutising it `cd "$_gcd/.."` resolves against
    the caller's CWD and picks whatever repo the operator happens to be standing in.

    The module's other fixtures are all linked worktrees, where git answers an
    ABSOLUTE path — so every one of them passes with the `case` line deleted.
    This phase's round found that: the one line that makes the fix correct was
    the one line nothing covered.
    """
    elsewhere = _repo_with_marker_venv(tmp_path / "elsewhere", "WRONG_REPO")
    src = tmp_path / "src"
    src.mkdir()
    subprocess.run(["git", "init", "-q", "."], cwd=src, check=True, capture_output=True)
    assert not (src / ".venv").exists()

    chosen = _resolve(src, tmp_path, cwd=elsewhere)

    assert chosen == "python3", (
        f"resolution leaked out of $SRC and answered {chosen!r} — it resolved "
        "against the process CWD, so a check run from anywhere would pick an "
        "unrelated repository's interpreter"
    )
    assert "elsewhere" not in chosen, chosen


def test_an_ambient_GIT_DIR_cannot_redirect_the_resolution(tmp_path: Path) -> None:
    """`git -C` does NOT override `GIT_DIR`, and this site ran no git before the fix.

    So the fix would have introduced the exposure `tests/test_git_env_hermeticity.py`
    exists for. Reachable from a hook, `git rebase --exec` or `git bisect run`.
    """
    elsewhere = _repo_with_marker_venv(tmp_path / "elsewhere", "WRONG_REPO")
    main, wt = _fixture_pair(tmp_path)

    chosen = _resolve(wt, tmp_path, env_extra={"GIT_DIR": str(elsewhere / ".git")})

    assert chosen == str(main / ".venv" / "bin" / "python3"), (
        f"an ambient GIT_DIR redirected the interpreter to {chosen!r}"
    )


def test_the_primary_checkouts_venv_is_resolved_from_a_linked_worktree(tmp_path: Path) -> None:
    """THE REGRESSION. This is the arm that was missing until 2026-09-19.

    A reviewer placed by the mandatory round gate stands here, and before the
    fix this returned the literal `python3`.
    """
    main, wt = _fixture_pair(tmp_path)
    chosen = _resolve(wt, tmp_path)
    assert chosen == str(main / ".venv" / "bin" / "python3"), (
        "a check run from a placed reviewer's worktree did not resolve the "
        f"PRIMARY checkout's venv; it chose {chosen!r}. This is the defect that "
        "put 25 red tests in front of every reviewer from Phase 288 onward."
    )


def test_the_checkouts_own_venv_still_wins_when_it_has_one(tmp_path: Path) -> None:
    """The primary checkout resolves itself, and does so by the FIRST probe.

    Widening a resolution is only safe if it did not reorder the existing
    answer: the ordinary cut runs in the primary checkout, and it must keep
    choosing its own venv.
    """
    main, _wt = _fixture_pair(tmp_path)
    chosen = _resolve(main, tmp_path)
    assert chosen == str(main / ".venv" / "bin" / "python3")


def test_the_bare_fallback_is_KEPT_for_a_tree_with_no_venv_anywhere(tmp_path: Path) -> None:
    """The fallback is the THIRD answer now, not the second — and still exists.

    Removing it would refuse on a CI box whose system interpreter legitimately
    carries the dependencies. This test is what stops the widening from turning
    into a narrowing.
    """
    # The PARENT carries a venv, deliberately. If the git probe's failure is
    # swallowed into a relative `_gcd` (e.g. `|| echo .`), resolution walks one
    # level up and silently adopts whatever venv is sitting there. Found by the
    # author's second battery: without this parent, that mutation survives,
    # because every other fixture's parent happens to be bare.
    # A PLAIN directory, deliberately NOT a git repo. The first draft made it a
    # repo, and the test failed correctly: a tree inside a checkout SHOULD
    # resolve that checkout's venv. The case under test is the one where git
    # finds nothing at all, and the parent's venv must still not be adopted.
    parent = tmp_path / "withvenv"
    (parent / ".venv" / "bin").mkdir(parents=True)
    marker = parent / ".venv" / "bin" / "python3"
    marker.write_text("#!/bin/sh\necho PARENT_VENV\n", encoding="utf-8")
    marker.chmod(0o755)
    loose = parent / "loose"
    loose.mkdir()
    chosen = _resolve(loose, tmp_path)
    assert chosen == "python3", (
        f"a venv-less NON-REPO tree resolved {chosen!r} — either the last-resort "
        "fallback is gone, or a failed git probe walked up into the parent's venv"
    )


@pytest.mark.parametrize(
    ("mutate", "why"),
    [
        pytest.param(
            lambda b: b.replace("--git-common-dir", "--show-toplevel"),
            "`--show-toplevel` answers which worktree the CALLER stands in, "
            "which is the worktree itself — the Phase 234 class",
            id="show-toplevel-instead-of-git-common-dir",
        ),
        pytest.param(
            lambda b: b.replace('cd "$_gcd/.." 2>/dev/null && pwd', 'printf ""'),
            "the primary checkout is never derived, so the middle step is inert",
            id="primary-root-never-derived",
        ),
        pytest.param(
            lambda b: b.replace('if [ ! -x "$PY" ]; then', "if false; then"),
            "the middle step is skipped outright",
            id="middle-step-skipped",
        ),
    ],
)
def test_a_weakened_resolution_is_caught(tmp_path: Path, mutate, why: str) -> None:
    """The guard above must FAIL on each way of undoing the fix.

    Written because this phase's own first mutation scored a false SURVIVED: it
    hardcoded a path containing the repo root, and the harness it ran under
    substitutes that string, so the mutation was neutralised rather than tested.
    An author's battery measures self-consistency until something independent
    reads it.
    """
    main, wt = _fixture_pair(tmp_path)
    block = mutate(_resolution_block())
    script = f'SRC={wt!s}\n{block}\nprintf %s "$PY"\n'
    r = subprocess.run(
        ["/bin/bash", "-c", script], capture_output=True, encoding="utf-8",
        env=_sealed_env(tmp_path),
    )
    # THE MUTANT MUST STILL BE A VALID SHELL. Without this the arm passes on a
    # bash SYNTAX ERROR — it cannot tell "the mutation weakened resolution" from
    # "the mutation broke the script", and a guard that accepts a broken subject
    # as a pass is scoring nothing. Found by the round.
    assert r.returncode == 0, (
        f"the mutated block is not runnable shell, so this case proves nothing "
        f"about resolution:\n{r.stderr}"
    )
    chosen = r.stdout.strip()
    assert chosen != str(main / ".venv" / "bin" / "python3"), (
        f"a mutation that should have broken resolution still found the "
        f"primary venv, so the guard above cannot see it: {why}"
    )


# === The EMITTED twin, which shipped with no guard at all ====================

BUILDER = REPO_ROOT / "tools" / "make_public_mirror.sh"

if not BUILDER.is_file():  # pragma: no cover - only true on the public mirror
    pytest.skip(
        "tools/make_public_mirror.sh is maintainer-side and excluded from the "
        "public mirror",
        allow_module_level=True,
    )


def _emitted_block(src: Path) -> str:
    """The resolution lines the builder PRINTS for a human to paste, rendered.

    Not a copy: the `echo` statements are lifted from the real builder and run
    with `$SRC` bound, so what this executes is exactly what an operator pastes.
    """
    lines = BUILDER.read_text(encoding="utf-8").splitlines()
    echoes = [ln for ln in lines
              if ln.startswith('echo "  PY=') or ln.startswith('echo "  [ -x ')]
    assert len(echoes) == 3, (
        f"expected the builder to emit a three-step resolution, found {len(echoes)} "
        f"line(s):\n" + "\n".join(echoes)
    )
    r = subprocess.run(
        ["/bin/bash", "-c", f'SRC="{src!s}"\n' + "\n".join(echoes)],
        capture_output=True, encoding="utf-8", check=True,
    )
    return r.stdout


def test_the_emitted_block_resolves_the_primary_checkout_too(tmp_path: Path) -> None:
    """THE OTHER HALF OF THE FIX, and this phase's round found it unguarded.

    Reverting the builder's emitted lines to the pre-fix single probe left every
    test in the repo green — sixteen modules reference this file and none reads
    what it emits. That matters more here than at the scanner, because the
    symptom is worse: the block is chained `&&` ahead of `gh pr create`, so a
    degraded interpreter makes the scanner refuse and a CLEAN body is blocked at
    the one irreversible step of the publish.
    """
    main, wt = _fixture_pair(tmp_path)
    chosen = _resolve(wt, tmp_path, block=_emitted_block(wt))
    assert chosen == str(main / ".venv" / "bin" / "python3"), (
        f"the pasted publish block resolved {chosen!r} from a linked worktree; "
        "at cut time that refuses a clean body at the irreversible step"
    )


def test_the_emitted_block_keeps_its_last_resort_fallback(tmp_path: Path) -> None:
    """The fail-closed arm the builder documents at length must still exist.

    `tests/test_cut_release_gate.py` asserts the chain treats a refusal like a
    finding; that arm only means anything while a venv-less tree really does
    reach the bare interpreter.
    """
    loose = tmp_path / "loose"
    loose.mkdir()
    assert _resolve(loose, tmp_path, block=_emitted_block(loose)) == "python3"


def test_the_emitted_block_obeys_the_files_no_apostrophe_rule(tmp_path: Path) -> None:
    """The builder forbids apostrophes and backticks on these lines, deliberately:
    an operator pastes them into an interactive shell."""
    emitted = _emitted_block(tmp_path)
    assert "'" not in emitted and "`" not in emitted, (
        f"the emitted resolution carries a character the builder forbids:\n{emitted}"
    )
