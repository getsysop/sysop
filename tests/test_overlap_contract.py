"""Phase 192 — the `Overlap:` writer-side contract (upstream #366).

`> **Overlap:**` drives `/auto-fix`'s and `/auto-judge`'s two-lane split
(parallel vs sequential) off a value that **nothing validates**. Before this
phase the field had: no write-time check, no stated reader-side default, and
three renderings of its non-`none` case across the tree (the generators'
`batch-N, batch-M`, `WORKFLOW.md`'s "conflicting batch numbers", and bare
numbers in `/auto-fix`'s own plan table, which disagreed with the prefixed form
in the same skill's deferred table 400 lines later).

The consequence the reporter measured was a lane assignment made on an
unchecked value. The mechanism this phase closes is the reader half: the rule
was stated as "batches with `Overlap: none`", which admits two opposite
readings. `> **Overlap:** none (batch 5 shares tests/)` routes to *parallel*
under a substring read and *sequential* under a whole-value read — and parallel
is the unsafe direction, because it puts two agents on files that really do
collide.

WHAT THIS FILE CAN AND CANNOT TEST — read before adding to it.

`Overlap:`'s readers are **prose instructions to an agent**, not code. There is
no function to call, so no test here can prove an agent *complies* with the
whole-value rule; the presence checks below prove only that the rule is stated
at every site that routes on the field. That is a real limit and it is the same
one Phase 188's guard docstring records for its own class. What IS executed
here is `review_index.py` — the field's only actual parser — and the point of
executing it is to prove a NEGATIVE the contract asserts: it validates nothing
and normalises nothing, so no reader may treat the shadow index as a check.

The other half — a tag that is **present and wrong** — was left open by Phase
192 and closed by bundle B-6 (`Q-042`): both routers now recompute overlap on
every run (their Step 1e) over every open batch, route a batch to the parallel
lane only when the tag is exactly `none` AND the recompute is `none`, show any
disagreement in the run's tables, and never write the recompute back. §4 pins
that text; like §3 it can prove the rule is stated, not that an agent obeys it.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _line_with(path: Path, needle: str) -> str:
    """The single line carrying `needle`, or an assertion failure.

    Phase 192's round found the whole `#366` guard class defeatable because
    every check was `needle in text` — file-scoped. A file-scoped check cannot
    tell WHICH bullet a phrase sits in, so the two routing lanes could be
    swapped outright, an exception could be carved out of the fail-safe
    default, and the whole-value rule could be moved 350 lines away from the
    step that routes on it, all with every asserted phrase still present. 12 of
    13 such inversions shipped green. Scope every rule assertion to the line
    that carries the rule.
    """
    hits = [ln for ln in path.read_text(encoding="utf-8").splitlines() if needle in ln]
    assert len(hits) == 1, (
        f"{path.name}: expected exactly one line containing {needle!r}, got {len(hits)}"
    )
    return hits[0]


WORKFLOW = REPO_ROOT / "core/companion/docs/WORKFLOW.md"
GENERATORS = {
    "codebase-review": REPO_ROOT / "core/skills/codebase-review/SKILL.md",
    "security-audit": REPO_ROOT / "core/skills/security-audit/SKILL.md",
}
ROUTERS = {
    "auto-fix": REPO_ROOT / "core/skills/auto-fix/SKILL.md",
    "auto-judge": REPO_ROOT / "core/skills/auto-judge/SKILL.md",
}
TRIAGE = REPO_ROOT / "core/skills/triage/SKILL.md"

sys.path.insert(0, str(REPO_ROOT / "core/companion/scripts"))


# ── §1 the index parses but does not validate (executed) ────────────────────


def _parse_overlap(value: str) -> str:
    """Run the real `review_index.py` parser over a one-batch tracker."""
    import review_index as ri

    d = Path(tempfile.mkdtemp())
    p = d / "review_tasks.md"
    p.write_text(
        "# T\n\n## Round 1 — 2026-08-12\n\n"
        "### Batch 1 — B `Pending`\n> **Branch:** `review/b`\n"
        f"> **Overlap:** {value}\n\n- [ ] **TASK-1**: t 🟢\n",
        encoding="utf-8",
    )
    return ri.parse_review_tasks(p)["batches"]["1"]["overlap"]


# Every shape a tracker can carry, and what the whole-value rule makes of it.
# `parallel_ok` is the CONTRACT's verdict, not the parser's — the parser has no
# verdict, which is what §1 exists to prove.
_SHAPES = [
    ("none", True),
    ("batch-1, batch-2", False),
    ("none (batch 5 shares tests/)", False),   # the reporter's mechanism
    ("1, 2", False),                           # an undeclared rendering
    ("none ", True),                           # trimmed before comparison
    ("None", False),                           # case is part of the literal
    ("TBD", False),
    ("", False),
]


def test_the_index_stores_every_shape_verbatim_and_validates_nothing():
    """The contract says the shadow index is not a check. This proves it.

    A future author who adds validation *here* must also update
    `WORKFLOW.md` § Batch metadata fields, which tells readers this parse is
    not validation — the routers' own recompute is the only check.
    """
    for value, _ in _SHAPES:
        assert _parse_overlap(value) == value, (
            f"review_index.py altered {value!r} — the contract states it "
            "stores the value verbatim and validates nothing"
        )


def test_the_whole_value_rule_separates_none_from_its_look_alikes():
    """The predicate the prose asks readers to apply, applied here to the
    parser's actual output. `none (batch 5 shares tests/)` is the value that
    motivated #366's serialisation half: it must NOT read as `none`."""
    for value, parallel_ok in _SHAPES:
        stored = _parse_overlap(value)
        assert (stored.strip() == "none") is parallel_ok, (
            f"{value!r}: whole-value test disagrees with the contract"
        )


def test_a_substring_reader_would_route_the_qualified_value_the_unsafe_way():
    """The defect, stated as an executable contrast rather than an assertion
    about prose. A substring reader sends a genuinely-overlapping batch to the
    parallel lane; the whole-value reader sends it to the sequential one. The
    two disagree, and the substring answer is the one that costs a conflict."""
    stored = _parse_overlap("none (batch 5 shares tests/)")
    assert "none" in stored, "fixture must reproduce the substring match"
    assert stored.strip() != "none", "the whole-value test must reject it"


# ── §2 one declared grammar across writers, readers and templates ───────────


def test_the_two_declared_shapes_are_what_the_generators_emit():
    """Both generators are the field's only writers. Their Step 4b must emit
    the two shapes `WORKFLOW.md` declares — the literal `none`, and a
    `batch-<N>` list. This is the grammar split that had three renderings.

    The ANTECEDENT is asserted, not just the arrow. The round swapped the two
    condition→value lines so the sole writer emitted `none` for batches that
    DO share files, and the earlier version of this test passed because it
    only looked for the two arrow fragments.
    """
    row = _line_with(WORKFLOW, "| `Overlap` |")
    assert "`none` \\| `batch-N, batch-M`" in row, (
        "WORKFLOW.md's Overlap row no longer declares the grammar"
    )
    for forbidden in ("free text", "any other shape", "or similar"):
        assert forbidden not in row, (
            f"the declared grammar admits {forbidden!r} — it is not a grammar"
        )
    for name, path in GENERATORS.items():
        text = path.read_text(encoding="utf-8")
        none_line = _line_with(path, "→ `Overlap: none`")
        assert "No shared files" in none_line, (
            f"{name}: `Overlap: none` is emitted for the wrong condition — "
            f"the sole writer's mapping is inverted: {none_line!r}"
        )
        list_line = _line_with(path, "→ `Overlap: batch-N, batch-M`")
        assert "Shares file(s)" in list_line, (
            f"{name}: the batch-list value is emitted for the wrong "
            f"condition: {list_line!r}"
        )
        assert "> **Overlap:** <none | batch-N, batch-M>" in text, (
            f"{name}: the emitted template disagrees with the declared grammar"
        )


def test_no_surface_still_advertises_the_retired_rendering():
    """`<conflicting batch numbers, or "none">` was the shape `WORKFLOW.md`'s
    two batch templates showed while the generators wrote `batch-N`. A reader
    who followed the doc produced a value the declared grammar does not
    contain."""
    for path in (WORKFLOW, *GENERATORS.values(), *ROUTERS.values()):
        text = path.read_text(encoding="utf-8")
        assert "conflicting batch numbers" not in text, (
            f"{path.name}: the retired Overlap rendering is back"
        )
        # Banning ONE retired phrase is not the property. The round reverted
        # WORKFLOW's templates to `<comma-separated batch numbers, or "none">`
        # — a different wording of the same defect — and this test passed.
        # Assert every template renders the declared form instead.
        for tpl in [ln for ln in text.splitlines()
                    if ln.startswith("> **Overlap:** <")]:
            assert tpl == "> **Overlap:** <none | batch-N, batch-M>", (
                f"{path.name}: an Overlap template renders a shape outside "
                f"the declared grammar: {tpl!r}"
            )

    # And the plan tables, the intra-skill half of the split: `/auto-fix`
    # rendered bare numbers in its plan table while its own deferred table 400
    # lines later used the prefixed form.
    for name, path in ROUTERS.items():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if not ln.startswith(("| 201 ", "| 202 ", "| 424 ")):
                continue
            cells = [c.strip() for c in ln.split("|")]
            # Any cell after the batch number that is itself a bare 3-digit
            # batch number is an Overlap column rendered in the retired shape.
            bare = [c for c in cells[3:] if c.isdigit() and len(c) == 3]
            assert not bare, (
                f"{name}: a plan-table row renders a bare batch number "
                f"{bare} in an Overlap column: {ln!r}"
            )


def test_the_workflow_reader_table_names_every_reader():
    """The row named only `/auto-fix` while three surfaces read the field. The
    adjacent `Flag`/`Triaged` rows enumerate all of theirs, so this one
    under-declared by two — and an under-declared row is what lets a fourth
    reader be added without anyone noticing the contract has more parties."""
    row = [ln for ln in WORKFLOW.read_text(encoding="utf-8").splitlines()
           if ln.startswith("| `Overlap`")]
    assert len(row) == 1, f"expected exactly one Overlap row, got {len(row)}"
    for reader in ("/auto-fix", "/auto-judge", "/triage", "review_index.py"):
        assert reader in row[0], f"the Overlap row does not name {reader}"


# ── §3 the rule is stated where the routing happens ─────────────────────────
#
# Presence checks. They prove the rule is STATED at each routing site, never
# that an agent followed it — see this module's docstring. They exist because
# the pre-phase text ("batches with `Overlap: none`") was ambiguous at exactly
# these three sites, and an ambiguity is only fixed where it is read.


def test_both_routers_bind_the_exact_none_test_to_the_NON_merge_lane():
    """Line-scoped, because file-scoped could not see the lanes swapped.

    The round swapped which mode owns which bullet — so the default parallel
    pass took exactly the batches that DO collide, strictly worse than the
    ambiguity this phase set out to fix — and every asserted phrase was still
    in the file. The binding that matters is `exactly none` ↔ the bullet
    WITHOUT `--merge`; assert that pairing on one line.
    """
    for name, path in ROUTERS.items():
        exact = _line_with(path, "is **exactly** `none`")
        assert exact.startswith("- **Without `--merge`**"), (
            f"{name}: the `exactly none` test is not bound to the non-merge "
            f"lane — the lanes may be swapped. Line was: {exact!r}"
        )
        other = _line_with(path, "every other batch")
        assert other.startswith("- **With `--merge`**"), (
            f"{name}: the not-none lane is not bound to --merge. Line: {other!r}"
        )
        assert "trimmed of surrounding whitespace" in exact, (
            f"{name}: the whole-value test no longer says it trims"
        )


def test_neither_router_carves_an_exception_out_of_the_fail_safe():
    """The round kept the fail-safe sentence and added an exception under it
    that returned the reporter's motivating value to the parallel lane. The
    sentence's presence is not the property worth pinning — its
    unconditionality is."""
    for name, path in ROUTERS.items():
        default = _line_with(path, "Anything you cannot parse counts as overlapping")
        assert "costs a merge conflict" in default, (
            f"{name}: the safe default lost the asymmetry that justifies it, "
            "so a future author will read it as arbitrary"
        )
        low = default.lower()
        for weasel in ("exception", "unless", "except when", "is enough"):
            assert weasel not in low, (
                f"{name}: the fail-safe default carries a carve-out "
                f"({weasel!r}) — it is not a default any more: {default!r}"
            )
        # The line names `none (batch 5 …)` as an ILLUSTRATION of an
        # overlapping value. Banning the string would redden that correct
        # sentence — a false kill, the thing this phase keeps having to fix.
        # Assert the classification instead: wherever it is named here, it is
        # named as overlapping.
        assert "`none (" in default and "*overlapping*" in default, (
            f"{name}: the default no longer classifies the qualified-none "
            f"value as overlapping: {default!r}"
        )


def test_the_whole_value_rule_sits_at_the_step_that_routes_on_it():
    """The round moved the rule ~350 lines away, above an output table, and
    every presence check passed. This phase's own stated criterion is that an
    ambiguity is only fixed where it is read."""
    for name, path in ROUTERS.items():
        lines = path.read_text(encoding="utf-8").splitlines()
        rule = next(i for i, ln in enumerate(lines) if "is **exactly** `none`" in ln)
        step = next(i for i, ln in enumerate(lines) if ln.startswith("### 4b."))
        assert 0 < rule - step < 15, (
            f"{name}: the routing rule is {rule - step} lines from Step 4b — "
            "it has drifted off the step that routes on it"
        )


def test_triage_states_the_rule_and_that_it_does_not_route():
    """`/triage` reads the field but assigns no lane. Saying so keeps the rule
    from being copied into a skill that would then act on it."""
    rule = _line_with(TRIAGE, "tested **whole** after trimming")
    assert "counts as overlapping" in rule, (
        f"/triage's Overlap rule is inverted or unstated: {rule!r}"
    )
    assert "counts as non-overlapping" not in rule, (
        f"/triage's fail-safe default is inverted: {rule!r}"
    )
    assert "`/auto-fix` and `/auto-judge` are what route on it" in rule


def test_the_generators_are_told_they_are_the_only_writers():
    """The `Flag:`/`Triaged:` contract (Phase 181) fixed an unauthorised-writer
    defect by naming the sole writer. `Overlap:`'s failure is the authorised
    writer emitting an unparseable value, so the statement it needs is the
    grammar plus the fact that nothing downstream will catch a mistake."""
    for name, path in GENERATORS.items():
        contract = _line_with(path, "one of this field's only two writers")
        assert "no validator" in contract, name
        assert "nothing else on the line" in contract, name
        # The round told the writers the reader is LENIENT — inverting the one
        # fact that makes the grammar worth obeying — while all three phrases
        # above stayed present, because they were checked file-wide.
        assert "test the value *whole*" in contract, (
            f"{name}: the writers are no longer told the reader tests whole: "
            f"{contract!r}"
        )
        assert "is read as *overlapping*, not as `none`" in contract, (
            f"{name}: the direction of the whole-value consequence is "
            f"inverted or gone: {contract!r}"
        )


def test_an_existing_bare_number_tag_routes_to_the_same_lane_as_before():
    """The back-compatibility claim, executed rather than asserted.

    Found by the author-side pass's rule-4 sweep of the real artefact: this
    repo's own `tests/test_flag_contract.py` fixtures carry `> **Overlap:**
    702`, and both routers' fallbacks *compute* bare numbers. Declaring a
    `batch-<N>` grammar would be a breaking change if an undeclared shape
    changed lanes — it does not. Under the old rule the value was "not
    `Overlap: none`" and under the new one it is "not exactly `none`"; both
    send it to the sequential lane, so no consumer tracker needs rewriting.
    """
    for legacy in ("702", "701, 702", "1, 2"):
        stored = _parse_overlap(legacy)
        assert stored.strip() != "none", f"{legacy!r} must stay in the sequential lane"
    assert "Existing trackers need no migration" in WORKFLOW.read_text(encoding="utf-8")


def test_both_fallbacks_name_the_declared_grammar():
    """The grammar split was intra-skill: `/auto-fix`'s Step 4a computed bare
    numbers while its own deferred table rendered `batch-N`. A fallback that
    names a different shape than the writers is a third rendering of one
    field, which is what made the reader rule ambiguous in the first place."""
    for name, path in ROUTERS.items():
        text = path.read_text(encoding="utf-8")
        assert "a `batch-<N>` list in the declared grammar" in text, (
            f"{name}: the Step 1e recompute does not name the declared grammar"
        )


def test_the_contract_states_the_recompute_and_its_limit():
    """The contract used to name its hole — a present-and-wrong tag was never
    recomputed. The routers now recompute every run, so the doc must say that,
    say the recompute is never written back, and name what it still cannot see
    (overlap no task anchor names). The old admission must be gone: a doc that
    still says "not implemented" next to a router that does it is the
    shipped-prose-asserts-the-wrong-mechanism class in reverse."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "recomputed, not trusted" in text
    assert "never written back" in text
    assert "the task anchors do not name" in text
    assert "no consumer reads" in text
    for stale in ("trusted, not verified", "only when the tag is **absent**",
                  "and it is not implemented", "fallbacks compute"):
        assert stale not in text, (
            f"WORKFLOW.md still carries the pre-recompute claim {stale!r}"
        )
    # The second lane condition, on the line that states the recompute.
    lane = _line_with(WORKFLOW, "recomputed, not trusted")
    assert "exactly `none` **and** the recompute finds no overlap" in lane, (
        f"WORKFLOW's recompute paragraph no longer binds the parallel lane to "
        f"both conditions: {lane!r}"
    )
    # The normative reader rule itself, which nothing read before this round.
    rule = _line_with(WORKFLOW, "routes to the sequential lane.**")
    assert "is exactly `none`**" in rule, (
        f"WORKFLOW's reader rule no longer binds the parallel lane to an "
        f"exact `none`: {rule!r}"
    )
    # Exclusivity, asserted as the ABSENCE of a licence rather than the
    # presence of a phrase. The round's D26 kept "not an alternative spelling"
    # verbatim and prefixed it with "readers may accept any other shape that
    # conveys the same information" — the guard passed while the grammar
    # stopped being a grammar. A phrase can always be preserved and negated
    # around; a licence has to actually appear.
    exclusive = _line_with(WORKFLOW, "entitled to assume")
    assert "not an alternative spelling" in exclusive, (
        "the declared grammar stopped being exclusive at its source of truth"
    )
    low = exclusive.lower()
    for licence in ("may accept any other", "any other shape", "conveys the same",
                    "readers may accept", "equivalent shape"):
        assert licence not in low, (
            f"the grammar's own sentence licenses shapes outside it "
            f"({licence!r}): {exclusive!r}"
        )


# ── §4 the routers recompute a present tag (`Q-042`) ────────────────────────
#
# Presence checks, line- or section-scoped, with the same limit as §3: they
# prove the rule is STATED where the routing happens, never that an agent
# follows it. Before this section the routers computed overlap only when the
# tag was absent, so a present `none` that was wrong ran in the parallel lane.

PLAN_STEP = {"auto-fix": "## Step 2: Report Plan", "auto-judge": "## Step 3: Report Plan"}


def _section(text: str, start: str, end: str) -> str:
    assert text.count(start) == 1, f"expected one {start!r}, got {text.count(start)}"
    body = text.split(start, 1)[1]
    assert end in body, f"no {end!r} after {start!r}"
    return body.split(end, 1)[0]


def test_neither_router_trusts_a_present_tag():
    """The recompute runs every time, and it runs before the plan table — a
    recompute at Step 4 would let the user confirm lane counts that Step 4b
    then contradicts, and `/auto-judge --dry-run` stops before Step 4."""
    for name, path in ROUTERS.items():
        text = path.read_text(encoding="utf-8")
        for stale in ("(if missing)", "lacks the tag", "If any lack the tag"):
            assert stale not in text, (
                f"{name}: the overlap computation is still conditional on a "
                f"missing tag ({stale!r})"
            )
        head = "### 1e. Recompute overlap (every run)"
        assert text.count(head) == 1, f"{name}: no single Step 1e recompute heading"
        assert text.index(head) < text.index(PLAN_STEP[name]), (
            f"{name}: the recompute runs after the plan table it feeds"
        )
        step = _section(text, head, "\n## Step ")
        assert "even when its `Overlap:` tag is present" in step, name


def test_the_parallel_lane_needs_both_the_tag_and_the_recompute():
    """The ruling: parallel only when the tag is exactly `none` AND the
    recompute is `none`. Line-scoped, like §3 — the conjunction has to sit on
    the line that owns the non-merge lane, or one half can be dropped
    elsewhere with every phrase still in the file."""
    for name, path in ROUTERS.items():
        exact = _line_with(path, "is **exactly** `none`")
        assert "**and** whose Step 1e recompute is `none`" in exact, (
            f"{name}: the parallel lane no longer requires the recompute to "
            f"agree: {exact!r}"
        )
        other = _line_with(path, "every other batch")
        for case in ("a missing tag", "a recompute that is not `none`"):
            assert case in other, (
                f"{name}: the sequential lane does not name {case!r}: {other!r}"
            )
        step = _section(path.read_text(encoding="utf-8"),
                        "### 1e. Recompute overlap (every run)", "\n## Step ")
        assert "a missing tag counts as one that does not say `none`" in step, (
            f"{name}: a missing tag can read as agreeing with a `none` recompute"
        )


def test_the_recompute_covers_every_open_batch():
    """The generators compare the batches of ONE Round, so a `none` is wrong by
    construction whenever another Round's open batch shares a file. A recompute
    over this run's pool alone would reproduce that miss, and a `--batches`
    narrowing would shrink it further."""
    for name, path in ROUTERS.items():
        step = _section(path.read_text(encoding="utf-8"),
                        "### 1e. Recompute overlap (every run)", "\n## Step ")
        pop = [ln for ln in step.splitlines() if ln.startswith("1. **Population.**")]
        assert len(pop) == 1, f"{name}: no single population rule in Step 1e"
        for needle in ("not `Merged`, `Complete` or `Ready for Review`",
                       "not only this run's pool",
                       "`In Progress` and `Review Ready` batches",
                       "batches `--batches` left out"):
            assert needle in pop[0], f"{name}: population rule lost {needle!r}: {pop[0]!r}"


def test_a_disagreement_is_shown_and_never_written_back():
    """A disagreement is named in the run's tables so a human sees the tag is
    wrong, and the recompute stays in memory: the generators are the tag's
    only writers."""
    for name, path in ROUTERS.items():
        text = path.read_text(encoding="utf-8")
        step = _section(text, "### 1e. Recompute overlap (every run)", "\n## Step ")
        assert "**Never write it to `review_tasks.md`**" in step, name
        plan = _section(text, PLAN_STEP[name], "\n## Step ")
        deferred = _section(text, "### Deferred (overlapping — use --merge)", "\n### ")
        for where, block in (("plan table", plan), ("Deferred table", deferred)):
            rows = [ln for ln in block.splitlines()
                    if ln.startswith("| ") and "(tag) / " in ln and "(computed)" in ln]
            assert rows, f"{name}: the {where} shows no tag/recompute disagreement"


def test_the_generators_no_longer_say_no_reader_recomputes():
    """The writers were told nothing downstream recomputes a present tag. That
    stopped being true; the sentence must say the routers recompute it, or a
    generator author reads the recompute as absent."""
    for name, path in GENERATORS.items():
        text = path.read_text(encoding="utf-8")
        assert "no reader ever recomputes" not in text, name
        contract = _line_with(path, "one of this field's only two writers")
        assert "recompute it on every run" in contract, (
            f"{name}: the writers' contract does not mention the routers' "
            f"recompute: {contract!r}"
        )
