"""`clear_user_action.py` — the clearing `Q-314` found nobody had written.

`user_action: true` gates dispatch: all three frontier filters exclude the task
from automated pickup. No shipped writer ever cleared it, so once the human had
supplied the credential the task was excluded **forever** — while
`roadmap/SKILL.md`'s unblock-the-human-first ordering promised that clearing it
early "converts a serial stall into parallel progress", and nothing implemented
a clearing. The only escape was a hand edit the tree never instructed, and which
`tasks/schema.md` then contradicted by scoping the `## User ops` section
"present only when `user_action: true`" — so following the schema you had to
delete the record of the step you had just performed.

Phase 237 ships the mechanism (one field, not two) and fixes both doc halves.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _prose_guard_helpers import normalize, section, states  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core/companion/scripts/clear_user_action.py"
CLAIM_SH = REPO_ROOT / "core/companion/scripts/claim_task.sh"
SCHEMA = REPO_ROOT / "core/companion/tasks/schema.md"
ROADMAP = REPO_ROOT / "core/skills/roadmap/SKILL.md"

INDEX = """schema_version: 1
phases:
  - id: P1
    title: first
tasks:
  - id: DATA-0001
    title: seed the vendor feed
    phase: P1
    status: open
    effort: 3
    user_action: true
    body: open/DATA-0001.md
  - id: TECH-0002
    title: no human step
    phase: P1
    status: open
    effort: 2
    user_action: false
    body: open/TECH-0002.md
  - id: DONE-0003
    title: closed already
    phase: P1
    status: done
    effort: 1
    user_action: true
    body: archive/DONE-0003.md
"""


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "proj"
    (root / "tasks").mkdir(parents=True)
    (root / "tasks" / "index.yml").write_text(INDEX, encoding="utf-8")
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
        check=True, capture_output=True,
    )
    return root


def _run(repo: Path, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(repo), capture_output=True, text=True,
    )


def _flag(repo: Path, task_id: str):
    data = yaml.safe_load((repo / "tasks" / "index.yml").read_text())
    for t in data["tasks"]:
        if t["id"] == task_id:
            return t.get("user_action", "<absent>")
    raise AssertionError(f"{task_id} not in index")


class TestItClears:
    def test_a_true_flag_becomes_false(self, repo):
        r = _run(repo, "DATA-0001")
        assert r.returncode == 0, r.stderr
        assert _flag(repo, "DATA-0001") is False

    def test_it_reports_the_task_rejoined_the_frontier(self, repo):
        r = _run(repo, "DATA-0001")
        assert "agent-executable frontier" in r.stdout

    def test_a_non_open_task_is_cleared_but_says_the_frontier_wont_take_it(self, repo):
        """Honest reporting beats a refusal. Clearing on a `done` task is not
        wrong, it is just not sufficient — and saying so is what stops the next
        reader concluding the mechanism is broken."""
        r = _run(repo, "DONE-0003")
        assert r.returncode == 0, r.stderr
        assert _flag(repo, "DONE-0003") is False
        assert "still will not pick it up" in r.stdout

    def test_it_never_commits(self, repo):
        _run(repo, "DATA-0001")
        log = subprocess.run(["git", "log", "--oneline"], cwd=repo,
                             capture_output=True, text=True)
        assert log.stdout.strip() == "", "the script committed"

    def test_it_hands_back_the_commit(self, repo):
        r = _run(repo, "DATA-0001")
        assert "git add tasks/index.yml" in r.stdout

    def test_it_leaves_no_temp_file_behind(self, repo):
        _run(repo, "DATA-0001")
        leftovers = [p.name for p in (repo / "tasks").iterdir()
                     if p.name.endswith(".tmp") or ".tmp" in p.name]
        assert not leftovers, leftovers

    def test_only_the_named_task_moves(self, repo):
        _run(repo, "DATA-0001")
        assert _flag(repo, "DONE-0003") is True, "a sibling flag was cleared"


class TestItWritesNothingWhenItShouldNot:
    def test_dry_run_writes_nothing(self, repo):
        before = (repo / "tasks" / "index.yml").read_text()
        r = _run(repo, "--dry-run", "DATA-0001")
        assert r.returncode == 0, r.stderr
        assert "DRY RUN" in r.stdout
        assert (repo / "tasks" / "index.yml").read_text() == before

    def test_an_already_false_flag_is_not_an_error_and_writes_nothing(self, repo):
        """Re-running after a successful clear is the ordinary way a human
        checks. A script that fails on its own settled state teaches people to
        ignore its exit code."""
        before = (repo / "tasks" / "index.yml").read_text()
        r = _run(repo, "TECH-0002")
        assert r.returncode == 0, r.stderr
        assert "nothing to clear" in r.stdout
        assert (repo / "tasks" / "index.yml").read_text() == before

    def test_running_twice_is_idempotent(self, repo):
        assert _run(repo, "DATA-0001").returncode == 0
        after_first = (repo / "tasks" / "index.yml").read_text()
        assert _run(repo, "DATA-0001").returncode == 0
        assert (repo / "tasks" / "index.yml").read_text() == after_first

    def test_an_unknown_task_refuses_and_writes_nothing(self, repo):
        before = (repo / "tasks" / "index.yml").read_text()
        r = _run(repo, "NOPE-9999")
        assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
        assert "not in" in r.stderr
        assert (repo / "tasks" / "index.yml").read_text() == before

    def test_a_missing_index_refuses(self, repo):
        (repo / "tasks" / "index.yml").unlink()
        r = _run(repo, "DATA-0001")
        assert r.returncode == 1, (r.returncode, r.stderr)
        assert "no task index" in r.stderr

    def test_outside_a_git_repo_it_refuses(self, tmp_path):
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "DATA-0001"],
            cwd=str(tmp_path), capture_output=True, text=True,
            env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin",
                 "GIT_CEILING_DIRECTORIES": str(tmp_path.parent)},
        )
        assert r.returncode != 0


# ── Where the `safe_dump` kwargs are pinned: NOT here ──
#
# The first cut of this module carried a `TestTheTwoWritersOfTheIndexAgree`
# class comparing `clear_user_action.py`'s dump kwargs against
# `claim_task.sh`'s, on the stated warrant that "nothing else compares them".
# That warrant was false, and this same commit falsified it: `tasks/index.yml`
# has **six** whole-file `yaml.safe_dump` writers, not two, and
# `tests/test_index_writer_class.py::test_every_index_writer_carries_the_canonical_kwargs`
# has pinned all of them since Phase 201 — parametrized over `INDEX_WRITERS`,
# which this phase added `clear_user_action.py` to. A two-member roster over a
# shipped six-member guard is the Phase-204 shape: it answers "is this
# guarded?" with a smaller and wronger set than the truth. Deleted rather than
# extended; the coverage lives next door and covers more.


class TestTheDocHalvesOfQ314:
    """Both halves are prose, so both are guarded through the shipped helpers.

    The first cut of this class used `assert "<literal>" in <whole file>` and
    failed on contact — the phrase it looked for is hard-wrapped in the source,
    so the substring does not exist. That is the same class Phase 236 recorded
    five of, which is why `normalize()` (folds wrapping and emphasis) and
    `section()` (slices to the next same-or-higher heading, and refuses a
    duplicate heading) exist.
    """

    def _user_ops(self) -> str:
        return section(SCHEMA.read_text(), "### User ops")

    def test_the_schema_no_longer_scopes_user_ops_to_the_flag(self):
        """The trap: following the schema, a human who performed the step had to
        delete the record of having performed it.

        Pinned on the ASSERTION, not the words. The correction has to quote the
        retired phrase in order to retire it, so a bare `not in file` would fail
        on the fix and pass only if the record of the fix were deleted — a guard
        rewarding the exact regression it exists to catch. So: the phrase may
        appear inside the paragraph that retires it, and nowhere else.
        """
        body = normalize(self._user_ops())
        # **Normalize the NEEDLE too.** `normalize()` strips `_`/`*`/backticks,
        # so `user_action` becomes `useraction` in `body` — and the first cut of
        # this test compared against a needle that still had the underscore.
        # It therefore counted 0 on every input, the `if occurrences:` branch
        # holding all the assertions never ran, and the test passed trivially
        # whatever schema.md said. Found by this phase's round (guards lens),
        # which is exactly what a guards lens is for: the test was green on the
        # pristine tree and green on a mutation that restored the retired rule
        # as a LIVE rule.
        retired = normalize("present only when `user_action: true`")
        assert retired == "present only when useraction: true", (
            f"normalize() changed shape; this needle no longer matches what it "
            f"is meant to find: {retired!r}"
        )
        occurrences = body.count(retired)
        # **The retirement must be RECORDED, not merely absent.** Deleting the
        # retiring paragraph outright also drives `occurrences` to 0, so an
        # `if occurrences:` test alone is satisfied by erasing the history of
        # the fix — which is the mirror of the failure the brief warns about
        # (a bare `not in file` fails ON the fix). Require the record, then
        # bound where the phrase may appear.
        assert states(body, "This sentence used to read"), (
            "tasks/schema.md no longer records that the User-ops scoping was "
            "retired — the phrase may be gone, but so is the reason, and the "
            "next author has nothing stopping them reinstating it"
        )
        if occurrences:
            assert "used to read" in body, (
                "tasks/schema.md scopes the User ops section to the flag again, "
                "with no sentence retiring it"
            )
            assert occurrences == 1, (
                f"the retired scoping appears {occurrences} times; only the "
                f"sentence that retires it may carry it"
            )

    def test_the_schema_says_the_section_survives_the_clearing(self):
        assert states(normalize(self._user_ops()), "kept after the flag is cleared")

    def test_the_schema_names_the_clearing_command(self):
        assert "clear_user_action.py" in self._user_ops()

    def test_the_schema_states_why_it_is_one_field_and_not_two(self):
        """The decision, not just the mechanism. Without it the next reader
        re-derives the `user_action_done:` companion the filing proposed."""
        body = normalize(self._user_ops())
        assert states(body, "One field, not two")

    def test_roadmaps_promise_names_its_mechanism(self):
        """`roadmap/SKILL.md` promised a clearing for many phases while nothing
        implemented one. A promise whose mechanism is unnamed is the defect."""
        text = ROADMAP.read_text()
        i = text.index("clearing it early converts a serial stall")
        window = text[i:i + 800]
        assert "clear_user_action.py" in window, (
            "the promise still does not name the command that keeps it"
        )

    def test_the_script_is_documented_in_workflow_8_4(self):
        wf = (REPO_ROOT / "core/companion/docs/WORKFLOW.md").read_text()
        assert "`clear_user_action.py" in wf

    def test_the_permission_template_binds_the_invocation_the_docs_prescribe(self):
        """A rule seeded against an invocation nothing issues binds nothing
        (Phase 152). The docs prescribe `python3 sysop/scripts/...`, so that is
        the command word the rule must carry."""
        import json
        rules = json.loads(
            (REPO_ROOT / "core/companion/.claude/settings.json").read_text()
        )["permissions"]["allow"]
        assert "Bash(python3 sysop/scripts/clear_user_action.py:*)" in rules
