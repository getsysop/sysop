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
