"""Phase 235 (`Q-235` leg #436): the `solo:` field and `/auto-build` Step 2 invariant `d.`

`solo: true` declares that a task mutates state shared *outside* the filesystem view — a
global lockfile, a singleton registry, a live schema, a shared fixture corpus — so it must
not batch with anything, even work whose paths are disjoint from it. That property is not
derivable from the tree: `blast_radius` grades surface area and `scope_overlap.py` grades
path overlap, and neither can see it.

The reader is skill prose with no runtime surface, so these are drift guards. They pin the
three things a later edit is most likely to get wrong:

1. **The letters.** `a.`/`b.`/`c.` must not be renumbered — the K=12 provenance note cites
   `a.` and `b.` by letter, and `schema.md` § Solo cites `d.`. Inserting `solo` as a new `b.`
   would silently repoint two prose citations at the wrong rule.
2. **Invariant `b.` must survive.** It is the hardcoded special case of the same property
   (SQL migrations, found by body-text grep). Deleting it as "superseded by `solo:`" would
   silently unprotect every existing task that relies on it and never declares the field.
3. **The non-overlap.** `solo` and `blast_radius: architectural` grade different things. If
   the schema stops saying so, the next reader collapses them and the field becomes a second
   way to spell `architectural`.
"""
from __future__ import annotations

import re
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _prose_guard_helpers import section, states  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTO_BUILD = REPO_ROOT / "core" / "skills" / "auto-build" / "SKILL.md"
ADD_TASK = REPO_ROOT / "core" / "skills" / "add-task" / "SKILL.md"
TASKS_README = REPO_ROOT / "core" / "companion" / "tasks" / "README.md"
SCHEMA = REPO_ROOT / "core" / "companion" / "tasks" / "schema.md"
VALIDATOR = REPO_ROOT / "core" / "companion" / "scripts" / "validate_tasks.py"


def _solo_invariant_block() -> str:
    """The fenced `Solo invariants` list inside Step 2's batch-sizing pseudocode."""
    text = AUTO_BUILD.read_text(encoding="utf-8")
    # assert rather than let str.index raise — a reworded heading should produce this
    # guard's message, not a bare ValueError traceback (the round flagged four such sites).
    assert "1. Solo invariants" in text, "the Solo invariants block is gone or renamed"
    start = text.index("1. Solo invariants")
    assert "2. Cross-module cap" in text[start:], "the Cross-module cap rule is gone or renamed"
    end = text.index("2. Cross-module cap", start)
    return text[start:end]


def _invariant_d_note() -> str:
    """Invariant `d.`'s own bracket note, not the whole block.

    The round satisfied `"stays" or "Retained"` from invariant **c.**'s unrelated
    "Retained for correctness/headroom" and rewrote `d.`'s note freely underneath.
    """
    block = _solo_invariant_block()
    assert "   d. " in block, "invariant d. is gone"
    note = block[block.index("   d. "):]
    end = note.find("\n   [")          # the next un-lettered bracket note ends it
    return note if end == -1 else note[:end]


def test_all_four_solo_invariants_are_present_and_lettered_in_order():
    block = _solo_invariant_block()
    letters = re.findall(r"^\s{3}([a-z])\. ", block, re.MULTILINE)
    assert letters == ["a", "b", "c", "d"], (
        f"solo invariants are {letters}, expected a/b/c/d in order — renumbering breaks the "
        "K=12 provenance note (cites `a.`, `b.`) and schema.md § Solo (cites `d.`)"
    )


def test_invariant_a_is_still_architectural_and_b_is_still_migrations():
    block = _solo_invariant_block()
    a_line = re.search(r"^\s{3}a\. (.+)$", block, re.MULTILINE).group(1)
    b_line = re.search(r"^\s{3}b\. (.+)$", block, re.MULTILINE).group(1)
    assert "architectural" in a_line, a_line
    assert "migrations/" in b_line and "ALTER TABLE" in b_line, b_line


def test_invariant_d_reads_the_solo_field():
    block = _solo_invariant_block()
    m = re.search(r"^\s{3}d\. (.+)$", block, re.MULTILINE)
    assert m is not None, "invariant d. has no lettered line"
    d_line = m.group(1)
    # `"solo" in line and "true" in line` was satisfied by "solo == true is NOT a solo
    # condition ... true also means no", which inverts the rule while staying green.
    assert states(d_line, "solo == true"), f"invariant d. does not assert the condition: {d_line}"
    assert not re.search(r"\bnot a solo\b|\bEXEMPT\b|\balias\b", d_line, re.IGNORECASE), (
        f"invariant d. is written as an exemption rather than a solo condition: {d_line}"
    )


def test_invariant_d_states_that_absence_means_no():
    """The field is optional and almost every task lacks it; the fail-safe direction is the
    whole reason a type-guard-only validator check is honest."""
    d_section = _invariant_d_note()
    assert re.search(r"absent/false means no|absent or false", d_section, re.IGNORECASE), d_section


def test_invariant_b_is_not_described_as_superseded():
    """`solo:` generalizes `b.`; it does not replace it. A task relying on the migrations
    heuristic without declaring the field must keep its protection."""
    forbidden = re.compile(r"supersed|replaces `?b\.?`?|instead of `?b\.?`?", re.IGNORECASE)

    note = _invariant_d_note()
    assert "stays" in note, (
        "invariant d.'s note no longer says `b.` stays — the round satisfied this from "
        "invariant c.'s unrelated 'Retained for correctness/headroom'"
    )
    assert not forbidden.search(note), (
        "invariant b. is described as superseded in auto-build/SKILL.md — it is the hardcoded "
        "special case and must keep firing for tasks that never declare `solo:`"
    )

    # And in schema.md § Solo, which states the same relationship for the reader who never
    # opens the skill. The author battery's B03 rewrote exactly this sentence and survived,
    # because the first cut of this guard read the auto-build block alone.
    sec = section(SCHEMA.read_text(encoding="utf-8"), "### Solo")
    assert states(sec, "`b.` **stays**"), "schema.md § Solo no longer says invariant `b.` stays"
    assert not forbidden.search(sec), "schema.md § Solo describes invariant b. as superseded"
    assert not re.search(r"\bredundant\b|should be deleted", sec, re.IGNORECASE), (
        "schema.md § Solo argues for deleting invariant b. without using the word 'supersede'"
    )


def test_schema_documents_solo_as_an_optional_bool_field():
    schema = SCHEMA.read_text(encoding="utf-8")
    rows = [l for l in schema.splitlines() if l.startswith("| `solo`")]
    assert len(rows) == 1, f"expected exactly one `solo` field row, got {len(rows)}"
    cells = [c.strip() for c in rows[0].strip("|").split("|")]
    assert cells[1] == "bool", cells
    assert cells[2] == "no", f"`solo` must stay optional — required would break every existing task: {cells}"


def test_schema_states_the_non_overlap_with_blast_radius():
    sec = section(SCHEMA.read_text(encoding="utf-8"), "### Solo")
    assert states(sec, "not a restatement of `blast_radius`"), (
        "schema.md § Solo no longer asserts the non-overlap (or asserts it inside a negation)"
    )
    # Both halves must survive, and on the correct sides. The round swapped the table's two
    # cells — leaving both keywords present while saying blast_radius grades serialization.
    row = next((l for l in sec.splitlines() if l.startswith("| Grades")), None)
    assert row is not None, "schema.md § Solo lost its Grades row"
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert "surface area" in cells[1], f"blast_radius must grade surface area: {row}"
    assert "serialization" in cells[2], f"solo must grade serialization: {row}"
    assert not re.search(r"\bequivalent in\b|\balias\b|\bexactly when\b", sec, re.IGNORECASE), (
        "schema.md § Solo argues the two fields are interchangeable"
    )


def test_schema_solo_section_is_not_inside_a_fence():
    """The `### User ops` defect was a citation resolving to a line inside the fenced body
    template. Do not repeat it for `### Solo`."""
    schema = SCHEMA.read_text(encoding="utf-8")
    assert schema.count("```", 0, schema.index("\n### Solo\n")) % 2 == 0


def test_validator_type_guards_solo_and_says_so():
    src = VALIDATOR.read_text(encoding="utf-8")
    assert "def _check_solo(" in src
    assert "_check_solo(task, loc_id, report)" in src, "_check_solo is defined but never called"
    assert "'solo' must be bool" in src


def test_a_worked_example_demonstrates_a_non_architectural_solo():
    """Example I is the one that shows `d.` reaching a case `a.`/`b.`/`c.` structurally
    cannot — a Low/single-file task that still must run alone."""
    text = AUTO_BUILD.read_text(encoding="utf-8")
    # Exact heading, not a prefix. The author battery's B09 renamed the example to
    # `Example I-disabled` and survived, because `startswith("- **Example I")` still
    # matched it — a guard keyed to a prefix accepts every extension of that prefix.
    heading = "- **Example I (`solo: true`)** —"
    matches = [l for l in text.splitlines() if l.startswith(heading)]
    assert len(matches) == 1, (
        f"expected exactly one `{heading}` line, found {len(matches)} — the worked example "
        "that demonstrates invariant `d.` is renamed or gone"
    )
    line = matches[0]
    assert "solo: true" in line, line
    assert "single-file" in line, line
    assert "Low" in line, line


def test_the_authoring_surfaces_do_not_teach_solo_as_a_blast_radius_alias():
    """`add-task/SKILL.md` and `tasks/README.md` carry the `solo` contract to consumers, and
    the round found NOTHING reading either — so both could describe the field as an alias for
    `blast_radius: architectural` with every other guard green. `README.md`'s template is the
    shape consumers copy by hand, which makes it the highest-leverage place to get wrong.
    """
    add_task = ADD_TASK.read_text(encoding="utf-8")
    i = add_task.index("- **`solo`**")
    bullet = add_task[i: add_task.find("\n- **", i + 1)]
    assert states(bullet, "not** a restatement of `blast_radius: architectural`"), (
        "add-task no longer distinguishes `solo` from `blast_radius`"
    )
    assert "name the shared state" in bullet, (
        "add-task lost the test that keeps `solo` from becoming an importance flag"
    )

    readme = TASKS_README.read_text(encoding="utf-8")
    row = next((l for l in readme.splitlines() if l.strip().startswith("solo:")), None)
    assert row is not None, "the tasks/README.md entry template no longer carries `solo:`"
    assert "false" in row, f"the template must default `solo` to false: {row}"
    assert not re.search(r"\balias\b|same as|equivalent", row, re.IGNORECASE), (
        f"the template describes `solo` as a `blast_radius` alias: {row}"
    )
