"""The hostile corpus for `close_batch.sh`'s annotation scope (Phase 198).

Built BEFORE the fix, per `_shared/adversarial-review.md` § *Before you spawn
anyone* rule 4: the change reinterprets a predicate over text other writers
produce, so the corpus is red before and green after, and that is the fix's own
evidence.

**What broke.** `CLOSE_AWK`'s `emit()` held exactly one line, so a task was left
open only when the *physically next* line was its `> Failed:` annotation. But
`/codebase-review` and `/security-audit` both emit a **two-line** task — a
checkbox line plus a mandatory indented `` `file:line` `` + provenance line — and
`/auto-judge` appends the annotation *below the task*, which is two lines below
the checkbox. So on the shape the shipped writers actually emit, the protection
`> Failed:` exists to provide could not fire: the task closed `[x]` with its
failure note sitting underneath, and the ORPHAN warning that noticed went to
stderr while `/review-close` Step 4b reads stdout.

**Why no test caught it.** Every awk-exercising fixture in this suite used
ONE-LINE tasks — `BASE_TASKS`, `FAILURE_TASKS`, `LOUD_TASKS`,
`_TRAILING_SECTION_TRACKER`, `_ARCHIVABLE_WITH_FAILURE`, and both
`test_failed_verdict_record.py` subprocess documents. A shape the shipped writers
never emit was the only shape under test, so the whole FAIL-hold suite exercised
fiction. Hence `_canonical_task()` below derives its fixture from the generators
rather than from an author's memory of them, and
`test_the_canonical_fixture_still_matches_what_the_generators_emit` fails if the
generators move.

**The rule this file pins.** An annotation protects the **nearest preceding task
bullet within its block**; the scan stops at the next task bullet, a blank line,
or a heading. That keeps the concern the old
`test_annotation_only_counts_for_the_line_above_it` was written to defend — an
annotation must not shield some arbitrary task further up the file — while
honouring the shape that actually ships.

`> Dropped:` is in here as a **control**, not decoration. A drop matches no
branch at all — not HELD, not NEARMISS, not ORPHAN — so a drop produces
byte-identical evidence whether or not the scope rule fired. Without the drop
cases, a regression that started closing drops incorrectly would be invisible.
"""
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core/companion/scripts/close_batch.sh"
CODEBASE_REVIEW = REPO_ROOT / "core/skills/codebase-review/SKILL.md"
SECURITY_AUDIT = REPO_ROOT / "core/skills/security-audit/SKILL.md"


# ── Deriving the canonical shape from the source of truth ──────────────
# Rule 1's "derive the population from the source of truth, not from an index or
# summary of it", moved to what a fixture CONTAINS. The generators' templates are
# markdown fences in their § 5c Batch Format sections; a task is a `- [ ]` line
# followed by exactly one indented continuation carrying `file:line` and the
# provenance tag.
TEMPLATE_TASK_RE = re.compile(
    r"^- \[ \] \*\*TASK-[^*]+\*\*:.*\n^(  \S.*`\[verified\|reported\]`.*)$",
    re.MULTILINE,
)


def _template_continuation(skill_path: Path) -> str:
    """The indented continuation line the generator emits under every task."""
    m = TEMPLATE_TASK_RE.search(skill_path.read_text(encoding="utf-8"))
    assert m, (
        f"{skill_path.relative_to(REPO_ROOT)} no longer emits a two-line task in the "
        "shape this corpus was derived from. Re-derive the fixtures from its § 5c "
        "Batch Format template before touching close_batch.sh — a corpus built from "
        "a stale template proves only that the author is self-consistent."
    )
    return m.group(1)


def _canonical_task(ident: str, title: str, skill_path: Path = CODEBASE_REVIEW) -> str:
    """One task in exactly the shape the shipped generators emit: a checkbox line
    plus the mandatory indented `file:line` + provenance continuation."""
    return f"- [ ] **{ident}**: {title}\n{_template_continuation(skill_path)}\n"


def _doc(*body: str, batch: int = 1, name: str = "Canonical shape") -> str:
    return (
        "# Review Tasks\n\n"
        f"### Batch {batch} — {name} `Pending`\n\n"
        + "".join(body)
    )


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root, tasks: str):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "review_tasks.md").write_text(tasks)
    (root / "README.md").write_text("# seed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(cwd, *args):
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(cwd), capture_output=True, text=True,
    )


def _close(tmp_path, doc: str, batch: str = "1"):
    """Run a real close and return (result, resulting review_tasks.md text)."""
    repo = _repo(tmp_path / "repo", doc)
    r = _run(repo, batch)
    return r, (repo / "review_tasks.md").read_text()


# ── The derivation guard ───────────────────────────────────────────────

TEMPLATE_BULLET_RE = re.compile(r"^- \[ \] \*\*TASK-[^*]+\*\*:.*$", re.MULTILINE)


def test_the_canonical_fixture_still_matches_what_the_generators_emit():
    """A corpus is only worth what its inputs are worth. If either generator stops
    emitting the two-line task, every case below is testing a shape nothing
    writes — which is the exact condition that let this defect ship.

    EVERY task bullet in each template is checked, not just the first one the
    search happens to land on. The author battery collapsed the template's first
    task to a single line and this guard stayed green, because both templates
    carry TWO example tasks and `TEMPLATE_TASK_RE.search` simply found the
    second. A derivation that silently falls through to the next candidate
    reports the shape it wanted rather than the shape the file has.
    """
    for skill in (CODEBASE_REVIEW, SECURITY_AUDIT):
        text = skill.read_text(encoding="utf-8")
        lines = text.splitlines()
        bullets = [i for i, ln in enumerate(lines) if TEMPLATE_BULLET_RE.match(ln)]
        assert len(bullets) >= 2, (
            f"{skill.name} no longer shows an example task bullet in its § 5c "
            "Batch Format template; re-derive this corpus from whatever it shows now"
        )
        for i in bullets:
            follower = lines[i + 1] if i + 1 < len(lines) else ""
            assert follower.startswith("  ") and follower.strip(), (
                f"{skill.name}:{i + 2} — the task bullet above it has no indented "
                f"continuation line, so the two-line shape this whole corpus is "
                f"derived from is no longer what this generator emits:\n"
                f"  {lines[i]}\n  {follower!r}"
            )
            assert "`[verified|reported]`" in follower, (skill.name, follower)

        cont = _template_continuation(skill)
        assert cont.startswith("  "), (skill, cont)
        assert "`[verified|reported]`" in cont, (skill, cont)

    # The two generators are independent writers of the same shape; if they ever
    # diverge in indentation the scope rule has two populations, not one.
    assert _template_continuation(CODEBASE_REVIEW)[:2] == \
        _template_continuation(SECURITY_AUDIT)[:2]


# ── The defect itself, on both generators' output ──────────────────────

class TestCanonicalShapeIsHeld:
    def test_codebase_review_shape_holds_a_failed_task_open(self, tmp_path):
        doc = _doc(
            _canonical_task("TASK-1", "the failed one", CODEBASE_REVIEW),
            "  > Failed: needs a cross-module signature change\n",
        )
        r, text = _close(tmp_path, doc)
        assert "- [ ] **TASK-1**: the failed one" in text, text
        assert "0 tasks closed, 1 failed" in r.stdout, r.stdout

    def test_security_audit_shape_holds_a_failed_task_open(self, tmp_path):
        doc = _doc(
            _canonical_task("TASK-1", "the failed one", SECURITY_AUDIT),
            "  > Failed: exploit path not reproducible in the test harness\n",
        )
        r, text = _close(tmp_path, doc)
        assert "- [ ] **TASK-1**: the failed one" in text, text
        assert "0 tasks closed, 1 failed" in r.stdout, r.stdout

    def test_the_held_task_is_named_on_stdout_not_stderr(self, tmp_path):
        # Step 4b tells the operator to read stdout. A protection reported only on
        # stderr is a protection the documented reader never sees.
        doc = _doc(
            _canonical_task("TASK-1", "the failed one"),
            "  > Failed: reason\n",
        )
        r, _ = _close(tmp_path, doc)
        # Line 5 is the TASK bullet, not the annotation on line 7 — the operator
        # needs the line they have to go and finish, not the note about it.
        assert "held open (line 5)" in r.stdout, r.stdout
        assert "held open" not in r.stderr, r.stderr

    def test_a_task_with_several_continuation_lines_is_still_held(self, tmp_path):
        doc = _doc(
            _canonical_task("TASK-1", "the failed one"),
            "  Additional context the agent wrote while working.\n",
            "  And a third line, because nothing caps this.\n",
            "  > Failed: reason\n",
        )
        r, text = _close(tmp_path, doc)
        assert "- [ ] **TASK-1**: the failed one" in text, text
        assert "0 tasks closed, 1 failed" in r.stdout, r.stdout

    def test_the_mixed_batch_closes_only_what_it_should(self, tmp_path):
        doc = _doc(
            _canonical_task("TASK-1", "fixed"),
            "\n",
            _canonical_task("TASK-2", "failed"),
            "  > Failed: reason\n",
            "\n",
            _canonical_task("TASK-3", "also fixed"),
        )
        r, text = _close(tmp_path, doc)
        assert "- [x] **TASK-1**: fixed" in text, text
        assert "- [ ] **TASK-2**: failed" in text, text
        assert "- [x] **TASK-3**: also fixed" in text, text
        assert "2 tasks closed, 1 failed" in r.stdout, r.stdout


# ── The controls: `> Dropped:` masks totally, so it must be exercised ───

class TestDropControls:
    def test_canonical_shape_drop_still_closes(self, tmp_path):
        doc = _doc(
            _canonical_task("TASK-1", "the dropped one"),
            "  > Dropped: premise was wrong\n",
        )
        r, text = _close(tmp_path, doc)
        assert "- [x] **TASK-1**: the dropped one" in text, text
        assert "1 tasks closed)." in r.stdout, r.stdout

    def test_a_drop_produces_no_diagnostic_noise(self, tmp_path):
        # A drop matches no branch — not HELD, not NEARMISS, not ORPHAN. That is
        # exactly why the sibling case masked this bug for so long, and why a
        # regression here would otherwise be invisible.
        doc = _doc(
            _canonical_task("TASK-1", "the dropped one"),
            "  > Dropped: premise was wrong\n",
        )
        r, _ = _close(tmp_path, doc)
        assert "TASK-1" not in r.stderr, r.stderr
        assert "held open" not in r.stdout, r.stdout
        assert "protects nothing" not in r.stdout + r.stderr

    def test_a_drop_does_not_shield_a_neighbour(self, tmp_path):
        doc = _doc(
            _canonical_task("TASK-1", "first"),
            "  > Dropped: premise was wrong\n",
            _canonical_task("TASK-2", "second"),
        )
        r, text = _close(tmp_path, doc)
        assert "- [x] **TASK-1**: first" in text, text
        assert "- [x] **TASK-2**: second" in text, text
        assert "2 tasks closed)." in r.stdout, r.stdout


# ── Where the scan must STOP — the concern the old test defended ───────

class TestTheScanStops:
    def test_a_whitespace_only_line_ends_the_block_too(self, tmp_path):
        # The author battery's A02 found this: `is_continuation` tests
        # `^[[:space:]]` AND not-blank, and dropping the not-blank half survived
        # every case in this file, because every "blank" line here was EMPTY.
        # A line of spaces matches `^[[:space:]]` and an empty one does not, so
        # only a whitespace-only separator distinguishes the two halves. Editors
        # and agents emit these constantly.
        doc = _doc(
            _canonical_task("TASK-1", "first"),
            "   \n",
            "  > Failed: attached to nothing\n",
        )
        r, text = _close(tmp_path, doc)
        assert "- [x] **TASK-1**: first" in text, text
        assert "protects nothing" in r.stdout + r.stderr, (r.stdout, r.stderr)

    def test_a_blank_line_ends_the_block(self, tmp_path):
        # The annotation is detached. It protects nothing, the task closes, and
        # the run says so — the pre-existing contract, unweakened.
        doc = _doc(
            _canonical_task("TASK-1", "first"),
            "\n",
            "  > Failed: attached to nothing\n",
        )
        r, text = _close(tmp_path, doc)
        assert "- [x] **TASK-1**: first" in text, text
        assert "protects nothing" in r.stdout + r.stderr

    def test_an_annotation_shields_the_nearest_bullet_not_a_farther_one(self, tmp_path):
        # The runaway-forward-scan case. TASK-2 is nearer, so TASK-2 is held and
        # TASK-1 closes normally.
        doc = _doc(
            _canonical_task("TASK-1", "first"),
            _canonical_task("TASK-2", "second"),
            "  > Failed: reason\n",
        )
        r, text = _close(tmp_path, doc)
        assert "- [x] **TASK-1**: first" in text, text
        assert "- [ ] **TASK-2**: second" in text, text
        assert "1 tasks closed, 1 failed" in r.stdout, r.stdout

    def test_a_heading_ends_the_block(self, tmp_path):
        doc = (
            "# Review Tasks\n\n"
            "### Batch 1 — First `Pending`\n\n"
            + _canonical_task("TASK-1", "first")
            + "### Batch 2 — Second `Pending`\n"
            + "  > Failed: across a heading\n"
        )
        r, text = _close(tmp_path, doc, "1")
        assert "- [x] **TASK-1**: first" in text, text

    def test_the_batch_metadata_block_is_not_mistaken_for_an_annotation(self, tmp_path):
        # The generators emit `> **Scope:**` / `> **Branch:**` / `> **Verify:**`
        # blockquote lines between the heading and the tasks. They are `>` lines
        # that are not annotations, and they sit where nothing is pending.
        doc = (
            "# Review Tasks\n\n"
            "### Batch 1 — First `Pending`\n\n"
            "> **Scope:** src/**\n"
            "> **Branch:** `fix/batch-1-thing`\n"
            "> **Verify:** `pytest`\n"
            "> **Overlap:** none\n\n"
            + _canonical_task("TASK-1", "first")
        )
        r, text = _close(tmp_path, doc)
        assert "- [x] **TASK-1**: first" in text, text
        assert "1 tasks closed)." in r.stdout, r.stdout


# ── What happens when the construct never closes ───────────────────────

class TestUnterminated:
    def test_task_and_continuation_at_eof_with_no_annotation_closes(self, tmp_path):
        doc = _doc(_canonical_task("TASK-1", "first"))
        r, text = _close(tmp_path, doc)
        assert "- [x] **TASK-1**: first" in text, text
        assert "1 tasks closed)." in r.stdout, r.stdout

    def test_annotation_at_eof_with_no_trailing_newline_is_honoured(self, tmp_path):
        doc = _doc(
            _canonical_task("TASK-1", "first"),
            "  > Failed: reason",  # no trailing newline
        )
        r, text = _close(tmp_path, doc)
        assert "- [ ] **TASK-1**: first" in text, text
        assert "0 tasks closed, 1 failed" in r.stdout, r.stdout

    def test_a_task_bullet_as_the_very_last_line_closes(self, tmp_path):
        doc = _doc("- [ ] **TASK-1**: no continuation at all")
        r, text = _close(tmp_path, doc)
        assert "- [x] **TASK-1**: no continuation at all" in text, text


# ── Blast radius: buffering must not reorder or drop a line ────────────

class TestLineOrderIsPreserved:
    def test_every_input_line_survives_exactly_once_and_in_order(self, tmp_path):
        doc = _doc(
            _canonical_task("TASK-1", "first"),
            "  a continuation line\n",
            "  another continuation line\n",
            "  > Failed: reason\n",
            "\n",
            _canonical_task("TASK-2", "second"),
            "  > Dropped: nope\n",
            "\n",
            "Some trailing prose that belongs to nobody.\n",
        )
        repo = _repo(tmp_path / "repo", doc)
        before = (repo / "review_tasks.md").read_text().splitlines()
        _run(repo, "1")
        after = (repo / "review_tasks.md").read_text().splitlines()
        assert len(before) == len(after), (before, after)
        for b, a in zip(before, after):
            # The only permitted differences are a checkbox flip on a task line
            # and the batch header's own `Pending` → `Merged`. Everything else —
            # continuation lines, annotations, blanks, trailing prose — must come
            # back byte-identical and in place.
            if b == a:
                continue
            if b.startswith("- [ ] ") and a == b.replace("- [ ] ", "- [x] ", 1):
                continue
            if b.startswith("### Batch ") and a == b.replace("`Pending`", "`Merged`"):
                continue
            raise AssertionError((b, a))


# ── The near miss, now that it can sit deeper in the block ─────────────

class TestNearMissInsideTheBlock:
    def test_a_near_miss_below_a_continuation_line_is_still_reported(self, tmp_path):
        doc = _doc(
            _canonical_task("TASK-1", "near miss"),
            "  > Fail: singular\n",
        )
        r, text = _close(tmp_path, doc)
        assert "- [x] **TASK-1**: near miss" in text, text
        assert "looks like a failure note but was NOT recognised" in r.stdout + r.stderr

    def test_a_near_miss_at_column_0_is_still_reported(self, tmp_path):
        """The round's sharpest code finding, and a regression this phase itself
        introduced. `is_failed` is deliberately tested at column 0 so an
        unindented annotation still counts — but the first cut of the block
        rewrite recorded near misses only inside the `is_continuation` branch,
        which a column-0 line never enters. So `> Fail:` at column 0 closed its
        task in SILENCE, producing evidence byte-identical to a clean close.

        That is the invariant `close_batch.sh` states in its own header — "a dead
        item and a clean one must not produce identical evidence" — broken in the
        same commit that moved these warnings to stdout to make them louder. No
        fixture in the tree used a column-0 annotation; every near-miss fixture
        was indented."""
        doc = _doc(
            _canonical_task("TASK-1", "near miss at column 0"),
            "> Fail: singular, and unindented\n",
        )
        r, text = _close(tmp_path, doc)
        assert "- [x] **TASK-1**: near miss at column 0" in text, text
        assert "looks like a failure note but was NOT recognised" in r.stdout, r.stdout
        assert "Failure-note near misses not honoured: 1" in r.stdout, r.stdout

    def test_a_column_0_failed_annotation_is_still_honoured(self, tmp_path):
        """The twin. `is_failed` is tested BEFORE the block-end test precisely so
        this keeps working; if that ordering is ever swapped, the task closes."""
        doc = _doc(
            _canonical_task("TASK-1", "unindented annotation"),
            "> Failed: unindented but real\n",
        )
        r, text = _close(tmp_path, doc)
        assert "- [ ] **TASK-1**: unindented annotation" in text, text
        assert "0 tasks closed, 1 failed" in r.stdout, r.stdout

    def test_the_near_miss_line_number_is_the_line_it_is_on(self, tmp_path):
        doc = _doc(
            _canonical_task("TASK-1", "near miss"),
            "  padding\n",
            "  > Fail: singular\n",
        )
        r, _ = _close(tmp_path, doc)
        # doc lines: 1 `# Review Tasks`, 2 blank, 3 heading, 4 blank,
        #            5 task, 6 continuation, 7 padding, 8 the near miss
        assert "line 8" in r.stdout + r.stderr, (r.stdout, r.stderr)


# ── What else matches this: the fenced-annotation case ────────────────

class TestFencedAnnotation:
    def test_a_failed_line_inside_a_fenced_block_under_a_task(self, tmp_path):
        """A task whose continuation quotes a fenced `> Failed:` — the classic
        "what else matches this" case for a rule keyed to a marker.

        `CLOSE_AWK` has never had fence awareness: pre-fix, a fenced annotation
        one line under the bullet was honoured just the same. What the block rule
        changes is the REACH — from one line to the whole continuation block — so
        this case is recorded with its real behaviour rather than assumed away.
        """
        doc = _doc(
            _canonical_task("TASK-1", "quotes a failure note"),
            "  ```\n",
            "  > Failed: this is quoted output, not a verdict\n",
            "  ```\n",
        )
        r, text = _close(tmp_path, doc)
        # Held. Over-holding is the SAFE direction — the task stays open and the
        # run says so on stdout, where the operator is told to look. Under-holding
        # is what loses work. Same asymmetry the `is_failed` matcher was widened
        # under (see close_batch.sh's "the generous side is the safe one").
        assert "- [ ] **TASK-1**: quotes a failure note" in text, text
        assert "held open" in r.stdout, r.stdout


# ── The range boundary ─────────────────────────────────────────────────

class TestRangeBoundary:
    def test_an_annotation_past_the_batch_end_still_protects_its_task(self, tmp_path):
        # Only the TASK line is range-checked, so a block that runs past `e`
        # still resolves. The widened scan extends further past `e` than the
        # one-line lookahead did, which is why this is pinned rather than assumed.
        doc = (
            "# Review Tasks\n\n"
            "### Batch 1 — First `Pending`\n\n"
            + _canonical_task("TASK-1", "failed")
            + "  > Failed: reason\n"
            + "\n"
            + "### Batch 2 — Second `Pending`\n\n"
            + _canonical_task("TASK-2", "untouched")
        )
        r, text = _close(tmp_path, doc, "1")
        assert "- [ ] **TASK-1**: failed" in text, text
        assert "- [ ] **TASK-2**: untouched" in text, text
        assert "0 tasks closed, 1 failed" in r.stdout, r.stdout

    def test_a_task_outside_the_range_is_neither_held_nor_orphaned(self, tmp_path):
        doc = (
            "# Review Tasks\n\n"
            "### Batch 1 — First `Pending`\n\n"
            + _canonical_task("TASK-1", "in range")
            + "\n"
            + "### Batch 2 — Second `Pending`\n\n"
            + _canonical_task("TASK-2", "out of range")
            + "  > Failed: reason\n"
        )
        r, text = _close(tmp_path, doc, "1")
        assert "- [x] **TASK-1**: in range" in text, text
        assert "- [ ] **TASK-2**: out of range" in text, text
        assert "TASK-2" not in r.stdout + r.stderr, (r.stdout, r.stderr)


# ── Negative control ───────────────────────────────────────────────────

def test_a_batch_with_no_annotations_produces_no_diagnostics(tmp_path):
    doc = _doc(
        _canonical_task("TASK-1", "first"),
        "\n",
        _canonical_task("TASK-2", "second"),
    )
    r, text = _close(tmp_path, doc)
    assert "- [x] **TASK-1**: first" in text, text
    assert "- [x] **TASK-2**: second" in text, text
    assert "2 tasks closed)." in r.stdout, r.stdout
    for marker in ("held open", "protects nothing", "NOT recognised"):
        assert marker not in r.stdout + r.stderr, (marker, r.stdout, r.stderr)


# ── Survivors the round's independent battery found ───────────────────
#
# Lens 3 designed its own battery and killed 15 of 28 rows against this phase's
# author-side 25/25. Applying all 13 survivors at once left the whole suite
# byte-identical, i.e. no test anywhere caught any of them. These are the ones
# with a live path.


class TestDetachedNearMiss:
    def test_a_detached_near_miss_is_reported(self, tmp_path):
        """The near-miss fix was incomplete, and the round proved it.

        `nmnr` is only ever set while a task is pending. A `> Fail:` sitting
        after a blank line, after a heading, or before any task therefore
        produced NO evidence — while a well-formed `> Failed:` in that same
        position produced ORPHAN. So a malformed detached annotation was
        byte-identical to a clean close, which is exactly the invariant this
        script's header states, and exactly what the previous round fix claimed
        to have closed "both directions".
        """
        doc = _doc(
            _canonical_task("TASK-1", "one"),
            "\n",
            "> Fail: detached and unrecognised\n",
        )
        r, text = _close(tmp_path, doc)
        assert "- [x] **TASK-1**: one" in text, text
        assert "was NOT recognised, AND is attached to no open task" in r.stdout, r.stdout
        assert "Annotations protecting nothing: 1" in r.stdout, r.stdout

    def test_a_detached_near_miss_before_any_task_is_reported(self, tmp_path):
        doc = _doc(
            "> Fail: before any task at all\n",
            "\n",
            _canonical_task("TASK-1", "one"),
        )
        r, _ = _close(tmp_path, doc)
        assert "attached to no open task" in r.stdout, r.stdout

    def test_a_detached_dropped_line_still_produces_no_noise(self, tmp_path):
        """The control. Widening what counts as annotation-shaped must not start
        firing on `> Dropped:`, which is a legitimate verdict."""
        doc = _doc(
            _canonical_task("TASK-1", "one"),
            "\n",
            "> Dropped: premise was wrong\n",
        )
        r, _ = _close(tmp_path, doc)
        for marker in ("protects nothing", "NOT recognised"):
            assert marker not in r.stdout + r.stderr, (marker, r.stdout)


class TestTheCountersAreNotTheConstantOne:
    """Every assertion on both summary counters used the value 1, so `= 1` was
    indistinguishable from the real count — in a line that exists precisely
    because per-line warnings scroll and a summary does not."""

    def test_two_orphans_are_counted_as_two(self, tmp_path):
        doc = _doc(
            _canonical_task("TASK-1", "one"),
            "\n",
            "> Failed: detached one\n",
            "\n",
            "> Failed: detached two\n",
        )
        r, _ = _close(tmp_path, doc)
        assert "Annotations protecting nothing: 2" in r.stdout, r.stdout

    def test_two_near_misses_are_counted_as_two(self, tmp_path):
        doc = _doc(
            _canonical_task("TASK-1", "one"),
            "  > Fail: first\n",
            "\n",
            _canonical_task("TASK-2", "two"),
            "  > Failure: second\n",
        )
        r, _ = _close(tmp_path, doc)
        assert "Failure-note near misses not honoured: 2" in r.stdout, r.stdout


class TestAcceptanceOfATaskLine:
    def test_an_already_closed_task_is_not_counted_again(self, tmp_path):
        """`is_open_task` must not accept `- [x]`. Widening it to `^- \\[`
        re-counts a done task as newly closed, so the Grand Total drifts by one
        on every close — silently, because the file already looks right."""
        doc = (
            "# Review Tasks\n\n"
            "### Batch 1 — Mixed `Pending`\n\n"
            + _canonical_task("TASK-1", "open one")
            + "- [x] **TASK-2**: already done\n"
            + "  `src/b.py:2` `[verified]` — already finished last round\n"
            + "\n## Statistics\n\n**Grand Total** — 6 done, 2 open\n"
        )
        repo = _repo(tmp_path / "repo", doc)
        r = _run(repo, "1")
        assert "1 tasks closed" in r.stdout, r.stdout
        text = (repo / "review_tasks.md").read_text()
        assert "7 done, 1 open" in text, text
