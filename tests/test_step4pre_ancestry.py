"""Phase 304 — EXECUTABLE guards for Step 4-pre's integration-branch ancestry (`Q-521`).

Why this module exists. Step 4-pre used to cut the integration branch from
`origin/<default branch>` and sweep the local-only `main` commits across with
`git cherry-pick origin/main..main`. The cherry-pick REWRITES those commits, so
neither the rollback nor the re-claim stays an ancestor of anything an approved
branch knows, and the merge-base collapses to `origin/main`. Step 4a's three-way
merge then resolves `tasks/index.yml` against a base that never saw the claim
flip, takes the branch's stale `open`, and reports `CLEAN`. The validator stays
green because `open` is a valid status, so **a green suite certified this**.

**Scope: Step 4a's PUBLISHED arm (`git merge --no-ff`).** The local-only arm rebases, which
replays patches rather than resolving trees against a base, and was never vulnerable --
measured, and pinned by `test_the_local_only_arm_was_never_vulnerable`. The first version
of this phase's record said the population was every approved branch cut from a rollback;
its round measured that wrong, and the two arm tests exist so the scope is checked rather
than asserted.

Two things about the fixture, both of which produced a false negative before the
real result and one of which cost an adversarial round its verdict:

  1. **Identical SHAs.** A cherry-pick onto the same parent, with the same tree,
     author, author date and message, produces a BYTE-IDENTICAL commit when the
     committer date also matches. The merge-base is then the rollback commit, the
     flip survives, and the defect looks unreproducible. Every fixture here forces
     distinct committer dates, and `test_the_control_is_not_vacuous` pins that.
  2. **Asserting on the merge's exit status alone.** A conflict and a silent
     revert are different outcomes and only one of them is the defect. These
     tests assert on the MERGE-BASE and on the resulting `status:` value, never on
     the exit status by itself.

The control (`test_the_cherry_pick_shape_reverts_the_claim_flip`) exists so the
prescribed-shape tests cannot pass vacuously: it reproduces the defect with the
old shape in the same fixture, so if the fixture ever stops exposing it, the
control goes green and this module says so.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from shape_lib import fenced_blocks, live_command_lines

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "core" / "skills" / "review-close" / "SKILL.md"

_GIT_DISCOVERY_VARS = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CEILING_DIRECTORIES",
)

# Distinct on purpose. `_BASE_DATE` stamps the original commits; `_PICK_DATE` stamps
# the cherry-pick or the base merge. If these two are ever made equal, the cherry-pick
# reproduces byte-identical SHAs and the control below stops reproducing anything.
_BASE_DATE = "2026-01-01T00:00:00Z"
_PICK_DATE = "2026-06-06T06:06:06Z"
_UPSTREAM_DATE = "2026-05-05T05:05:05Z"


def _hermetic_env(**extra: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_DISCOVERY_VARS}
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_SYSTEM=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
        GIT_AUTHOR_NAME="Fixture",
        GIT_AUTHOR_EMAIL="fixture@example.invalid",
        GIT_COMMITTER_NAME="Fixture",
        GIT_COMMITTER_EMAIL="fixture@example.invalid",
        GIT_AUTHOR_DATE=_BASE_DATE,
        GIT_COMMITTER_DATE=_BASE_DATE,
    )
    env.update(extra)
    return env


def _git(cwd: Path, *args: str, check: bool = True, **envextra: str):
    return subprocess.run(
        ["git", *args], cwd=cwd, env=_hermetic_env(**envextra),
        capture_output=True, encoding="utf-8", check=check,
    )


def _index(status: str, title: str, body: str) -> str:
    """A realistic multi-field entry.

    Deliberately not the three-line shape: on a three-line entry `title:` and
    `status:` share a diff hunk, which changes the outcome of the identical-SHA
    arm from a silent revert to a conflict and so muddies what is being pinned.
    """
    return (
        "schema_version: 1\n"
        "tasks:\n"
        "  - id: FEAT-0042\n"
        f'    title: "{title}"\n'
        "    phase: 12\n"
        f"    status: {status}\n"
        "    effort: Medium\n"
        "    blast_radius: single-module\n"
        "    user_action: false\n"
        "    depends_on: []\n"
        "    surfaced_by: []\n"
        "    branch: feat/widget\n"
        f"    body: {body}\n"
    )


def _build(tmp_path: Path, *, edit: str = "title", advance_origin: bool = False) -> dict:
    """Build the four-condition fixture and return the interesting SHAs.

    C0 (pushed)  task is `in_progress`
    C1 (local)   rollback `in_progress` -> `open`
    C2 (local)   re-claim `open` -> `in_progress`   => net zero against origin/main
    feat/widget  cut from C1, so its base copy carries `open`
    """
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(origin)],
                   env=_hermetic_env(), check=True, capture_output=True)
    work.mkdir()
    _git(work, "init", "-q", ".")
    _git(work, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(work, "remote", "add", "origin", str(origin))
    (work / "tasks").mkdir()
    idx = work / "tasks" / "index.yml"

    idx.write_text(_index("in_progress", "Original title", "open/FEAT-0042.md"))
    (work / "README.md").write_text("base\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "C0 baseline")
    c0 = _git(work, "rev-parse", "HEAD").stdout.strip()
    _git(work, "push", "-q", "origin", "main")

    idx.write_text(_index("open", "Original title", "open/FEAT-0042.md"))
    _git(work, "commit", "-qam", "C1 rollback FEAT-0042 to open")
    c1 = _git(work, "rev-parse", "HEAD").stdout.strip()

    idx.write_text(_index("in_progress", "Original title", "open/FEAT-0042.md"))
    _git(work, "commit", "-qam", "C2 claim FEAT-0042")

    _git(work, "checkout", "-q", "-b", "feat/widget", c1)
    if edit == "title":
        idx.write_text(_index("open", "REVISED title", "open/FEAT-0042.md"))
    elif edit == "status_done":
        # The branch edits its OWN task's `status:` -- the one field the integration side
        # also moves. Under the old shape this merged silently to `done`; under the fix the
        # two sides genuinely conflict, which is correct and is a NEW state for Step 4a.
        idx.write_text(_index("done", "Original title", "open/FEAT-0042.md"))
    elif edit == "untouched":
        # The branch never touches tasks/index.yml at all. Its base copy still
        # carries `open`, which is the whole of what the merge needs.
        (work / "src.txt").write_text("unrelated source change\n")
        _git(work, "add", "src.txt")
    else:  # pragma: no cover - guard against a typo in a future caller
        raise AssertionError(f"unknown edit shape {edit!r}")
    _git(work, "commit", "-qam", "branch work")

    if advance_origin:
        up = tmp_path / "up"
        subprocess.run(["git", "clone", "-q", str(origin), str(up)],
                       env=_hermetic_env(), check=True, capture_output=True)
        (up / "README.md").write_text("base\ndep\n")
        _git(up, "commit", "-qam", "deps: bump", GIT_COMMITTER_DATE=_UPSTREAM_DATE)
        _git(up, "push", "-q", "origin", "main")

    _git(work, "checkout", "-q", "main")
    _git(work, "fetch", "-q", "origin", "main")
    return {"work": work, "c0": c0, "c1": c1,
            "origin_tip": _git(work, "rev-parse", "origin/main").stdout.strip()}


def _step4pre(work: Path, shape: str) -> None:
    """Run Step 4-pre's integration-branch shape.

    `prescribed` is what the skill says today; `cherry_pick` is what it said
    before Phase 304 and is kept only as the control.
    """
    if shape == "cherry_pick":
        _git(work, "checkout", "-q", "-b", "integ", "origin/main")
        _git(work, "cherry-pick", "origin/main..main", GIT_COMMITTER_DATE=_PICK_DATE)
    elif shape == "prescribed":
        _git(work, "checkout", "-q", "-b", "integ", "main")
        _git(work, "merge", "--no-edit", "origin/main", GIT_COMMITTER_DATE=_PICK_DATE)
    else:  # pragma: no cover
        raise AssertionError(f"unknown shape {shape!r}")


def _status_of(work: Path) -> str:
    text = (work / "tasks" / "index.yml").read_text()
    m = re.search(r"^    status: (\S+)", text, re.M)
    assert m is not None, f"no status field in:\n{text}"
    return m.group(1)


# --------------------------------------------------------------------------------
# The defect, and the control that proves the fixture exposes it
# --------------------------------------------------------------------------------

def test_the_cherry_pick_shape_reverts_the_claim_flip(tmp_path: Path) -> None:
    """CONTROL. The pre-Phase-304 shape loses the flip, silently.

    If this ever goes green the fixture has stopped reproducing `Q-521`, and every
    other test in this module is passing for a reason that is no longer the
    mechanism. Treat a failure here as "the fixture broke", not "the bug is fixed".
    """
    f = _build(tmp_path)
    work = f["work"]
    _step4pre(work, "cherry_pick")

    assert _git(work, "merge-base", "integ", "feat/widget").stdout.strip() == f["c0"], (
        "the cherry-pick should have collapsed the merge-base to origin/main"
    )
    merged = _git(work, "merge", "--no-edit", "feat/widget", check=False)
    assert merged.returncode == 0, "the defect is the SILENT path; a conflict is a different case"
    assert _status_of(work) == "open", "control did not reproduce Q-521"


def test_the_control_is_not_vacuous(tmp_path: Path) -> None:
    """The cherry-pick must actually rewrite the commits.

    Same parent, tree, author, author date and message: the ONLY thing keeping
    the rewritten commit distinct is the committer date. Phase 303's adversarial
    round ran a fixture without this property, got identical SHAs, and reported
    `Q-521` irreproducible.
    """
    f = _build(tmp_path)
    work = f["work"]
    _step4pre(work, "cherry_pick")
    picked_c1 = _git(work, "rev-parse", "integ~1").stdout.strip()
    assert picked_c1 != f["c1"], (
        "cherry-pick reproduced a byte-identical SHA -- the fixture is testing nothing. "
        "_BASE_DATE and _PICK_DATE must differ."
    )


# --------------------------------------------------------------------------------
# The prescribed shape
# --------------------------------------------------------------------------------

@pytest.mark.parametrize("edit", ["title", "untouched"])
@pytest.mark.parametrize("advance_origin", [False, True])
def test_prescribed_shape_preserves_the_flip(
    tmp_path: Path, edit: str, advance_origin: bool
) -> None:
    """Cutting from local `main` keeps the rollback commit as a real ancestor.

    `edit="untouched"` is the case the filing said could not happen: it claimed the
    branch had to edit the same entry, far enough from `status:` that the hunks do
    not overlap. A branch that never opens `tasks/index.yml` reverts the flip just
    the same under the old shape, because the collapse is about ancestry, not hunks.
    """
    f = _build(tmp_path, edit=edit, advance_origin=advance_origin)
    work = f["work"]
    _step4pre(work, "prescribed")

    assert _git(work, "merge-base", "integ", "feat/widget").stdout.strip() == f["c1"], (
        "merge-base must be the rollback commit, not its parent"
    )
    merged = _git(work, "merge", "--no-edit", "feat/widget", check=False)
    assert merged.returncode == 0, f"merge should be clean: {merged.stdout}{merged.stderr}"
    assert _status_of(work) == "in_progress", "the claim flip was reverted"


def _step4a_local_only(work: Path) -> None:
    """Step 4a's LOCAL-ONLY arm, verbatim: rebase onto the merge target, then ff.

    This is the arm `SKILL.md` calls *"the common case: `/claim-task` branches are usually
    never pushed under `pr` policy"*.
    """
    _git(work, "checkout", "-q", "feat/widget")
    _git(work, "rebase", "integ", GIT_COMMITTER_DATE=_PICK_DATE)
    _git(work, "checkout", "-q", "integ")
    _git(work, "merge", "--ff-only", "feat/widget")


def test_the_local_only_arm_was_never_vulnerable(tmp_path: Path) -> None:
    """The defect's population is the PUBLISHED arm, and this records why.

    Phase 304's first record said *"every approved branch cut from a rollback"* and its
    round measured that wrong: run the OLD shape and then Step 4a's local-only arm and the
    flip SURVIVES. A rebase replays each commit's PATCH against its real parent, and the
    branch never changed `status:` -- so there is no status hunk to replay and no collapsed
    merge-base to resolve against. Only the three-way merge reads the collapsed base.

    Kept as a test rather than a sentence because the correct scope of the defect is what
    the next editor will price a change to this step with.
    """
    f = _build(tmp_path, edit="title")
    work = f["work"]
    _step4pre(work, "cherry_pick")
    assert _git(work, "merge-base", "integ", "feat/widget").stdout.strip() == f["c0"], (
        "control: the old shape must still have collapsed the merge-base"
    )
    _step4a_local_only(work)
    assert _status_of(work) == "in_progress", (
        "the local-only arm reverted the flip -- the defect is wider than the published "
        "arm and the record scoping it to the published arm is now wrong"
    )
    assert "REVISED title" in (work / "tasks" / "index.yml").read_text()


def test_the_fix_holds_on_the_local_only_arm_too(tmp_path: Path) -> None:
    """The arm that was never vulnerable must not be broken BY the fix."""
    f = _build(tmp_path, edit="title")
    work = f["work"]
    _step4pre(work, "prescribed")
    _step4a_local_only(work)
    assert _status_of(work) == "in_progress"
    assert "REVISED title" in (work / "tasks" / "index.yml").read_text()


def test_a_branch_editing_its_own_status_now_CONFLICTS_rather_than_merging(tmp_path: Path) -> None:
    """The fix creates a new state, and it is the right one -- but it is a state.

    A branch that edits its own task's `status:` touches the one field the integration side
    also moves. Under the cherry-pick shape the merge-base had never seen the flip, so the
    branch's value won **silently**: measured, `status = done`. With ancestry preserved the
    two sides conflict, `git merge` exits non-zero, and the close stops.

    Stopping is correct -- two actors disagreeing about a task's status is exactly what a
    human should adjudicate -- but Phase 304's first test set asserted `returncode == 0` on
    every prescribed-shape case, so this outcome was untested and Step 4a's conflict prose
    was written for `tasks/index.yml` APPEND conflicts, not a `status:` field conflict.
    Found by the phase's round.
    """
    f = _build(tmp_path, edit="status_done")
    work = f["work"]

    # Control: the old shape took the branch's value with no conflict at all.
    _step4pre(work, "cherry_pick")
    assert _git(work, "merge", "--no-edit", "feat/widget", check=False).returncode == 0
    assert _status_of(work) == "done", "control: the old shape merged this silently"

    _git(work, "checkout", "-q", "main")
    _git(work, "branch", "-q", "-D", "integ")
    _step4pre(work, "prescribed")
    merged = _git(work, "merge", "--no-edit", "feat/widget", check=False)
    assert merged.returncode != 0, (
        "a branch editing its own `status:` merged cleanly -- one side's value was taken "
        "without anyone being asked, which is the class Q-521 is about"
    )
    assert "index.yml" in (merged.stdout + merged.stderr)


def test_prescribed_shape_keeps_the_branch_work(tmp_path: Path) -> None:
    """The fix must not trade one loss for another."""
    f = _build(tmp_path, edit="title")
    work = f["work"]
    _step4pre(work, "prescribed")
    _git(work, "merge", "--no-edit", "feat/widget")
    assert "REVISED title" in (work / "tasks" / "index.yml").read_text()


def test_prescribed_shape_still_builds_on_the_current_base(tmp_path: Path) -> None:
    """The property that motivated cutting from `origin/main` is kept, not traded.

    The PR's required checks must run against whatever landed since the run
    started, so the tip of `origin/main` has to be an ancestor of the merge target.
    """
    f = _build(tmp_path, advance_origin=True)
    work = f["work"]
    _step4pre(work, "prescribed")
    contained = _git(work, "merge-base", "--is-ancestor", f["origin_tip"], "integ",
                     check=False)
    assert contained.returncode == 0, "integration branch is not built on the current base"
    assert "dep" in (work / "README.md").read_text(), "upstream commit was lost"


def test_a_branch_main_pending_doc_is_now_contained(tmp_path: Path) -> None:
    """Step 4c step 1b's ancestry test stops false-positiving on `branch: main`.

    `/document-work` run on `main` writes a pending-doc whose frontmatter is
    `branch: main`. Under the cherry-pick shape that doc scored non-zero on EVERY
    `pr`-policy close and was classified NOT-MERGED while its content was provably
    in the merge target. Cutting from local `main` makes `main` a real ancestor.
    """
    f = _build(tmp_path)
    work = f["work"]

    _step4pre(work, "cherry_pick")
    before = _git(work, "rev-list", "--count", "main", "^HEAD").stdout.strip()
    assert before != "0", "control: the old shape must misclassify"

    _git(work, "checkout", "-q", "main")
    _git(work, "branch", "-q", "-D", "integ")
    _step4pre(work, "prescribed")
    after = _git(work, "rev-list", "--count", "main", "^HEAD").stdout.strip()
    assert after == "0", "a `branch: main` pending doc is still misclassified NOT-MERGED"


# --------------------------------------------------------------------------------
# Drift guards — scoped to Step 4-pre, because the file legitimately discusses
# cherry-picks elsewhere (Step 4c step 1b's fallback still rests on one).
# --------------------------------------------------------------------------------

def _step4pre_text() -> str:
    """Step 4-pre's section, located by heading PREFIX.

    Prefix rather than full heading text, as `test_review_close_pr_policy._section`
    already does: pinning the whole heading made a reword raise a bare
    `ValueError: substring not found` with no diagnosis -- a guard that fails without
    saying why.
    """
    text = SKILL.read_text(encoding="utf-8")
    try:
        start = text.index("### 4-pre.")
        end = text.index("### 4a.", start)
    except ValueError:  # pragma: no cover - diagnosis path
        raise AssertionError(
            "could not locate Step 4-pre between the `### 4-pre.` and `### 4a.` headings "
            "-- a heading was renamed or re-levelled; re-point these guards deliberately"
        ) from None
    return text[start:end]


def _live_lines() -> list[str]:
    """Step 4-pre's executable command lines.

    `shape_lib.live_command_lines` rather than a local re-implementation: it is the shared
    primitive for exactly this, it keeps only FENCED text -- so prose, blockquoted
    illustrations and HTML comments cannot satisfy a guard -- and it drops whole-line
    comments while keeping trailing ones. Phase 304's first fix hand-rolled the filter,
    which is the duplicate-then-diverge shape `Q-367` was filed for.
    """
    return live_command_lines(_step4pre_text())


# The complete set of `git` invocations Step 4-pre prescribes. An ALLOWLIST, matched on the
# WHOLE line, deliberately.
#
# Phase 304's first guards pinned the presence of two lines and constrained nothing else,
# and the round walked six mutations through them -- every one an ordinary in-repo idiom,
# every one restoring `Q-521` in full:
#
#     git reset --hard origin/<default branch>        (after the cut, or after the merge)
#     git checkout -B "$INTEGRATION_BRANCH" origin/<default branch>
#     git rebase origin/<default branch>
#     git -c advice.detachedHead=false cherry-pick origin/…..<default branch>
#     git cherry-pick "origin/…..<default branch>"    (operand quoted)
#
# A presence pin cannot see an ADDED line, and a `startswith` pin on one spelling of
# `cherry-pick` cannot see the other five. Whole-line membership closes both classes at
# once: any added command, and any respelling of a prescribed one, is a line not in the set.
#
# Strict on purpose. A legitimate change to a command here reddens one test with the
# offending line quoted, and updating this set is the deliberate act such a change warrants.
_ALLOWED_GIT_LINES = {
    'git checkout "<approved branch name>"',
    'git checkout -b "$INTEGRATION_BRANCH" <default branch>',
    "git checkout <default branch>",
    'git fetch origin "<approved branch name>"; echo "--- fetch exit (MUST be 0):  $?"',
    "git fetch origin <default branch>",
    "git merge --no-edit origin/<default branch>",
    'git rev-list --count "<approved branch name>..origin/<approved branch name>"',
    'git rev-list --count "<approved branch name>..origin/<default branch>"',
    'git rev-list --count origin/<default branch>..<default branch> --not "<approved branch name>"',
}


def _code(line: str) -> str:
    """The command with any trailing `# ...` comment removed, quote-aware.

    Quote-aware because `#` is also a parameter-expansion operator, a sed address and a URL
    fragment; `tools/reader_census.py::_trailing_comment` exists for the same reason. Both
    guards below normalise through this, so a trailing comment -- a meaning-preserving edit
    -- does not redden either. The round measured that as over-strictness after the first
    hardening: a `# onto the current base` comment failed the sequence pin.
    """
    out, q = [], None
    for ch in line:
        if q:
            out.append(ch)
            if ch == q:
                q = None
            continue
        if ch in "\"'":
            q = ch
            out.append(ch)
            continue
        if ch == "#":
            break
        out.append(ch)
    return "".join(out).strip()


def _git_lines() -> list[str]:
    return [_code(ln) for ln in _live_lines() if _code(ln).startswith("git ")]


def test_step4pre_prescribes_no_git_command_outside_the_allowlist() -> None:
    """The composition guard -- it closes the whole additive class in one assertion."""
    unexpected = [ln for ln in _git_lines() if ln not in _ALLOWED_GIT_LINES]
    assert not unexpected, (
        "Step 4-pre prescribes `git` command(s) not in the allowlist:\n  "
        + "\n  ".join(unexpected)
        + "\n\nIf deliberate, add the exact line to `_ALLOWED_GIT_LINES`. If not: "
        "`reset --hard`, `checkout -B`, `rebase` and any spelling of `cherry-pick` "
        "against origin all restore `Q-521` in full."
    )


def test_the_allowlist_is_not_vacuous() -> None:
    """Every allowlisted line must still be prescribed, or the set is rotting."""
    missing = sorted(_ALLOWED_GIT_LINES - set(_git_lines()))
    assert not missing, (
        "allowlisted `git` lines Step 4-pre no longer prescribes (stale entries -- remove "
        "them, and check the step still does what they did):\n  " + "\n  ".join(missing)
    )


# The integration-branch block's git commands, IN ORDER. The allowlist above is a set, so
# it cannot see a DELETION (a second copy of the same line elsewhere keeps it satisfied) or
# a REORDERING. Both are live defects the round demonstrated:
#
#   - drop `git fetch origin <default branch>` and the base merge resolves against a stale
#     remote-tracking ref -- silently, because the other `git fetch origin <default branch>`
#     in the probe block keeps the set happy;
#   - insert `git checkout <default branch>` before the base merge and the merge lands on
#     the LOCAL default branch in the shared primary worktree, not on the integration branch.
#
# Every line here is allowlisted individually, so only the sequence catches these.
_INTEGRATION_BLOCK_SEQUENCE = [
    "git fetch origin <default branch>",
    'git checkout -b "$INTEGRATION_BRANCH" <default branch>',
    "git merge --no-edit origin/<default branch>",
]


def _integration_block() -> str:
    """The one fenced block that builds the integration branch."""
    marker = 'INTEGRATION_BRANCH="merge/review-close-'
    blocks = [b for _, b in fenced_blocks(_step4pre_text()) if marker in b]
    assert len(blocks) == 1, (
        f"expected exactly one fenced block assigning INTEGRATION_BRANCH, found {len(blocks)}"
    )
    return blocks[0]


def test_the_integration_block_runs_exactly_these_commands_in_this_order() -> None:
    # NOT `live_command_lines` here: `fenced_blocks` already returns the block's CONTENT,
    # and that helper re-extracts fences from what it is given -- on unfenced text it finds
    # none and returns [], which is a guard that passes over an empty population. Filter the
    # block's own lines instead, dropping blanks and whole-line comments the same way.
    got = [_code(ln) for ln in _integration_block().splitlines()
           if ln.strip() and not ln.lstrip().startswith("#")
           and _code(ln).startswith("git ")]
    assert got == _INTEGRATION_BLOCK_SEQUENCE, (
        "the integration-branch block's `git` sequence changed.\n"
        f"  expected: {_INTEGRATION_BLOCK_SEQUENCE}\n"
        f"  got:      {got}\n"
        "A deletion here resolves the base merge against a stale ref; an insertion can put "
        "the merge on the local default branch. Neither is visible to a set-membership check."
    )


def test_step4pre_does_not_sweep_with_a_cherry_pick() -> None:
    """Named separately so a failure reads as "the sweep is back"."""
    picks = [ln for ln in _git_lines() if "cherry-pick" in ln]
    assert not picks, (
        "Step 4-pre reintroduced the commit sweep that collapses the merge-base (Q-521):\n  "
        + "\n  ".join(picks)
    )


def test_step4pre_cuts_the_integration_branch_from_the_local_default() -> None:
    live = _git_lines()
    assert 'git checkout -b "$INTEGRATION_BRANCH" <default branch>' in live, (
        "no LIVE line cuts the integration branch from the local default branch"
    )
    assert not any(ln.startswith('git checkout -b "$INTEGRATION_BRANCH" origin/') for ln in live)


def test_step4pre_brings_the_branch_onto_the_current_base() -> None:
    live = [ln for ln in _git_lines() if ln.startswith("git merge")]
    assert live, "without a LIVE base merge the PR's checks no longer run against the current base"
    for ln in live:
        assert ln == "git merge --no-edit origin/<default branch>", (
            f"the base merge carries a tail or a respelling: {ln!r}. A swallowed conflict "
            "leaves the integration branch mid-merge and the close proceeds over it."
        )


# --------------------------------------------------------------------------------
# `Q-524` — Step 4c must re-stage the body it just moved
# --------------------------------------------------------------------------------

_GIT_ADD_DST = re.compile(
    r"""subprocess\.run\(\s*\[\s*["']git["']\s*,\s*["']add["'][^\]]*?\bdst\b[^\]]*\]\s*,"""
    r"""\s*check\s*=\s*(?P<check>True|False)""",
    re.S,
)


def test_step4c_restages_the_moved_body() -> None:
    """The source half of `Q-524`, spelling-tolerant and comment-blind.

    The behaviour is asserted by RUNNING Step 4c, in
    `test_review_close_index_write.py::test_a_body_edited_before_the_close_is_staged_by_the_move`.
    What that execution test cannot see is `check=False`, which swallows a failed add while
    behaving identically on the happy path -- so this one stays, scoped to that.

    **It replaces a 700-character substring window, which the round defeated three ways** --
    a comment merely *naming* the call, a decoy `git mv`/`git add` pair earlier in the file
    that the window's anchor locked onto, and a legitimate comment that pushed the real call
    out of the window (76 characters of slack were left). It also false-positived on
    `git add -A -- dst` and on dropping the spaces after the commas, both meaning-preserving.
    Comment lines are stripped first, so a comment quoting the call cannot satisfy it.
    """
    live = "\n".join(
        ln for ln in SKILL.read_text(encoding="utf-8").splitlines()
        if not ln.lstrip().startswith("#")
    )
    mv = live.index("subprocess.run(['git', 'mv', src, dst], check=True)")
    m = _GIT_ADD_DST.search(live, mv)
    assert m, (
        "no `git add` naming `dst` follows the `git mv` — a body edited during the close is "
        "committed stale (Q-524). Any spelling that stages `dst` is accepted; a comment "
        "mentioning one is not."
    )
    assert m.group("check") == "True", (
        "the re-stage runs with `check=False`, so a failed `git add` is swallowed and the "
        "commit archives the pre-edit body with nothing raised"
    )
    assert not re.search(r"""\[\s*["']git["']\s*,\s*["']add["']\s*,\s*src\b""", live), (
        "staging the pre-rename path aborts the whole invocation"
    )


def test_an_edit_made_after_the_git_mv_reaches_the_commit(tmp_path: Path) -> None:
    """The behaviour the guard above is standing in for.

    `git mv` stages the rename of the COMMITTED content. An edit made to the moved
    file afterwards is unstaged, and without the re-add the commit archives the
    pre-edit text -- which is the state Step 7's post-commit gate then fails on.
    """
    work = tmp_path / "r"
    work.mkdir()
    _git(work, "init", "-q", ".")
    _git(work, "symbolic-ref", "HEAD", "refs/heads/main")
    for d in ("tasks/open", "tasks/archive"):
        (work / d).mkdir(parents=True)
    (work / "tasks" / "open" / "FEAT-1.md").write_text("original body\n")
    (work / "tasks" / "index.yml").write_text("x\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-qm", "seed")

    _git(work, "mv", "tasks/open/FEAT-1.md", "tasks/archive/FEAT-1.md")
    (work / "tasks" / "archive" / "FEAT-1.md").write_text("EDITED DURING CLOSE\n")

    # Without the re-add the edit is left unstaged -- pinned, so the guard above
    # cannot be satisfied by a `git add` that names the wrong path. `RM` is the whole
    # point: index says Renamed, worktree says Modified, so the rename is staged and
    # the edit is not.
    porcelain = _git(work, "status", "--porcelain").stdout.strip()
    assert porcelain.startswith("RM "), porcelain
    assert porcelain.endswith("tasks/archive/FEAT-1.md"), porcelain

    _git(work, "add", "tasks/archive/FEAT-1.md")
    (work / "tasks" / "index.yml").write_text("y\n")
    _git(work, "add", "tasks/index.yml")
    _git(work, "commit", "-qm", "docs: consolidate documentation")

    committed = _git(work, "show", "HEAD:tasks/archive/FEAT-1.md").stdout
    assert committed == "EDITED DURING CLOSE\n"
    assert _git(work, "status", "--porcelain").stdout == "", (
        "Step 7's gate requires a clean tree after the consolidation commit"
    )
