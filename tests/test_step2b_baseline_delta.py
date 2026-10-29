"""Step 2b's primary-tree baseline/delta (Phase 200, Q-194 leg 2).

These tests exist because the first version of this fix was **inert**: the
baseline capture was written into a blockquote 82 lines *after* the spawn it
had to precede, so an operator reading the file top to bottom captured the
baseline with the breach already in it and the assertion then printed
"primary tree unchanged by 2b" over the very mutation it was built to catch.
An adversarial reviewer found it by walking the file in reading order.

So the ordering is tested structurally, and the commands are tested by
running them -- prose asserting an order is not a test of it.

Since Phase 421 (`Q-665`) the capture is `review_pins.py baseline` and the five assertions are
`review_pins.py check`: under `dontAsk` the step's `rm -f`, its `>` redirects and its
`diff <(…)` lines bound no rule. Every property below is held against those two calls, run as the
skill prescribes them, with the script path substituted (a fixture has no `sysop/scripts/`).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import sys

import pytest
from skill_runner_text import text_of

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "core/skills/review-close/SKILL.md"


def _lines() -> list[str]:
    return text_of(SKILL).split("\n")


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
    return re.match(r"^\s*(?:\d+\.\s+|Then )[Ss]pawn an Agent with:", ln) is not None


def _is_placement_step(ln: str) -> bool:
    """Match Phase 290's reviewer-placement block, which now opens the spawn step.

    Placement is the first act of item 3 that touches git state (it runs
    `git worktree add`), so the baseline must precede IT, not merely the
    `Agent` call two paragraphs later. Content-keyed for the same reason
    `_is_spawn_step` is: inserting a step renumbers the list.
    """
    return re.match(r"^\s*\d+\.\s+\*\*Create each reviewer's checkout", ln) is not None


SCRIPTS = REPO / "core/companion/scripts"
CAPTURE = "python3 sysop/scripts/review_pins.py baseline"
CHECK = "python3 sysop/scripts/review_pins.py check"
CLEAN = ["no agent worktrees", "no agent branches", "primary tree unchanged by 2b",
         "local config unchanged by 2b", "no pinned checkouts"]


# --------------------------------------------------------------------------
# ordering -- the defect that made v1 inert
# --------------------------------------------------------------------------

def test_the_baseline_capture_precedes_the_agent_spawn_in_reading_order() -> None:
    """The whole gate is inert if this inverts. Non-negotiable. The placement is the first act
    of item 3 that touches git state, so the capture must precede it too."""
    capture = _line_of(lambda l: l.strip() == CAPTURE, "the baseline capture command")
    placement = _line_of(_is_placement_step, "the reviewer placement step")
    spawn = _line_of(_is_spawn_step, "the agent spawn step")
    assert capture < placement < spawn, (
        f"the baseline capture is at :{capture}, the placement at :{placement} and the spawn at "
        f":{spawn} -- an operator reading top to bottom captures the baseline AFTER the agents "
        "have already run, which records any breach as pre-existing and makes the delta "
        "assertion certify the tree clean"
    )


def test_the_delta_assertion_comes_after_the_spawn() -> None:
    """The other half of the ordering: comparing before the agents run is vacuous."""
    spawn = _line_of(_is_spawn_step, "the agent spawn step")
    assertion = _line_of(lambda l: l.lstrip("> ").strip() == CHECK, "the delta assertion")
    assert spawn < assertion, "the delta must be compared after the agents have run"


def test_capture_and_assertion_use_the_same_untracked_mode() -> None:
    """`--untracked-files=all` on one side only silently changes what the diff means. Plain
    `--porcelain` collapses an untracked directory to one `?? dir/` line, so an agent writing
    inside an already-untracked directory is invisible. One function serves both ends."""
    src = (SCRIPTS / "review_pins.py").read_text(encoding="utf-8")
    assert src.count("git('status', '--porcelain', '-uall')") == 1, "one status read, in tree_now()"
    assert src.count("tree_now()") == 3, "the capture and the check must read the tree one way"


def test_the_capture_clears_a_stale_baseline_first(repo: Path) -> None:
    """A capture must never leave a PREVIOUS close's file to diff against: it removes both
    baselines before it reads either, so one that fails part-way leaves nothing behind."""
    src = (SCRIPTS / "review_pins.py").read_text(encoding="utf-8")
    body = src[src.index("def cmd_baseline() -> None:"):src.index("def cmd_add(")]
    assert body.index("old.unlink()") < body.index("tree_now()"), (
        "the capture reads the tree before removing the old baselines")
    (repo / "sysop/runtime").mkdir(parents=True)
    stale = repo / "sysop/runtime/2b-baseline.txt"
    stale.write_text("?? from an earlier close\n")
    subprocess.run([sys.executable, str(SCRIPTS / "review_pins.py"), "baseline"], cwd=repo,
                   check=True, capture_output=True)
    assert "from an earlier close" not in stale.read_text()
    # And a capture that fails part-way leaves none (lens B): a corrupt index fails the status
    # read after the removal.
    stale.write_text("?? from an earlier close\n")
    (repo / ".git" / "index").write_bytes(b"garbage")
    r = subprocess.run([sys.executable, str(SCRIPTS / "review_pins.py"), "baseline"], cwd=repo,
                       capture_output=True, text=True)
    assert r.returncode == 2 and r.stdout.startswith("STOP:"), r.stdout
    assert not stale.exists() and not (repo / "sysop/runtime/2b-config-baseline.txt").exists()


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


def _shipped(command: str) -> str:
    """The command the skill prescribes, located in the skill and pointed at the shipped script."""
    found = [l.lstrip("> ").strip() for l in _lines() if l.lstrip("> ").strip() == command]
    assert found, f"the skill no longer prescribes {command!r}"
    return found[0].replace("python3 sysop/scripts/", f'"{sys.executable}" "{SCRIPTS}/').replace(
        ".py ", '.py" ', 1)


def _capture(repo: Path) -> None:
    subprocess.run(_shipped(CAPTURE), cwd=repo, shell=True, check=True, capture_output=True)


def _check(repo: Path) -> list[str]:
    return subprocess.run(_shipped(CHECK), cwd=repo, shell=True, capture_output=True,
                          text=True).stdout.splitlines()


def _delta(repo: Path) -> bool:
    """True when the tree assertion PASSES (tree unchanged)."""
    return "primary tree unchanged by 2b" in _check(repo)


def _cfg_delta(repo: Path) -> bool:
    """True when the config assertion PASSES (config unchanged)."""
    return "local config unchanged by 2b" in _check(repo)


def test_a_clean_round_prints_the_five_clean_lines(repo: Path) -> None:
    _capture(repo)
    assert _check(repo) == CLEAN


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
    """Why the untracked mode is required, not cosmetic: plain --porcelain reports `?? scratch/`
    before AND after, so the breach cancels in the diff and the gate passes over it."""
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
    """A skipped capture must not read as success, and must say why."""
    out = _check(repo)
    assert "primary tree unchanged by 2b" not in out
    assert any(l.startswith("MISSING BASELINE: sysop/runtime/2b-baseline.txt") for l in out), out


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
# --------------------------------------------------------------------------

def test_the_capture_writes_a_config_baseline_too(repo: Path) -> None:
    _capture(repo)
    assert (repo / "sysop/runtime/2b-config-baseline.txt").is_file(), (
        "step 2 must snapshot the local config as well as the tree; a spawn "
        "writes to both and only one was being captured"
    )


def test_the_assertion_has_a_fourth_check_for_config(repo: Path) -> None:
    _capture(repo)
    assert _check(repo)[3] == "local config unchanged by 2b"


def test_the_prose_and_the_check_agree_on_the_count() -> None:
    """A count word in prose is a claim the check can falsify."""
    text = text_of(SKILL)
    assert "assert all five are clean" in text and "It runs the five in order" in text
    for stale in ("three", "four"):
        assert f"assert all {stale} are clean" not in text, (
            f"the prose still says {stale} while the check runs five"
        )


def test_an_unchanged_config_does_not_false_fail(repo: Path) -> None:
    _capture(repo)
    assert _cfg_delta(repo) is True


def test_the_hookspath_rewrite_is_caught(repo: Path) -> None:
    """The measured harness behaviour: relative -> absolute, same directory."""
    _git(repo, "config", "--local", "core.hooksPath", ".githooks")
    _capture(repo)
    _git(repo, "config", "--local", "core.hooksPath", str(repo / ".githooks"))
    assert _cfg_delta(repo) is False, (
        "the assertion passed over a rewritten core.hooksPath -- this is the "
        "defect Q-049 reports and the whole reason for the fourth check"
    )


def test_the_shipped_restore_puts_the_relative_value_back(repo: Path) -> None:
    """The remedy, run: `restore-hooks-path` reads the baseline, not memory."""
    _git(repo, "config", "--local", "core.hooksPath", ".githooks")
    _capture(repo)
    _git(repo, "config", "--local", "core.hooksPath", str(repo / ".githooks"))
    r = subprocess.run([sys.executable, str(SCRIPTS / "review_pins.py"), "restore-hooks-path"],
                       cwd=repo, capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.startswith("RESTORED: core.hooksPath .githooks"), r.stdout
    assert _cfg_delta(repo) is True


def test_a_repo_with_no_hookspath_is_unaffected(repo: Path) -> None:
    """The precondition, guarded: only a repo that set the key is exposed. A
    clean fourth check here is the ordinary result, not an inert check."""
    _capture(repo)
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
    text = text_of(SKILL)
    i = text.index("The fourth check's delta")
    para = text[i:i + 1400]
    assert "core.hookspath" in para, (
        "the remedy must warn that the key is lower-cased in --list output, "
        "or a reader writes the grep that reports clean over the rewrite"
    )
    assert "**Match on the lower-cased key.**" in para, (
        "the lower-cased-key directive was removed; the token alone is not the "
        "instruction, and a reader who skims takes the camelCase spelling"
    )
    assert "python3 sysop/scripts/review_pins.py restore-hooks-path" in para, "no restore command"


def test_a_missing_config_baseline_fails_loudly_rather_than_passing(repo) -> None:
    """The tree baseline has this guard, and so must the config one."""
    _capture(repo)
    (repo / "sysop/runtime/2b-config-baseline.txt").unlink()
    out = _check(repo)
    assert "local config unchanged by 2b" not in out
    assert "MISSING BASELINE: sysop/runtime/2b-config-baseline.txt (run baseline before the first spawn)" in out
    text = text_of(SKILL)
    assert "third or fourth check prints `MISSING BASELINE:`" in text, (
        "the loud-failure note covers only one of the two baselines"
    )
