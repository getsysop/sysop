"""Drift guard for Phase 150 / upstream #202 — nothing arms hooks behind you.

``claim_task.sh`` and ``batch_work.sh`` ran ``install_hooks.sh`` on every
worktree creation. Worktrees share one hooks directory, so the call could not
help; what it did instead was push the *claimed branch's*
``sysop/scripts/hooks/*`` into the MAIN checkout's hooks — silently replacing a
consumer's armed checks with the shipped skeletons. GDP would have lost 7
blocking + 15 advisory checks that way, and it was caught by human inspection at
``/review-close``, not by anything in the tooling.

The fix is two deleted blocks, which is exactly the kind of change that
re-accretes: the next author who believes "a worktree needs its own hooks" — the
premise WORKFLOW.md itself stated in three places until this phase — puts it
straight back. Hence guards on both halves, code and prose.

SCOPE, stated honestly rather than implied by the module name:

* Code — ``core/companion/scripts/*.sh`` (non-recursive) and every skill body.
  ``install.sh`` is deliberately NOT scanned by the command-position heuristic:
  its usage heredoc contains lines like ``bash sysop/scripts/install_hooks.sh``
  that are documentation, not invocation, and teaching the heuristic about
  heredocs would cost more reliability than it buys. install.sh has never
  shelled out to the script — it arms via its own ``arm_git_hooks``.
* Prose — the four shipped documents this phase corrected.

Mentions in user-facing messages are fine and deliberate: ``self_check.sh``
prints the arm command when it finds a hook unarmed. The code guard therefore
discriminates by *command position* — a line whose first word is a comment or a
message builtin may name the script; anything else may not. That heuristic has
known false negatives (a message command and an invocation joined by ``&&`` or
``;`` on one line, or a command substitution inside a message); it catches every
shape this codebase actually uses, and the skill-body and prose guards below do
not depend on it.
"""
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "core/companion/scripts"
SKILLS_DIR = REPO_ROOT / "core/skills"
WORKFLOW_MD = REPO_ROOT / "core/companion/docs/WORKFLOW.md"

# Message helpers actually DEFINED in the scanned scripts (`grep -E '^(name)\(\)'`
# over core/companion/scripts/*.sh), plus the two shell builtins. Keep this list
# earned: an unused entry is pure false-negative surface. A new companion script
# that defines its own output helper must add it here.
MESSAGE_CMDS = {"echo", "printf", ":", "ok", "bad", "info"}

COMPANION_SCRIPTS = sorted(
    p for p in SCRIPTS_DIR.glob("*.sh") if p.name != "install_hooks.sh"
)


def _invocation_lines(text):
    """Lines that name install_hooks.sh in command position (not in a message)."""
    hits = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if "install_hooks.sh" not in line:
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        words = stripped.split()
        if not words:
            continue
        # `(cd X && bash …)` should be judged on `cd`, not on the paren.
        first = words[0].lstrip("({&|")
        if first in MESSAGE_CMDS:
            continue
        hits.append((lineno, stripped))
    return hits


def test_the_guard_itself_detects_the_removed_invocation():
    """Non-vacuity, against the real deleted code rather than a retyped copy.

    Reads the pre-Phase-150 claim_task.sh straight out of git, so this cannot
    drift from what actually shipped the way a hand-copied fixture would."""
    path = "core/companion/scripts/claim_task.sh"
    log = subprocess.run(
        ["git", "log", "--format=%H", "-40", "--", path],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
    )
    if log.returncode != 0:
        pytest.skip("git history unavailable")

    # Walk back to the most recent revision that genuinely INVOKED the script.
    # Checking for the literal string is not enough: the post-removal body still
    # names it in the explanatory comment, which is exactly the distinction this
    # guard exists to draw.
    hits = []
    for sha in log.stdout.split():
        blob = subprocess.run(
            ["git", "show", f"{sha}:{path}"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )
        if blob.returncode != 0:
            continue
        hits = _invocation_lines(blob.stdout)
        if hits:
            break
    else:
        pytest.skip("no revision invoking install_hooks.sh within the searched history")
    assert hits, (
        "the guard does not detect the invocation it was written to catch — "
        "it would pass on the very code Phase 150 removed"
    )
    # The paired `echo` advising a manual re-run must NOT count as an invocation.
    assert all(not line.startswith("echo") for _, line in hits)


def test_self_check_mention_is_not_flagged():
    """The advisory 'arm: bash …install_hooks.sh' message must stay allowed."""
    text = (SCRIPTS_DIR / "self_check.sh").read_text()
    assert "install_hooks.sh" in text, "fixture drifted — self_check no longer mentions it"
    assert _invocation_lines(text) == []


def test_companion_script_set_is_not_empty():
    """A moved/renamed scripts dir must fail loudly, not shrink the guard to
    an empty parametrization that pytest reports as a skip."""
    assert COMPANION_SCRIPTS, f"no companion scripts found under {SCRIPTS_DIR}"


@pytest.mark.parametrize("script", COMPANION_SCRIPTS, ids=lambda p: p.name)
def test_no_companion_script_invokes_install_hooks(script):
    hits = _invocation_lines(script.read_text())
    assert not hits, (
        f"{script.name} invokes install_hooks.sh at {[n for n, _ in hits]}.\n"
        "Arming from a lifecycle script writes into the SHARED hooks directory "
        "and can replace a consumer's armed checks with the shipped skeletons "
        "(upstream #202). Worktrees never need their own arm."
    )


def test_no_skill_tells_an_agent_to_arm_hooks():
    """Skills are where lifecycle *orchestration* lives — a 'then arm the hooks
    in the worktree' instruction re-creates #202 exactly, with no script change
    for the guard above to catch. No skill mentions the script today; keep it
    that way rather than adjudicate the wording of a future one."""
    offenders = [
        str(p.relative_to(REPO_ROOT))
        for p in SKILLS_DIR.rglob("*.md")
        if "install_hooks" in p.read_text()
    ]
    assert not offenders, (
        f"skill(s) reference install_hooks.sh: {offenders}. Arming is a human, "
        "main-checkout action — a skill instructing it inside a worktree "
        "re-creates upstream #202."
    )


class TestWorktreePremiseIsGoneFromDocs:
    """The code bug was the expression of a documented false premise. Leaving
    the prose in place invites a reader to re-create the damage by hand — so
    every surface this phase corrected is pinned, including the script header
    that a reader consults precisely when deciding to arm by hand."""

    PROSE_SURFACES = [
        "core/companion/docs/WORKFLOW.md",
        "core/companion/docs/WORKFLOW_GUIDE.md",
        "docs/install-and-update.md",
        "core/companion/scripts/install_hooks.sh",
    ]

    STALE_PHRASINGS = [
        "Must be re-installed after creating a new worktree",
        "after cloning the repo or creating a worktree",
        "re-run after new worktree",
        "Run this after cloning or creating a worktree",
        "Install hooks in the worktree",
    ]

    @pytest.mark.parametrize("surface", PROSE_SURFACES)
    @pytest.mark.parametrize("stale", STALE_PHRASINGS)
    def test_stale_worktree_phrasing_is_absent(self, surface, stale):
        text = (REPO_ROOT / surface).read_text()
        assert stale not in text, (
            f"{surface} still implies a worktree needs its own hook install: {stale!r}"
        )

    def test_the_correction_is_stated(self):
        text = WORKFLOW_MD.read_text()
        assert "Worktrees do not need their own install" in text
        assert "core.hooksPath" in text, "the skip behavior is undocumented"
