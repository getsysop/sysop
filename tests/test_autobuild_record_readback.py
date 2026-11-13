"""`Q-462`: `/auto-build`'s orchestrator-side re-read of the `## Test decision` record.

Two things have to hold, and only one of them is a text comparison.

The block `/auto-build` item `1‑record` prescribes is `/claim-task` Step 8's, ported
because that verifier takes exactly `(claim_id, branch, body_rel)` and touches no run
directory. A port creates a second copy, and a second copy drifts -- so the payload is
pinned byte-identical here. But a pin alone would have been satisfied by two copies that
are identically WRONG, which is `Q-468`'s shape: that defect lived in this very block and
a text pin would have propagated it into a second skill without comment. So the ported
block is also EXECUTED, against the fence body that reproduces `Q-468`.
"""
from __future__ import annotations

import pathlib
import re
import subprocess

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CLAIM = REPO_ROOT / "core" / "skills" / "claim-task" / "SKILL.md"
BUILD = REPO_ROOT / "core" / "skills" / "auto-build" / "SKILL.md"

_CLAIM_OPENER = "python3 - <<'PY' \"<CLAIM_ID>\" \"<BRANCH_NAME>\" \"<BODY_PATH_AS_RESOLVED>\""
_BUILD_OPENER = "python3 - <<'RECORD_PY' \"<TASK_ID>\" \"<BRANCH_NAME>\" \"<BODY_PATH_FROM_REPO_ROOT>\""


def _payload(path: pathlib.Path, opener: str, terminator: str) -> str:
    """The python between a heredoc's opener and its terminator, or a loud failure.

    Anchored on the opener's full argument list rather than on `<<'PY'` alone: the
    skill bodies carry several heredocs and an earlier draft of this helper silently
    matched the wrong one, which is a green test over an unmeasured block.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    # `lstrip()`, not `==`: a heredoc indented under a numbered list item is legal
    # markdown and the sibling helper in test_test_decision_readback.py already
    # tolerates it. Round lens 1, LOW X2 -- over-strictness is the direction that
    # hides, and this one reddens four tests on a formatting change that means nothing.
    hits = [i for i, ln in enumerate(lines) if ln.lstrip() == opener]
    assert len(hits) == 1, (
        f"COULD NOT LOCATE exactly one {opener!r} in {path.name} (found {len(hits)}). "
        f"Nothing was compared -- re-point this helper."
    )
    start = hits[0]
    end = next((i for i in range(start + 1, len(lines)) if lines[i] == terminator), None)
    assert end is not None, f"{path.name}: heredoc opened at {start + 1} never terminated"
    return "\n".join(lines[start + 1:end])


def test_the_ported_payload_is_byte_identical_to_step_8s():
    claim = _payload(CLAIM, _CLAIM_OPENER, "PY")
    build = _payload(BUILD, _BUILD_OPENER, "RECORD_PY")
    assert build == claim, (
        "`/auto-build` item `1‑record` and `/claim-task` Step 8 have drifted. These are "
        "one verifier in two skills on purpose; whichever was edited alone now grades a "
        "different record from the other, and the two paths stop agreeing about what "
        "counts as a record."
    )


def test_the_pinned_payload_is_not_empty():
    """Control. An extractor that returns '' makes the pin above vacuously green."""
    assert len(_payload(CLAIM, _CLAIM_OPENER, "PY").splitlines()) > 40


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "consumer"
    (r / "tasks" / "open").mkdir(parents=True)
    _git(r.parent, "init", "-q", "consumer")
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "T")):
        _git(r, "config", k, v)
    (r / "README.md").write_text("seed\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "seed")
    _git(r, "branch", "-M", "main")
    return r


def _on_branch(repo, name, body):
    _git(repo, "checkout", "-q", "-b", name, "main")
    f = repo / "tasks" / "open" / "T.md"
    f.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", name)
    _git(repo, "checkout", "-q", "main")
    return name


def _resolve(body_value: str) -> str:
    """Apply the derivation the step prescribes, rather than hard-coding its answer.

    This function is the fixture's whole point. The first version of this module passed
    the literal `"tasks/open/T.md"` -- the ANSWER -- so it could not see that the step
    told an operator to produce something else. `/auto-build` has no resolver, and the
    only other definition of a body placeholder in that file (item `3-record`) means the
    raw `body:` value; a reader following it produced `open/T.md`, which `git show`
    reports as absent and the block then passes at exit 0. Deriving here means a
    prescription that stops being followable reds this module.
    """
    return body_value if body_value.startswith("tasks/") else "tasks/" + body_value


def _run(repo, branch, body_value="open/T.md"):
    """Drive the block as `/auto-build` prescribes it -- the ported copy, not Step 8's.

    `body_value` is what `tasks/index.yml` carries, in either accepted spelling; the
    third argument is DERIVED from it, never supplied.
    """
    payload = _payload(BUILD, _BUILD_OPENER, "RECORD_PY")
    r = subprocess.run(
        ["python3", "-", "TECH-X", branch, _resolve(body_value)],
        input=payload + "\n", cwd=str(repo), capture_output=True, text=True,
    )
    return r.returncode, r.stdout.strip()


def test_both_accepted_body_spellings_resolve_to_the_same_path():
    """Both are legal in `tasks/index.yml`; blind concatenation breaks the legacy one."""
    assert _resolve("open/T.md") == "tasks/open/T.md"
    assert _resolve("tasks/open/T.md") == "tasks/open/T.md"


def test_the_raw_body_value_does_not_silently_pass(repo):
    """`Q-468`'s round, HIGH 1. The failure mode is a PASS, which is why it needs a row.

    Passing the raw canonical `body:` value -- what item `3-record`'s definition of its
    own placeholder yields -- makes `git show` report the path absent, and the block
    takes its NOT ON BRANCH arm and exits 0. A gate that exits 0 over a body with no
    record is inert, and prints reassurance while being so. The step now names its
    placeholder differently and spells out the derivation; this row is what keeps that
    prescription honest.
    """
    b = _on_branch(repo, "raw-value", "# T\n\n## Requirements\n1. thing\n")
    payload = _payload(BUILD, _BUILD_OPENER, "RECORD_PY")
    r = subprocess.run(["python3", "-", "TECH-X", b, "open/T.md"],
                       input=payload + "\n", cwd=str(repo), capture_output=True, text=True)
    assert r.returncode == 0 and "NOT ON BRANCH" in r.stdout, (r.returncode, r.stdout)
    rc, out = _run(repo, b)
    assert rc == 1 and out.startswith("MISSING"), (
        "the DERIVED path must reach the real verdict: " + repr((rc, out)))


class TestThePortedBlockActuallyRuns:
    """A byte-identical pin over a block nothing executes proves only that two files
    match. These rows are why the pin is worth having."""

    def test_a_missing_record_fails_the_task(self, repo):
        b = _on_branch(repo, "no-record", "# T\n\n## Requirements\n1. thing\n")
        rc, out = _run(repo, b)
        assert rc == 1 and out.startswith("MISSING"), (rc, out)

    def test_a_real_record_passes(self, repo):
        b = _on_branch(repo, "good", "# T\n\n## Test decision\ntest tests/t.py proves it\n")
        rc, out = _run(repo, b)
        assert rc == 0 and out.startswith("test-decision record present"), (rc, out)

    def test_the_port_carries_the_q468_fence_fix(self, repo):
        """The reason this file executes the port instead of only diffing it.

        `Q-468` lived in this block: an info-string marker was accepted as a closer, so
        a record quoted inside the plan's own fence certified as the branch's record. A
        text pin would have copied that into a second skill silently."""
        body = (
            "# T\n\n## Requirements\n1. thing\n\n## Plan\n"
            "````\nan example block:\n"
            "````json\n## Test decision\ntest tests/x.py proves y\n"
            "````yaml\nkey: value\n````\n")
        b = _on_branch(repo, "fenced", body)
        rc, out = _run(repo, b)
        assert rc == 1 and out.startswith("MISSING"), (rc, out)

    def test_the_port_carries_the_opener_info_string_rule(self, repo):
        """`Q-477`: a backtick run whose info string holds a backtick is an inline span, not
        a fence (CommonMark). Read as an opener, it swallows this legal body's real record,
        the `bash` block's bare closer balances the walk, and the task is marked `FAILED`."""
        body = ("# T\n\n## Requirements\n```a`b``` is inline code, not a fence.\n\n"
                "## Test decision\ntest tests/x.py proves y\n\n"
                "## Notes\n```bash\necho hi\n```\n")
        b = _on_branch(repo, "opener-backtick-info", body)
        rc, out = _run(repo, b)
        assert rc == 0 and out.startswith("test-decision record present"), (rc, out)
        assert "unbalanced" not in out, out

    def test_the_port_still_reads_a_tilde_fence_whose_info_string_holds_a_backtick(self, repo):
        """The rule is backtick-only: a `~~~` opener's info string may hold a backtick."""
        body = ("# T\n\n## Plan\n~~~markdown `quoted`\n## Test decision\n"
                "test only inside a tilde fence\n~~~\n")
        b = _on_branch(repo, "tilde-backtick-info", body)
        rc, out = _run(repo, b)
        assert rc == 1 and out.startswith("MISSING"), (rc, out)


def _refill_step() -> str:
    """The `1‑record` step's prose, sliced out of `/auto-build`'s refill section.

    Sliced rather than searched whole-file so a failure names where it looked, and so a
    needle that drifts into a NEIGHBOURING step cannot satisfy these rows.
    """
    whole = BUILD.read_text(encoding="utf-8")
    # Slice the REFILL SECTION first. Round lens 1, MEDIUM 1: this helper used to `find`
    # over the whole file, so relocating the entire step into `### Phase 6e` -- leaving the
    # refill list with no record check at all -- kept every row below green. Wade ratified
    # "per task at the rolling-window refill, as each Phase-6e envelope is collected", and
    # a guard that cannot see WHERE the step lives does not hold that decision.
    sec = whole.find("### Rolling-window refill on completion")
    assert sec != -1, (
        "COULD NOT LOCATE `### Rolling-window refill on completion` in /auto-build. Nothing "
        "was checked -- re-point this helper.")
    nxt = whole.find("\n## ", sec)
    t = whole[sec:nxt if nxt != -1 else len(whole)]
    start = t.find("1‑record. **Re-read the `## Test decision` record")
    assert start != -1, (
        "COULD NOT LOCATE `/auto-build` item `1‑record`. Nothing was checked -- either "
        "the step was deleted (which is the defect) or it was renamed and this helper "
        "needs re-pointing."
    )
    end = t.find("2. If the queue still has unstarted batch tasks", start)
    assert end != -1, "the refill list's item 2 vanished; re-point this helper"
    return t[start:end]


@pytest.mark.parametrize("label,needle", [
    ("fails the task on a MISSING verdict", "this task's Step 8 status becomes `FAILED`"),
    ("does not halt the batch", "**the batch continues**"),
    ("does not compose the record itself",
     "Do not write the record yourself from `PLAN_TEXT[<TASK_ID>]`"),
    ("runs only on an EXECUTED envelope", "only when its envelope says `STATUS: EXECUTED`"),
])
def test_the_verdict_arm_says_what_the_exit_code_means(label: str, needle: str) -> None:
    """Found by this phase's own author-side battery, as its ONE survivor.

    Inverting the verdict arm -- `becomes FAILED` to `is unchanged` -- left all 282 tests
    green. The block was pinned byte-identical AND executed, and the sentence saying what
    to DO with its exit code was guarded by nothing, so a later edit could keep the whole
    verifier and throw away its consequence. Each row is a decision `Q-462` says had to be
    made before the check could be built; reversing any one is a different design, not an
    edit, and Wade ratified this shape on 2026-09-11.
    """
    step = _refill_step()
    assert needle in step, (
        f"`/auto-build` item `1‑record` no longer says it {label}. The verifier can be "
        "perfectly correct and still do nothing: this arm is where its exit code becomes "
        "a consequence."
    )


_REVERSAL_VOCABULARY = (
    "advisory", "is not the case", "do not fail", "status is unchanged",
    "ignore the verdict", "rather than failing", "no longer fails", "merely report",
)


def test_the_verdict_arm_carries_no_reversal_vocabulary():
    """Round lens 2, MEDIUM 4: the four presence rows above are walked by negation.

    Measured by that lens, not argued: rewriting the step to say *"treat the verdict as
    ADVISORY ... It is NOT the case that this task's Step 8 status becomes `FAILED`"*
    keeps all four pinned needles present and was killed by **0 of 6,756 tests**. A
    substring-presence guard cannot tell an assertion from its negation, which is this
    repo's `adversarial-review.md` rule-1 class *"a check requiring N phrases is satisfied
    by N disconnected phrases in a sentence asserting the opposite"*.

    This is the companion check, in the shape `/review-close`'s `2-also` arm already uses:
    the needles must be present AND the step must not carry the vocabulary of a reversal.
    """
    step = _refill_step().lower()
    found = [v for v in _REVERSAL_VOCABULARY if v in step]
    assert not found, (
        "`/auto-build` item `1-record`'s verdict arm carries reversal vocabulary "
        f"{found!r}. The four presence rows above stay green through a negation written "
        "around them, so this is the half that sees it. If a rewrite legitimately needs "
        "one of these words, it is a design change and wants its own round."
    )


_REPUDIATION = (
    "an earlier draft", "earlier draft said", "that was wrong", "was too strict",
    "is overstated", "no longer", "superseded", "we now", "that is no longer",
)


def _sentence_with(text: str, needle: str) -> str:
    """The sentence carrying `needle`. Presence guards read the file; this reads the claim."""
    i = text.index(needle)
    start = max(text.rfind(". ", 0, i), text.rfind("\n\n", 0, i)) + 1
    end = text.find(". ", i + len(needle))
    return text[start:end if end != -1 else len(text)]


@pytest.mark.parametrize("label,needle", [
    ("fails the task on a MISSING verdict", "this task's Step 8 status becomes `FAILED`"),
    ("does not halt the batch", "**the batch continues**"),
    ("does not compose the record itself",
     "Do not write the record yourself from `PLAN_TEXT[<TASK_ID>]`"),
    ("runs only on an EXECUTED envelope", "only when its envelope says `STATUS: EXECUTED`"),
])
def test_no_pinned_decision_is_quoted_only_to_be_repudiated(label: str, needle: str) -> None:
    """Round lens 1, HIGH 3 — and it is about the phase's OWN correction failing.

    The phase closed its author battery's one survivor with four presence rows and wrote
    *"Reversing any one is a different design rather than an edit."* The lens measured the
    opposite: **three of the four** are walked by keeping the needle and wrapping it in a
    repudiation — *"record the printed line as an advisory Note and carry on. An earlier
    draft said this task's Step 8 status becomes `FAILED`… that was too strict"*. All four
    needles stay present; only deleting one outright was killed. That is the rubric's own
    diagnosis: presence rows are **reversion guards**, and they prove wiring, not assertion.

    This row reads the sentence the needle sits in, which is where a repudiation lives.
    """
    step = _refill_step()
    sentence = _sentence_with(step, needle).lower()
    found = [v for v in _REPUDIATION if v in sentence]
    assert not found, (
        f"`/auto-build` item `1‑record` still contains the {label!r} needle, but the "
        f"sentence carrying it repudiates it ({found!r}):\n\n  {sentence.strip()[:400]}\n\n"
        "A pinned decision quoted only to be overturned is not a pinned decision. If the "
        "design genuinely changed, that is a round's subject, not an edit."
    )


def test_the_failed_verdict_names_where_its_notes_come_from():
    """`Q-491`: the `Notes` source was stranded in a fragment from Phase 281 (`3bb3c40`) on.

    Phase 281 inserted the `NOT ON BRANCH` clause between *"status becomes `FAILED`"* and
    its own tail, so the tail read *"… not just the exit code.** with the printed line as its
    `Notes`, and **the batch continues**"* -- a clause attached to nothing. Every row above
    stayed green through it, because both of their needles survived the split. This row reads
    the sentence the `FAILED` needle sits in, which is where the orchestrator looks for what
    to write into the row it is about to fill.
    """
    step = _refill_step()
    sentence = _sentence_with(step, "this task's Step 8 status becomes `FAILED`")
    # The `Notes` source may sit in its own sentence (Phase 370's round: pinning it inside
    # the `FAILED` sentence reddened a correct rewrite); the stranded shape is the
    # detector's job below. What must hold is that the step names it at all.
    flat = " ".join(step.split())
    assert re.search(r"printed lines? (?:as|is|are) (?:its|the) `Notes`|`Notes` (?:are|is) the printed lines?",
                     flat), (
        "`/auto-build` item `1‑record` no longer says what goes in a `FAILED` task's `Notes`, so "
        "the one arm that hands the human a failure hands them nothing to act on")
    # And `NOT ON BRANCH` fails the task too: drop the clause and an exit-0 `NOT ON BRANCH`
    # reads as executed (Phase 370's round, lens 2 — it survived every test).
    assert "`NOT ON BRANCH`" in sentence and "failure" in sentence, (
        f"the `FAILED` sentence no longer makes `NOT ON BRANCH` a failure:\n\n  {sentence.strip()[:400]}")


def _prose_sentence_openers_in_lowercase(text: str) -> list[str]:
    """Sentences in `text`'s prose (fences dropped) that open on a lowercase word.

    A lowercase opener after a full stop is how a clause stranded by an insertion reads, which
    is the shape `Q-491` had. Fences are dropped because a code block's line starts are not
    sentences.
    """
    prose, fenced = [], False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if not fenced:
            prose.append(line)
    joined = "\n".join(prose)
    # An abbreviation's full stop ends no sentence: "(e.g. never committed)" is ordinary
    # prose, and reddened this detector (Phase 370's round, lens 2).
    return [joined[max(0, m.start() - 50):m.end() + 30]
            for m in re.finditer(r"(?<!\be\.g)(?<!\bi\.e)(?<!\betc)(?<!\bvs)[.!?]\**\s+\**[a-z]\w*", joined)]


def test_no_sentence_in_the_record_step_opens_on_a_stranded_clause():
    found = _prose_sentence_openers_in_lowercase(_refill_step())
    assert found == [], (
        "`/auto-build` item `1‑record` has a sentence opening on a lowercase word -- the "
        "shape a clause takes when an insertion strands it from its subject (`Q-491`):\n  "
        + "\n  ".join(repr(f) for f in found)
    )


def test_the_stranded_clause_detector_sees_the_q491_shape():
    """Detection floor: the exact pre-fix text must be flagged, and the fixed text must not."""
    before = ("**Read the printed line, not just the exit code.** with the printed line as its "
              "`Notes`, and **the batch continues** — go on to item 2.")
    after = ("**Read the printed line, not just the exit code.** Whichever fired, "
             "**the batch continues** — go on to item 2.")
    assert _prose_sentence_openers_in_lowercase(before), "the Q-491 shape walked through"
    assert _prose_sentence_openers_in_lowercase(after) == []


def test_an_unreadable_record_fails_the_task():
    """`Q-661` (Wade's answer, Phase 371): the record block's `UNREADABLE` arm exits 0, and
    until this phase the step never said what it means, so as written the task passed as
    executed on a record nobody could read. It fails the task, like `NOT ON BRANCH`."""
    flat = " ".join(_refill_step().split())
    m = re.search(r"\*\*`UNREADABLE` \(also exit 0\) fails the task the same way\*\*([^.]*)", flat)
    assert m, "`/auto-build` item `1‑record` no longer says `UNREADABLE` fails the task"
    # The source, not just the token: "leaving its `Notes` empty" kept the token (Phase 371's round).
    assert re.search(r"\bits printed lines as the `Notes`", m.group(1)), (
        "the `UNREADABLE` arm no longer names its own printed lines as its `Notes`")


# --- Phase 7's recovered arm runs item `1‑record` -------------------------------------------
#
# A task whose envelope never parsed reaches `EXECUTED (envelope-recovered)` on filesystem
# evidence alone -- a commit and a pending doc -- and that agent is the one least likely to
# have run its own record check. Phase 7 runs item `1‑record` for it, by reference: the block
# has one copy, pinned identical to `/claim-task` Step 8's above.


def _phase7() -> str:
    whole = BUILD.read_text(encoding="utf-8")
    # The heading at a line start: item 1 and item `1‑record` cite it in backticks, earlier.
    start = whole.find("\n## Phase 7: Envelope Recovery\n")
    assert start != -1, "COULD NOT LOCATE `## Phase 7: Envelope Recovery`; re-point this helper"
    assert whole.count("\n## Phase 7: Envelope Recovery\n") == 1, "two Phase 7 headings"
    end = whole.find("\n## Step 8", start)
    assert end != -1, "COULD NOT LOCATE `## Step 8` after Phase 7; re-point this helper"
    return whole[start:end]


def _phase7_block() -> str:
    t = _phase7()
    start = t.find("```bash\n", t.find("### Phase 7 procedure"))
    assert start != -1, "COULD NOT LOCATE Phase 7's procedure block; re-point this helper"
    end = t.find("\n```", start + 8)
    return t[start + 8:end]


def test_phase_7_runs_item_1_record_by_reference_not_by_copy():
    t = _phase7()
    flat = " ".join(t.split())
    assert "run item `1‑record` of `### Rolling-window refill on completion` for this task" in flat, (
        "Phase 7's recovered arm no longer runs item `1‑record`, so a task recovered on a "
        "commit and a pending doc counts as executed with its record never read")
    # One copy: a second would drift from the pinned one, which is worse than none.
    for copy_marker in ("<<'RECORD_PY'", "RECORD_PY", "def fence_mark", "git rev-parse --git-common-dir"):
        assert copy_marker not in t, f"Phase 7 carries a copy of the record block ({copy_marker!r})"
    # The routing, by name: every verdict that fails a task on the refill path fails it here.
    m = re.search(r"\*\*Apply that item's outcomes as written there\.\*\*(.*?)Only `test-decision record present`", flat)
    assert m, "Phase 7's arm no longer says to apply item `1‑record`'s outcomes"
    for verdict in ("`MISSING`", "`TEMPLATE`", "`NOT ON BRANCH`", "`UNREADABLE`"):
        assert verdict in m.group(1), f"Phase 7's arm no longer fails a recovered task on {verdict}"
    assert "Step 8 status `FAILED`" in m.group(1) and "printed lines as its `Notes`" in m.group(1)
    sentence = m.group(1).lower()
    found = [v for v in _REVERSAL_VOCABULARY + _REPUDIATION if v in sentence]
    assert not found, f"Phase 7's routing sentence carries reversal vocabulary {found!r}"


def test_phase_7_substitutes_the_claimed_branch_not_its_sanitized_name():
    """`BRANCH_NAME` in Phase 7 is `branch --show-current | tr / -`: the pending-doc stem.

    `1‑record` builds `refs/heads/<BRANCH_NAME>` from what it is handed, so passing Phase 7's
    name fails every slashed branch as `UNREADABLE` -- see the executed row below."""
    flat = " ".join(_phase7().split())
    assert "**For `<BRANCH_NAME>`, substitute the branch Step 5 claimed for this task**" in flat
    assert "`(task_id, worktree_path, branch_name)` tuple" in flat
    assert "This block's `BRANCH_NAME` is not it." in flat, (
        "Phase 7 no longer says its own sanitized `BRANCH_NAME` is the wrong value to substitute")


def test_the_record_steps_scope_names_the_recovered_route():
    step = _refill_step()
    sentence = " ".join(_sentence_with(step, "only when its envelope says `STATUS: EXECUTED`").split())
    assert "`## Phase 7: Envelope Recovery`" in sentence and "`EXECUTED (envelope-recovered)`" in sentence, (
        "item `1‑record`'s scope no longer names the Phase 7 route, so a reader of the item "
        "alone skips the recovered population:\n\n  " + sentence[:400])


def test_item_1_runs_phase_7_on_a_parse_miss():
    """Timing: the read-back lands at recovery, as the refill collects each envelope."""
    whole = BUILD.read_text(encoding="utf-8")
    start = whole.find("1. Collect that agent's result.")
    end = whole.find("1‑record. **Re-read", start)
    assert start != -1 and end != -1, "COULD NOT LOCATE refill item 1; re-point this helper"
    assert "If neither yields an envelope that parses, run `## Phase 7: Envelope Recovery` for this task now." in whole[start:end]


def test_step_8_reporting_names_the_failed_read_back():
    t = " ".join(_phase7().split())
    assert "A recovered task the read-back failed appears as `FAILED`" in t
    assert "whose record read back present MUST appear" in t


class TestTheRecoveredArmEndToEnd:
    """Phase 7's block run as written, then item `1‑record`'s block with each branch value."""

    def _recovered(self, repo, tmp_path, body):
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "-q", "-b", "tech/tech-w", str(wt), "main")
        pre = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], check=True,
                             capture_output=True, text=True).stdout.strip()
        (wt / "tasks" / "open").mkdir(parents=True, exist_ok=True)
        (wt / "tasks" / "open" / "T.md").write_text(body, encoding="utf-8")
        _git(wt, "add", "-A")
        _git(wt, "commit", "-qm", "work")
        pending = wt / "sysop" / "runtime" / "pending-docs"
        pending.mkdir(parents=True)
        (pending / "tech-tech-w.md").write_text("doc\n", encoding="utf-8")
        block = _phase7_block().replace("<worktree path>", str(wt)).replace("<pre-exec head>", pre)
        r = subprocess.run(["bash", "-c", block], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        return r.stdout

    def test_the_block_prints_its_verdict(self, repo, tmp_path):
        """No variable outlives the block, so a verdict it does not print is unreadable."""
        out = self._recovered(repo, tmp_path, "# T\n\n## Test decision\ntest t.py proves it\n")
        assert "RECOVERED_STATUS=EXECUTED (envelope-recovered)" in out, repr(out)
        assert "NEW_COMMITS=1" in out, repr(out)
        assert "RECOVERED_ERROR=none" in out, "the failure reason must be printed too: " + repr(out)

    def test_the_claimed_branch_reads_the_record_and_the_sanitized_name_cannot(self, repo, tmp_path):
        self._recovered(repo, tmp_path, "# T\n\n## Test decision\ntest t.py proves it\n")
        rc, out = _run(repo, "tech/tech-w")
        assert rc == 0 and out.startswith("test-decision record present"), (rc, out)
        rc, out = _run(repo, "tech-tech-w")
        assert rc == 0 and out.startswith("UNREADABLE"), (
            "the sanitized name should fail the read -- the trap Phase 7's arm names: " + repr((rc, out)))

    def test_a_recovered_task_with_no_record_is_missing(self, repo, tmp_path):
        out = self._recovered(repo, tmp_path, "# T\n\n## Requirements\n1. thing\n")
        assert "RECOVERED_STATUS=EXECUTED (envelope-recovered)" in out, repr(out)
        rc, out = _run(repo, "tech/tech-w")
        assert rc == 1 and out.startswith("MISSING"), (rc, out)


def test_phase_7_reads_back_before_step_8_and_never_writes_the_record():
    """The read-back is placed before Step 8, which reports its outcome, and the refill
    item's ban on composing the record from the plan carries to the recovered arm: a
    recovered task is the one most tempting to "repair"."""
    flat = " ".join(_phase7().split())
    assert "for this task, before Step 8**" in flat, (
        "Phase 7's read-back is no longer placed before Step 8")
    assert "Its prohibition on writing the record yourself holds here too." in flat, (
        "Phase 7's arm no longer carries the ban on writing the record yourself")


def _section(title: str) -> str:
    t = _phase7()
    start = t.find(f"\n### {title}\n")
    assert start != -1 and t.count(f"\n### {title}\n") == 1, f"COULD NOT LOCATE ### {title}"
    end = t.find("\n### ", start + 1)
    return t[start:end if end != -1 else len(t)]


#: The recovered arm's whole text, hash-pinned: its condition, its substitution and its routing
#: each changed alone, and a needle test passed on a negated or inverted sentence (Phase 474's
#: round, lens 2). Re-pin only for an intended change, and say so in the commit.
READ_BACK_SHA16 = "4470e66bdbfbc667"


def test_the_recovered_arm_text_is_pinned():
    import hashlib
    got = hashlib.sha256(_section("Read back a recovered task's record").encode("utf-8")).hexdigest()[:16]
    assert got == READ_BACK_SHA16, f"Phase 7's recovered arm changed (sha {got}); re-pin only if intended"


def test_item_1_runs_phase_7_now_and_reporting_fails_a_failed_read_back():
    whole = " ".join(BUILD.read_text(encoding="utf-8").split())
    assert ("If neither yields an envelope that parses, run `## Phase 7: Envelope Recovery` for this "
            "task now. After consuming the JSON file,") in whole
    rep = " ".join(_section("Reporting in Step 8").split())
    assert ("A recovered task the read-back failed appears as `FAILED`, its `Notes` naming the "
            "recovery and then the read-back's printed lines.") in rep
    assert rep.count("`FAILED`") == 1, "Step 8's reporting text offers a second status for a failed read-back"
