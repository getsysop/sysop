"""The archiver refuses a tracker whose unterminated fence hides a batch (Q-240).

The defect, reproduced by execution before the fix: `_fenced_mask` ignores an
**unterminated** fence on purpose — honouring one would disable structural
parsing to end-of-file, which is worse than no fence rule — so a
`### Batch 9 — EXAMPLE ONLY \\`Merged\\`` inside a fence nobody closed parses as a
REAL batch. On the shape the entry predicts (fence opener inside a preceding
batch, so no orphan line sits above the first header) the archiver reported
`residue []`, 2 batches, `TOTAL 2 tasks` — the illustration counted as completed
work and archivable, with nothing left to refuse it.

Until now the only thing between that state and a destructive archive was the
`Q-116` orphaned-lines guard catching the fence opener as a line belonging to no
batch. That is **defence by coincidence**: it depends on where the opener happens
to sit. This module pins the declared mechanism that replaced it.

**The controls are half the module.** Over-strictness is the direction that
hides, and a refusal that fires on a legal tracker is worse than the bug — it
blocks routine maintenance the workflow prescribes. So a closed fence containing
a batch header, an unterminated fence containing no batch header, and an ordinary
tracker must all archive normally.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
ARCHIVER = SCRIPTS / "archive_review_tasks.py"
sys.path.insert(0, str(SCRIPTS))

from archive_review_tasks import (  # noqa: E402
    _unterminated_fence,
    parse_archivable_batches,
    unterminated_batch_span,
)

REAL_BATCH = [
    "# Review Tasks",
    "",
    "## Round 1 — a real round",
    "",
    "### Batch 1 — real work `Merged`",
    "",
    # The blockquote metadata block every real batch carries. Built from what
    # the shipped writers emit (`codebase-review/SKILL.md`), not from a model of
    # a tracker: without it this module never exercises the `(?:> ?)*` arm of
    # `_FENCE_OPEN_RE` — the arm `review_index.py`'s own header calls the one
    # that matters, because a fence opener inside a blockquote is still a fence.
    "> **Scope:** the thing under review",
    "> **Branch:** review/batch-1",
    "> **Verify:** pytest",
    "",
    "- [x] **TASK-1** A real task that really was done.",
    "",
]
EXAMPLE = [
    "### Batch 9 — EXAMPLE ONLY `Merged`",
    "",
    "- [x] **TASK-999** An illustration. Nobody did this work.",
]


def _write(tmp_path, lines):
    (tmp_path / "sysop" / "scripts").mkdir(parents=True, exist_ok=True)
    for name in ("archive_review_tasks.py", "_log.py"):
        (tmp_path / "sysop" / "scripts" / name).write_bytes(
            (SCRIPTS / name).read_bytes()
        )
    f = tmp_path / "review_tasks.md"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # The archiver appends into an existing archive; a consumer that has never
    # rotated one has no such file, and that is a separate path. Seed it so this
    # module tests the refusal, not archive bootstrapping.
    arch = tmp_path / "review_tasks_archive.md"
    if not arch.exists():
        arch.write_text(
            "# Review Tasks Archive\n"
            "\n"
            "## Grand Total (Archived)\n"
            "\n"
            "| Round | Total | Completed | Deferred | Status |\n"
            "|---|---|---|---|---|\n",
            encoding="utf-8",
        )
    return f


def _run(tmp_path, *args):
    return subprocess.run(
        [sys.executable, "sysop/scripts/archive_review_tasks.py", *args],
        cwd=tmp_path, capture_output=True, text=True, timeout=60, input="y\n",
    )


# ── the defect ────────────────────────────────────────────────────────────────

DEFECT = REAL_BATCH + ["Here is how you would document an example:", "", "```markdown"] + EXAMPLE


def test_the_parser_still_counts_the_fenced_example(tmp_path):
    """The underlying parse is UNCHANGED, and that is deliberate.

    The fix is a refusal, not a parsing change: making `_fenced_mask` honour an
    unterminated fence would disable structural parsing to EOF, which Phase 181's
    round established is worse than the bug. This test pins that the defect is
    still reachable at the parser layer, so a later "simplification" of the
    refusal cannot look harmless.
    """
    lines = DEFECT
    rounds = parse_archivable_batches(lines)
    batches = [b for r in rounds for b in r["batches"]]
    assert len(batches) == 2, [b["lines"][0] for b in batches]
    assert sum(b["task_count"] for b in batches) == 2
    assert all(r["all_merged"] for r in rounds)


def test_the_refusal_fires_on_the_predicted_shape(tmp_path):
    _write(tmp_path, DEFECT)
    proc = _run(tmp_path)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "refusing to archive" in proc.stderr
    assert "unterminated" in proc.stderr
    assert "Batch 9" in proc.stderr


def test_the_refusal_precedes_any_accounting(tmp_path):
    """A refusal printed after a wrong total is the defect, not a fix for it."""
    _write(tmp_path, DEFECT)
    proc = _run(tmp_path)
    assert "Total:" not in proc.stdout, proc.stdout
    assert "2 tasks" not in proc.stdout
    assert proc.stdout.strip() == "", proc.stdout


def test_dry_run_refuses_too(tmp_path):
    """A dry run whose preview counts an illustration is the report acted on."""
    _write(tmp_path, DEFECT)
    proc = _run(tmp_path, "--dry-run")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "refusing to archive" in proc.stderr


def test_the_tracker_is_not_mutated_by_a_refusal(tmp_path):
    f = _write(tmp_path, DEFECT)
    arch = tmp_path / "review_tasks_archive.md"
    before, arch_before = f.read_text(encoding="utf-8"), arch.read_text(encoding="utf-8")
    _run(tmp_path)
    assert f.read_text(encoding="utf-8") == before
    assert arch.read_text(encoding="utf-8") == arch_before


def test_the_remedy_named_is_the_one_that_works(tmp_path):
    """Rule 3 of the author-side pass: run the prescribed fix, do not assert it.

    The refusal tells the operator to close the fence. If that does not actually
    clear the refusal, the diagnostic is a dead end — the class Phase 173 and
    Phase 178 both paid for.
    """
    _write(tmp_path, DEFECT)
    assert _run(tmp_path).returncode == 1
    _write(tmp_path, DEFECT + ["```"])
    proc = _run(tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "refusing to archive" not in proc.stderr


# ── controls: over-strictness is the direction that hides ─────────────────────

CLOSED_FENCE = REAL_BATCH + ["```markdown"] + EXAMPLE + ["```"]
UNTERMINATED_NO_BATCH = REAL_BATCH + ["```python", 'print("no batch header here")']
ORDINARY = REAL_BATCH


@pytest.mark.parametrize(
    "name,lines",
    [
        ("closed fence containing a batch header", CLOSED_FENCE),
        ("unterminated fence containing no batch header", UNTERMINATED_NO_BATCH),
        ("ordinary tracker with no fences", ORDINARY),
    ],
)
def test_legal_trackers_are_not_refused(tmp_path, name, lines):
    _write(tmp_path, lines)
    proc = _run(tmp_path, "--dry-run")
    assert proc.returncode == 0, f"{name} was refused:\n{proc.stderr}"
    assert "refusing to archive" not in proc.stderr, name


def test_a_closed_fence_still_masks_its_example(tmp_path):
    """The control that proves the control.

    If a closed fence were NOT masked, `test_legal_trackers_are_not_refused`
    would pass for the wrong reason — the tracker would be legal *and* the
    example would be counted.
    """
    batches = [b for r in parse_archivable_batches(CLOSED_FENCE) for b in r["batches"]]
    assert len(batches) == 1, [b["lines"][0] for b in batches]
    assert "Batch 1" in batches[0]["lines"][0]


# ── the predicate itself ──────────────────────────────────────────────────────

def test_span_returns_none_when_there_is_nothing_to_report():
    assert unterminated_batch_span(ORDINARY) is None
    assert unterminated_batch_span(CLOSED_FENCE) is None
    assert unterminated_batch_span(UNTERMINATED_NO_BATCH) is None


def test_span_reports_one_indexed_positions():
    hit = unterminated_batch_span(DEFECT)
    assert hit is not None
    fence_line, marker, header_line, header_text = hit
    assert DEFECT[fence_line - 1].startswith("```")
    assert DEFECT[header_line - 1] == header_text
    assert marker == "```"


@pytest.mark.parametrize(
    "opener,closer,still_open",
    [
        ("````", "```", True),    # a 4-backtick fence is not closed by 3 (length)
        ("```", "````", False),   # ...but 4 does close 3
        ("~~~", "```", True),     # a tilde fence is not closed by backticks (char)
        ("~~~", "~~~", False),
    ],
)
def test_the_close_predicate_keeps_both_halves(opener, closer, still_open):
    """Both halves of the close rule are load-bearing and data-reachable.

    Duplicated from `review_index.py`, so it can drift. This is the mutation the
    author-side pass calls for: assert the ASSUMPTION, not just the content.
    """
    lines = ["# t", opener, "example", closer]
    assert (_unterminated_fence(lines) is not None) is still_open


def test_the_duplicated_helpers_match_their_source():
    """`_unterminated_fence` is duplicated verbatim from `review_index.py`.

    Duplicated rather than imported because this module resolves the markdown via
    `parents[2]` while `review_index` walks to the git root, so an import can
    raise a non-`ImportError` in an ordinary worktree — and a refusal that fails
    open on an import error is worse than no refusal. The cost of duplication is
    drift, so it is pinned here, the same way `_fenced_mask` already is.
    """
    import ast

    def body_of(path, name):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                # Compare structure, not comments or docstrings: the two copies
                # deliberately explain themselves differently.
                stripped = [
                    n for n in node.body
                    if not (isinstance(n, ast.Expr)
                            and isinstance(n.value, ast.Constant)
                            and isinstance(n.value.value, str))
                ]
                return ast.dump(ast.Module(body=stripped, type_ignores=[]))
        raise AssertionError(f"{name} not found in {path}")

    assert body_of(ARCHIVER, "_unterminated_fence") == body_of(
        SCRIPTS / "review_index.py", "_unterminated_fence"
    ), "_unterminated_fence has drifted from its review_index.py source"


# ── the closed-fence counting defect, found while testing the above ──────────
#
# Self-initiated scope addition, recorded as one in PHASE_LOG.md. It surfaced
# because `test_the_remedy_named_is_the_one_that_works` printed "Batch 1: 2
# tasks" for a batch holding one real task, which is not what that test was
# looking for.

CLOSED_FENCE_WITH_TASKS = REAL_BATCH + [
    "Documentation example, properly fenced and closed:",
    "",
    "```markdown",
    "- [x] **TASK-901** illustration one",
    "- [ ] **TASK-902** illustration two",
    "```",
]


def test_a_closed_fences_task_lines_are_not_counted():
    """Distinct from Q-240: this fence is CLOSED and correctly masked.

    The batch-level mask worked — one batch, not two — but `count_round_tasks`
    read `b["lines"]`, into which the parser deliberately accumulates fenced
    content so archiving does not drop it. Before the fix: `(2, 3)`.
    """
    from archive_review_tasks import count_round_tasks
    r = parse_archivable_batches(CLOSED_FENCE_WITH_TASKS)[0]
    assert len(r["batches"]) == 1
    assert count_round_tasks(r) == (1, 1), count_round_tasks(r)


def test_the_fenced_example_is_still_preserved_for_archiving():
    """The control on the fix: masking must not become dropping.

    If the fix had removed fenced lines from `b["lines"]` instead of skipping
    them while counting, archiving would silently delete the consumer's
    documentation — trading a wrong number for lost content.

    **This test used to be vacuous for the defect it names.** It called only
    `parse_archivable_batches`, never `count_round_tasks` — which is where the
    fix lives and where a line-dropping implementation would do its damage. The
    round applied exactly that defect inside `count_round_tasks` and this test
    passed. It now calls the function, and asserts the batch body afterwards.
    """
    from archive_review_tasks import count_round_tasks
    r = parse_archivable_batches(CLOSED_FENCE_WITH_TASKS)[0]
    assert count_round_tasks(r) == (1, 1)
    body = r["batches"][0]["lines"]
    assert sum(1 for line in body if "TASK-90" in line) == 2, (
        "count_round_tasks mutated the batch body instead of skipping while "
        "counting; the fenced example would be deleted on archive: %r" % (body,)
    )


def test_the_two_counters_agree_on_an_ordinary_batch():
    """Non-vacuity: the mask must not zero out real tasks."""
    from archive_review_tasks import count_round_tasks
    r = parse_archivable_batches(ORDINARY)[0]
    assert count_round_tasks(r) == (1, 1)
    assert r["batches"][0]["task_count"] == 1


# ── the review round's MEDIUM finding: an unterminated fence with task lines ──
#
# The first cut refused only when a `### Batch` header sat inside an
# unterminated fence, and `count_round_tasks`'s docstring then asserted that
# covered the unterminated case generally. It did not. A fence holding only
# `- [x]` illustration lines was masked by nothing and refused by nothing.

UNTERMINATED_WITH_TASKS = REAL_BATCH + [
    "An example block nobody closed, holding NO batch header:",
    "",
    "```markdown",
    "- [x] **TASK-901** illustration one",
]
UNTERMINATED_PROSE_ONLY = REAL_BATCH + [
    "```python",
    'print("no task lines and no batch header in here")',
]


def test_an_unterminated_fence_with_task_lines_is_refused(tmp_path):
    _write(tmp_path, UNTERMINATED_WITH_TASKS)
    proc = _run(tmp_path, "--dry-run")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "completed-task line" in proc.stderr, proc.stderr


def test_without_the_refusal_those_lines_count_as_real_work():
    """Pins the defect, so the guard above cannot pass vacuously.

    `(2, 2)` is what the round measured: one real task plus one illustration,
    both counted — and that total is what `update_archive_total` writes durably
    into the archive's Grand Total row.
    """
    from archive_review_tasks import count_round_tasks
    r = parse_archivable_batches(UNTERMINATED_WITH_TASKS)[0]
    assert count_round_tasks(r) == (2, 2), count_round_tasks(r)


def test_a_prose_only_unterminated_fence_is_NOT_refused(tmp_path):
    """The over-strictness control, and the reason the span is two functions.

    Nothing miscounts a fence holding only prose, so refusing it would block a
    legal tracker — and a refusal that fires on legal input is the kind the next
    author weakens rather than fixes.
    """
    _write(tmp_path, UNTERMINATED_PROSE_ONLY)
    proc = _run(tmp_path, "--dry-run")
    assert proc.returncode == 0, proc.stderr
    assert "refusing to archive" not in proc.stderr


def test_the_batch_header_case_still_names_a_batch_header(tmp_path):
    """The two spans must stay distinguishable in the diagnostic."""
    _write(tmp_path, DEFECT)
    proc = _run(tmp_path, "--dry-run")
    assert proc.returncode == 1
    assert "a batch header" in proc.stderr, proc.stderr


def test_the_task_span_is_none_on_every_legal_shape():
    from archive_review_tasks import unterminated_task_span
    for lines in (ORDINARY, CLOSED_FENCE, UNTERMINATED_NO_BATCH,
                  UNTERMINATED_PROSE_ONLY, CLOSED_FENCE_WITH_TASKS):
        assert unterminated_task_span(lines) is None, lines[:3]
    assert unterminated_task_span(UNTERMINATED_WITH_TASKS) is not None


def test_the_span_uses_the_PERMISSIVE_header_pattern():
    """Mutation M09, which the author's battery scored as killed and was not.

    The battery substituted `ARCHIVABLE_BATCH_RE` — a symbol that does not
    exist — so the run died of `NameError` and the red was recorded as a guard
    firing. Re-run with the real constant (`BATCH_HEADER_RE`), the whole module
    stayed green: nothing pinned which of the two patterns the span uses.

    It has to be the PERMISSIVE one. `BATCH_HEADER_RE` demands an em-dash and a
    backticked status; `ANY_BATCH_HEADER_RE` does not. A near-miss header —
    ASCII hyphen, missing backticks, a tab — still reads to a human as a batch
    inside the example, and the strict pattern would let it through the refusal
    while the parser happily opened a batch for it.
    """
    import archive_review_tasks as A
    near_miss = "### Batch 9 - EXAMPLE ONLY `Merged`"
    assert A.ANY_BATCH_HEADER_RE.match(near_miss), "permissive pattern changed"
    assert not A.BATCH_HEADER_RE.match(near_miss), (
        "the two patterns no longer differ on this shape, so this test proves "
        "nothing — pick a header the strict pattern still rejects"
    )
    hit = unterminated_batch_span(REAL_BATCH + ["```markdown", near_miss])
    assert hit is not None, (
        "a near-miss batch header inside an unterminated fence is not refused; "
        "the span has been narrowed to the strict pattern"
    )
    assert hit[3] == near_miss


# ── round survivors: the refusal predicate had one spelling and no EOF case ──

@pytest.mark.parametrize("header", [
    "### Batch 9 — EXAMPLE ONLY `Merged`",     # em-dash, the only shape tested before
    "### Batch 9: EXAMPLE ONLY `Merged`",      # colon
    "###\tBatch 9 — EXAMPLE ONLY `Merged`",    # tab after the hashes
    "### Batch 9 - EXAMPLE ONLY `Merged`",     # ASCII hyphen
    "### Batch 9",                             # bare, no title or status
])
def test_the_refusal_is_not_keyed_to_one_header_spelling(header):
    """Narrowing the refusal's predicate survived, because every fixture used
    the same header. `ANY_BATCH_HEADER_RE` is deliberately permissive — it
    exists to notice a header the STRICT pattern rejected — so adding
    `and " — " in line` or `and "`Merged`" in line` inside the span silently
    reopens the class for every other spelling a human would still read as a
    batch."""
    hit = unterminated_batch_span(REAL_BATCH + ["```markdown", header])
    assert hit is not None, header
    assert hit[3] == header


def test_a_fenced_header_on_the_last_line_is_still_found():
    """The scan's EOF boundary: `range(start + 1, len(lines) - 1)` survived.

    No fixture put the header last, so an off-by-one at the end of the file was
    invisible — and a tracker whose example block is the final thing in the file
    is the ordinary shape, not an exotic one.
    """
    lines = REAL_BATCH + ["```markdown", "### Batch 9 — EXAMPLE ONLY `Merged`"]
    assert lines[-1].startswith("### Batch 9")
    assert unterminated_batch_span(lines) is not None
    tasks = REAL_BATCH + ["```markdown", "- [x] **TASK-901** illustration"]
    assert tasks[-1].startswith("- [x]")
    from archive_review_tasks import unterminated_task_span
    assert unterminated_task_span(tasks) is not None


def test_a_fence_opened_inside_a_blockquote_is_still_a_fence():
    """`_FENCE_OPEN_RE` carries a `(?:> ?)*` arm; nothing here exercised it.

    Two halves, and the second is the one worth stating. A blockquoted opener
    IS an unterminated fence — that arm is live. But a *blockquoted* batch
    header is not a batch to anything: `ANY_BATCH_HEADER_RE` is `^###`, so the
    parser does not open a batch for `> ### Batch 9` and the refusal has nothing
    to refuse. The two agree, which is the property that matters; the first
    draft of this test asserted a refusal there and was simply wrong about the
    tree.
    """
    from archive_review_tasks import _unterminated_fence, ANY_BATCH_HEADER_RE

    quoted = REAL_BATCH + ["> ```markdown", "> ### Batch 9 — EXAMPLE `Merged`"]
    assert _unterminated_fence(quoted) is not None, "the `> ` fence arm is dead"
    assert not ANY_BATCH_HEADER_RE.match("> ### Batch 9 — EXAMPLE `Merged`")
    assert not any(
        b["lines"][0].startswith("> ###")
        for r in parse_archivable_batches(quoted) for b in r["batches"]
    ), "the parser opened a batch for a blockquoted header"
    assert unterminated_batch_span(quoted) is None

    # ...but a PLAIN header inside a blockquoted fence is a real phantom batch,
    # because the parser does open one for it. That is the case the arm buys.
    mixed = REAL_BATCH + ["> ```markdown", "### Batch 9 — EXAMPLE `Merged`"]
    assert unterminated_batch_span(mixed) is not None, mixed[-2:]
