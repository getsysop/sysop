"""`Q-575` — an expired lock that still carries the seeded placeholder is warned about.

Both lock writers (`claim_task.sh`, `batch_work.sh`) seed
`plan_summary: (update with a one-line description of the work)` and an empty
`notes:`, and before this nothing read either field. Once `expires:` lapsed, a
deliberate park and an abandoned claim looked identical, and two sessions reached
the same wrong conclusion about one such lock by two different routes.

`validate_tasks.py` now WARNS (never errors) when a lock is past `expires:` AND
still carries the placeholder. The tests here pin:

* the constant is what BOTH writers emit — derived by running them;
* the two conditions are ANDed — each arm has a control that changes only what
  that arm reads;
* the reported discrimination: flags an expired placeholder lock, and not an
  annotated park with an extended expiry, an expired lock whose summary was
  filled in, or a fresh lock;
* the scope: an `in_progress` task's lock and a `BATCH-<N>.lock`, not an orphan
  lock with no in_progress task;
* altitude: a warning never changes the exit code, and nothing a stub or
  hand-edited lock can contain crashes the validator.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import validate_tasks as vt

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
VALIDATE = SCRIPTS / "validate_tasks.py"

PAST = "2020-01-01T00:00:00Z"
FUTURE = "2999-01-01T00:00:00Z"
PLACEHOLDER = vt.LOCK_PLAN_SUMMARY_PLACEHOLDER


def _index(*ids):
    entries = "".join(
        f"  - id: {tid}\n    title: \"t\"\n    phase: 1\n    status: in_progress\n"
        f"    effort: Low\n    user_action: false\n    depends_on: []\n"
        f"    surfaced_by: []\n    body: tasks/open/{tid}.md\n"
        for tid in ids
    )
    return ("schema_version: 1\n\nphases:\n  - number: 1\n    title: \"P\"\n"
            "    status: in_progress\n    current_focus: true\n\ntasks:\n" + entries)


def _tree(root, *ids):
    """A tasks/ tree whose tasks are all in_progress. Not a git repo, so the
    locks dir falls back to <root>/sysop/runtime/locks."""
    tasks = root / "tasks"
    (tasks / "open").mkdir(parents=True)
    (tasks / "index.yml").write_text(_index(*ids))
    for tid in ids:
        (tasks / "open" / f"{tid}.md").write_text(f"# {tid}\n\nbody.\n")
    locks = root / "sysop/runtime/locks"
    locks.mkdir(parents=True)
    return tasks, locks


def _lock_body(claim, expires, summary, notes=""):
    lines = [f"task_id: {claim}", "status: in_progress", "agent: a", "branch: b"]
    if expires is not None:
        lines.append(f"expires: {expires}")
    if summary is not None:
        lines.append(f"plan_summary: {summary}")
    lines.append(f"notes:{(' ' + notes) if notes else ''}")
    return "\n".join(lines) + "\n"


def _flagged(report):
    return [w for w in report.warnings if "does not say why it is still held" in w.message]


def _validate(tmp_path, locks_by_claim, ids=("FEAT-ONE",)):
    tasks, locks = _tree(tmp_path, *ids)
    for claim, body in locks_by_claim.items():
        p = locks / f"{claim}.lock"
        if isinstance(body, bytes):
            p.write_bytes(body)
        else:
            p.write_text(body)
    return vt.validate(tasks, project_root=tmp_path)


# ── The constant is what both writers emit ───────────────────────────────────

class TestPlaceholderIsSingleSourced:
    """Derived by RUNNING both writers, so a reworded seed in either reddens this
    instead of silently disabling the check."""

    def test_claim_task_sh_emits_the_constant(self, tmp_path):
        from tests.test_claim_task_sh import _repo, _run
        repo = _repo(tmp_path / "repo")
        r = _run(repo, "--branch", "--lock", "FEAT-ONE", "feat/one", "Agent-7")
        assert r.returncode == 0, r.stderr
        text = (repo / "sysop/runtime/locks/FEAT-ONE.lock").read_text()
        assert yaml.safe_load(text)["plan_summary"] == PLACEHOLDER
        assert f"\nplan_summary: {PLACEHOLDER}\n" in text, "not byte-identical"

    def test_batch_work_sh_emits_the_constant(self, tmp_path):
        from tests.test_batch_claim_kinds import _claim, _lock, _repo
        repo = _repo(tmp_path / "repo")
        _claim(repo, 7)
        text = _lock(repo, 7).read_text()
        assert yaml.safe_load(text)["plan_summary"] == PLACEHOLDER
        assert f"\nplan_summary: {PLACEHOLDER}\n" in text, "not byte-identical"


# ── End to end, from a lock a writer actually produced ───────────────────────

class TestWriterProducedLock:
    def _claimed_repo(self, tmp_path):
        from tests.test_claim_task_sh import _repo, _run
        repo = _repo(tmp_path / "repo")
        tasks = repo / "tasks"
        (tasks / "open").mkdir(parents=True)
        (tasks / "index.yml").write_text(_index("FEAT-ONE"))
        (tasks / "open" / "FEAT-ONE.md").write_text("# FEAT-ONE\n\nbody.\n")
        r = _run(repo, "--branch", "--lock", "FEAT-ONE", "feat/one", "Agent-7")
        assert r.returncode == 0, r.stderr
        return repo, repo / "sysop/runtime/locks/FEAT-ONE.lock"

    def test_a_fresh_claim_is_silent(self, tmp_path):
        repo, _ = self._claimed_repo(tmp_path)
        report = vt.validate(repo / "tasks", project_root=repo)
        assert report.ok, [e.format() for e in report.errors]
        assert _flagged(report) == [], [w.format() for w in report.warnings]

    def test_the_same_claim_past_its_expiry_is_flagged(self, tmp_path):
        repo, lock = self._claimed_repo(tmp_path)
        text = lock.read_text()
        before = text
        text = "\n".join(
            f"expires: {PAST}" if ln.startswith("expires: ") else ln
            for ln in text.split("\n"))
        assert text != before, "fixture edit did not apply"
        lock.write_text(text)
        report = vt.validate(repo / "tasks", project_root=repo)
        assert report.ok, "a warning must never become an error"
        flagged = _flagged(report)
        assert len(flagged) == 1, [w.format() for w in report.warnings]
        msg = flagged[0].message
        assert "FEAT-ONE" in msg and PAST in msg
        # The warning names all three ways out, and never offers release for finished work.
        assert "plan_summary" in msg and "extend expires:" in msg
        assert "/review-close" in msg and "do not release it" in msg
        assert "bash sysop/scripts/claim_task.sh --release FEAT-ONE" in msg


# ── The discrimination the entry requires, one control per ANDed arm ──────────

class TestDiscrimination:
    def test_expired_placeholder_is_flagged(self, tmp_path):
        report = _validate(tmp_path, {"FEAT-ONE": _lock_body("FEAT-ONE", PAST, PLACEHOLDER)})
        assert len(_flagged(report)) == 1
        assert report.ok

    def test_expiry_arm_control_fresh_placeholder_is_silent(self, tmp_path):
        """Differs from the flagged row ONLY in `expires:`."""
        report = _validate(tmp_path, {"FEAT-ONE": _lock_body("FEAT-ONE", FUTURE, PLACEHOLDER)})
        assert _flagged(report) == []

    def test_summary_arm_control_expired_but_filled_is_silent(self, tmp_path):
        """Differs from the flagged row ONLY in `plan_summary:`."""
        report = _validate(tmp_path, {"FEAT-ONE": _lock_body("FEAT-ONE", PAST, "wire the importer")})
        assert _flagged(report) == []

    def test_annotated_park_with_extended_expiry_is_silent(self, tmp_path):
        """The reported install's three correctly-read locks."""
        body = _lock_body("FEAT-ONE", FUTURE, "NOT STALE - BLOCKED ON vendor key",
                          notes="parked 2026-09-18, resumes when the key lands")
        report = _validate(tmp_path, {"FEAT-ONE": body})
        assert _flagged(report) == []

    def test_a_mixed_install_flags_exactly_the_unannotated_one(self, tmp_path):
        """The reported shape: four live locks, three annotated, one not."""
        ids = ("FEAT-A", "FEAT-B", "FEAT-C", "FEAT-D")
        locks = {
            "FEAT-A": _lock_body("FEAT-A", FUTURE, "NOT STALE: waiting on review"),
            "FEAT-B": _lock_body("FEAT-B", FUTURE, "BLOCKED ON upstream fix"),
            "FEAT-C": _lock_body("FEAT-C", FUTURE, "NOT STALE: long migration"),
            "FEAT-D": _lock_body("FEAT-D", PAST, PLACEHOLDER),
        }
        report = _validate(tmp_path, locks, ids=ids)
        flagged = _flagged(report)
        assert len(flagged) == 1 and "FEAT-D" in flagged[0].message, \
            [w.format() for w in report.warnings]

    def test_notes_arm_control_expired_but_annotated_in_notes_is_silent(self, tmp_path):
        """Differs from the flagged row ONLY in `notes:`. The schema tells an operator to
        write why in `plan_summary` or `notes`, so either one annotates the claim."""
        body = _lock_body("FEAT-ONE", PAST, PLACEHOLDER, notes="PARKED, blocked on vendor key")
        report = _validate(tmp_path, {"FEAT-ONE": body})
        assert _flagged(report) == [], [w.format() for w in report.warnings]

    @pytest.mark.parametrize("claim", ["FEAT-ONE", "BATCH-4"])
    def test_park_record_arm_control_a_recorded_park_is_silent(self, tmp_path, claim):
        """Differs from the flagged row ONLY in a park record: `/claim-task` (for a task or
        a `BATCH-<N>`) and `/auto-build` park by leaving the lock and writing
        `sysop/runtime/parked/<ID>__<RUN>.md`, and never touch `plan_summary`."""
        import os
        tasks, locks = _tree(tmp_path, "FEAT-ONE")
        body = _lock_body(claim, PAST, PLACEHOLDER) + "started: 2020-01-01T00:00:00Z\n"
        (locks / f"{claim}.lock").write_text(body)
        parked = locks.parent / "parked"
        parked.mkdir()
        (parked / f"{claim}X__20260101T000000Z-deadbeef.md").write_text("other claim\n")
        report = vt.validate(tasks, project_root=tmp_path)
        assert len(_flagged(report)) == 1, "a park record for ANOTHER id must not silence it"
        mine = parked / f"{claim}__20260101T000000Z-deadbeef.md"
        mine.write_text("parked: why\n")
        # Left over from an EARLIER claim of the same id: a release does not remove it,
        # so a record older than this claim's `started:` says nothing (round 2, lens 4).
        os.utime(mine, (1500000000, 1500000000))
        report = vt.validate(tasks, project_root=tmp_path)
        assert len(_flagged(report)) == 1, "a park record from before the claim must not silence it"
        os.utime(mine, None)
        report = vt.validate(tasks, project_root=tmp_path)
        assert _flagged(report) == [], [w.format() for w in report.warnings]

    @pytest.mark.parametrize("notes,flagged", [
        ("", 1), ("'   '", 1), ("[]", 1), ("{}", 1), ("0", 1), ("false", 1), ('[""]', 1), ("~", 1),
        ("PARKED, blocked on the vendor key", 0), ("[waiting on review]", 0), ("{why: vendor key}", 0),
    ])
    def test_only_text_in_notes_annotates(self, tmp_path, notes, flagged):
        """An empty container, a number or a boolean says nothing (round 2, lens 4)."""
        body = _lock_body("FEAT-ONE", PAST, PLACEHOLDER).replace("notes:\n", f"notes: {notes}\n")
        assert f"notes: {notes}" in body
        report = _validate(tmp_path, {"FEAT-ONE": body})
        assert len(_flagged(report)) == flagged, (notes, [w.format() for w in report.warnings])

    @pytest.mark.parametrize("offset,flagged", [(-5, 1), (60, 0)])
    def test_the_expiry_boundary_is_now(self, tmp_path, offset, flagged):
        """Seconds either side of now: no grace period, and no early warning."""
        from datetime import datetime, timedelta, timezone
        when = (datetime.now(timezone.utc) + timedelta(seconds=offset)).strftime("%Y-%m-%dT%H:%M:%SZ")
        report = _validate(tmp_path, {"FEAT-ONE": _lock_body("FEAT-ONE", when, PLACEHOLDER)})
        assert len(_flagged(report)) == flagged, when

    def test_placeholder_matched_after_yaml_quoting(self, tmp_path):
        """Quoting the untouched placeholder does not annotate it."""
        report = _validate(tmp_path, {"FEAT-ONE": _lock_body("FEAT-ONE", PAST, f'"{PLACEHOLDER}"')})
        assert len(_flagged(report)) == 1

    def test_placeholder_with_one_character_changed_is_silent(self, tmp_path):
        """Exact match, not a substring or prefix test: an operator who edited the
        text at all has written something."""
        edited = PLACEHOLDER.replace("work)", "work) - parked")
        report = _validate(tmp_path, {"FEAT-ONE": _lock_body("FEAT-ONE", PAST, edited)})
        assert _flagged(report) == []


# ── Scope: task locks and batch locks, not orphans ──────────────────────────

class TestScope:
    def test_an_expired_placeholder_batch_lock_is_flagged(self, tmp_path):
        report = _validate(tmp_path, {
            "FEAT-ONE": _lock_body("FEAT-ONE", FUTURE, PLACEHOLDER),
            "BATCH-12": _lock_body("BATCH-12", PAST, PLACEHOLDER),
        })
        flagged = _flagged(report)
        assert len(flagged) == 1, [w.format() for w in report.warnings]
        assert "BATCH-12" in flagged[0].message
        assert "bash sysop/scripts/batch_work.sh --release 12" in flagged[0].message

    def test_a_fresh_batch_lock_is_silent(self, tmp_path):
        report = _validate(tmp_path, {
            "FEAT-ONE": _lock_body("FEAT-ONE", FUTURE, PLACEHOLDER),
            "BATCH-12": _lock_body("BATCH-12", FUTURE, PLACEHOLDER),
        })
        assert _flagged(report) == []

    def test_a_lock_name_that_only_resembles_a_batch_is_not_read(self, tmp_path):
        report = _validate(tmp_path, {
            "FEAT-ONE": _lock_body("FEAT-ONE", FUTURE, PLACEHOLDER),
            "BATCH-X": _lock_body("BATCH-X", PAST, PLACEHOLDER),
            "OLD-BATCH-3": _lock_body("OLD-BATCH-3", PAST, PLACEHOLDER),
        })
        assert _flagged(report) == []

    def test_an_orphan_task_lock_is_not_this_checks_business(self, tmp_path):
        """A lock whose task is not in_progress (or not in the index) is an orphan,
        a different defect. Reading it here would warn on state the validator has
        no task entry to attribute to."""
        report = _validate(tmp_path, {
            "FEAT-ONE": _lock_body("FEAT-ONE", FUTURE, PLACEHOLDER),
            "FEAT-GONE": _lock_body("FEAT-GONE", PAST, PLACEHOLDER),
        })
        assert _flagged(report) == []


# ── What expiry can and cannot be read from ─────────────────────────────────

class TestExpiryParsing:
    @pytest.mark.parametrize("expires", [
        PAST,                          # the writers' format
        "2020-01-01",                  # a hand-written date
        "2020-01-01 00:00:00",         # naive, space-separated
        "2020-01-01T00:00:00+02:00",   # an explicit offset
        "'2020-01-01T00:00:00Z'",      # quoted: a string, not a YAML timestamp
        "'2020-01-01 00:00:00'",       # quoted AND naive: the fromisoformat path's UTC fix
    ])
    def test_readable_past_expiries_flag(self, tmp_path, expires):
        report = _validate(tmp_path, {"FEAT-ONE": _lock_body("FEAT-ONE", expires, PLACEHOLDER)})
        assert len(_flagged(report)) == 1, expires

    @pytest.mark.parametrize("expires", ["next tuesday", "", "12345", "2020-13-45T99:00:00Z"])
    def test_unreadable_expiry_is_silent_and_never_an_error(self, tmp_path, expires):
        """Expiry cannot be established, so the AND cannot be — no warning, and
        above all no crash and no error."""
        report = _validate(tmp_path, {"FEAT-ONE": _lock_body("FEAT-ONE", expires, PLACEHOLDER)})
        assert report.ok, [e.format() for e in report.errors]
        assert _flagged(report) == []

    def test_missing_expiry_is_silent(self, tmp_path):
        report = _validate(tmp_path, {"FEAT-ONE": _lock_body("FEAT-ONE", None, PLACEHOLDER)})
        assert report.ok and _flagged(report) == []

    @pytest.mark.parametrize("body", [
        "ci-stub: see .github/workflows/security.yml (task-schema)\n",   # a consumer CI stub
        "",                                                              # empty
        "- a\n- list\n",                                                 # not a mapping
        "task_id: [unclosed\n",                                          # YAML error
        b"plan_summary: \xff\xfe\n",                                     # not UTF-8
    ])
    def test_a_stub_or_broken_lock_never_crashes_or_errors(self, tmp_path, body):
        report = _validate(tmp_path, {"FEAT-ONE": body, "BATCH-4": body})
        assert report.ok, [e.format() for e in report.errors]
        assert _flagged(report) == []


# ── Altitude: a warning never changes the exit code ─────────────────────────

def test_the_cli_exits_zero_and_prints_the_warning(tmp_path):
    tasks, locks = _tree(tmp_path, "FEAT-ONE")
    (locks / "FEAT-ONE.lock").write_text(_lock_body("FEAT-ONE", PAST, PLACEHOLDER))
    r = subprocess.run([sys.executable, str(VALIDATE), "--path", str(tasks)],
                       capture_output=True, text=True, cwd=str(tmp_path),
                       env={**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null",
                            "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CEILING_DIRECTORIES": str(tmp_path.parent)})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[WARNING]" in r.stdout and "does not say why it is still held" in r.stdout, r.stdout
    assert "0 errors, 1 warnings" in r.stdout, r.stdout


def test_the_site_says_why_it_is_not_enforced():
    """The entry: 'why isn't this enforced?' is the first question a reader will
    have. The answer must sit at the check, in its docstring — not in a commit."""
    import inspect
    doc = inspect.getdoc(vt._check_expired_placeholder_lock) or ""
    flat = " ".join(doc.split())
    assert "A WARNING, never an error." in flat
    assert "`sysop/runtime/` is gitignored" in flat
    assert "stub locks" in flat


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0,
                    reason="root reads a mode-000 directory")
def test_an_unreadable_locks_dir_does_not_crash_the_validator(tmp_path):
    """The batch-lock listing is new code on the validator's path; a locks dir it
    cannot list must not turn a schema run into a `validator crashed` exit 2.
    (Invariant 9 still reports the lock it cannot see — that is its job.)"""
    tasks, locks = _tree(tmp_path, "FEAT-ONE")
    (locks / "FEAT-ONE.lock").write_text(_lock_body("FEAT-ONE", PAST, PLACEHOLDER))
    locks.chmod(0o000)
    try:
        report = vt.validate(tasks, project_root=tmp_path)
    finally:
        locks.chmod(0o755)
    assert _flagged(report) == []
