"""Phase 249 (`Q-370`): `/review-close` Step 1a classified every worktree except the
one whose *branch* was named `main`, and called that "the primary". Those are the same
worktree only while the primary happens to be on `main`.

A consumer had exactly one worktree — the primary checkout — on the ordinary feature
branch `data/archive-byte-counts`, which is how a change not started through
`/claim-task` gets made. One untracked file there (a whitelisted eval fixture) made the
loop classify the runner's own vantage `dirty`; Step 2a step 0 turns `dirty` into an
automatic SKIP, so a close whose seven commits had passed every gate was excluded from
Steps 3b, 4 and 6 by a data file.

The class was already known and already fixed elsewhere: `test_worktree_root_resolution.py`
(Phase 234, `Q-020`/`Q-307`(b)) names it exactly — "a script that resolves the repo with
`git rev-parse --show-toplevel` is asking 'which worktree am I standing in', and every one
of these scripts meant 'which checkout is the primary'" — and pins `cleanup_worktrees.sh`
and `batch_work.sh`. It reads no skill body, so the class survived in one. That is why
this file exists beside it rather than inside it: the guard that owns the class could not
see the file the class survived in, and nothing announced the gap.

Behaviour tests over real repos, per that file's own reasoning: the block is EXTRACTED
from the shipped skill and RUN, so it cannot drift from what the operator is told to run,
and the two pre-fix predicates are exercised as negative controls so the assertions are
known to measure something.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from _reversal import assert_no_reversal, slice_between

REPO_ROOT = Path(__file__).resolve().parents[1]

# The shipped skip, as one literal. Re-pointed in the round when the `--branch` carve-out
# and the porcelain-first fallback landed; anchoring the controls on it keeps them honest
# about what they are reverting.
NEW_SKIP = '''  if [[ -z "$primary_claimed" ]] \\
     && { [[ "$wt_path" -ef "$main_root" ]] || [[ "$wt_path" == "$primary_wt" ]]; }; then
    continue
  fi'''
SKILL = REPO_ROOT / "core/skills/review-close/SKILL.md"
# Prefix, not the whole line: the heading carries a parenthetical
# ("silent-data-loss guard, BeanRider ISSUE-0016") that is free to change.
SECTION = "### 1a."

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _step_1a_block() -> str:
    """The shipped Step 1a bash block, verbatim.

    Located by the SECTION HEADING and the first ```bash fence under it — never by a
    comment line. The first version anchored on the block's opening comment and matched
    it whole, so **rewrapping that comment** made the extractor report
    `anchor is not unique (0 hits)`, which surfaces as six behavioural failures with no
    hint that nothing was measured. That is failure-to-locate wearing failure-to-comply's
    costume, and this round found it as a false alarm on a legal reformat — one commit
    after `test_claim_task_step7_contracts.py` was re-pointed off the identical defect,
    with a comment explaining why. The fix did not travel to the file that copied it.
    """
    lines = SKILL.read_text(encoding="utf-8").split("\n")
    heads = [i for i, l in enumerate(lines) if l.strip().startswith(SECTION)]
    assert len(heads) == 1, (
        f"COULD NOT LOCATE Step 1a: section heading {SECTION!r} found {len(heads)}x. "
        f"Nothing was measured — re-point this extractor; do not read the failures "
        f"below as the skill being wrong.")
    opens = [i for i in range(heads[0], len(lines)) if lines[i].strip() == "```bash"]
    assert opens, "COULD NOT LOCATE Step 1a: no ```bash fence under the heading"
    start = opens[0] + 1
    ends = [i for i in range(start, len(lines)) if lines[i].strip() == "```"]
    assert ends, "COULD NOT LOCATE Step 1a: block has no closing fence"
    return "\n".join(lines[start:ends[0]]) + "\n"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _fixture(tmp_path):
    """The reporter's exact shape: an ordinary feature branch checked out in the PRIMARY,
    seven commits ahead, one untracked file — plus a genuine linked worktree that is also
    dirty, so a fix that simply stopped classifying everything would be caught."""
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "-c", "init.defaultBranch=main", "init", "-q", ".")
    _git(primary, "config", "user.email", "t@t")
    _git(primary, "config", "user.name", "t")
    (primary / "README.md").write_text("base\n", encoding="utf-8")
    _git(primary, "add", "-A")
    _git(primary, "commit", "-qm", "base")

    _git(primary, "checkout", "-qb", "data/archive-byte-counts")
    for i in range(7):
        (primary / "work.txt").write_text(f"c{i}\n", encoding="utf-8")
        _git(primary, "add", "-A")
        _git(primary, "commit", "-qm", f"c{i}")
    (primary / "eval-fixture.bin").write_bytes(b"\x00" * 128)   # the untracked data file

    linked = tmp_path / "other-wt"
    _git(primary, "worktree", "add", "-q", "-b", "feat/other", str(linked), "main")
    (linked / "untracked.txt").write_text("scratch\n", encoding="utf-8")
    return primary, linked


DEFAULT_BRANCH_SH = REPO_ROOT / "core/companion/scripts/default_branch.sh"


def _resolve_placeholders(block: str, cwd: Path) -> str:
    """Substitute `<default branch>` exactly as the agent does (`Q-381`, Phase 255).

    The shipped block carries a placeholder, not the literal `main`: Rule A tells the
    agent to run `default_branch.sh` BARE and substitute what it prints. bash cannot
    resolve a placeholder, so this harness performs the same substitution — which means
    these tests now exercise the resolve step instead of assuming it, and they would go
    red if `default_branch.sh` stopped answering for a fixture like this one.

    Non-vacuity is asserted separately by
    `test_step1a_actually_carries_the_placeholder_this_harness_substitutes`: if the block
    regressed to a literal, this function would be a silent no-op and every behavioural
    test below would keep passing while the defect shipped.
    """
    if "<default branch>" not in block:
        return block
    r = subprocess.run(["bash", str(DEFAULT_BRANCH_SH), str(cwd)],
                       capture_output=True, text=True)
    name = r.stdout.strip()
    assert r.returncode == 0 and name, (
        f"default_branch.sh could not resolve the fixture's default branch: {r.stderr!r}")
    return block.replace("<default branch>", name)


def _run(block: str, cwd: Path) -> str:
    r = subprocess.run(["bash", "-c", _resolve_placeholders(block, cwd)], cwd=str(cwd),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


class TestTheShippedBlock:
    def test_the_primary_is_skipped_whatever_branch_it_holds(self, tmp_path):
        primary, _ = _fixture(tmp_path)
        out = _run(_step_1a_block(), primary)
        assert "data/archive-byte-counts" not in out, (
            "the primary checkout was classified; on a `dirty` verdict Step 2a step 0 "
            "SKIPs the branch and excludes it from Steps 3b, 4 and 6:\n" + out)

    def test_a_genuine_linked_worktree_is_still_classified_dirty(self, tmp_path):
        """The silent-data-loss guard (BeanRider ISSUE-0016) must survive the fix. A
        change that skipped everything would pass the test above and gut this one."""
        primary, _ = _fixture(tmp_path)
        out = _run(_step_1a_block(), primary)
        assert "DIRTY    feat/other" in out, out

    def test_the_verdict_does_not_depend_on_the_runners_vantage(self, tmp_path):
        """The `--show-toplevel` half. Run from inside a linked worktree, the old block
        resolved `repo_root` to THAT worktree while calling it "the primary", so the
        .gitignore consulted by the symlink downgrade was the wrong one."""
        primary, linked = _fixture(tmp_path)
        block = _step_1a_block()
        assert _run(block, primary) == _run(block, linked)


class TestTheNegativeControls:
    """Each restores one half of the pre-fix predicate. Both must break an assertion
    above, or that assertion is not measuring the fix."""

    def test_the_branch_name_skip_reproduces_the_reported_defect(self, tmp_path):
        primary, _ = _fixture(tmp_path)
        block = _step_1a_block()
        import re
        m = re.search(r"^  if \[\[ -z \"\$primary_claimed\" \]\].*?\n  fi$",
                      block, re.S | re.M)
        assert m, (
            "COULD NOT LOCATE the identity skip (matched on `primary_claimed`, not on the "
            "whole literal, so renaming a neighbouring local does not read as the "
            "predicate having been deleted). Nothing was measured.")
        out = _run(block.replace(m.group(0), '  [[ "$branch" == "main" ]] && continue'),
                   primary)
        assert "DIRTY    data/archive-byte-counts" in out, out

    def test_show_toplevel_makes_the_verdict_depend_on_the_vantage(self, tmp_path):
        primary, linked = _fixture(tmp_path)
        block = _step_1a_block()
        old = 'main_root=$(cd "$(git rev-parse --git-common-dir)/.." && pwd -P)'
        assert old in block, "the primary resolution is gone from the shipped block"
        broken = block.replace(old, "main_root=$(git rev-parse --show-toplevel)")
        assert _run(broken, primary) != _run(broken, linked)


def test_step_1a_gains_no_reversal_vocabulary():
    """The softening class, closed generically rather than phrase by phrase.

    This phase's own battery left three survivors and all three were one move: keep
    every pinned string, add a sentence beside it that licenses the opposite. Against
    Step 1a it read *"Matching on `$branch == \"main\"` is equivalent in practice and
    either form is acceptable"* — every assertion above still green.

    Zero exemptions on purpose: the slice was measured clean of the whole vocabulary
    when this was wired, so anything that appears later is new, and an empty `exempt=`
    is the strongest form this check has.
    """
    step = slice_between(SKILL.read_text(encoding="utf-8"),
                         "### 1a. Classify Worktree State", "### 1b.", "Step 1a")
    assert_no_reversal(step, "review-close Step 1a")


class TestTheOtherTwoClassificationArms:
    """`_fixture` makes every worktree dirty, so until this class existed the block was
    "extracted and run" over ONE THIRD of its output space: `AHEAD` and `MERGED` were
    emitted by no test at all. The round found three mutations living in that gap, and
    two of them route work to deletion — `clean-merged` is documented as *"Safe to remove
    in Step 6"*, so swapping the two arms, or comparing against `origin/main` instead of
    `main`, offers an unmerged branch for cleanup.
    """

    @staticmethod
    def _clean_worktrees(tmp_path):
        primary = tmp_path / "primary"
        primary.mkdir()
        _git(primary, "-c", "init.defaultBranch=main", "init", "-q", ".")
        _git(primary, "config", "user.email", "t@t")
        _git(primary, "config", "user.name", "t")
        (primary / "README.md").write_text("base\n", encoding="utf-8")
        _git(primary, "add", "-A"); _git(primary, "commit", "-qm", "base")

        # AHEAD: two commits past main, working tree clean.
        ahead = tmp_path / "wt-ahead"
        _git(primary, "worktree", "add", "-q", "-b", "feat/ahead", str(ahead), "main")
        for i in range(2):
            (ahead / f"a{i}.txt").write_text("x\n", encoding="utf-8")
            _git(ahead, "add", "-A"); _git(ahead, "commit", "-qm", f"a{i}")

        # MERGED: tip identical to main, working tree clean.
        merged = tmp_path / "wt-merged"
        _git(primary, "worktree", "add", "-q", "-b", "feat/merged", str(merged), "main")
        return primary

    def test_a_clean_branch_ahead_of_main_reports_AHEAD(self, tmp_path):
        out = _run(_step_1a_block(), self._clean_worktrees(tmp_path))
        assert "AHEAD    feat/ahead" in out, out
        assert "2 commits ahead" in out, out

    def test_a_clean_branch_at_main_reports_MERGED(self, tmp_path):
        out = _run(_step_1a_block(), self._clean_worktrees(tmp_path))
        assert "MERGED   feat/merged" in out, out

    def test_the_two_arms_are_not_interchangeable(self, tmp_path):
        """Swapping the arm bodies must be visible. `MERGED` is what Step 6 treats as
        safe to delete, so a branch with unmerged commits wearing that label is work
        offered for cleanup."""
        out = _run(_step_1a_block(), self._clean_worktrees(tmp_path))
        assert "MERGED   feat/ahead" not in out, out
        assert "AHEAD    feat/merged" not in out, out

    def test_the_ahead_count_is_measured_against_main_not_origin_main(self, tmp_path):
        """`origin/main` does not exist in a consumer that has not fetched, so the count
        silently becomes 0 and every branch classifies MERGED — safe to remove."""
        block = _step_1a_block()
        assert '<default branch>..$branch' in block, (
            "stale mutation anchor: the block no longer spells the range this way, so "
            "the replace below is a no-op and the assertion proves nothing")
        broken = block.replace('"<default branch>..$branch"',
                               '"origin/<default branch>..$branch"')
        assert broken != block, "the mutation did not apply"
        out = _run(broken, self._clean_worktrees(tmp_path))
        assert "AHEAD" not in out, (
            "with no origin, the mutated count is 0 and unmerged work reads MERGED:\n" + out)


def _master_fixture(tmp_path):
    """The same shape as `_fixture`, on a `master`-default repo.

    Every other fixture in this module is built with `init.defaultBranch=main`, which made
    `_resolve_placeholders` unfalsifiable: replacing its whole body with
    `block.replace("<default branch>", "main")` left all 17 tests green, so the module
    would keep passing if `default_branch.sh` were deleted (Phase 255 round, guards lens).
    A `master` fixture is what makes the substitution mean something.
    """
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "-c", "init.defaultBranch=master", "init", "-q", ".")
    _git(primary, "config", "user.email", "t@t")
    _git(primary, "config", "user.name", "t")
    (primary / "README.md").write_text("base\n", encoding="utf-8")
    _git(primary, "add", "-A")
    _git(primary, "commit", "-qm", "base")
    _git(primary, "checkout", "-qb", "feat/ahead")
    (primary / "work.txt").write_text("c\n", encoding="utf-8")
    _git(primary, "add", "-A")
    _git(primary, "commit", "-qm", "ahead")
    _git(primary, "checkout", "-q", "master")
    linked = tmp_path / "wt-ahead"
    _git(primary, "worktree", "add", "-q", str(linked), "feat/ahead")
    return primary


def test_the_block_classifies_correctly_on_a_master_default_repo(tmp_path):
    """The whole point of `Q-381`, executed rather than asserted.

    Pre-fix, Step 1a compared against a literal `main` that does not exist here, the ahead
    count came back 0, and a branch carrying an unreviewed commit reported MERGED — work
    silently eligible for a close. This is also the test that kills a `_resolve_placeholders`
    hard-coded to `main`: on this repo that substitution produces the pre-fix behaviour.
    """
    primary = _master_fixture(tmp_path)
    out = _run(_step_1a_block(), primary)
    assert "AHEAD    feat/ahead" in out, (
        "a branch one commit ahead of `master` did not classify AHEAD — the block is "
        "comparing against a branch this repository does not have:\n" + out
    )
    assert "MERGED   feat/ahead" not in out


def test_step1a_actually_carries_the_placeholder_this_harness_substitutes():
    """`_resolve_placeholders` is a silent no-op on a block with no placeholder.

    If Step 1a ever regresses to the literal `main`, every behavioural test in this module
    would keep passing while a `master` consumer's classifier silently reported every
    branch MERGED — the exact defect `Q-381` closed. Pin the premise the harness rests on.
    """
    block = _step_1a_block()
    assert "<default branch>" in block, (
        "Step 1a no longer carries the `<default branch>` placeholder — the substitution "
        "in `_resolve_placeholders` is vacuous and this module measures nothing about it")


class TestTheBranchModeCarveOut:
    """`claim_task.sh --branch` sets `WORKSPACE_PATH="$REPO_ROOT"`: that mode's work in
    progress lives in the PRIMARY checkout. Skipping the primary unconditionally — which
    the first version of this fix did — hands a half-implemented `--branch` claim to
    Step 2a as reviewable, restoring for one mode exactly the silent merge BeanRider
    ISSUE-0016 exists to prevent. The lock records `workspace:`, so the skip asks it.

    Found by the round's execution lens, which built the mode rather than reading it.
    """

    @staticmethod
    def _claimed_primary(tmp_path, with_lock):
        primary = tmp_path / "primary"
        primary.mkdir()
        _git(primary, "-c", "init.defaultBranch=main", "init", "-q", ".")
        _git(primary, "config", "user.email", "t@t")
        _git(primary, "config", "user.name", "t")
        (primary / "README.md").write_text("base\n", encoding="utf-8")
        _git(primary, "add", "-A"); _git(primary, "commit", "-qm", "base")
        _git(primary, "checkout", "-qb", "feat/task-1")
        (primary / "impl.py").write_text("v1\n", encoding="utf-8")
        _git(primary, "add", "-A"); _git(primary, "commit", "-qm", "impl")
        (primary / "impl.py").write_text("v1\nv2\n", encoding="utf-8")   # uncommitted
        if with_lock:
            locks = primary / "sysop" / "runtime" / "locks"
            locks.mkdir(parents=True)
            (locks / "TASK-1.lock").write_text(
                f"task_id: TASK-1\nbranch: feat/task-1\nworkspace: {primary.resolve()}\n",
                encoding="utf-8")
        return primary

    def test_a_branch_mode_claim_in_the_primary_still_classifies_dirty(self, tmp_path):
        primary = self._claimed_primary(tmp_path, with_lock=True)
        out = _run(_step_1a_block(), primary)
        assert "DIRTY    feat/task-1" in out, (
            "a --branch claim's uncommitted work in the primary was waved through:\n" + out)

    def test_the_same_tree_without_a_claim_is_still_skipped(self, tmp_path):
        """The Q-370 case must not regress: no lock means nobody claimed this, so the
        primary is just where the operator stands."""
        primary = self._claimed_primary(tmp_path, with_lock=False)
        out = _run(_step_1a_block(), primary)
        assert "feat/task-1" not in out, out

    def test_a_lock_naming_some_other_workspace_does_not_arm_the_carve_out(self, tmp_path):
        """Over-strictness check: only a lock whose `workspace:` IS the primary counts.
        An ordinary worktree-mode claim records its own worktree and must not make every
        close start classifying the primary again."""
        primary = self._claimed_primary(tmp_path, with_lock=False)
        locks = primary / "sysop" / "runtime" / "locks"
        locks.mkdir(parents=True)
        (locks / "TASK-9.lock").write_text(
            f"task_id: TASK-9\nbranch: feat/other\nworkspace: {tmp_path / 'elsewhere'}\n",
            encoding="utf-8")
        out = _run(_step_1a_block(), primary)
        assert "feat/task-1" not in out, out


# The retired mechanism, as PHRASINGS rather than as the two literals this phase happened
# to correct. The round reverted three OTHER sites — Step 3b's HARD RULE, Step 6's `pr`
# re-sync note and Step 4a's TMPDIR note — and all three survived, because the guard
# enumerated corrections instead of deriving a population. Phase 248's own rule, applied
# to one of four sites.
RETIRED_MECHANISM = (
    "the worktree whose branch is `main`",
    "skips the main worktree",
    "skip the main worktree",
    "the runner's vantage; not a feature worktree",
    'branch" == "main" ]] && continue',
)


def test_no_site_in_the_skill_still_asserts_the_branch_name_mechanism():
    """Derived from the file, not from a list of the edits this phase made.

    Every one of these phrasings says the primary is identified by its BRANCH NAME. That
    stopped being true, and a rationale left asserting it ships a false statement beside
    working code — Phase 248's rule, which the first version of this guard applied at one
    of the four sites that needed it.

    The one legal occurrence is this phase's own historical note, which QUOTES the old
    wording in italics to say it was replaced; it is exempted by span, not by weakening
    the pattern.
    """
    text = SKILL.read_text(encoding="utf-8")
    exempt = "until this phase both sites said *the worktree whose branch is `main`*"
    assert exempt in text, "the historical-note exemption is stale — re-point it"
    haystack = text.replace(exempt, "")
    hits = [ph for ph in RETIRED_MECHANISM if ph in haystack]
    assert not hits, (
        f"the retired branch-name mechanism is still asserted at {hits}. The primary is "
        f"matched by path identity now; prose that says otherwise is false.")


def test_the_skill_states_the_population_by_identity():
    text = SKILL.read_text(encoding="utf-8")
    for phrase in ("excluding the **primary checkout**",
                   "it skips the **primary checkout**, matched by path identity",
                   "excludes the primary checkout by path identity",
                   "deliberately skips the primary checkout"):
        assert phrase in text, f"a corrected site lost its identity wording: {phrase!r}"


def test_both_gitignore_owners_resolve_the_primary_not_the_callers_worktree():
    """Step 1a and Step 6 run the SAME symlink-downgrade rule and both consult the
    primary's `.gitignore`. The round reverted the Step 6 site alone to `--show-toplevel`
    and it survived: the new module read only the Step 1a fence, and the sibling class
    guard (`test_worktree_root_resolution.py`) reads only two shell scripts, so the gap
    between them was covered by nothing."""
    text = SKILL.read_text(encoding="utf-8")
    resolutions = text.count('main_root=$(cd "$(git rev-parse --git-common-dir)/.." && pwd -P)')
    assert resolutions == 2, (
        f"expected the primary resolved this way at BOTH gitignore-owner sites, found "
        f"{resolutions}")
    assert "repo_root=$(git rev-parse --show-toplevel)" not in text, (
        "a gitignore owner is resolved with --show-toplevel again, which answers which "
        "worktree the caller stands in")
    assert text.count('git -C "$main_root" check-ignore') == 2, (
        "check-ignore must consult the primary at both sites")
