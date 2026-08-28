"""`/review-close` Step 2e — extracted from the skill and EXECUTED.

Phase 237's part B leg 1 shipped Step 2e with **no test coverage of any kind**.
Its own round's guards lens found it: no test anywhere in `tests/` referenced a
single one of the step's output strings, and unlike Phase 236's `close_batch.sh`
and `claim_task.sh` blocks — which this repo's convention says to extract and
run — nothing executed the heredoc. Whole-section deletion, removal of the
symlink-containment check, inversion of the "never changes a disposition" rule
and shrinking the artifact list all passed the suite. That was the highest-
severity finding of the round, and this module is the answer to it.

The shape follows `test_claim_task_heredocs_execute.py`: pull the fenced block
out of the shipped skill, run it against real fixtures, and assert on what it
prints. A prose guard alone cannot see any of the defects below, because every
one of them is a behaviour.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _prose_guard_helpers import normalize, section, states  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "core/skills/review-close/SKILL.md"
STEP_HEADING = "### 2e. Claim-Artifact Report"
# `section()` needs the FULL heading line, not a prefix.
FULL_HEADING = '### 2e. Claim-Artifact Report (report, never reject — Phase 237, part B leg 1)'


def _step_2e() -> str:
    text = SKILL.read_text(encoding="utf-8")
    start = text.index(STEP_HEADING)
    end = text.index("\n## Step 3: Run Verification", start)
    return text[start:end]


def _heredoc() -> str:
    """The Python body of Step 2e's `python3 - <<'PY'` block."""
    m = re.search(r"python3 - <<'PY'[^\n]*\n(.*?)\nPY\n", _step_2e(), re.S)
    assert m, "Step 2e no longer carries a `python3 - <<'PY'` block"
    return m.group(1)


@pytest.fixture(scope="module")
def script(tmp_path_factory) -> Path:
    body = _heredoc()
    compile(body, "step2e", "exec")  # syntax, before anything else
    p = tmp_path_factory.mktemp("step2e") / "step2e.py"
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture
def repo(tmp_path) -> Path:
    root = tmp_path / "proj"
    (root / "sysop/runtime/locks").mkdir(parents=True)
    (root / "sysop/runtime/subagent-envelopes").mkdir(parents=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    return root


def _lock(repo: Path, task_id: str, branch: str, extra: str = "") -> None:
    (repo / "sysop/runtime/locks" / f"{task_id}.lock").write_text(
        f"task_id: {task_id}\nstatus: in_progress\nbranch: {branch}\n{extra}",
        encoding="utf-8",
    )


def _run(repo: Path, claim_id: str, run_id: str = "20260827T120000Z-aaaaaaaa") -> Path:
    d = repo / "sysop/runtime/claim" / claim_id / run_id
    d.mkdir(parents=True)
    return d


def shipped_classification(verdict: str) -> str:
    """The shape `/claim-task` Step 7c actually writes: json.dumps in a fence."""
    return "# Classification\n\n```yaml\n{}\n```\n".format(
        json.dumps({"claim_id": "X", "verdict": verdict}, indent=2)
    )


def _exec(script: Path, repo: Path, *branches):
    return subprocess.run([sys.executable, str(script), *branches],
                          cwd=str(repo), capture_output=True, text=True)


class TestItRuns:
    def test_no_branches_is_a_clean_no_op(self, script, repo):
        r = _exec(script, repo, "")
        assert r.returncode == 0, r.stderr
        assert "nothing to report" in r.stdout

    def test_an_unsubstituted_placeholder_is_refused(self, script, repo):
        """`mkdir -p`-style silent acceptance of a literal placeholder is the
        Phase-236 defect; this step must refuse rather than report on a claim
        named `<branch 1>`."""
        r = _exec(script, repo, "<branch 1>")
        assert r.returncode == 2
        assert "placeholder not substituted" in r.stderr

    def test_a_branch_with_no_lock_says_so_without_looking(self, script, repo):
        r = _exec(script, repo, "hotfix/nothing")
        assert r.returncode == 0, r.stderr
        assert "no lock names this branch" in r.stdout


class TestReportUnknownNeverDidNotRun:
    """The rule the whole step rests on. Absence is UNKNOWN, never 'skipped'."""

    def test_a_missing_claim_dir_is_unknown_and_says_why(self, script, repo):
        _lock(repo, "FEAT-1", "task/feat-1")
        r = _exec(script, repo, "task/feat-1")
        assert "UNKNOWN" in r.stdout
        assert "gitignored" in r.stdout
        assert "did not run" not in r.stdout.replace("not 'did not run'", "")

    def test_an_empty_claim_dir_is_unknown(self, script, repo):
        _lock(repo, "FEAT-1", "task/feat-1")
        (repo / "sysop/runtime/claim/FEAT-1").mkdir(parents=True)
        r = _exec(script, repo, "task/feat-1")
        assert "holds no run" in r.stdout and "UNKNOWN" in r.stdout

    def test_no_envelope_is_never_reported_as_a_skipped_stage(self, script, repo):
        _lock(repo, "FEAT-1", "task/feat-1")
        _run(repo, "FEAT-1")
        r = _exec(script, repo, "task/feat-1")
        assert "Claude Code only" in r.stdout


class TestTheVerdictMatchesTheShippedWriter:
    """The round's HIGH: a line-prefix scan matched nothing Step 7c produces."""

    @pytest.mark.parametrize("verdict", ["PROCEED", "BLOCKED", "SUPERSEDED"])
    def test_the_fenced_json_verdict_is_read(self, script, repo, verdict):
        _lock(repo, "FEAT-1", "task/feat-1")
        d = _run(repo, "FEAT-1")
        (d / "classification.md").write_text(shipped_classification(verdict))
        r = _exec(script, repo, "task/feat-1")
        assert f"verdict: {verdict}" in r.stdout, r.stdout

    def test_a_run_with_no_classification_says_so(self, script, repo):
        _lock(repo, "FEAT-1", "task/feat-1")
        _run(repo, "FEAT-1")
        r = _exec(script, repo, "task/feat-1")
        assert "no classification.md in this run" in r.stdout


class TestArtifactEnumeration:
    def test_all_five_run_files_are_enumerated(self, script, repo):
        """Shrinking this list is invisible to any prose guard."""
        _lock(repo, "FEAT-1", "task/feat-1")
        d = _run(repo, "FEAT-1")
        for n in ("plan.md", "planner-integrity.md", "review.md",
                  "classification.md", "outcome.md"):
            (d / n).write_text("x")
        r = _exec(script, repo, "task/feat-1")
        for n in ("plan.md", "planner-integrity.md", "review.md",
                  "classification.md", "outcome.md"):
            assert n in r.stdout, f"{n} missing from the report"
        assert "absent:  none" in r.stdout

    def test_present_and_absent_partition_the_set(self, script, repo):
        _lock(repo, "FEAT-1", "task/feat-1")
        d = _run(repo, "FEAT-1")
        (d / "plan.md").write_text("x")
        r = _exec(script, repo, "task/feat-1")
        present = [l for l in r.stdout.splitlines() if "present:" in l][0]
        absent = [l for l in r.stdout.splitlines() if "absent:" in l][0]
        assert "plan.md" in present
        assert "outcome.md" in absent and "review.md" in absent


class TestBranchToClaimResolution:
    def test_the_first_branch_line_wins_matching_claim_task_sh(self, script, repo):
        """`claim_task.sh` uses `awk '/^branch:/{...; exit}'`. A lock's free-text
        `notes:` tail can carry a column-0 `branch:` line; the two readers of
        that field disagreeing is worse than either rule alone."""
        _lock(repo, "FEAT-1", "task/feat-1", extra="notes:\nbranch: task/FAKE\n")
        _run(repo, "FEAT-1")
        r = _exec(script, repo, "task/feat-1")
        assert "(FEAT-1)" in r.stdout
        assert "task/FAKE" not in r.stdout

    def test_an_empty_task_id_falls_back_to_the_lock_filename(self, script, repo):
        (repo / "sysop/runtime/locks/EMPTYID.lock").write_text(
            "task_id:\nbranch: task/empty\n", encoding="utf-8")
        r = _exec(script, repo, "task/empty")
        assert "EMPTYID" in r.stdout

    def test_two_locks_on_one_branch_are_reported_not_silently_resolved(
            self, script, repo):
        """`/sitrep` has no duplicate-lock-branch check, so nothing else would
        surface this. Picking one silently can name the wrong claim."""
        _lock(repo, "DUP-A", "task/dup")
        _lock(repo, "DUP-B", "task/dup")
        r = _exec(script, repo, "task/dup")
        assert "AMBIGUOUS" in r.stdout
        assert "DUP-A" in r.stdout and "DUP-B" in r.stdout

    def test_a_batch_branch_resolves(self, script, repo):
        """Step 2e must NOT be batch-blind — that is what disqualified Phase
        155's gate. `batch_work.sh` writes `task_id:` and `branch:` too."""
        _lock(repo, "BATCH-3", "review/batch-3")
        _run(repo, "BATCH-3")
        r = _exec(script, repo, "review/batch-3")
        assert "(BATCH-3)" in r.stdout


class TestContainmentAndRobustness:
    def test_a_run_symlinked_outside_the_claim_root_is_refused(self, script, repo):
        """The security check. Removing it is invisible to a prose guard."""
        _lock(repo, "FEAT-1", "task/feat-1")
        claim_root = repo / "sysop/runtime/claim/FEAT-1"
        claim_root.mkdir(parents=True)
        outside = repo / "elsewhere"
        outside.mkdir()
        (outside / "plan.md").write_text("not this claim's")
        os.symlink(outside, claim_root / "zzz-escaped")
        r = _exec(script, repo, "task/feat-1")
        assert "resolves outside the claim root" in r.stdout
        assert "plan.md" not in r.stdout

    def test_one_unreadable_claim_dir_does_not_abort_the_whole_report(
            self, script, repo):
        """The Phase-219 shape: an abort inside a loop whose contract forbids
        aborting takes every healthy row with it."""
        _lock(repo, "PERM-1", "task/perm")
        _lock(repo, "FEAT-1", "task/feat-1")
        _run(repo, "FEAT-1")
        bad = repo / "sysop/runtime/claim/PERM-1"
        bad.mkdir(parents=True)
        (bad / "run").mkdir()
        os.chmod(bad, 0o000)
        try:
            r = _exec(script, repo, "task/perm", "task/feat-1")
        finally:
            os.chmod(bad, 0o755)
        assert r.returncode == 0, r.stderr
        assert "UNKNOWN" in r.stdout
        assert "(FEAT-1)" in r.stdout, "the healthy branch's row was lost"

    def test_the_newest_run_is_chosen_lexically_and_older_ones_counted(
            self, script, repo):
        _lock(repo, "FEAT-1", "task/feat-1")
        _run(repo, "FEAT-1", "20260826T090000Z-99999999")
        d = _run(repo, "FEAT-1", "20260828T090000Z-bbbbbbbb")
        (d / "plan.md").write_text("x")
        r = _exec(script, repo, "task/feat-1")
        assert "20260828T090000Z-bbbbbbbb" in r.stdout
        assert "+1 older run(s)" in r.stdout


class TestTheRulesArePinnedInProse:
    """The two rules that are decisions, not implementation details."""

    def test_the_step_states_it_never_changes_a_disposition(self):
        body = normalize(section(SKILL.read_text(), FULL_HEADING))
        assert states(body, "It never changes a branch's disposition")

    def test_the_step_states_the_report_unknown_rule(self):
        """Plain substring, deliberately — NOT `states()`.

        The rule's own wording is a prohibition ("Never report ..."), and
        `states()` refuses a phrase whose sentence carries a negator. That is
        `states()` behaving correctly and being the wrong instrument: here the
        negation IS the assertion. Polarity is instead pinned by the three
        behavioural tests above, which fail if absence stops rendering as
        UNKNOWN.
        """
        body = normalize(section(SKILL.read_text(), FULL_HEADING))
        assert 'Report unknown. Never report "did not run"' in body
        assert "gitignored" in body and "Claude Code only" in body, (
            "the rule's two grounding reasons were dropped; without them it "
            "reads as a style note rather than a consequence"
        )

    def test_the_step_still_exists_at_all(self):
        assert STEP_HEADING in SKILL.read_text(), (
            "Step 2e was deleted — whole-section removal passed the suite "
            "before this module existed"
        )
