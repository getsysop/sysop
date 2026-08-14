"""Step 2b's primary-tree baseline/delta (Phase 200, Q-194 leg 2).

These tests exist because the first version of this fix was **inert**: the
baseline capture was written into a blockquote 82 lines *after* the spawn it
had to precede, so an operator reading the file top to bottom captured the
baseline with the breach already in it and the assertion then printed
"primary tree unchanged by 2b" over the very mutation it was built to catch.
An adversarial reviewer found it by walking the file in reading order.

So the ordering is tested structurally, and the commands are tested by
running them -- prose asserting an order is not a test of it.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "core/skills/review-close/SKILL.md"


def _lines() -> list[str]:
    return SKILL.read_text().split("\n")


def _line_of(pred, what: str) -> int:
    for i, ln in enumerate(_lines(), start=1):
        if pred(ln):
            return i
    raise AssertionError(f"could not locate {what} in {SKILL}")


def _is_spawn_step(ln: str) -> bool:
    """Match the spawn by its CONTENT, never by its list number.

    Keyed to a literal `3.` this guard is walked through by renumbering --
    which is exactly what inserting a step does, so the one edit most likely
    to reintroduce the ordering defect is the one that would silently turn
    this test into a "could not locate" error instead of a real verdict.
    Found by mutating this very test.
    """
    return re.match(r"^\s*\d+\.\s+Spawn an Agent with:", ln) is not None


# --------------------------------------------------------------------------
# ordering -- the defect that made v1 inert
# --------------------------------------------------------------------------

def test_the_baseline_capture_precedes_the_agent_spawn_in_reading_order() -> None:
    """The whole gate is inert if this inverts. Non-negotiable."""
    capture = _line_of(lambda l: "2b-baseline.txt" in l and ">" in l and "mkdir -p" in l,
                       "the baseline capture command")
    spawn = _line_of(_is_spawn_step, "the agent spawn step")
    assert capture < spawn, (
        f"the baseline capture is at :{capture} and the spawn at :{spawn} -- an "
        "operator reading top to bottom captures the baseline AFTER the agents "
        "have already run, which records any breach as pre-existing and makes "
        "the delta assertion certify the tree clean"
    )


def test_the_delta_assertion_comes_after_the_spawn() -> None:
    """The other half of the ordering: comparing before the agents run is vacuous."""
    spawn = _line_of(_is_spawn_step, "the agent spawn step")
    assertion = _line_of(lambda l: "diff <(git status --porcelain" in l,
                         "the delta assertion")
    assert spawn < assertion, "the delta must be compared after the agents have run"


def test_capture_and_assertion_use_the_same_untracked_mode() -> None:
    """`-uall` on one side only silently changes what the diff means.

    Plain `--porcelain` collapses an untracked directory to one `?? dir/`
    line, so an agent writing inside an already-untracked directory is
    invisible. Both ends must agree or the delta reports phantom differences.
    """
    text = SKILL.read_text()
    capture = re.search(r"mkdir -p sysop/runtime && git status --porcelain(\s+-uall)?", text)
    assert capture, "baseline capture command not found"
    assert capture.group(1), "the capture must use -uall (see the collapse test below)"
    assertion = re.search(r"diff <\(git status --porcelain(\s+-uall)?\)", text)
    assert assertion, "delta assertion command not found"
    assert assertion.group(1), "the assertion must use -uall to match the capture"


def test_the_capture_clears_a_stale_baseline_first() -> None:
    """Without `rm -f`, a skipped capture silently reuses a PREVIOUS close's file.

    The design's one safety property -- a skipped capture fails loudly -- then
    holds only on the first close ever run in the repo.
    """
    text = SKILL.read_text()
    i = text.index("2b-baseline.txt")
    window = text[max(0, i - 400):i + 200]
    assert "rm -f sysop/runtime/2b-baseline.txt" in window, (
        "the capture block must delete any stale baseline, or a close that "
        "skips the capture diffs against an earlier close's tree"
    )


# --------------------------------------------------------------------------
# behaviour -- run the prescribed commands
# --------------------------------------------------------------------------

def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", ".")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "T")
    (r / ".gitignore").write_text("sysop/runtime/\n")
    (r / "f.txt").write_text("base\n")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    return r


def _capture(repo: Path) -> None:
    subprocess.run(
        "rm -f sysop/runtime/2b-baseline.txt && mkdir -p sysop/runtime && "
        "git status --porcelain -uall > sysop/runtime/2b-baseline.txt",
        cwd=repo, shell=True, check=True,
    )


def _delta(repo: Path) -> bool:
    """True when the assertion PASSES (tree unchanged)."""
    r = subprocess.run(
        "diff <(git status --porcelain -uall) sysop/runtime/2b-baseline.txt",
        cwd=repo, shell=True, capture_output=True, text=True,
        executable="/bin/bash",
    )
    return r.returncode == 0


def test_a_pre_existing_dirty_tree_does_not_false_fail(repo: Path) -> None:
    """The Phase-155 shape: a gate that false-FAILs on the dominant path."""
    (repo / "f.txt").write_text("edited by the human\n")
    _capture(repo)
    assert _delta(repo), "ordinary uncommitted work present before 2b must not trip the gate"


def test_an_agent_created_untracked_file_is_caught(repo: Path) -> None:
    _capture(repo)
    (repo / "agent-probe.py").write_text("scratch\n")
    assert not _delta(repo), "a new untracked scratch file must be caught"


def test_a_file_inside_an_already_untracked_directory_is_caught(repo: Path) -> None:
    """Why `-uall` is required, not cosmetic.

    Plain --porcelain reports `?? scratch/` before AND after, so the breach
    cancels in the diff and the gate passes over it.
    """
    (repo / "scratch").mkdir()
    (repo / "scratch" / "pre.txt").write_text("already here\n")
    _capture(repo)
    (repo / "scratch" / "agent-probe.py").write_text("scratch\n")
    assert not _delta(repo), (
        "an agent writing into an already-untracked directory must be caught -- "
        "this is what -uall buys and it is invisible without it"
    )


def test_a_tracked_file_modified_by_an_agent_is_caught(repo: Path) -> None:
    _capture(repo)
    (repo / "f.txt").write_text("mutated by an agent\n")
    assert not _delta(repo), "a tracked-file edit must be caught"


def test_a_missing_baseline_fails_loudly_rather_than_passing(repo: Path) -> None:
    """A skipped capture must not read as success."""
    r = subprocess.run(
        "diff <(git status --porcelain -uall) sysop/runtime/2b-baseline.txt",
        cwd=repo, shell=True, capture_output=True, text=True,
        executable="/bin/bash",
    )
    assert r.returncode != 0, "a missing baseline must not report the tree unchanged"
    assert "No such file" in (r.stderr + r.stdout), "the failure must name the missing file"


def test_git_diff_cannot_see_the_breach_this_gate_catches(repo: Path) -> None:
    """The reason the gate uses `status --porcelain` and not `git diff`.

    If this ever fails, `git diff` grew untracked-file awareness and the
    prose justifying the choice needs re-reading.
    """
    (repo / "agent-probe.py").write_text("scratch\n")
    for args in (["diff", "--quiet", "HEAD", "--"], ["diff", "--quiet"],
                 ["diff", "--cached", "--quiet"]):
        r = subprocess.run(["git", *args], cwd=repo, capture_output=True)
        assert r.returncode == 0, (
            f"git {' '.join(args)} unexpectedly saw an untracked file -- the "
            "skill's stated reason for using status --porcelain is now wrong"
        )
