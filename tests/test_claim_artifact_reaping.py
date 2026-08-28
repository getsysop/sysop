"""Phase 236 — the orchestrator group's first slice.

Covers three separable things, and the split is deliberate:

**1. Behaviour, driven as a real subprocess** (`TestBatchArtifactReaping`,
`TestAtomicLockCreate`). `close_batch.sh`'s new `remove_claim_artifacts()` is
ordinary shell in an allow-ruled script with ~950 lines of existing
real-subprocess coverage, so it is tested by running it. `claim_task.sh`'s
atomic lock write cannot be reached through the CLI in its interesting state —
the existence guard ~200 lines earlier refuses first — so the shipped block is
**extracted from the script and executed**, which is the shape Phase 171's
different-model adjudication settled on ("the four defects that mattered were
all found by RUNNING the commands and none by any of the 272 mutations").

**2. Prose that carries a decision** (`TestCorrectedClaims`). Every guard here
uses `_prose_guard_helpers.states()` / `section()` rather than
`assert "<literal>" in <whole file>`. Phase 235's round ran 64 mutations against
that shape and 41 survived: a literal is satisfied inside its own negation, by an
incidental hit elsewhere in a long file, or from a neighbouring section a naive
slice swallowed.

**3. Reasons, not facts** (`TestReasonsArePinned`). Phase 235's method note: a
drift guard asserting that one of two phrases appears *somewhere* in a file
cannot tell a stated rationale from a stripped one, and that is how a falsehood
survived. Where this phase replaced a wrong *reason* for a right *decision*, the
guard asserts the corrected reason and the absence of the retired one.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _prose_guard_helpers import normalize, section, states  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
CLOSE_BATCH = REPO_ROOT / "core/companion/scripts/close_batch.sh"
CLAIM_TASK = REPO_ROOT / "core/companion/scripts/claim_task.sh"
REVIEW_CLOSE = REPO_ROOT / "core/skills/review-close/SKILL.md"
CLAIM_SKILL = REPO_ROOT / "core/skills/claim-task/SKILL.md"
AUTO_BUILD = REPO_ROOT / "core/skills/auto-build/SKILL.md"
WORKFLOW = REPO_ROOT / "core/companion/docs/WORKFLOW.md"
# `tools/` is mirror-excluded, so on the public snapshot this file is ABSENT and
# every guard below that reads it would redden the required `pytest` check. Read it
# once here and skip the whole module when it is gone, the way tests/test_registry_drift.py
# does — a read inside a decorator would be a collection ERROR rather than a failure.
SPEC = REPO_ROOT / "tools/CLAIM_TASK_ORCHESTRATOR_SPEC.md"
if not SPEC.is_file():  # pragma: no cover - public-snapshot path
    pytest.skip(
        "tools/CLAIM_TASK_ORCHESTRATOR_SPEC.md is mirror-excluded and absent here",
        allow_module_level=True,
    )

BASE_TASKS = """\
# Review Tasks

### Batch 1 — First batch `Pending`

- [x] task one
- [x] task two

### Batch 2 — Second batch `Merged`

- [x] done task
"""


def _find(text: str, needle: str, what: str) -> int:
    """`text.index(needle)`, but failing with a message that names the anchor.

    The round ran 21 negative controls and **5 falsely reddened, every one of them a
    bare `ValueError: substring not found`** from a slice like this — renaming a
    python local (`inside` -> `contained`), renaming a shell variable
    (`LOCK_CONTENT` -> `LOCK_BODY`). Those are legitimate rewrites. The guards SHOULD
    notice, because they extract by anchor, but a reader must be told the anchor
    moved rather than left staring at a stack trace. Over-strictness that reports
    itself is a maintenance cost; over-strictness that does not is a trap.
    """
    i = text.find(needle)
    assert i >= 0, (
        f"guard anchor moved: expected to find {needle!r} ({what}). If this was a "
        f"deliberate rename, update the anchor here — the guard extracts by anchor "
        f"and cannot follow a rename on its own."
    )
    return i


def _step4c_claim_block(strip_comments: bool = True) -> str:
    """Step 4c's claim-artifact cleanup, as CODE.

    Comment-stripped by default, because the first shape of these guards asserted
    an ordering with `block.index("rmtree")` — and the block's own comment explains
    the rmtree, above the code, so the ordering assertion was satisfied by prose
    describing the thing it was meant to check. Same failure as `_fn_lines()` below
    and as the shell-comment case: a guard reading a whole region cannot tell an
    explanation from an instruction.
    """
    body = REVIEW_CLOSE.read_text()
    i = _find(body, "claim_root = Path('sysop/runtime/claim')", "Step 4c claim-cleanup block start")
    j = _find(body[i:], "# Report what this code DID", "Step 4c report block") + i
    block = body[i:j]
    if not strip_comments:
        return block
    return "\n".join(ln for ln in block.splitlines() if not ln.lstrip().startswith("#"))


def _comment_prose(block: str) -> str:
    """A shell comment block as flowing prose.

    `normalize()` folds hard wrapping but leaves the `#` markers, so a phrase
    broken across two comment lines reads as `read by NO runtime # consumer` and
    no substring check matches it. Strip the markers first. Without this the
    guards below pass or fail on comment reflow, which is not the property they
    are about.
    """
    lines = [re.sub(r"^\s*#\s?", "", ln) for ln in block.splitlines()]
    return normalize("\n".join(lines))


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
        check=True, capture_output=True,
    )
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "review_tasks.md").write_text(BASE_TASKS)
    (root / "README.md").write_text("# seed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _seed_artifacts(repo: Path, batch: int) -> tuple[Path, Path]:
    """A park marker and a per-run artifact dir for `BATCH-<batch>`, as
    /claim-task Step 7c writes them."""
    parked = repo / "sysop/runtime/parked"
    parked.mkdir(parents=True, exist_ok=True)
    marker = parked / f"BATCH-{batch}__20260827T101500Z-deadbeef.md"
    marker.write_text(f"# BATCH-{batch} — PARKED\n\nreason: needs a human\n")

    run = repo / f"sysop/runtime/claim/BATCH-{batch}/20260827T101500Z-deadbeef"
    run.mkdir(parents=True, exist_ok=True)
    (run / "plan.md").write_text("the plan\n")
    (run / "review.md").write_text("REVIEW_REPORT: clean\n")
    (run / "classification.md").write_text("PROCEED\n")
    return marker, run


def _run(cwd: Path, *args):
    return subprocess.run(
        ["bash", str(CLOSE_BATCH), *args],
        cwd=str(cwd), capture_output=True, text=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Behaviour — close_batch.sh reaps a batch claim's artifacts
# ─────────────────────────────────────────────────────────────────────────────
class TestBatchArtifactReaping:
    """The defect: a `/claim-task` park of a BATCH-<N>, and that batch's whole
    per-run artifact directory, were removed by **nothing**. `/review-close`
    Step 4c is the only shipped deleter and its id list is built from
    `roadmap_ids` only, so no batch id can reach it."""

    def test_a_closed_batch_loses_its_park_marker_and_artifact_dir(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        marker, run = _seed_artifacts(repo, 1)
        claim_dir = run.parent

        r = _run(repo, "1")
        assert r.returncode == 0, r.stderr
        assert not marker.exists(), "park marker survived the close"
        assert not claim_dir.exists(), "claim artifact directory survived the close"
        # The removal must SAY it happened. A silent reap cannot be told apart
        # from one that never ran — the rule remove_batch_lock() already states.
        assert "Removed park marker" in r.stdout, r.stdout
        assert "Removed claim artifacts" in r.stdout, r.stdout

    def test_absence_is_reported_not_silent(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "1")
        assert r.returncode == 0, r.stderr
        assert "No park markers for Batch 1" in r.stdout, r.stdout
        assert "No claim artifacts at" in r.stdout, r.stdout

    def test_only_the_closed_batch_is_reaped(self, tmp_path):
        """Id scoping. `BATCH-1` and `BATCH-12` share a prefix; a glob written
        as `BATCH-1*` would take both, and the second batch is still in flight."""
        repo = _repo(tmp_path / "repo")
        target_marker, target_run = _seed_artifacts(repo, 1)
        other_marker, other_run = _seed_artifacts(repo, 12)

        r = _run(repo, "1")
        assert r.returncode == 0, r.stderr
        assert not target_marker.exists()
        assert not target_run.parent.exists()
        assert other_marker.exists(), "BATCH-12's marker was taken by BATCH-1's close"
        assert other_run.parent.exists(), "BATCH-12's artifacts were taken by BATCH-1's close"

    def test_artifacts_are_kept_when_the_close_did_not_land_on_main(self, tmp_path):
        """The `pr`-policy deferral. /review-close Step 4b runs this script on an
        INTEGRATION branch while `main` still reads the batch `Pending`. Removing
        a park verdict there destroys the one record of why the work stopped, and
        the merge may never land."""
        repo = _repo(tmp_path / "repo")
        marker, run = _seed_artifacts(repo, 1)
        _git(repo, "checkout", "-q", "-b", "integration/close-1")

        r = _run(repo, "1")
        assert r.returncode == 0, r.stderr
        assert marker.exists(), "park marker destroyed on an unmerged integration branch"
        assert run.parent.exists(), "claim artifacts destroyed on an unmerged integration branch"
        # `Locks kept` is pinned independently by tests/test_batch_claim_kinds.py; what
        # this phase added is the second half, so that is what this asserts.
        assert "the claim artifacts with them" in r.stdout, r.stdout

    def test_an_already_finished_batch_is_reaped_on_a_later_run_from_main(self, tmp_path):
        """The recovery path for the deferral above: once the PR merges and
        `main` reads `Merged`, re-running here clears what was kept. This is the
        MERGED_UNLOCK arm, which is a different call site from the CLOSED arm."""
        repo = _repo(tmp_path / "repo")
        marker, run = _seed_artifacts(repo, 2)  # Batch 2 is already `Merged`

        r = _run(repo, "2")
        assert r.returncode == 0, r.stderr
        assert "already-merged" in r.stdout, r.stdout
        assert not marker.exists(), "an already-Merged batch kept its park marker forever"
        assert not run.parent.exists(), "an already-Merged batch kept its artifacts forever"

    def test_dry_run_removes_nothing(self, tmp_path):
        repo = _repo(tmp_path / "repo")
        marker, run = _seed_artifacts(repo, 1)
        r = _run(repo, "--dry-run", "1")
        assert r.returncode == 0, r.stderr
        assert marker.exists() and run.parent.exists(), "--dry-run reaped real artifacts"


class TestBatchReapingIsGuarded:
    """The one `rm -rf`-shaped operation in this script. The batch id reaches it
    through a digits-only parse, so the numeric re-assert is belt-and-braces —
    but it is the belt that stops an empty or `..` path component from widening
    the delete from one claim to the whole runtime tree."""

    @staticmethod
    def _fn_lines() -> list[str]:
        """The function body as CODE lines — comments stripped.

        Written this way because the first shape of this guard used
        `fn.index("rm -rf")`, which matched the *comment* that explains why the
        numeric re-assert exists. The comment sits ABOVE the guard, so the
        ordering assertion was satisfied by prose describing the thing it was
        supposed to be checking, and would have stayed green with the guard
        deleted. Exactly the failure mode this phase's own method note names.
        """
        body = CLOSE_BATCH.read_text()
        fn = body[body.index("remove_claim_artifacts() {"):]
        fn = fn[: fn.index("\n}\n")]
        return [ln for ln in fn.splitlines() if not ln.lstrip().startswith("#")]

    @staticmethod
    def _first(lines: list[str], needle: str) -> int:
        for i, ln in enumerate(lines):
            if needle in ln:
                return i
        raise AssertionError(f"{needle!r} appears in no CODE line of remove_claim_artifacts()")

    def test_the_numeric_guard_is_present_and_precedes_the_rm(self):
        lines = self._fn_lines()
        guard = self._first(lines, "=~ ^[0-9]+$")
        rm = self._first(lines, "rm -rf")
        assert guard < rm, "the numeric guard must run BEFORE the recursive remove"

    def test_the_rm_is_not_reachable_with_an_unresolved_main_root(self):
        """The early return must belong to the MAIN-ROOT branch.

        The first shape of this asserted `any("return 0" in ln for ln in
        lines[resolve:rm])` — and the round showed that window also contains the
        NUMERIC guard's `return 0`, so replacing the main-root return with
        `main_root=""` left the assertion green while `rm -rf` ran against an
        absolute `/sysop/runtime/...` path. The incidental-hit failure this
        class's own docstring claims to have closed, committed in the same file.
        Bind the return to its own `if`.
        """
        lines = self._fn_lines()
        resolve = self._first(lines, "resolve_main_root")
        # The main-root branch opens at the resolve and closes at its `fi`.
        fi = next((i for i in range(resolve, len(lines)) if lines[i].strip() == "fi"), None)
        assert fi is not None, "the main-root resolve is not inside an if/fi block"
        branch = lines[resolve:fi]
        assert any("return 0" in ln for ln in branch), (
            "the main-root failure branch does not return — execution falls through "
            "to a path built from an empty variable:\n" + "\n".join(branch)
        )
        # And it must still precede the rm.
        assert fi < self._first(lines, "rm -rf")

    def test_an_unresolvable_main_root_removes_nothing(self, tmp_path):
        """Executed, because the structural check above can only see shape. Run the
        function outside any git repo: `resolve_main_root` fails, and nothing may be
        removed or reported as removed."""
        (tmp_path / "sysop/runtime/claim/BATCH-1").mkdir(parents=True)
        script = tmp_path / "probe.sh"
        body = CLOSE_BATCH.read_text()
        fn = body[body.index("resolve_main_root() {"):]
        fn = fn[: fn.index("\nremove_claim_artifacts() {")]
        fn2 = body[body.index("remove_claim_artifacts() {"):]
        fn2 = fn2[: fn2.index("\n}\n") + 2]
        script.write_text("set -u\n" + fn + "\n" + fn2 + '\nremove_claim_artifacts 1\n')
        r = subprocess.run(["bash", str(script)], cwd=str(tmp_path),
                           capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})
        assert (tmp_path / "sysop/runtime/claim/BATCH-1").exists(), (
            "artifacts removed despite an unresolvable main checkout\n" + r.stdout + r.stderr
        )
        assert "Removed claim artifacts" not in r.stdout, r.stdout

    def test_both_symlink_arms_are_present(self):
        """`|| -L` on each test is the code's own stated reason for existing — a
        dangling symlink is skipped by a bare `-e`/`-d` while `rm` really does
        remove it, so the report says the opposite of what happened. The round
        deleted both and nothing went red."""
        lines = self._fn_lines()
        marker_test = self._first(lines, '-e "$marker"')
        assert '-L "$marker"' in lines[marker_test], lines[marker_test]
        dir_test = self._first(lines, '-d "$claim_dir"')
        assert '-L "$claim_dir"' in lines[dir_test], lines[dir_test]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Behaviour — the lock write is atomic (Q-030 leg c)
# ─────────────────────────────────────────────────────────────────────────────
def _extract_atomic_write() -> str:
    """The shipped noclobber block, lifted verbatim from claim_task.sh.

    Extracted rather than re-typed: a test that re-types the idiom passes while
    the script keeps a plain `cat >`, which is exactly the defect. If the block
    is reshaped, this extraction fails loudly rather than testing a copy nobody
    ships.
    """
    body = CLAIM_TASK.read_text()
    start = _find(body, 'LOCK_CONTENT=$(cat <<EOF', "claim_task.sh lock-content heredoc")
    end = _find(body[start:], '2>/dev/null; then', "the noclobber write's test") + start
    return body[start:end] + "2>/dev/null; then\n  echo RACE_LOST\n  exit 9\nfi\necho WROTE\n"


class TestAtomicLockCreate:
    def test_the_shipped_write_is_a_noclobber_subshell_not_a_bare_redirect(self):
        body = CLAIM_TASK.read_text()
        # The plain form is the defect: `cat > "$LOCK_FILE" <<EOF` truncates an
        # existing lock, so the second of two racing claimants silently
        # overwrites the first's.
        assert 'cat > "$LOCK_FILE"' not in body, (
            "the lock write is a plain truncating redirect again — the TOCTOU is reopened"
        )
        # CODE lines only. The round noted this regex is satisfiable from a comment,
        # so a plain truncating redirect plus a comment describing the idiom would
        # have passed (it was killed by real-subprocess coverage elsewhere, not here).
        code = "\n".join(ln for ln in body.splitlines() if not ln.lstrip().startswith("#"))
        assert re.search(r'\(\s*set -C;.*?> "\$LOCK_FILE"', code, re.S), (
            "no `set -C` (noclobber) subshell around the lock write, in live code"
        )

    def test_the_extracted_block_creates_when_absent(self, tmp_path):
        script = tmp_path / "probe.sh"
        script.write_text(
            'set -u\nLOCK_FILE="$PWD/t.lock"\n'
            'TASK_ID=T-1\nAGENT_NAME=a\nBRANCH_NAME=b\nMODE=m\n'
            'WORKSPACE_PATH=w\nTIMESTAMP=t\nEXPIRES_TIMESTAMP=e\n'
            + _extract_atomic_write()
        )
        r = subprocess.run(["bash", str(script)], cwd=str(tmp_path),
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "WROTE" in r.stdout
        assert "task_id: T-1" in (tmp_path / "t.lock").read_text()

    def test_the_extracted_block_refuses_and_preserves_a_rival_lock(self, tmp_path):
        """The race, reproduced: the guard passed, then a rival won. The write
        must FAIL and must leave the rival's lock byte-for-byte intact."""
        rival = "task_id: T-1\nagent: the-other-agent\nstatus: in_progress\n"
        (tmp_path / "t.lock").write_text(rival)
        script = tmp_path / "probe.sh"
        script.write_text(
            'set -u\nLOCK_FILE="$PWD/t.lock"\n'
            'TASK_ID=T-1\nAGENT_NAME=me\nBRANCH_NAME=b\nMODE=m\n'
            'WORKSPACE_PATH=w\nTIMESTAMP=t\nEXPIRES_TIMESTAMP=e\n'
            + _extract_atomic_write()
        )
        r = subprocess.run(["bash", str(script)], cwd=str(tmp_path),
                           capture_output=True, text=True)
        assert r.returncode == 9, (r.returncode, r.stdout, r.stderr)
        assert "RACE_LOST" in r.stdout
        assert (tmp_path / "t.lock").read_text() == rival, "the rival's lock was clobbered"

    def test_the_loser_is_not_told_to_run_release(self):
        """`--release` refuses on an ABSENT lock; here the lock exists and belongs
        to the winner, so `--release` would either refuse or release someone
        else's claim. The recovery text must name the worktree and branch instead."""
        body = CLAIM_TASK.read_text()
        start = body.index("was claimed by another agent while this claim was setting up")
        block = body[start: start + 1800]
        # Only what the operator SEES. The block deliberately discusses --release
        # in a comment, to say why it is the wrong recovery — a guard reading the
        # whole block cannot tell that explanation from a instruction to run it.
        echoed = "\n".join(ln for ln in block.splitlines() if ln.lstrip().startswith("echo "))
        assert "git worktree remove" in echoed and "git branch -D" in echoed, echoed
        assert "--release" not in echoed, (
            "the race-loser recovery prints --release, which cannot work here: "
            "the lock exists and belongs to the winner"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. The corrected claims
# ─────────────────────────────────────────────────────────────────────────────
class TestCorrectedClaims:
    def test_review_close_reaps_the_roadmap_half(self):
        """Three of the round's survivors lived in the first shape of this test, and
        all three were mention-counting rather than code-reading:

        * `shutil` could be dropped from the heredoc's import line — the block then
          `NameError`s at the rmtree, aborting Step 4c *after* the index rewrite —
          while `"shutil.rmtree" in body` stayed green;
        * `print('CLAIM_ARTIFACTS_REMOVED: …')` could be deleted with the token left
          in a neighbouring comment, because `count(...) >= 2` counts mentions;
        * `shutil.rmtree(claim_dir)` could be widened to `rmtree(claim_root)`,
          deleting every other claim's in-flight artifacts on every close.
        """
        body = REVIEW_CLOSE.read_text()
        code = _step4c_claim_block()

        # The import the rmtree depends on, on the actual import line.
        imp = _find(body, "import datetime, os,", "Step 4c heredoc import line")
        assert "shutil" in body[imp: body.index("\n", imp)], (
            "shutil is not imported — the heredoc NameErrors at the rmtree, after the "
            "index rewrite has already been staged"
        )

        # The removal target, read as code. `claim_root` is the PARENT of every claim.
        assert "shutil.rmtree(claim_dir)" in code, (
            "the rmtree does not target the single claim's directory:\n" + code
        )
        assert "shutil.rmtree(claim_root)" not in code, (
            "the rmtree targets the whole claim ROOT — every close would delete other "
            "claims' in-flight artifacts"
        )

        # Both rows must be PRINTED, not merely mentioned.
        for row in ("CLAIM_ARTIFACTS_REMOVED", "CLAIM_ARTIFACTS_FAILED"):
            printed = [ln for ln in body.splitlines()
                       if ln.lstrip().startswith("print(") and row in ln]
            assert printed, f"{row} is computed but never printed"
        # ...and Step 8 must ask for them, outside the heredoc.
        step8 = body[_find(body, "Locks cleaned:", "Step 8 report block"):]
        assert "CLAIM_ARTIFACTS_REMOVED" in step8, (
            "Step 8's report never asks for the artifact row"
        )

    def test_step_4c_resolves_containment_before_removing(self):
        code = _step4c_claim_block()
        assert "resolve()" in code, "no containment re-check before the rmtree"
        assert code.index("inside") < code.index("shutil.rmtree"), (
            "the containment result is computed after the remove"
        )

    def test_the_dir_arm_still_tests_is_dir(self):
        """`elif claim_dir.is_dir():` -> `elif True:` survived the round. With the
        try/except it no longer loses data, but every closing task with no claim
        directory is then reported under CLAIM_ARTIFACTS_FAILED — turning the row a
        human reads for real trouble into one that is noisy on the normal path."""
        code = _step4c_claim_block()
        i = _find(code, "shutil.rmtree(claim_dir)", "the rmtree call")
        guard = code[:i].rsplit("elif", 1)[-1]
        assert "is_dir()" in guard, (
            "the rmtree arm no longer tests is_dir(); its condition is: elif" + guard
        )

    def test_the_reapers_are_ASSERTED_not_merely_unmentioned(self):
        """**The round's largest single class: every retired falsehood could be
        restored in new words.** All five WORKFLOW mutations survived, and
        `claim-task/SKILL.md` could be made to say *"A review batch's marker is
        removed by nothing"* again — the exact claim this phase exists to retire —
        because the guards pinned the OLD SENTENCES rather than the claim.

        A negative check can always be walked around by rephrasing. The positive one
        cannot: the file has to assert the reaper exists, in a sentence that is not a
        negation (`states()` refuses one). Both directions are kept — the negative
        catches a verbatim revert, the positive catches a rewrite.
        """
        wf = WORKFLOW.read_text()
        assert states(wf, "Removed at close, by claim kind"), (
            "WORKFLOW § 8.6 no longer ASSERTS that the claim artifact set is reaped"
        )
        assert states(wf, "remove_claim_artifacts()"), (
            "WORKFLOW no longer names the batch-side reaper"
        )
        skill = CLAIM_SKILL.read_text()
        assert states(skill, "What cleans it up — the close, and only the close."), (
            "/claim-task no longer asserts that the artifact set is cleaned at close"
        )
        assert states(skill, "is removed by `close_batch.sh`'s `remove_claim_artifacts()`"), (
            "/claim-task no longer names the batch marker's reaper — the round showed "
            "the retired 'removed by nothing' claim can be reinstated in new words"
        )

    def test_the_nothing_removes_it_claims_are_gone(self):
        wf = normalize(WORKFLOW.read_text())
        assert "Nothing removes it yet" not in wf, (
            "WORKFLOW § 8.6 still says the claim artifact set is never removed"
        )
        skill = normalize(CLAIM_SKILL.read_text())
        assert "What cleans it up, stated as it is rather than as it should be. Nothing does" not in skill

    @pytest.mark.parametrize("phrase", [
        "close-time cleanup is part B of the Phase 171 reshape",
        "a BATCH-<N> marker is removed by nothing",
    ])
    def test_retired_workflow_phrases_do_not_return(self, phrase):
        assert normalize(phrase) not in normalize(WORKFLOW.read_text())

    def test_auto_build_records_its_classification_durably(self):
        body = AUTO_BUILD.read_text()
        sec = section(body, "### Phase 6d: Halt-on-Blocker OR Write Revised Plan")
        assert "classification.md" in sec, "6d writes no classification record"
        # The WRITE's own path, not any mention of the namespace. The round repointed
        # the `Write` to `sysop/runtime/auto-build/` (the per-worktree scratch that
        # `git worktree remove` destroys, and that leg 3 does not reap) and this stayed
        # green, because the `mkdir` line above still contained the namespace string.
        write = [ln for ln in sec.splitlines()
                 if "`Write`" in ln and "classification.md" in ln]
        assert write, "no `Write` line names classification.md"
        assert all("sysop/runtime/claim/" in ln for ln in write), (
            "the classification record is written outside sysop/runtime/claim/ — it "
            "would not survive worktree removal and nothing would reap it:\n"
            + "\n".join(write)
        )
        # It must not claim to bind execution — v1 still absorbs inline.
        assert states(sec, "is **not** an input to Phase 6e"), (
            "6d's record does not say what it is; a record implying it bound "
            "execution when it did not is worse than one that says so"
        )

    def test_the_classification_record_demands_per_clause_rationale(self):
        sec = section(AUTO_BUILD.read_text(),
                      "### Phase 6d: Halt-on-Blocker OR Write Revised Plan")
        assert "Rejection rationale (per clause)" in sec
        assert "none rejected" in sec, (
            "no instruction for the empty case — an empty section is "
            "indistinguishable from a lost one"
        )

    def test_auto_build_no_longer_calls_the_retype_verbatim(self):
        body = AUTO_BUILD.read_text()
        assert "the `PLAN_TEXT[<TASK_ID>]` verbatim, followed by the Prompt Template" not in body
        assert "constructs this prompt as `PLAN_TEXT[<TASK_ID>]` verbatim" not in body

    def test_auto_build_states_why_verbatim_is_wrong_there(self):
        sec = section(AUTO_BUILD.read_text(), "### Step 7b: Adversarial-Reviewer Agent Prompt")
        assert states(sec, "`/auto-build` has no file"), (
            "the section does not assert the fact the whole correction rests on"
        )
        assert "retype" in sec, "the mechanism is not named"
        assert "bidirectional" in sec, (
            "only one direction of the harm is stated — a dropped clause "
            "manufactures a phantom finding, a smoothed one hides a real finding, "
            "and both leave identical evidence"
        )

    def test_claim_task_records_why_7b_inlines(self):
        body = CLAIM_SKILL.read_text()
        i = body.index("contents of `<ARTIFACT_DIR>/plan.md` verbatim")
        block = body[i: i + 2600]
        assert "asymmetry" in block, "the 7e-by-path asymmetry is still unexplained"
        assert "Do not \"fix\" this asymmetry" in block, (
            "no instruction to the next reader, who will otherwise optimise it away"
        )


class TestReasonsArePinned:
    """Pin the reason, not the fact — Phase 235's method note. Each of these
    replaced a wrong justification for a decision that was right anyway, so the
    guard has to be able to tell a stated rationale from a stripped one."""

    def test_the_lock_validator_falsehood_is_retired_and_replaced(self):
        body = CLAIM_TASK.read_text()
        # Pin the retired ASSERTION, not the words. The correction necessarily
        # quotes the phrase in order to retire it, so a bare
        # `"lock-validator tooling" not in body` fails on the fix and passes only
        # if the record of the fix is deleted — the guard rewarding the exact
        # regression it exists to catch. What must not return is the parenthetical
        # that STATED it as the reason.
        flat = _comment_prose(body)
        assert "(which downstream lock-validator tooling treats as malformed)" not in flat, (
            "the invented lock-validator justification is asserted again"
        )
        # And it must not be ASSERTED in any other wording. The first shape of this
        # used a character window around the retirement (`[i_fix-400, i_fix+1500]`)
        # and the round re-asserted the falsehood 400 characters after the
        # retirement — inside the guard's own exclusion. A window drawn in
        # characters is a window an editor moves. `states()` is polarity-aware and
        # needs no window: the retirement sentence carries a negator ("incorrectly")
        # so it does not count as an assertion, while any fresh assertion anywhere
        # in the file does.
        assert not states(flat, "lock-validator tooling treats"), (
            "the retired lock-validator justification is ASSERTED somewhere in this "
            "file — it may only appear inside a sentence that retires it"
        )
        i = body.index("Expiry = 4 hours from now")
        block = _comment_prose(body[i: i + 3000])
        # The corrected reason, both halves. Either alone leaves the next reader
        # able to conclude the field is dead and delete it.
        assert "read by NO runtime consumer" in block, block[:800]
        assert "pinned by tests" in block, block[:800]

    def test_the_spec_no_longer_says_the_reshape_is_unbuilt(self):
        body = SPEC.read_text()
        assert "the orchestrator reshape is not. Supersedes" not in body
        # "562 lines today" is QUOTED elsewhere in this file, in the note that
        # records the repair — so a whole-file check here would fail on the fix
        # and pass only if the record of the fix were deleted. Scope to the row
        # that made the claim.
        rows = [ln for ln in body.splitlines()
                if ln.startswith("| `core/skills/claim-task/SKILL.md` |")]
        assert len(rows) == 1, f"expected one migration row, found {len(rows)}"
        assert "DONE, Phase 171" in rows[0], rows[0]
        assert not re.search(r"is \*\*?\d+ lines today", rows[0]), (
            "the migration row states a line count again — it rots on every touch"
        )

    def test_the_spec_writes_down_the_abcd_cut(self):
        body = SPEC.read_text()
        sec = section(body, "## What is built, what is not — the A/B/C/D cut")
        for part in ("**A**", "**B**", "**C**", "**D**"):
            assert part in sec, f"part {part} missing from the ratified cut"
        assert "BUILT — Phase 171" in sec
        # PROPERTY, not the phase-236 snapshot. `Leg 3 BUILT — Phase 236` was
        # pinned here verbatim, so when Phases 237 and 238 shipped the rest of
        # the reshape this guard held the table at a stale state -- the third
        # place in this phase where a guard pinning a CLAIM was keeping the tree
        # wrong. What the table must do is name every part's state and stay
        # honest about what is still open.
        for part_row in ("**A**", "**B**", "**C**", "**D**"):
            i = sec.index(part_row)
            row = sec[i:sec.find("\n", i)]
            assert "BUILT" in row or "OPEN" in row, (
                f"part {part_row}'s row states no state: {row[:120]!r}")
        assert "Phase 238" in sec, (
            "the cut table does not mention Phase 238, which closed parts C and D "
            "tiers 1-2 -- three phases in a row repaired this table by hand and the "
            "fourth did not, which is how it went stale unnoticed")
        assert "Q-317" in sec, (
            "the cut table claims part B without naming the gap it closes WITH -- "
            "/sitrep's predicate is roadmap-only and a parked batch is invisible")

    def test_the_spec_forbids_copying_the_retired_validator_precedent(self):
        body = SPEC.read_text()
        i = body.index("Do NOT copy its validator treatment")
        block = body[i: i + 1800]
        assert "Phase 234 retired it" in block
        assert "ZERO validator change" in block, (
            "the rule for Part C is stated without its operative instruction"
        )

    def test_the_spec_corrects_the_sitrep_drift_guard_claim_by_halves(self):
        """The old claim was that the sitrep SKILL tables are not drift-guarded.
        One table now is; the other is not. A guard asserting only that the
        paragraph changed would pass on either half being wrong."""
        body = SPEC.read_text()
        i = body.index("The \"not drift-guarded\" claim is HALF-FALSE")
        block = body[i: i + 2000]
        assert "Classification states" in block, "the guarded table is not named"
        assert "Recommendation routing rules" in block, "the unguarded table is not named"
        assert "scoped to the routing-rules table only" in block

    def test_the_sitrep_state_table_guard_the_spec_cites_actually_exists(self):
        """The correction above asserts a shipped guard. Verify it rather than
        repeat it — the class of defect this whole phase is about."""
        guard = (REPO_ROOT / "tests/test_sitrep_survey.py").read_text()
        assert "core/skills/sitrep/SKILL.md" in guard
        assert "| State | Deterministic signal |" in guard

    def test_the_sitrep_routing_rules_table_is_still_unguarded(self):
        """The other half. If someone adds a routing-rules guard, this fails and
        the spec's paragraph must be re-scoped in the same change — which is the
        point: a correction that rots silently is the defect it corrected."""
        guard = (REPO_ROOT / "tests/test_sitrep_survey.py").read_text()
        assert "Recommendation routing rules" not in guard, (
            "a routing-rules guard now exists — update the spec's HALF-FALSE "
            "paragraph, which still says that table is unguarded"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. What the round found — every one of these had NO guard when it was found
# ─────────────────────────────────────────────────────────────────────────────
def _extract_claim_dir_gate() -> str:
    """The shipped `CLAIM_DIR=` + `case` + `mkdir` block from /auto-build 6d."""
    body = AUTO_BUILD.read_text()
    start = body.index('CLAIM_DIR="sysop/runtime/claim/')
    end = body.index('mkdir -p "$CLAIM_DIR"', start) + len('mkdir -p "$CLAIM_DIR"')
    return body[start:end]


class TestTheClassificationDirGate:
    """**The round's sharpest finding, and it was a defect in the FIX for an
    earlier finding.** The author-side pass caught an ungated `mkdir -p`; the gate
    written for it put the placeholders in the `case` subject and *again* in the
    `mkdir`, so an agent substituting only the first passed the gate and created
    the literal `<TASK_ID>` directory anyway — the exact outcome the gate exists to
    prevent. Nothing pinned it: `tests/test_phantom_shell_vars.py` matches
    `line.startswith("mkdir -p")`, which the `case` form no longer does, so the
    pattern could be neutered entirely with the suite green.
    """

    def test_the_placeholders_appear_exactly_once(self):
        block = _extract_claim_dir_gate()
        assert block.count("<TASK_ID>") == 1, (
            "the task-id placeholder is written more than once, so a partial "
            "substitution can satisfy the gate and still reach the mkdir:\n" + block
        )
        assert block.count("<CYCLE_TS>") == 1, block

    def test_the_gate_is_in_a_live_bash_fence(self):
        """Re-fencing ```bash as ```text makes the prescribed command dead prose, and
        the round found no guard notices — the claim-task module has a fence mutation,
        /auto-build had none."""
        body = AUTO_BUILD.read_text()
        i = _find(body, 'CLAIM_DIR="sysop/runtime/claim/', "auto-build 6d CLAIM_DIR")
        opener = body.rfind("```", 0, i)
        lang = body[opener: body.index("\n", opener)].strip("` ")
        assert lang in ("bash", "sh"), (
            f"the prescribed classification-dir block is fenced as {lang!r}, not a "
            "runnable language — the command is dead prose"
        )

    def test_the_gate_tests_the_variable_the_mkdir_uses(self):
        block = _extract_claim_dir_gate()
        assert 'case "$CLAIM_DIR"' in block, "the gate does not test the built path"
        assert 'mkdir -p "$CLAIM_DIR"' in block, "the mkdir does not use the tested path"

    @pytest.mark.parametrize(
        "task_id,cycle,expect_created",
        [
            ("TECH-0007", "20260827T101500Z", True),   # both substituted
            ("<TASK_ID>", "<CYCLE_TS>", False),        # neither
            ("TECH-0007", "<CYCLE_TS>", False),        # partial — the round's case
            ("<TASK_ID>", "20260827T101500Z", False),  # partial, other half
        ],
    )
    def test_the_shipped_gate_runs_correctly(self, tmp_path, task_id, cycle, expect_created):
        """Executed, not read. The block is lifted from the skill so a reshape that
        breaks it fails here rather than passing against a re-typed copy."""
        block = _extract_claim_dir_gate().replace("<TASK_ID>", task_id).replace("<CYCLE_TS>", cycle)
        script = tmp_path / "gate.sh"
        script.write_text("set -u\n" + block + "\necho CREATED\n")
        r = subprocess.run(["bash", str(script)], cwd=str(tmp_path),
                           capture_output=True, text=True)
        made = (tmp_path / "sysop/runtime/claim").exists()
        if expect_created:
            assert r.returncode == 0 and made, (r.returncode, r.stdout, r.stderr)
        else:
            assert r.returncode != 0, (
                f"the gate passed with task_id={task_id!r} cycle={cycle!r}"
            )
            assert not made, "a directory was created despite the gate refusing"


class TestStep4cSurvivesAFailedRemoval:
    """`shutil.rmtree` was the first realistically-raising call in a loop whose own
    contract is that an abort mid-loop must not have destroyed an earlier task's
    records. The round made one claim directory unremovable and the whole heredoc
    exited 1 with a park marker already gone, a later task's lock never cleaned, and
    **none of the report rows printed** — putting Step 8 back to supplying them from
    memory, the Phase-219 failure this block claims to have fixed."""

    def test_the_removal_is_wrapped_and_records_the_failure(self):
        body = REVIEW_CLOSE.read_text()
        i = body.index("shutil.rmtree(claim_dir)")
        window = body[i - 400: i + 400]
        assert "try:" in window and "except OSError" in window, (
            "the rmtree is not wrapped — a raise here aborts the loop mid-cleanup"
        )
        assert "artifacts_failed" in window, "the failure is swallowed rather than recorded"

    def test_the_failure_row_is_printed_and_read(self):
        body = REVIEW_CLOSE.read_text()
        assert body.count("CLAIM_ARTIFACTS_FAILED") >= 2, (
            "the failed list is computed but never printed, or printed but never "
            "asked for by Step 8 — a value that reaches nobody"
        )

    def test_containment_gates_both_removal_arms(self):
        """The first cut gated only the rmtree. The symlink arm ran unguarded, so a
        `tid` of `../../../escaped_link` unlinked a symlink at the repo root and
        reported it as a claim artifact."""
        code = _step4c_claim_block()
        assert "if not inside:" in code, (
            "containment is not the first branch — an arm below it can run unguarded"
        )
        # No removal call may appear before the containment branch, in CODE.
        head = code[: code.index("if not inside:")]
        for call in ("rmtree", "unlink("):
            assert call not in head, f"{call} is reachable before the containment check"
        # And every removal must sit in an `elif` of that same chain, not a fresh `if`
        # — a new `if` after the chain is unguarded again and reads identically.
        for call in ("shutil.rmtree(claim_dir)", "claim_dir.unlink("):
            k = code.index(call)
            preceding = code[:k]
            assert preceding.rindex("if not inside:") < k, call
            assert "elif" in preceding[preceding.rindex("if not inside:"):], (
                f"{call} is not inside the containment branch chain"
            )
