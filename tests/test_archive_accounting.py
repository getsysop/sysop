"""Content deleted from review_tasks.md that the archive never receives (Q-116, Phase 208).

`parse_archivable_batches` closes the current batch on a bare `---` — the
documented inter-batch separator — so anything between that separator and the
next `### Batch` header belongs to no batch. For an `all_merged` round,
`update_review_tasks` deletes the round's whole line range while
`build_archive_block` re-emits only header + preamble + batches. The orphaned
content is removed from `review_tasks.md` and never written to the archive.

The round-level instance of this already had a targeted fix: the `preamble`
capture (Phase 149) exists because the same gap swallowed the Tier-0 coverage
ledger. Only the half that had bitten someone was closed. This is the general
form.

**Why a residue check and not "every line accounted for".** The emitter drops
two shapes on purpose — the `---` separator it consumes without re-emitting, and
each batch's trailing blank lines. A strict check therefore reports those as
losses. `archive_review_tasks.py` has no `--force`, so one false positive makes
the archive path unusable. Measured on every real tracker on this machine with
an archivable round (BeanRider: 3 rounds / 591 deleted lines; a second
internal tracker: 1 round / 202), the residue check reports **0** on both — that is what
`test_real_consumer_corpora_produce_no_residue` pins.
"""
import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core/companion/scripts/archive_review_tasks.py"


def _load():
    spec = importlib.util.spec_from_file_location("arc_under_test", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


arc = _load()


# The exact shape Q-116 reports: a task and its annotation placed AFTER the
# `---` separator, before the next batch header.
ORPHANED = """\
# Review Tasks

## Round 1 — Example

### Batch 1 — First `Merged`

- [x] **TASK-1**: done

---

- [ ] **TASK-9**: THE ORPHAN
  > Failed: never ran

### Batch 2 — Second `Merged`

- [x] **TASK-2**: done

## Statistics
"""

CLEAN = """\
# Review Tasks

## Round 1 — Example

### Batch 1 — First `Merged`

- [x] **TASK-1**: done

---

### Batch 2 — Second `Merged`

- [x] **TASK-2**: done

## Statistics
"""


def _residue(doc: str):
    lines = doc.splitlines()
    rounds = arc.parse_archivable_batches(lines)
    archivable = [r for r in rounds if r.get("all_merged")]
    block = arc.build_archive_block(archivable)
    return arc.unaccounted_lines(lines, archivable, block), archivable


def test_the_orphaned_task_between_separator_and_next_batch_is_detected():
    residue, archivable = _residue(ORPHANED)
    assert archivable, "fixture produced no archivable round — the case is vacuous"
    assert "- [ ] **TASK-9**: THE ORPHAN" in residue, residue
    assert "> Failed: never ran" in " ".join(residue), residue


def test_a_round_with_nothing_orphaned_produces_no_residue():
    """The control. Without it, a check that flags everything looks identical to
    a check that flags the right thing."""
    residue, archivable = _residue(CLEAN)
    assert archivable, "fixture produced no archivable round — the case is vacuous"
    assert residue == [], residue


# Every residue line in ORPHANED is interior to the range, unique, and
# prefix-unique — so a whole family of loosenings is a no-op against it. The
# round demonstrated three that leave the module green: membership instead of
# multiset, a 4-character prefix match, and `lines[start:end - 1]`. Each fixture
# below is built to be the one thing ORPHANED is not.

# Residue that DUPLICATES a line the archive block legitimately emits. Kills
# membership-instead-of-multiset accounting.
ORPHAN_DUPLICATES_AN_EMITTED_LINE = ORPHANED.replace(
    "- [ ] **TASK-9**: THE ORPHAN\n  > Failed: never ran",
    "- [x] **TASK-1**: done",
)

# Residue sharing a long prefix with an emitted line. Kills prefix matching.
ORPHAN_SHARES_A_PREFIX = ORPHANED.replace(
    "- [ ] **TASK-9**: THE ORPHAN\n  > Failed: never ran",
    "- [x] **TASK-1**: done but this copy is orphaned",
)

# A SINGLE orphaned line, on the round range's final line. Kills both a
# `len(orphaned) > 1` threshold and an `end - 1` truncation — ORPHANED has two
# residue lines, neither of them last, so it sees neither.
ORPHAN_IS_ONE_LINE_AT_THE_END = """\
# Review Tasks

## Round 1 — Example

### Batch 1 — First `Merged`

- [x] **TASK-1**: done

---

- [ ] **TASK-9**: THE ONLY ORPHAN, AND THE RANGE'S LAST LINE
## Statistics
"""


def test_residue_survives_the_loosenings_the_base_fixture_cannot_see():
    """One assertion per shape the base corpus is blind to."""
    for name, doc, expected in (
        ("duplicates-an-emitted-line", ORPHAN_DUPLICATES_AN_EMITTED_LINE,
         "- [x] **TASK-1**: done"),
        ("shares-a-prefix", ORPHAN_SHARES_A_PREFIX,
         "- [x] **TASK-1**: done but this copy is orphaned"),
        ("single-line-at-the-range-end", ORPHAN_IS_ONE_LINE_AT_THE_END,
         "- [ ] **TASK-9**: THE ONLY ORPHAN, AND THE RANGE'S LAST LINE"),
    ):
        residue, archivable = _residue(doc)
        assert archivable, f"{name}: no archivable round — the case is vacuous"
        assert expected in residue, (
            f"{name}: the orphaned line was accounted for by coincidence.\n"
            f"residue={residue}"
        )


def test_a_single_orphaned_line_is_enough_to_refuse():
    """Pins the threshold at 'any', not 'more than one'.

    `if len(orphaned) > 1` leaves the module green against the two-line base
    fixture while losing a single line silently — and one line is a whole task.
    """
    residue, _ = _residue(ORPHAN_IS_ONE_LINE_AT_THE_END)
    assert len(residue) == 1, f"fixture no longer isolates a single line: {residue}"


def test_the_separator_and_blank_lines_are_the_only_exemptions():
    """Pins the exempt set itself. Widening it to swallow, say, `>` lines would
    silently re-open the Phase 149 ledger loss this check generalises."""
    assert arc._ACCOUNTING_EXEMPT == frozenset({"", "---"}), arc._ACCOUNTING_EXEMPT


# Sibling checkouts of this repo, DERIVED rather than written down. An earlier
# cut hardcoded two absolute paths here and put the author's home directory plus
# two private project names into a file the public mirror ships —
# `test_mirror_leak_gate.py::test_pass_1b_no_absolute_home_paths` is a
# MUST-be-empty gate and went red. It reads git-TRACKED files, so it could not
# see the leak until the commit that introduced it, which is why several
# full-suite runs came back clean beforehand.
def _sibling_trackers():
    return sorted(REPO_ROOT.parent.glob("*/review_tasks.md"))


@pytest.mark.parametrize("tracker", _sibling_trackers() or [None])
def test_real_consumer_corpora_produce_no_residue(tracker):
    """The false-positive budget is zero: there is no `--force` on this path.

    Skipped rather than failed when no sibling checkout is present — these are
    working checkouts, not fixtures, and CI has none.
    """
    if tracker is None or not tracker.is_file():
        pytest.skip("no sibling review_tasks.md checkout on this machine")
    lines = tracker.read_text(encoding="utf-8", errors="replace").splitlines()
    rounds = arc.parse_archivable_batches(lines)
    archivable = [r for r in rounds if r.get("all_merged")]
    if not archivable:
        pytest.skip("no archivable round in this corpus")
    block = arc.build_archive_block(archivable)
    residue = arc.unaccounted_lines(lines, archivable, block)
    assert residue == [], f"{len(residue)} false positive(s): {residue[:5]}"


def test_both_remedies_the_refusal_prescribes_actually_clear_it():
    """Run the instructions, do not just print them.

    The first wording said "move it above the round's first batch header where
    the preamble capture will carry it". That capture is blockquote-only, so
    following it literally with plain prose still refused — a dead end on a path
    with no `--force`. Both remedies the message now names are executed here.
    """
    inside = ORPHANED.replace(
        "---\n\n- [ ] **TASK-9**: THE ORPHAN\n  > Failed: never ran\n\n",
        "- [ ] **TASK-9**: THE ORPHAN\n  > Failed: never ran\n\n---\n\n",
    )
    assert inside != ORPHANED, "remedy 1 fixture did not change"
    assert _residue(inside)[0] == [], f"remedy 1 (move inside a batch) still refuses: {_residue(inside)[0]}"

    as_preamble = ORPHANED.replace(
        "---\n\n- [ ] **TASK-9**: THE ORPHAN\n  > Failed: never ran\n\n",
        "---\n\n",
    ).replace(
        "## Round 1 — Example\n\n",
        "## Round 1 — Example\n\n> a promoted convention\n> and its rationale\n\n",
    )
    assert as_preamble != ORPHANED, "remedy 2 fixture did not change"
    assert _residue(as_preamble)[0] == [], (
        f"remedy 2 (blockquote in the round preamble) still refuses: {_residue(as_preamble)[0]}"
    )


def test_plain_prose_in_the_preamble_position_is_still_orphaned():
    """The reason the remedy names blockquotes specifically.

    Kept as a control so nobody 'simplifies' the message back to 'move it above
    the first batch header' — that is only true for `> ` lines.
    """
    prose = ORPHANED.replace(
        "---\n\n- [ ] **TASK-9**: THE ORPHAN\n  > Failed: never ran\n\n", "---\n\n"
    ).replace(
        "## Round 1 — Example\n\n", "## Round 1 — Example\n\na promoted convention\n\n"
    )
    residue, _ = _residue(prose)
    assert "a promoted convention" in residue, (
        "plain prose above the first batch header is now accounted for — if the "
        "preamble capture has widened, the refusal's remedy text should widen too"
    )


def test_the_run_refuses_when_exactly_one_line_would_be_lost(tmp_path):
    """End to end at the threshold.

    The function-level fixture proves the residue is one line; only this proves
    the RUN refuses on it. Without this, `if orphaned:` → `if len(orphaned) > 1:`
    leaves everything green while losing a whole task silently.
    """
    r, before_tasks, before_archive, repo = _run_archiver(tmp_path, ORPHAN_IS_ONE_LINE_AT_THE_END)
    assert r.returncode != 0, f"a single-line loss archived silently\n{r.stdout}\n{r.stderr}"
    assert "refusing to archive" in r.stderr, r.stderr
    assert "THE ONLY ORPHAN" in r.stderr, r.stderr
    assert (repo / "review_tasks.md").read_text() == before_tasks
    assert (repo / "review_tasks_archive.md").read_text() == before_archive


def _run_archiver(tmp_path, doc: str):
    repo = tmp_path / f"repo{abs(hash(doc)) % 10000}"
    (repo / "sysop" / "scripts").mkdir(parents=True)
    (repo / "review_tasks.md").write_text(doc)
    (repo / "review_tasks_archive.md").write_text(
        "# Archive\n\n## Grand Total\n\n| Round | Tasks |\n|---|---|\n"
    )
    for helper in ("archive_review_tasks.py", "_log.py"):
        src = REPO_ROOT / "core/companion/scripts" / helper
        if src.is_file():
            (repo / "sysop" / "scripts" / helper).write_text(src.read_text())
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(repo)],
                   check=True, capture_output=True)
    before_tasks = (repo / "review_tasks.md").read_text()
    before_archive = (repo / "review_tasks_archive.md").read_text()
    r = subprocess.run(["python3", "sysop/scripts/archive_review_tasks.py"],
                       cwd=str(repo), capture_output=True, text=True)
    return r, before_tasks, before_archive, repo


def test_the_run_refuses_and_writes_nothing(tmp_path):
    """End to end: the refusal must land BEFORE either file is touched."""
    repo = tmp_path / "repo"
    (repo / "sysop" / "scripts").mkdir(parents=True)
    (repo / "review_tasks.md").write_text(ORPHANED)
    (repo / "review_tasks_archive.md").write_text(
        "# Archive\n\n## Grand Total\n\n| Round | Tasks |\n|---|---|\n"
    )
    for helper in ("archive_review_tasks.py", "_log.py"):
        src = REPO_ROOT / "core/companion/scripts" / helper
        if src.is_file():
            (repo / "sysop" / "scripts" / helper).write_text(src.read_text())
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(repo)],
                   check=True, capture_output=True)

    before_tasks = (repo / "review_tasks.md").read_text()
    before_archive = (repo / "review_tasks_archive.md").read_text()

    r = subprocess.run(
        ["python3", "sysop/scripts/archive_review_tasks.py"],
        cwd=str(repo), capture_output=True, text=True,
    )

    assert r.returncode != 0, f"the archive ran despite orphaned content\n{r.stdout}\n{r.stderr}"
    assert "refusing to archive" in r.stderr, r.stderr
    assert "THE ORPHAN" in r.stderr, r.stderr
    assert (repo / "review_tasks.md").read_text() == before_tasks, "review_tasks.md was mutated"
    assert (repo / "review_tasks_archive.md").read_text() == before_archive, "archive was mutated"
