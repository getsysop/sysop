"""Phase 249 (`Q-369`): `/claim-task` Step 7e makes the executor responsible for writing
`## Test decision` into the task body, and on one consumer cycle it wrote it once out of
four — four branches claimed the same day through the same path, measured at the branch
tip. Two of the three misses shipped substantial tests, so this is a missing *record*,
not missing coverage.

Nothing downstream catches it in time. Phase 234 retired `validate_tasks.py`'s warn-only
Invariant 13 — correctly, since it read the body off the working tree while the record
lives on the branch — which leaves `/review-close` Step 2d as the only enforcement, at
the merge, after implementation, where the dispositions are waive or hold otherwise-ready
work. The record is cheap at plan time and expensive at close time.

Two arms ship, and this file exercises the load-bearing one. The executor now re-reads
its own write before committing; but the failure being closed *is* an executor skipping
a sequence item, so the arm that decides the case is the ORCHESTRATOR's, at Step 8 —
a different agent, deterministic, reading the same revision Step 2d will read.

The probe is EXTRACTED from the shipped skill and RUN over every shape it distinguishes,
because the defects that matter in this repo come from running the prescribed commands
rather than reading them.
"""
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "core/skills/claim-task/SKILL.md"
BODY_NEEDLE = "NOT ON BRANCH"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")

TEMPLATE = ('<recorded at /claim-task plan time — "test <X> proves <Y>" or '
            '"no test because <Z>". See "Test decision" below.>')


def _probe_block():
    """The shipped Step 8 read-back: (heredoc line, body).

    Selected by a string the block's own BODY emits, never by its opening line. The first
    version pinned the exact `python3 - <<'PY' "<CLAIM_ID>" …` line, so **reordering the
    positional arguments** — consistently, in both the heredoc line and the `sys.argv`
    unpack, a change that alters nothing — made every test in this file fail with
    `anchor is not unique (0 hits)`. Failure-to-locate reported as failure-to-comply, in
    a module whose whole claim is that it runs the shipped block.
    """
    lines = SKILL.read_text(encoding="utf-8").split("\n")
    blocks, i = [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith("python3 - <<'PY'"):
            j = next((k for k in range(i + 1, len(lines)) if lines[k].strip() == "PY"), None)
            assert j is not None, "COULD NOT LOCATE: heredoc has no PY terminator"
            blocks.append((lines[i], "\n".join(lines[i + 1:j])))
            i = j
        i += 1
    hits = [b for b in blocks if BODY_NEEDLE in b[1]]
    assert len(hits) == 1, (
        f"COULD NOT LOCATE the Step 8 read-back: {len(hits)} of {len(blocks)} prescribed "
        f"python blocks contain {BODY_NEEDLE!r}. Nothing was measured — re-point this "
        f"extractor; do not read the failures below as the skill being wrong.")
    return hits[0]


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("claim")
    _git(root, "-c", "init.defaultBranch=main", "init", "-q", ".")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "README.md").write_text("x\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")

    for branch, section in {
        "good": "## Test decision\ntest tests/test_x.py::test_y proves the cap holds",
        "heading3": "### Test Decision\nno test because this is a pure rename",
        "missing": "## Notes\nnothing here",
        "template": "## Test decision\n" + TEMPLATE,
    }.items():
        _git(root, "checkout", "-q", "-b", branch, "main")
        body = root / "tasks" / "open" / "T.md"
        body.parent.mkdir(parents=True, exist_ok=True)
        body.write_text(f"# T\n\n{section}\n", encoding="utf-8")
        _git(root, "add", "-A")
        _git(root, "commit", "-qm", branch)
    _git(root, "checkout", "-q", "main")
    return root


def _probe() -> str:
    return _probe_block()[1] + "\n"


def _arg_order() -> list[str]:
    """The placeholder order the skill prescribes, read off the heredoc line.

    Derived rather than assumed so that reordering the three positional arguments —
    consistently, in both the heredoc line and the `sys.argv` unpack, which changes no
    behaviour — does not redden nineteen behavioural tests. The round wrote exactly that
    edit as a negative control and it fired.
    """
    order = re.findall(r"<([A-Z_]+)>", _probe_block()[0])
    assert sorted(order) == sorted(["CLAIM_ID", "BRANCH_NAME", "BODY_PATH_AS_RESOLVED"]), (
        f"COULD NOT LOCATE the probe's argument contract: parsed {order}. Nothing was "
        f"measured — re-point this helper.")
    return order


def _run(repo, claim, branch, body, cwd=None):
    vals = {"CLAIM_ID": claim, "BRANCH_NAME": branch, "BODY_PATH_AS_RESOLVED": body}
    argv = [vals[k] for k in _arg_order()]
    r = subprocess.run(["python3", "-", *argv],
                       input=_probe(), cwd=str(cwd or repo),
                       capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


class TestTheProbeBlocks:
    """Exit 1 is the loud arm. These two are the whole point of the read-back."""

    def test_a_missing_record_blocks(self, repo):
        rc, out = _run(repo, "CLAIM-1", "missing", "tasks/open/T.md")
        assert rc == 1 and out.startswith("MISSING"), (rc, out)

    def test_an_unfilled_schema_template_blocks(self, repo):
        """The one a bare heading check passes. `/review-close` Step 2d classifies a
        surviving placeholder as `missing`, so a probe that accepts it hands the close a
        record that will be rejected there anyway — one step too late to amend cheaply."""
        rc, out = _run(repo, "CLAIM-1", "template", "tasks/open/T.md")
        assert rc == 1 and out.startswith("TEMPLATE"), (rc, out)


class TestTheProbePasses:
    def test_a_written_record_passes(self, repo):
        rc, out = _run(repo, "CLAIM-1", "good", "tasks/open/T.md")
        assert rc == 0 and out.startswith("test-decision record present"), (rc, out)

    def test_the_heading_match_is_case_and_level_insensitive(self, repo):
        """`tasks/schema.md` defines the heading as any level whose text matches
        `test decision`, case-insensitively. A stricter probe would block `### Test
        Decision`, which the schema explicitly permits."""
        rc, out = _run(repo, "CLAIM-1", "heading3", "tasks/open/T.md")
        assert rc == 0 and out.startswith("test-decision record present"), (rc, out)


class TestTheNonBlockingArms:
    """Neither asserts anything about the record, so neither may block. A probe that
    exits 1 here halts a run over its own inability to read, which is the shape that
    gets a gate disabled by the first operator who hits it."""

    def test_a_body_absent_at_the_revision_reports_and_continues(self, repo):
        rc, out = _run(repo, "CLAIM-1", "main", "tasks/open/T.md")
        assert rc == 0 and out.startswith("NOT ON BRANCH"), (rc, out)

    def test_an_unresolvable_revision_reports_and_continues(self, repo):
        rc, out = _run(repo, "CLAIM-1", "no-such-branch", "tasks/open/T.md")
        assert rc == 0 and out.startswith("UNREADABLE"), (rc, out)

    def test_the_two_are_not_collapsed(self, repo):
        """They have different causes and different remedies: one is the documented
        untracked-body case, the other is a wrong branch or path."""
        _, absent = _run(repo, "CLAIM-1", "main", "tasks/open/T.md")
        _, unread = _run(repo, "CLAIM-1", "no-such-branch", "tasks/open/T.md")
        assert absent.split()[0] != unread.split()[0]


class TestTheProbeIsNotFooled:
    @pytest.mark.parametrize("slot", ["CLAIM_ID", "BRANCH_NAME", "BODY_PATH_AS_RESOLVED"])
    def test_every_argument_is_checked_for_an_unsubstituted_placeholder(self, repo, slot):
        """The round narrowed the guard to `claim_id` alone and it survived, because the
        only test passed an unsubstituted `<CLAIM_ID>`. With the body path unchecked the
        probe reports the DOCUMENTED benign case and exits 0 on a branch whose record is
        genuinely missing — a fabricated pass, which is the one outcome this block's own
        prose says at length it must never produce."""
        vals = {"CLAIM_ID": "CLAIM-1", "BRANCH_NAME": "good",
                "BODY_PATH_AS_RESOLVED": "tasks/open/T.md"}
        vals[slot] = f"<{slot}>"
        r = subprocess.run(["python3", "-", *[vals[k] for k in _arg_order()]],
                           input=_probe(), cwd=str(repo), capture_output=True, text=True)
        assert r.returncode == 2, (slot, r.returncode, r.stdout, r.stderr)
        assert "placeholder not substituted" in r.stderr.lower(), (slot, r.stderr)

    def test_an_unsubstituted_placeholder_refuses(self, repo):
        vals = {"CLAIM_ID": "<CLAIM_ID>", "BRANCH_NAME": "good",
                "BODY_PATH_AS_RESOLVED": "tasks/open/T.md"}
        r = subprocess.run(["python3", "-", *[vals[k] for k in _arg_order()]],
                           input=_probe(), cwd=str(repo), capture_output=True, text=True)
        assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
        assert "placeholder not substituted" in r.stderr.lower(), r.stderr

    def test_it_reads_the_branch_tip_not_HEAD(self, repo):
        """The failure that can fabricate a pass. An operand that loses its `<rev>:`
        turns `git show <path>` into `git show HEAD -- <path>`, which exits 0 off the
        WRONG revision. Standing on `good`, a HEAD-read of the `missing` branch would
        report a record that is not there."""
        _git(repo, "checkout", "-q", "good")
        try:
            rc, out = _run(repo, "CLAIM-1", "missing", "tasks/open/T.md")
        finally:
            _git(repo, "checkout", "-q", "main")
        assert rc == 1 and out.startswith("MISSING"), (rc, out)

    def test_it_works_from_a_subdirectory(self, repo):
        """The answer must not depend on where the orchestrator stands.

        **This does not prove the `--git-common-dir` resolution is load-bearing, and an
        earlier docstring said it did.** Measured by the round: delete the resolution
        entirely and every cell of a three-vantage matrix is unchanged, because
        `git show <rev>:<path>` resolves the path from the repo root whatever the CWD.
        The resolution is kept for consistency with the stranded-body probe beside it,
        which genuinely needs it (`git -C main_root diff`), and this test is a regression
        guard on the ANSWER, not evidence for the mechanism."""
        deep = repo / "deep" / "er"
        deep.mkdir(parents=True, exist_ok=True)
        rc, out = _run(repo, "CLAIM-1", "missing", "tasks/open/T.md", cwd=deep)
        assert rc == 1 and out.startswith("MISSING"), (rc, out)


class TestTheHostileCorpus:
    """`tasks/schema.md` documents that `## Plan` carries the reviewed plan verbatim in a
    fenced block, that *"the fenced plan contains its own `## Test decision` line"*, and
    that the real section is ordered FIRST so a first-match reader meets it first.

    That makes this probe a predicate applied to text other writers produce, which is the
    author-side pass's rule-4 trigger. Built after the first version rather than before it
    — the rule says before — and it found two defects in that version, one in each
    direction: a body with NO real record read as compliant (fence-blind matching), and a
    body with a GOOD record was refused because the plan fence quoted the schema
    (whole-body template test). The false refusal is the worse of the two: that is the
    direction that gets a gate switched off by the first operator who meets it.
    """

    TPL = TEMPLATE

    @staticmethod
    def _body(section: str) -> str:
        return "# T\n\n" + section + "\n"

    def _branch(self, repo, name, section):
        _git(repo, "checkout", "-q", "-b", name, "main")
        body = repo / "tasks" / "open" / "T.md"
        body.parent.mkdir(parents=True, exist_ok=True)
        body.write_text(self._body(section), encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", name)
        _git(repo, "checkout", "-q", "main")
        return name

    def test_a_record_that_exists_only_inside_the_plan_fence_is_missing(self, repo):
        """The false PASS. Fence-blind, this body certifies as having a record when the
        only occurrence is the plan's own copy — precisely the shape the schema's
        ordering note exists to warn readers about."""
        b = self._branch(repo, "h-only-fenced",
                         "## Notes\nnone\n\n## Plan\n```\n## Test decision\n"
                         "test only inside the fence\n```")
        rc, out = _run(repo, "CLAIM-1", b, "tasks/open/T.md")
        assert rc == 1 and out.startswith("MISSING"), (rc, out)

    def test_a_good_record_is_not_refused_because_the_plan_quotes_the_schema(self, repo):
        """The false REFUSAL. The record is present and filled; the plan fence happens to
        contain the schema placeholder. A whole-body template test blocks the claim."""
        b = self._branch(repo, "h-fenced-template",
                         "## Test decision\ntest tests/test_y.py proves the cap\n\n"
                         "## Plan\n```\n## Test decision\n" + self.TPL + "\n```")
        rc, out = _run(repo, "CLAIM-1", b, "tasks/open/T.md")
        assert rc == 0 and out.startswith("test-decision record present"), (rc, out)

    def test_the_real_section_still_wins_when_both_are_present(self, repo):
        b = self._branch(repo, "h-real-plus-fenced",
                         "## Test decision\ntest tests/test_x.py proves the cap\n\n"
                         "## Plan\n```\n## Test decision\ntest something else\n```")
        rc, out = _run(repo, "CLAIM-1", b, "tasks/open/T.md")
        assert rc == 0, (rc, out)

    def test_a_template_real_section_blocks_even_with_a_filled_copy_in_the_fence(self, repo):
        """The record that matters is the section, not the best-looking occurrence."""
        b = self._branch(repo, "h-template-plus-fenced",
                         "## Test decision\n" + self.TPL + "\n\n"
                         "## Plan\n```\n## Test decision\ntest a real one proves it\n```")
        rc, out = _run(repo, "CLAIM-1", b, "tasks/open/T.md")
        assert rc == 1 and out.startswith("TEMPLATE"), (rc, out)

    def test_it_does_not_depend_on_the_schemas_section_ordering(self, repo):
        """The schema orders the real section first and says why. Depending on that would
        make this probe correct only while every writer honours it; fence-awareness makes
        the ordering a convenience rather than a load-bearing assumption."""
        b = self._branch(repo, "h-plan-first",
                         "## Plan\n```\n## Test decision\ntest inside the plan fence\n```\n\n"
                         "## Test decision\ntest tests/test_z.py proves it")
        rc, out = _run(repo, "CLAIM-1", b, "tasks/open/T.md")
        assert rc == 0 and out.startswith("test-decision record present"), (rc, out)

    def test_an_unterminated_fence_reports_and_does_not_block(self, repo):
        """A fence that never closes swallows the rest of the body. Phase 181 measured
        this exact shape being handled *worse* than the bug it replaced, so the arm is
        explicit: say the body is malformed, fall back to a fence-blind read — which can
        only err toward accepting — and let Step 2d re-read the same record at the merge.
        Blocking here would refuse a claim over a formatting defect in its body."""
        b = self._branch(repo, "h-unterminated",
                         "## Plan\n```\n## Test decision\ntest inside a fence that never closes")
        rc, out = _run(repo, "CLAIM-1", b, "tasks/open/T.md")
        assert rc == 0, (rc, out)
        assert "unbalanced" in out.lower(), out


class TestTheFenceScannerMatchesTheWritersItReads:
    """The round's HIGH, and the reason it was HIGH: the first fence scanner recognised
    only ``` and ignored fence LENGTH, while `/claim-task` Step 7f — the writer that puts
    a `## Plan` on a body in the first place — emits *"a fence longer than any run of
    backticks in EITHER embedded document"*. So a plan containing an ordinary ```-block
    is wrapped in a FOUR-backtick fence, the 3-backtick reader treats the plan's first
    inner fence as the close, and everything after it is read as body. Measured on a real
    option-C body with no record at all: `rc=0 test-decision record present`.

    The correct scanner already shipped 400 lines earlier in the same file (`fence_mark`),
    with a docstring naming both properties. This phase re-derived it and got both wrong.
    """

    @staticmethod
    def _commit(repo, name, body):
        _git(repo, "checkout", "-q", "-b", name, "main")
        f = repo / "tasks" / "open" / "T.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
        _git(repo, "add", "-A"); _git(repo, "commit", "-qm", name)
        _git(repo, "checkout", "-q", "main")
        return name

    def test_a_four_backtick_plan_fence_does_not_leak_its_own_heading(self, repo):
        body = (
            "# T\n\n## Requirements\n1. thing\n\n## Plan\n"
            "````markdown\n### Steps\n1. The section to change reads:\n\n"
            "```markdown\n## Test decision\ntest tests/test_gate.py proves the halt\n```\n"
            "````\n")
        b = self._commit(repo, "f-nested4", body)
        rc, out = _run(repo, "CLAIM-1", b, "tasks/open/T.md")
        assert rc == 1 and out.startswith("MISSING"), (rc, out)

    def test_a_tilde_fence_is_a_fence(self, repo):
        body = ("# T\n\n## Plan\n~~~markdown\n## Test decision\n"
                "test only inside a tilde fence\n~~~\n")
        b = self._commit(repo, "f-tilde", body)
        rc, out = _run(repo, "CLAIM-1", b, "tasks/open/T.md")
        assert rc == 1 and out.startswith("MISSING"), (rc, out)

    def test_a_shorter_run_inside_a_longer_fence_does_not_close_it(self, repo):
        """The length half, isolated: the record is real and OUTSIDE the plan, and the
        plan's inner ``` must not end the outer ```` early and start swallowing it."""
        body = ("# T\n\n## Test decision\ntest tests/test_real.py proves it\n\n"
                "## Plan\n````\n```\nsome code\n```\n````\n")
        b = self._commit(repo, "f-length", body)
        rc, out = _run(repo, "CLAIM-1", b, "tasks/open/T.md")
        assert rc == 0 and out.startswith("test-decision record present"), (rc, out)


class TestTheProbeInternals:
    """Rows the round found living where no fixture reached: which heading wins, whether
    an indented fence is a fence, and which heading levels count."""

    @staticmethod
    def _commit(repo, name, body):
        _git(repo, "checkout", "-q", "-b", name, "main")
        f = repo / "tasks" / "open" / "T.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body, encoding="utf-8")
        _git(repo, "add", "-A"); _git(repo, "commit", "-qm", name)
        _git(repo, "checkout", "-q", "main")
        return name

    def test_the_first_matching_section_is_the_record_not_the_last(self, repo):
        """`tasks/schema.md` orders the real section first. Grading the LAST match reads a
        later duplicate — which is what a half-applied edit leaves behind."""
        b = self._commit(repo, "i-two-sections",
                         "# T\n\n## Test decision\n" + TEMPLATE +
                         "\n\n## Test decision\ntest tests/test_late.py proves it\n")
        rc, out = _run(repo, "CLAIM-1", b, "tasks/open/T.md")
        assert rc == 1 and out.startswith("TEMPLATE"), (rc, out)

    def test_an_indented_fence_is_still_a_fence(self, repo):
        """A plan nested under a list item is indented. `lstrip()` is what makes the
        scanner see it; without that the fenced copy leaks out as the record."""
        b = self._commit(repo, "i-indented",
                         "# T\n\n## Plan\n1. like so:\n\n   ```\n   ## Test decision\n"
                         "   test inside an indented fence\n   ```\n")
        rc, out = _run(repo, "CLAIM-1", b, "tasks/open/T.md")
        assert rc == 1 and out.startswith("MISSING"), (rc, out)

    def test_every_heading_level_the_schema_permits_is_accepted(self, repo):
        """`tasks/schema.md` permits any level. Narrowing the pattern refuses a
        schema-legal body, which is the over-strictness direction."""
        for lvl in (1, 2, 3, 4, 5, 6):
            b = self._commit(repo, f"i-h{lvl}",
                             f"# T\n\n{'#' * lvl} Test decision\nno test because docs only\n")
            rc, out = _run(repo, "CLAIM-1", b, "tasks/open/T.md")
            assert rc == 0, (lvl, rc, out)


class TestTheAbsentBodyMessages:
    """git emits two different fatals for an absent path, and which one you get depends on
    whether the file is in the WORKTREE:

      - `does not exist in '<rev>'`            — absent from disk too
      - `exists on disk, but not in '<rev>'`   — present but untracked

    The documented case this arm exists for — an `/add-task` body nobody committed — always
    leaves the file on disk, so it produces the SECOND message. The first version tested
    only the first string, which pointed the reassuring "Expected ONLY for…" text at the
    suspicious case and handed the benign one a raw fatal. Exactly inverted.
    """

    def test_the_documented_untracked_body_case_is_recognised(self, repo, tmp_path):
        _git(repo, "checkout", "-q", "-b", "d-untracked", "main")
        f = repo / "tasks" / "open" / "T.md"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("# T\n", encoding="utf-8")          # on disk, NEVER committed
        try:
            rc, out = _run(repo, "CLAIM-1", "d-untracked", "tasks/open/T.md")
        finally:
            f.unlink()
            _git(repo, "checkout", "-q", "main")
        assert rc == 0, (rc, out)
        assert out.startswith("NOT ON BRANCH"), out
        assert "add-task" in out, "the benign case lost its explanation: " + out

    def test_both_absent_shapes_land_on_the_same_arm(self, repo):
        rc, out = _run(repo, "CLAIM-1", "main", "tasks/open/T.md")
        assert rc == 0 and out.startswith("NOT ON BRANCH"), (rc, out)


def test_a_byte_order_mark_does_not_hide_the_record(repo):
    """A BOM keeps `^#` from matching, and the answer that produces is `MISSING`, which
    BLOCKS. A false halt over an invisible byte is the worst shape this probe has."""
    _git(repo, "checkout", "-q", "-b", "bom", "main")
    f = repo / "tasks" / "open" / "T.md"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\ufeff# T\n\n## Test decision\ntest tests/test_b.py proves it\n",
                 encoding="utf-8")
    _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "bom")
    _git(repo, "checkout", "-q", "main")
    rc, out = _run(repo, "CLAIM-1", "bom", "tasks/open/T.md")
    assert rc == 0 and out.startswith("test-decision record present"), (rc, out)


def _live_text() -> str:
    """The skill with HTML-comment regions removed.

    Every pin in this file was `"..." in text` over the raw bytes, so the round retired
    the ENTIRE 7e read-back arm by wrapping it in `<!-- RETIRED ... -->` and all three
    assertions still passed. A commented-out instruction is not shipped guidance; a
    presence check that cannot tell the difference is satisfied by a corpse.
    """
    return re.sub(r"<!--.*?-->", "", SKILL.read_text(encoding="utf-8"), flags=re.S)


def test_neither_arm_can_be_retired_by_commenting_it_out():
    live = _live_text()
    for phrase in ("**Then read it back, before you go on.**",
                   "The authority is the orchestrator's Step 8 read-back",
                   "so a second reader that is not that agent is the whole point",
                   "**Do not compose it yourself from the diff**"):
        assert phrase in live, (
            f"{phrase!r} is absent from the LIVE skill text. If it is still in the file, "
            f"it has been commented out, which retires it while leaving every raw-text "
            f"pin green.")


class TestTheExecutorArm:
    """Arm 1. Cheap, and it is the difference between an edit and an amend — but it asks
    the agent that skipped sequence item 3 to run item 3's own verification, so it is
    pinned as a backstop, never as the mechanism."""

    def test_the_executor_is_told_to_read_its_write_back(self):
        text = _live_text()
        assert "**Then read it back, before you go on.**" in text
        assert "grep -niE -A1 '^#{1,6}[[:space:]]*test[[:space:]]+decision" in text, (
            "-A1 is load-bearing: without it the step tells the executor to inspect the "
            "line under the heading, which its own output never shows")
        assert 'case "$body" in *"<"*)' in text, (
            "an unsubstituted <BODY_PATH_AS_RESOLVED> makes grep exit 2 for a missing "
            "FILE, which reads exactly like a missing RECORD")
        assert "The authority is the orchestrator's Step 8 read-back" in text, (
            "the grep is fence-blind; a step that does not say so invites the next "
            "reader to delete the arm that is not")

    def test_the_executor_is_told_the_template_is_not_a_record(self):
        text = _live_text()
        assert "is the schema template, not a record" in text

    def test_the_orchestrator_arm_is_named_as_the_second_reader(self):
        """If this sentence goes, the next reader sees two checks of the same fact and
        deletes one — and the one that looks redundant is the one that works."""
        text = _live_text()
        assert "so a second reader that is not that agent is the whole point" in text


def test_the_repair_does_not_authorise_inventing_the_record():
    """Composing a fresh decision from the diff substitutes an unreviewed judgment for
    one 7a made and 7b scrutinised — the exact substitution Step 2d exists to catch."""
    text = _live_text()
    assert "**Do not compose it yourself from the diff**" in text
    assert "amend" in textwrap.shorten(
        text[text.index("**If that printed `MISSING` or `TEMPLATE`"):][:900], 900)
