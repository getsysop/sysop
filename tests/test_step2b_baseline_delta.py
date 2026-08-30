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


# --------------------------------------------------------------------------
# Phase 240 -- the config baseline (Q-049)
#
# Spawning with isolation: "worktree" rewrites a RELATIVE core.hooksPath to an
# absolute path in the repo's shared --local config and never restores it. The
# tree snapshot above cannot see that: it is not a file change.
#
# These tests EXTRACT the prescribed commands from the skill and run them.
# The helpers above retype theirs, which is why a shipped gate could once be
# weakened with the suite green -- a test that types its own copy of a command
# is testing its own copy. The three EXECUTION rows below extract and run;
# the prose-pin rows do retype, deliberately and only where the thing being
# pinned is wording rather than a command. An earlier comment here said
# "Nothing below is retyped", which was false for 5 of the 8 rows.
# --------------------------------------------------------------------------

def _fence_after(anchor: str) -> list[str]:
    """The commands in the first ```bash fence at/after `anchor`, blockquote
    prefixes stripped. Reads the shipped file -- never a copy of it."""
    raw = SKILL.read_text().split("\n")
    start = next(i for i, ln in enumerate(raw) if anchor in ln)
    body, opened = [], False
    for ln in raw[start:]:
        # Strip the blockquote PREFIX, not a character set. `lstrip("> ")`
        # eats leading `>` and spaces greedily, so `>&2 echo x` became
        # `&2 echo x` and `>> f` became `f` -- and these lines are executed.
        stripped = re.sub(r"^(?:[ \t]*>)*[ \t]*", "", ln).rstrip()
        if stripped.startswith("```"):
            if opened:
                break
            opened = True
            continue
        # Comments are not commands. Pinning arity and index over a list that
        # includes them makes an ordinary `# why` addition redden the suite --
        # the round measured that at 2 of its 4 false kills.
        if opened and stripped and not stripped.startswith("#"):
            body.append(stripped)
    assert body, f"no fenced commands found after {anchor!r}"
    return body


def test_the_capture_writes_a_config_baseline_too() -> None:
    cmds = _fence_after("Capture the primary-tree baseline")
    joined = "\n".join(cmds)
    assert "2b-config-baseline.txt" in joined, (
        "step 2 must snapshot the local config as well as the tree; a spawn "
        "writes to both and only one was being captured"
    )
    assert "git config --local --list" in joined
    assert "rm -f" in joined and "2b-config-baseline.txt" in cmds[0], (
        "the stale config baseline must be cleared with the tree one, or a "
        "close that skips the capture diffs against an earlier close's config"
    )


def test_the_assertion_has_a_fourth_command_for_config() -> None:
    cmds = _fence_after("assert all four are clean")
    assert len(cmds) == 4, f"expected 4 assertion commands, got {len(cmds)}: {cmds}"
    assert any("config --local --list" in c and "2b-config-baseline.txt" in c
               for c in cmds), cmds


def test_the_prose_and_the_fence_agree_on_the_command_count() -> None:
    """A count word in prose is a claim the fence can falsify.

    An earlier version of this docstring credited Phase 200's inert gate to
    "prose and mechanism drifting apart". Phase 240's round checked: Phase 200
    records an ORDERING defect -- the baseline capture sat 82 lines after the
    spawn it had to precede. The check stands on its own terms; the precedent
    it cited was not real.
    """
    text = SKILL.read_text()
    assert "assert all four are clean" in text
    assert "assert all three are clean" not in text, (
        "the prose still says three while the fence ships four"
    )


def _cfg_capture(repo: Path) -> None:
    """Run the SHIPPED capture commands, not a retyped twin."""
    for cmd in _fence_after("Capture the primary-tree baseline"):
        subprocess.run(cmd, cwd=repo, shell=True, check=True,
                       executable="/bin/bash")


def _cfg_delta(repo: Path) -> bool:
    """True when the SHIPPED config assertion PASSES (config unchanged)."""
    cmd = next(c for c in _fence_after("assert all four are clean")
               if "2b-config-baseline.txt" in c)
    return subprocess.run(cmd, cwd=repo, shell=True, capture_output=True,
                          text=True, executable="/bin/bash").returncode == 0


def test_an_unchanged_config_does_not_false_fail(repo: Path) -> None:
    _cfg_capture(repo)
    assert _cfg_delta(repo) is True


def test_the_hookspath_rewrite_is_caught(repo: Path) -> None:
    """The measured harness behaviour: relative -> absolute, same directory."""
    _git(repo, "config", "--local", "core.hooksPath", ".githooks")
    _cfg_capture(repo)
    _git(repo, "config", "--local", "core.hooksPath", str(repo / ".githooks"))
    assert _cfg_delta(repo) is False, (
        "the assertion passed over a rewritten core.hooksPath -- this is the "
        "defect Q-049 reports and the whole reason for the fourth command"
    )


def test_a_repo_with_no_hookspath_is_unaffected(repo: Path) -> None:
    """The precondition, guarded: only a repo that set the key is exposed. A
    clean fourth command here is the ordinary result, not an inert check."""
    _cfg_capture(repo)
    assert _cfg_delta(repo) is True


def test_a_targeted_grep_for_the_camelcase_key_would_report_clean(repo: Path) -> None:
    """Why this is a diff against a baseline and not a probe for one key.
    `git config --list` lower-cases the key, so a detector grepping for
    `core.hooksPath` finds nothing and certifies a rewritten repo as clean."""
    _git(repo, "config", "--local", "core.hooksPath", str(repo / ".githooks"))
    listed = subprocess.run(["git", "config", "--local", "--list"], cwd=repo,
                            capture_output=True, text=True, check=True).stdout
    assert "core.hookspath=" in listed
    assert "core.hooksPath=" not in listed, (
        "if git ever preserves the camelCase key here, the lower-case warning "
        "in the skill's remedy prose is stale and should be re-derived"
    )


def test_the_remedy_names_the_lowercased_key_trap() -> None:
    text = SKILL.read_text()
    i = text.index("The fourth command's delta")
    para = text[i:i + 1400]
    assert "core.hookspath" in para, (
        "the remedy must warn that the key is lower-cased in --list output, "
        "or a reader writes the grep that reports clean over the rewrite"
    )
    # A06 survived the first battery: the token `core.hookspath` also appears
    # in the explanatory clause, so removing the DIRECTIVE left the token
    # behind and this test passed over it. Pin the directive itself.
    assert "**Match on the lower-cased key.**" in para, (
        "the lower-cased-key directive was removed; the token alone is not the "
        "instruction, and a reader who skims takes the camelCase spelling"
    )
    assert "git config --local core.hooksPath" in para, "no restore command"


def test_a_missing_config_baseline_fails_loudly_rather_than_passing(repo) -> None:
    """G04: the tree baseline has this guard and the config baseline did not.

    A `diff` against a file that does not exist exits 2, which is non-zero, so
    the assertion fails -- but the skill's prose is what tells the operator
    that means "the capture was skipped" rather than "an agent mutated
    something". Both must hold, and the round found only the tree half tested.
    """
    # capture the tree baseline only, as a close that skipped step 2's new line
    subprocess.run(
        "mkdir -p sysop/runtime && git status --porcelain -uall > sysop/runtime/2b-baseline.txt",
        cwd=repo, shell=True, check=True, executable="/bin/bash")
    assert not (repo / "sysop/runtime/2b-config-baseline.txt").exists()
    assert _cfg_delta(repo) is False, (
        "a missing config baseline reported the config unchanged -- a skipped "
        "capture must fail loudly, not certify"
    )
    text = SKILL.read_text()
    assert "third or fourth command reports `No such file or directory`" in text, (
        "the loud-failure note covers only one of the two baselines"
    )
