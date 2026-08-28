"""Phase 239 (`Q-319`) — Step 4b's zero-batch arm, and the namespace it must not read.

THE DEFECT. `/review-close` Step 4b opened unconditionally with
``bash sysop/scripts/close_batch.sh <N1> <N2> <N3>`` and **never said where the
operands came from**, then prescribed a trust-but-verify gate keyed on a
``docs: close Batch …`` tip. On the ordinary `/claim-task` single-task cycle
there are no review batches, so that commit never exists and never will — and
the step said ``Halt before Step 4c``. The halt lands *after* step 5's merges,
which is the expensive place to stop, and it stops the compliant operator
specifically: the one who infers a no-op gets through, the one who follows the
written step does not.

WHY THIS MODULE EXISTS IN THE SHAPE IT DOES. `Q-318` measured skill-prose guards
at 76–81% mutation-survivable across two independent lenses, and recorded that
the one layer which killed everything it covered was the **execution** layer —
tests that run what the prose prescribes against a real repo. So the two claims
this fix actually rests on are executed here, not asserted:

* ``close_batch.sh TASK-0001`` is rejected at argument parsing (exit 1), which
  is why ``review_task_ids`` cannot be Step 4b's input. The filing for `Q-319`
  proposed exactly that field as the fix's source; running it refutes the
  proposal, and the failure is at arg-parse, *before* any batch lookup — a
  detail this phase's own first draft of the prose got wrong.
* ``close_batch.sh`` with no operands also exits 1 and commits nothing, so
  "run it anyway with an empty list" is not an escape from the empty-set arm.

The prose assertions below are deliberately the weaker half and are scoped to
properties rather than spellings: that the empty set has a named arm, that the
arm skips the gate, and that the gate sentence no longer stands unqualified.
"""
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "core/skills/review-close/SKILL.md"
CLOSE_BATCH = REPO_ROOT / "core/companion/scripts/close_batch.sh"


def _skill() -> str:
    return SKILL.read_text(encoding="utf-8")



def _norm(s: str) -> str:
    r"""Whitespace- and emphasis-insensitive view of skill prose.

    Lens 3 wrote 13 negative controls against this module and **10 reddened** —
    a higher false-kill rate than its bypass rate, which is the over-strictness
    direction rule 1 calls the one that hides. The offenders were all ordinary
    edits: a markdown reflow through a pinned phrase, `__bold__` instead of
    `**bold**`, nested emphasis inside a bold span, italics instead of bold, and
    a plural noun. None of them changes a claim. Normalize once here rather than
    threading `\s+` and emphasis alternations through every pattern.
    """
    s = re.sub(r"\s+", " ", s)
    s = s.replace("__", "**")          # CommonMark bold, same meaning
    s = re.sub(r"(?<!\*)\*(?!\*)", "", s)  # drop single-* emphasis, keep ** spans
    return s


def _step_4b(text: str) -> str:
    """Step 4b's body: from its heading to the next `### ` heading.

    Scoped rather than whole-file because `close_batch.sh` and the
    `docs: close Batch` subject are named in several other steps, and a
    whole-file substring check would pass on any of them.
    """
    m = re.search(r"^### 4b\. ", text, re.M)
    assert m, "Step 4b's heading is gone — this guard's anchor needs revisiting"
    nxt = re.search(r"^### ", text[m.end():], re.M)
    return text[m.start(): m.end() + nxt.start()] if nxt else text[m.start():]


def _repo(root: Path) -> Path:
    """A scratch repo carrying one Pending batch, in the shape close_batch.sh parses."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    for k, v in (("user.email", "test@test"), ("user.name", "test"),
                 ("commit.gpgsign", "false")):
        subprocess.run(["git", "config", k, v], cwd=str(root),
                       check=True, capture_output=True)
    (root / "review_tasks.md").write_text(
        "# Review Tasks\n\n### Batch 1 — First batch `Pending`\n\n- [ ] task one\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=str(root), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=str(root),
                   check=True, capture_output=True)
    return root


def _run(cwd: Path, *args):
    return subprocess.run(["bash", str(CLOSE_BATCH), *args],
                          cwd=str(cwd), capture_output=True, text=True)


def _head_subject(repo: Path) -> str:
    return subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=str(repo),
                          capture_output=True, text=True).stdout.strip()


# ---------------------------------------------------------------- execution


def test_a_review_task_id_is_rejected_at_argument_parsing(tmp_path):
    """The refutation of `Q-319`'s proposed fix source, by execution.

    The filing said Step 4c step 1b's ``review_task_ids`` "is simply never named
    as Step 4b's input". It cannot be: those are `TASK-NNNN` ids and this script
    takes batch integers. It does not fail a lookup — it never gets that far.
    """
    repo = _repo(tmp_path / "repo")
    before = _head_subject(repo)
    r = _run(repo, "TASK-0001")
    assert r.returncode == 1, (
        f"close_batch.sh accepted a TASK- id (exit {r.returncode}); if the script's "
        "argument grammar has widened, Step 4b's namespace warning needs re-deriving"
    )
    assert "Unknown argument: TASK-0001" in r.stderr, (
        "the rejection is no longer at argument parsing — Step 4b's prose says it is, "
        f"verified by running it. stderr was:\n{r.stderr}"
    )
    assert _head_subject(repo) == before, "a rejected invocation still committed"


def test_the_batch_prefixed_form_is_accepted(tmp_path):
    """The other half of the namespace claim, and the reason "it takes integers"
    is the wrong shorthand: `BATCH-<N>` IS accepted (the prefix is stripped), so
    the rejection above is about the `TASK-` namespace specifically, not about
    every non-bare-integer operand. Step 4b's prose says exactly this; without
    this test the guard above would license the sloppier claim.
    """
    repo = _repo(tmp_path / "repo")
    r = _run(repo, "--dry-run", "BATCH-1")
    assert r.returncode == 0, (
        f"close_batch.sh rejected the BATCH- form (exit {r.returncode}); Step 4b's "
        f"prose and WORKFLOW.md § 8.4 both say it is accepted.\nstderr:\n{r.stderr}"
    )
    assert "Closed: 1" in r.stdout, (
        f"BATCH-1 parsed but resolved no batch; stdout:\n{r.stdout}"
    )


def test_an_empty_operand_list_is_not_an_escape_hatch(tmp_path):
    """Why the empty set must skip the script rather than call it with nothing."""
    repo = _repo(tmp_path / "repo")
    before = _head_subject(repo)
    r = _run(repo)
    assert r.returncode == 1
    assert "No batch numbers provided" in r.stderr, (
        f"the no-operand refusal changed shape; stderr was:\n{r.stderr}"
    )
    assert _head_subject(repo) == before
    assert not _head_subject(repo).startswith("docs: close Batch"), (
        "a zero-batch run produced the very commit Step 4b's gate looks for — "
        "if that ever becomes true, the gate could be unscoped again"
    )


def _prescribed_gate_command() -> str:
    """The landing-gate command AS THE STEP SHIPS IT, extracted not retyped.

    Lens 3's row A18: the first version of the test below typed its own copy of
    the gate into a `bash -c`, so weakening the shipped fence to
    `git log -1 --pretty=%s | grep -q '^docs: ' && git diff --quiet` — any
    `docs:` subject satisfies it, staged changes no longer checked — left every
    test green. A grep of `tests/` confirmed nothing read the prescribed text.
    A test that types its own copy is testing its own copy.
    """
    body = _step_4b(_skill())
    fences = [f.strip() for f in re.findall(r"```bash\n(.*?)```", body, re.S)]
    # Two fences in this step name `docs: close Batch` — the gate, and recovery
    # path 2's hand-commit. The gate is the one that READS the tip; the recovery
    # WRITES it. Disambiguate on that, not on the shared subject string.
    gate = [f for f in fences if f.startswith("git log -1")]
    assert len(gate) == 1, (
        f"Step 4b should prescribe exactly one landing-gate fence beginning "
        f"`git log -1`; found {len(gate)}. If the gate moved out of a bash fence "
        "it is no longer a command an operator can run, and nothing here reads it."
    )
    assert "docs: close Batch" in gate[0], (
        "the landing gate no longer matches on the `docs: close Batch ` subject — "
        "widening it lets any commit certify a close that never ran close_batch.sh"
    )
    return gate[0]


def test_the_prescribed_gate_command_is_specific_enough_to_be_a_gate(tmp_path):
    """The shipped fence must reject a tree it should reject.

    Executed against the real text, so weakening the subject match or dropping
    a `git diff` arm reddens here rather than in a hand-typed twin.
    """
    cmd = _prescribed_gate_command()
    repo = _repo(tmp_path / "repo")

    # A close-batch commit is the ONLY thing that should satisfy it. An ordinary
    # docs: commit must not — that is exactly what A18's weakening allowed.
    subprocess.run(["git", "commit", "-qm", "docs: something else", "--allow-empty"],
                   cwd=str(repo), check=True, capture_output=True)
    r = subprocess.run(["bash", "-c", cmd], cwd=str(repo), capture_output=True, text=True)
    assert r.returncode != 0, (
        "the prescribed gate passes on a plain `docs:` commit — its subject match "
        "has been widened past `docs: close Batch `, so it certifies a close that "
        "never ran close_batch.sh"
    )

    # The real subject passes only with a clean tree; a dirty one must fail, which
    # is the second and third arms A18 deleted.
    subprocess.run(["git", "commit", "-qm", "docs: close Batch 1", "--allow-empty"],
                   cwd=str(repo), check=True, capture_output=True)
    assert subprocess.run(["bash", "-c", cmd], cwd=str(repo),
                          capture_output=True).returncode == 0, (
        "the prescribed gate rejects a correct close-batch tip on a clean tree"
    )
    (repo / "review_tasks.md").write_text("dirtied\n", encoding="utf-8")
    assert subprocess.run(["bash", "-c", cmd], cwd=str(repo),
                          capture_output=True).returncode != 0, (
        "the prescribed gate passes with review_tasks.md still modified — the "
        "`git diff --quiet` arms are gone, and Step 4c would fold those edits in"
    )


def test_the_gate_command_stays_red_on_a_zero_batch_tree(tmp_path):
    """The halt Step 4b used to prescribe, reproduced.

    This is the failure `Q-319` reports, executed rather than described: on a
    healthy close carrying no batches, the gate's own command reports failure.
    The fix is that the step no longer reaches it, so this test pins the
    *reason* the empty-set arm has to skip — not a behaviour anyone should fix
    in the script. The command is EXTRACTED from the step (A18), not retyped.
    """
    repo = _repo(tmp_path / "repo")
    gate = subprocess.run(
        ["bash", "-c", _prescribed_gate_command()],
        cwd=str(repo), capture_output=True, text=True,
    )
    assert gate.returncode != 0, (
        "the gate passed on a tree with no close-batch commit — that would make "
        "Q-319's halt unreproducible and this guard vacuous"
    )


# -------------------------------------------------------------------- prose


def _paragraph_containing(body: str, needle: str) -> str:
    """The blank-line-delimited paragraph holding `needle`.

    Battery rows A03 and A06 both walked through whole-section substring checks by
    satisfying a required phrase *elsewhere in Step 4b* while deleting the real
    one — rule 1's "a check satisfied by a substring is satisfied by an incidental
    use of that substring", which is worse than a gap because it marks a dangerous
    paragraph compliant. Scoping to the paragraph is what closes them.
    """
    n = body.count(needle)
    assert n == 1, (
        f"anchor {needle!r} appears {n} times in Step 4b, expected exactly 1. "
        "Lens 3's G14: this helper returned the FIRST matching paragraph, so a "
        "planted compliant paragraph ahead of the real one made every check read "
        "the decoy while the real paragraph said the opposite. Uniqueness is the "
        "structural close; a first-match scope is not a scope."
    )
    for para in body.split("\n\n"):
        if needle in para:
            return para
    raise AssertionError("unreachable")


def test_step_4b_names_the_locks_as_its_batch_set_source():
    """Closes battery row A06.

    The first version asserted `"BATCH-" in body and "lock" in body.lower()`, which
    both survive deleting the source sentence — `BATCH-<N>.lock` is named again two
    sentences later, and "lock" appears in "the landing gate ... locked" prose. Pin
    the source *sentence*, in its own paragraph, by the glob it must name.
    """
    body = _step_4b(_skill())
    para = _paragraph_containing(body, "Determine the batch set first")
    # `review_tasks.md` is authoritative, NOT the locks. The first version of this
    # fix derived the set from locks alone, and the round showed that drops a merged
    # batch which has no lock — a state `close_batch.sh` itself calls ordinary
    # ("claimed before batch locks shipped, or already released") — after which the
    # empty-set arm fires and the close reports `none this cycle` over a batch left
    # Pending. That trades a loud halt for a silent false record.
    assert re.search(r"the source is `review_tasks\.md`", _norm(para)), (
        "Step 4b's batch-set paragraph no longer ASSERTS review_tasks.md as the "
        "source. Deriving from locks alone silently drops a merged batch that has "
        "no lock, and the empty-set arm then reports success over it."
    )
    assert "review_index.py --list" in para, (
        "the paragraph no longer names the reader that makes review_tasks.md "
        "machine-readable — without it the derivation is an instruction to guess"
    )
    for wrong in ("the source is the **locks**",
                  "the source is the pending-doc frontmatter",
                  "the source is `review_task_ids`"):
        assert wrong not in body, (
            f"Step 4b names {wrong!r} as its batch-set source. Locks corroborate and "
            "review_task_ids is the wrong namespace entirely; neither defines the set."
        )


def test_step_4b_says_a_lockless_merged_batch_is_ordinary():
    """The round's HIGH, pinned so the locks-only derivation cannot come back.

    The defect was not that locks are a bad signal — it is that treating them as
    the *definition* makes a routine state invisible. This asserts the step keeps
    saying so, because the sentence is the whole reason the source moved.
    """
    body = _step_4b(_skill())
    assert "corroborate" in body, (
        "Step 4b no longer distinguishes corroboration from definition — that "
        "distinction is the fix"
    )
    assert re.search(r"merged batch with no lock is an ordinary state", body), (
        "Step 4b no longer states that a merged batch with no lock is ordinary. "
        "Without it a later reader re-derives the locks-only rule and the empty-set "
        "arm goes back to reporting success over a dropped batch."
    )


def test_the_empty_set_must_be_derived_not_inferred_from_absence():
    """Absence of locks is not emptiness. Pinned separately from the arm itself,
    because the arm can be perfectly worded while its trigger is wrong."""
    body = _step_4b(_skill())
    assert re.search(r"never inferred from absence", body), (
        "Step 4b no longer forbids inferring the empty set from absent locks — the "
        "false-empty is the path that turns a missed batch into a clean report"
    )


def test_the_set_operation_is_an_intersection_not_a_union():
    """Row M05 of the round's independent battery: swapping 'intersect' for 'take
    the union of' reddened nothing, and a union closes batches whose branches were
    never merged — the mirror of the defect this step exists to prevent."""
    para = _paragraph_containing(_step_4b(_skill()), "Determine the batch set first")
    assert "Intersect" in para or "intersect" in para, (
        "Step 4b's derivation is no longer an intersection. A union closes batches "
        "step 5 never merged, which is the opposite error and just as silent."
    )
    assert "union" not in para.lower(), (
        "Step 4b describes its batch-set derivation as a union"
    )


def test_step_4b_refuses_the_review_task_ids_namespace():
    """Closes battery row A07.

    Asserting only that `review_task_ids` is MENTIONED passes a Step 4b that names
    it as the source — which is exactly what Q-319's filing proposed and execution
    refuted. Require the refusal, in the same paragraph, and require the evidence
    to be the executed one rather than a reasoned-about one.
    """
    # Anchor on the refusal itself, not the field name: the field is legitimately
    # named twice in this step (the refusal, and the citation of Step 4c's note),
    # and _paragraph_containing now requires a unique anchor.
    para = _paragraph_containing(_step_4b(_skill()), "Do not read")
    assert re.search(r"\bDo not read\b", para), (
        "Step 4b's review_task_ids paragraph no longer refuses the field. Presence "
        "is not polarity: the filing proposed this field as the fix, and a guard "
        "that only checks it is mentioned licenses reinstating it."
    )
    assert "TASK-" in para and "Unknown argument" in para, (
        "the refusal no longer carries its executed evidence (the argument-parse "
        "rejection). A refusal without it is an assertion, which is what the first "
        "draft of this paragraph was — and it was wrong about the BATCH- form."
    )


def test_step_4b_has_an_empty_set_arm_that_skips_the_gate():
    """Closes battery row A03.

    The skip clause was checked against the whole section, so planting the words
    "skip the landing gate" in a neighbouring sentence while deleting the real
    clause left the guard green over an arm that reports and then halts anyway.
    """
    body = _step_4b(_skill())
    # The arm's REGION, not its paragraph: the report line lives in its own fence,
    # so a paragraph scope around it holds three words and nothing else. The region
    # runs from the arm's lead sentence to the gate it suppresses — which is also
    # exactly the span row A03 planted its decoy outside of.
    start = body.index("**The empty set is the ordinary case")
    end = body.index("**Verify the close-batch commit landed")
    arm = body[start:end]
    assert "no review batches this cycle" in arm, (
        "the empty-set arm's report line is no longer inside the arm's own region"
    )
    # The skip must be a DIRECTIVE, not a mention. Scoping to the region was not
    # enough: row A03 plants its decoy *inside* the arm ("Operators sometimes ask
    # whether to skip the landing gate here; the answer depends on the shape")
    # while deleting the real clause, and a bare substring search cannot tell an
    # instruction from a musing about one. This file bolds its directives, so
    # require the skip inside a bold span — loose within the span, so rewording
    # the instruction is legal and only de-instructing it reddens.
    assert re.search(r"\*\*[^*]*skip[^*]*landing gate[^*]*\*\*", _norm(arm), re.I), (
        "the empty-set arm no longer gives skipping the landing gate as an "
        "instruction — a hedge or an aside about the gate is not an arm. A report "
        "line beside an unconditional halt is the pre-Phase-239 state with a nicer "
        "message."
    )


def test_the_empty_set_arm_is_stated_before_the_gate_it_suppresses():
    """Closes battery row A08 — ordering, which no test executed.

    An arm that says "skip the gate below" is worthless if it appears *after* the
    gate: a reader working top-down has already halted. Rule 1: "if the fix depends
    on ordering, mutate the ordering. Prose asserting an order is not a test of it."
    This is structural rather than pattern-matched, so it cannot be worded around.
    """
    body = _step_4b(_skill())
    arm = body.index("no review batches this cycle")
    gate = body.index("Verify the close-batch commit landed")
    assert arm < gate, (
        f"Step 4b states its empty-set arm at offset {arm} but the landing gate at "
        f"{gate} — the arm must come first, because a reader who reaches the gate "
        "before the arm has already halted on the cycle the arm exists to release."
    )



# The round walked BOTH scope guards by keeping the word "non-empty" and reversing
# the sentence around it — "applies to a non-empty batch set and, out of caution, to
# an empty one too". Deleting the qualifier was killed; reversing it was not. These
# are the two sites this phase's own record calls "scoped together, because either
# one alone still reads as unconditional", so a reversal at either is the defect
# restored. Presence of the qualifier is necessary and not sufficient: also refuse
# the constructions that re-admit the empty set in the same breath.
_READMITS_EMPTY = re.compile(
    r"(?:and|or)[^.]{0,60}\b(?:to )?an empty one|empty (?:set|batch set|one)[^.]{0,40}\b(?:too|as well|also)",
    re.I,
)


def _assert_scoped_to_non_empty(sentence: str, label: str) -> None:
    assert "non-empty" in sentence, (
        f"{label} stands unqualified again — that exact sentence is what halted "
        "every batch-free close (Q-319)"
    )
    m = _READMITS_EMPTY.search(sentence)
    assert not m, (
        f"{label} names a non-empty set and then re-admits the empty one "
        f"({m.group(0)!r}). Keeping the qualifier while reversing the meaning is how "
        "the round walked this guard; the scope has to exclude, not merely mention."
    )


def test_the_landing_gate_is_scoped_to_a_non_empty_set():
    body = _step_4b(_skill())
    m = re.search(r"\*\*Verify the close-batch commit landed[^*]*\*\*", _norm(body))
    assert m, "the landing gate's lead sentence is gone or reshaped past this anchor"
    _assert_scoped_to_non_empty(m.group(0), "the landing gate's lead sentence")
    assert "non-empty" in m.group(0), (
        "the landing gate's lead sentence stands unqualified again — that exact "
        "sentence is what halted every batch-free close (Q-319)"
    )


def test_the_halt_clause_is_scoped_too():
    body = _step_4b(_skill())
    m = re.search(r"If the check fails[^:]*:", _norm(body))
    assert m, "the halt clause is gone or reshaped past this anchor"
    _assert_scoped_to_non_empty(m.group(0), "the halt clause")
    assert "non-empty" in m.group(0), (
        "the halt clause no longer scopes itself to a non-empty batch set; the "
        "gate's lead sentence and this clause must be scoped together, because "
        "either one alone still reads as unconditional"
    )


def test_step_8_reports_the_batch_set():
    """A skipped Step 4b left no trace in the artifact the human reads."""
    text = _skill()
    # Scoped to Step 8's own report template. Lens 3's A15 renamed the row and
    # planted `Batches:` in a Step 4b fence; a whole-file grep stayed green while
    # the row an operator reads was gone.
    m = re.search(r"^## Step 8: ", text, re.M)
    assert m, "Step 8's heading is gone — this guard's anchor needs revisiting"
    nxt = re.search(r"^## ", text[m.end():], re.M)
    step8 = text[m.start(): m.end() + nxt.start()] if nxt else text[m.start():]
    assert re.search(r"^Batches:\s", step8, re.M), (
        "Step 8's report template has no `Batches:` row; without it a close that "
        "never reached Step 4b is indistinguishable from one with no batches"
    )


def test_step_4c_does_not_point_back_at_an_unsourced_step_4b():
    """The other end of the loop.

    Step 4c said review-task closure "happens in Step 4b" while Step 4b named no
    source. Closing only one end leaves a reader circling.
    """
    text = _skill()
    m = re.search(r"`review_task_ids` is \*\*documentary only\*\*.{0,400}", _norm(text))
    assert m, "Step 4c's documentary-only note is gone or reshaped past this anchor"
    assert "nor is it consulted there" in m.group(0), (
        "Step 4c's note points at Step 4b without stating that Step 4b does not "
        "read this field either — which is the circularity Q-319 named"
    )


def test_no_later_step_reinstates_the_gate_the_arm_skipped():
    """Population, not spelling — lens 3's G2.

    Every prose guard here slices Step 4b at the next `### ` heading, so a
    sentence in **Step 4c** telling the operator to go back and run the skipped
    gate undoes the whole arm while each one stays green. The population has to
    be the steps the arm's decision reaches, not the step it is written in.

    Scoped to a *directive* about the landing gate, so 4c may still mention it.
    """
    text = _skill()
    m = re.search(r"^### 4c\. ", text, re.M)
    assert m, "Step 4c's heading is gone — this guard's anchor needs revisiting"
    nxt = re.search(r"^### ", text[m.end():], re.M)
    step4c = _norm(text[m.start(): m.end() + nxt.start()] if nxt else text[m.start():])

    for pat, why in [
        (r"go back and run that gate", "sends the operator back to the skipped gate"),
        (r"run (?:the )?(?:landing )?gate now", "re-runs the gate the arm skipped"),
        (r"must not reach 4c without", "reinstates the gate as a precondition of 4c"),
        (r"close Batch[^.]{0,40}tip.{0,40}(?:required|must)", "requires the tip the arm forgoes"),
    ]:
        hit = re.search(pat, step4c, re.I)
        assert not hit, (
            f"Step 4c {why} ({hit.group(0)!r}). Step 4b's empty-set arm is then "
            "undone one heading away, which is where no guard in this module looks."
        )


def test_the_monograph_states_the_artifact_set_size_the_code_ships():
    """Lens 3's G11, and the phase's own most-repeated defect.

    Phase 239 wrote the three-artifact undercount **three times** — in the
    `/review-close` glossary entry, in the `/claim-task` entry it inherited, and
    a third time in `WORKFLOW.md` inside the commit that declared the class
    corrected. Nothing read any of them: reverting the monograph's
    `Five, not the three the pipeline first shipped` back to `Three, as the
    pipeline first shipped` left the whole suite green, on a PUBLIC page.

    Pinned against the shipped list rather than the literal word, so renaming an
    artifact moves the guard with the code.
    """
    names = re.search(r"NAMES = \[(.*?)\]", _skill(), re.S)
    assert names, "review-close's Step 2e NAMES list is gone — re-anchor this guard"
    n = len(re.findall(r'"([a-z-]+\.md)"', names.group(1)))
    assert n >= 5, f"Step 2e's NAMES list has shrunk to {n}; re-derive this guard"

    fig = (REPO_ROOT / "docs/workflow.html").read_text(encoding="utf-8")
    words = {3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}
    # Read the HEAD of the claim, not any occurrence of a number word. The correct
    # sentence is "Five, not the three the pipeline first shipped" — it names the
    # wrong number on purpose, so a bare `\bthree\b` search false-positives on the
    # very text it exists to protect. (It did, on the first cut of this guard.)
    claim = re.search(r"<strong>(\w+), not the \w+ the pipeline first shipped</strong>", fig)
    assert claim, (
        "the monograph's artifact-set sentence is gone or reshaped past this "
        "anchor; it is the sentence Phase 239 wrote to correct a three-times-"
        "repeated undercount, on a public page, and nothing else reads it"
    )
    assert claim.group(1).lower() == words[n], (
        f"the monograph claims the artifact set is {claim.group(1)!r} while Step 2e "
        f"ships {n} names ({words[n]}). Reverting this sentence restores the "
        "undercount this phase corrected three times."
    )


def test_the_runtime_figure_guards_read_node_names_not_whole_lines():
    """Lens 3's G16 — the same hole as C2/C3, in the PRE-EXISTING park guard.

    `tests/test_install_park_migration.py` asserts `any("parked/" in ln)` across
    every tree line in the file, so renaming the node to `park-log/` and planting
    `parked/` inside a neighbour's comment keeps it green. C2/C3 were closed by
    reading the node NAME at its own depth; this asserts the same property for
    `parked/` so the figure cannot lose either node the same way.
    """
    fig = (REPO_ROOT / "docs/workflow.html").read_text(encoding="utf-8")
    nodes = [ln for ln in fig.splitlines() if re.match(r"│   │   [├└]── ", ln)]
    names = [re.sub(r"\s.*$", "", ln.split("── ", 1)[1]) for ln in nodes]
    for required in ("claim/", "parked/", "locks/"):
        assert required in names, (
            f"the sysop/runtime/ figure has no {required} node at its own depth "
            f"(found {sorted(names)}). A guard matching the whole line is satisfied "
            "by an incidental mention in a sibling's comment."
        )


# ------------------------------------------------- the reaping the close prescribes


def test_the_workflow_scripts_table_names_the_batch_half_of_the_reaping():
    """Closes battery row C06.

    `tests/test_workflow_scripts_table.py` captures each § 8.4 row's *filename* and
    nothing else, so the `close_batch.sh` row's whole description could be replaced
    with "It also tidies up after the batch claim" and stay green. That row is the
    only place the batch half of close-time reaping is documented — Step 4c's id
    list is built from `roadmap_ids`, so no batch id ever reaches it, and before
    Phase 236 a `BATCH-<N>` marker was removed by nothing at all.
    """
    text = (REPO_ROOT / "core/companion/docs/WORKFLOW.md").read_text(encoding="utf-8")
    row = next((ln for ln in text.splitlines()
                if ln.startswith("| `close_batch.sh <N>")), None)
    assert row, "§ 8.4's close_batch.sh row is gone or reshaped past this anchor"
    assert "remove_claim_artifacts()" in row and "not** call" not in row \
            and "does **not**" not in row, (
        "§ 8.4's close_batch.sh row no longer names remove_claim_artifacts() — the "
        "batch half of close-time reaping is then documented nowhere, and § 2.8 "
        "step 7 only covers the roadmap half"
    )


def test_the_monograph_runtime_figure_lists_the_claim_directory():
    """Closes battery row C04.

    `tests/test_install_park_migration.py` pins the figure's `parked/` node because
    a phase once renamed it; nothing read `claim/`, which is why the figure omitted
    it for 68 phases while the same page cited
    `sysop/runtime/claim/<id>/<run>/` in the `/claim-task` glossary entry. A figure
    that disagrees with its own page is the drift this asserts against.
    """
    fig = (REPO_ROOT / "docs/workflow.html").read_text(encoding="utf-8")
    # Lens 3's C2 and C3: `any()` over every tree line in the file matched an
    # incidental `claim/` inside the LOCKS node's comment, and re-indenting the
    # node from `│   │   ├──` to `│   ├──` moved it out of sysop/runtime/ without
    # detection. Read the node NAME at its own depth, not the whole line.
    nodes = [ln for ln in fig.splitlines()
             if re.match(r"│   │   [├└]── ", ln)]
    assert nodes, "the sysop/runtime/ figure's node lines are gone or re-indented"
    names = [re.sub(r"\s.*$", "", ln.split("── ", 1)[1]) for ln in nodes]
    assert any(n == "claim/" for n in names), (
        "docs/workflow.html's sysop/runtime/ figure does not list claim/, while the "
        "glossary on the same page names sysop/runtime/claim/<id>/<run>/ as where "
        "every orchestration seam leaves its file"
    )
