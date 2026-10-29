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
from skill_runner_text import text_of

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "core/skills/review-close/SKILL.md"
STEP_HEADING = "### 2e. Claim-Artifact Report"
# `section()` needs the FULL heading line, not a prefix.
FULL_HEADING = '### 2e. Claim-Artifact Report (report, never reject)'


def _step_2e() -> str:
    text = text_of(SKILL)
    start = text.index(STEP_HEADING)
    end = text.index("\n## Step 3: Run Verification", start)
    return text[start:end]


# Step 2e's program was a `python3 - <<'PY'` heredoc until Phase 387 (`Q-409` P3); the
# step now runs the shipped script, and these tests run it the same way.
SCRIPT = REPO_ROOT / "core/companion/scripts/claim_artifacts.py"
INVOCATION = ('python3 sysop/scripts/claim_artifacts.py "<branch 1>" "<branch 2>" '
              '"<...one argument per branch under review...>"')


@pytest.fixture(scope="module")
def script() -> Path:
    assert INVOCATION in _step_2e(), "Step 2e no longer runs claim_artifacts.py as written"
    return SCRIPT


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

    def test_an_envelope_that_failed_to_key_is_counted_not_called_absent(self, script, repo):
        """A hook envelope under another name is evidence the hook ran and failed to key, so
        the report counts it instead of saying the harness writes none (Phase 387's round:
        this arm had no test before or after the move)."""
        _lock(repo, "FEAT-1", "task/feat-1")
        _run(repo, "FEAT-1")
        (repo / "sysop/runtime/subagent-envelopes/unkeyed-1.json").write_text("{}", encoding="utf-8")
        r = _exec(script, repo, "task/feat-1")
        assert r.returncode == 0, r.stderr
        assert "none matched this claim id (1 other envelope file(s)" in r.stdout
        assert "failed to key" in r.stdout
        assert "Claude Code only" not in r.stdout


class TestTheVerdictMatchesTheShippedWriter:
    """The round's HIGH: a line-prefix scan matched nothing Step 7c produces."""

    @pytest.mark.parametrize("verdict", ["PROCEED", "BLOCKED", "SUPERSEDED"])
    def test_the_fenced_json_verdict_is_read(self, script, repo, verdict):
        _lock(repo, "FEAT-1", "task/feat-1")
        d = _run(repo, "FEAT-1")
        (d / "classification.md").write_text(shipped_classification(verdict))
        r = _exec(script, repo, "task/feat-1")
        assert f"verdict: {verdict}" in r.stdout, r.stdout

    def test_the_auto_build_verdict_line_is_read_whole(self, script, repo):
        """Internal tracker #772: `/auto-build` Phase 6d is the second writer, and its line is
        unfenced prose. The fallback kept one word and reported `ALL`. The line
        is read from the shipped template, so a reworded template is tested."""
        tmpl = (REPO_ROOT / "core/skills/auto-build/SKILL.md").read_text(
            encoding="utf-8")
        line = next(l.strip() for l in tmpl.splitlines()
                    if l.strip().lstrip("*").lower().startswith("verdict:"))
        _lock(repo, "FEAT-1", "task/feat-1")
        d = _run(repo, "FEAT-1", run_id="20260930T120000Z")
        (d / "classification.md").write_text(
            "# FEAT-1 — adversarial classification\n\n"
            + line.replace("<N>", "3") + "\n")
        r = _exec(script, repo, "task/feat-1")
        assert "verdict: ALL FIXABLE\n" in r.stdout, r.stdout

    @pytest.mark.parametrize("line, want", [
        # One word, except the one two-word verdict a Sysop writer emits
        # (`/auto-build` Phase 6d's `ALL FIXABLE`), however it is punctuated.
        ("Verdict: PROCEED — Some reason", "PROCEED"),
        ("**verdict:** BLOCKED (see below)", "BLOCKED"),
        ("Verdict: BLOCKED Pending review", "BLOCKED"),
        ("Verdict: BLOCKED CI (red)", "BLOCKED"),
        ("Verdict: BLOCKED SQL INJECTION (high)", "BLOCKED"),
        ("Verdict: PROCEED OK.", "PROCEED"),
        ("Verdict: PROCEED N/A", "PROCEED"),
        ("Verdict: PROCEED\nFIXABLE on the next line", "PROCEED"),
        ("Verdict: ALL FIXABLE: 3 findings", "ALL FIXABLE"),
        ("Verdict: **ALL FIXABLE** (3)", "ALL FIXABLE"),
        ("Verdict: ALL FIXABLE \u2013 proceeding", "ALL FIXABLE"),
        ("Verdict: ALL\tFIXABLE!", "ALL FIXABLE"),
        ("Verdict: ALL FIXABLE 3 findings", "ALL FIXABLE"),
        ("Verdict: ALL FIXABLES", "ALL"),
        ("verdict: proceed", "proceed"),
        ("verdict: all fixable", "all fixable"),
        ("Verdict: BLOCKED PENDING (review)", "BLOCKED"),
    ])
    def test_the_line_fallback_stops_at_the_caps_run(self, script, repo, line, want):
        _lock(repo, "FEAT-1", "task/feat-1")
        d = _run(repo, "FEAT-1")
        (d / "classification.md").write_text(line + "\n")
        r = _exec(script, repo, "task/feat-1")
        # The verdict is the report's last line, so a value that ran onto the
        # next line of the file shows up as a stray last line.
        assert r.stdout.rstrip("\n").splitlines()[-1] == f"      verdict: {want}", r.stdout

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
        body = normalize(section(text_of(SKILL), FULL_HEADING))
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
        body = normalize(section(text_of(SKILL), FULL_HEADING))
        assert 'Report unknown. Never report "did not run"' in body
        assert "gitignored" in body and "Claude Code only" in body, (
            "the rule's two grounding reasons were dropped; without them it "
            "reads as a style note rather than a consequence"
        )

    def test_the_step_still_exists_at_all(self):
        assert STEP_HEADING in text_of(SKILL), (
            "Step 2e was deleted — whole-section removal passed the suite "
            "before this module existed"
        )


def test_a_lock_that_is_not_a_regular_file_is_skipped_not_waited_on(script, repo):
    """Phase 325's round: this loop had no `is_file()` guard, so a FIFO named `*.lock`
    blocked `read_text` forever. The directory is a control: `except OSError` already
    covered it, and it must stay harmless."""
    locks = repo / "sysop/runtime/locks"
    os.mkfifo(locks / "A-FIFO.lock")
    (locks / "B-DIR.lock").mkdir()
    _lock(repo, "TASK-1", "feat/x")
    r = subprocess.run([sys.executable, str(script), "feat/x"], cwd=str(repo),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "TASK-1" in r.stdout, r.stdout


def _pre_313_python():
    """An interpreter where `Path.is_file()` still RAISES on EACCES, if this host has one."""
    import shutil
    for cand in ("/usr/bin/python3", shutil.which("python3.12"), shutil.which("python3.9")):
        if not cand or not os.path.exists(cand):
            continue
        v = subprocess.run([cand, "-c", "import sys; print(sys.version_info[:2] < (3, 13))"],
                           capture_output=True, text=True)
        if v.stdout.strip() == "True":
            return cand
    return None


@pytest.mark.skipif(os.geteuid() == 0, reason="root stats through a mode-000 directory")
@pytest.mark.skipif(_pre_313_python() is None, reason="no pre-3.13 interpreter on this host")
def test_a_lock_that_cannot_be_stated_does_not_kill_the_report_on_the_floor(script, repo, tmp_path):
    """Phase 325's round 2: below 3.13 `is_file()` raised `PermissionError` out of the
    loop, exit 1. The report must still name the readable claim."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "real.lock").write_text("task_id: AAA\nbranch: feat/x\n", encoding="utf-8")
    (repo / "sysop/runtime/locks" / "AAA.lock").symlink_to(vault / "real.lock")
    _lock(repo, "TASK-1", "feat/x")
    vault.chmod(0)
    try:
        r = subprocess.run([_pre_313_python(), str(script), "feat/x"], cwd=str(repo),
                           capture_output=True, text=True, timeout=30)
    finally:
        vault.chmod(0o755)
    assert r.returncode == 0, r.stderr
    assert "TASK-1" in r.stdout, r.stdout
