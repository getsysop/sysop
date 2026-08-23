"""Phase 222 (Q-014) — the two near-identical batch statuses and their readers.

`Review Ready` (live — review work done, a human runs `/review-close`) and
`Ready for Review` (terminal — a finished batch) are opposites that read like each
other. The scripts settled the canon in Phases 190/191 (`batch_work.sh` declares it
outright), but the *prose* readers lagged: `/claim-task`'s status ladder had no arm at
all for `Review Ready` (undefined behaviour on an explicit claim), the three
orchestrator skip lists named only the terminal twin, WORKFLOW § 4's declared value
list omitted the live status entirely, and the generators' legend advertised four of
the six values.

These tests derive the canon from the tracker's own declaration line and pin every
prose reader to it — plus a class guard: any skill aware of one twin must be aware of
both, because a reader that names only one is exactly how the stranding starts.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "core" / "skills"
WORKFLOW = REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md"
BATCH_WORK = REPO_ROOT / "core" / "companion" / "scripts" / "batch_work.sh"

CANON = ["Pending", "In Progress", "Review Ready", "Complete", "Merged", "Ready for Review"]


def test_the_canon_is_derived_from_the_tracker_not_assumed():
    """The list above must EQUAL batch_work.sh's own `Declared:` line — the ratified
    source (`/roadmap` quotes it as authoritative). Set equality, not membership: the
    round's BS-5 added a seventh status to the declaration and a subset check stayed
    green, so a canon that silently under-covers the tracker is exactly what this
    must catch. If the declaration changes, this fails first and the rest of the
    module is re-derived, not trusted."""
    decl = [
        l for l in BATCH_WORK.read_text(encoding="utf-8").splitlines() if "Declared:" in l
    ]
    assert len(decl) == 1, f"expected one Declared: line in batch_work.sh, got {len(decl)}"
    # The line is a shell `echo "... Declared: ... (finished)." >&2` — cut the
    # closing quote + redirect before parsing the interpunct list.
    listing = decl[0].split("Declared:", 1)[1].split('"')[0]
    declared = [
        re.sub(r"\s*\((?:live|finished)\)\s*", "", part).strip().rstrip(".")
        for part in listing.split("·")
    ]
    assert declared == CANON, (
        f"batch_work.sh declares {declared!r} but the module's canon is {CANON!r} — "
        "re-derive the module from the tracker"
    )
    # The near-identical pair must carry their live/finished marking in the declaration.
    assert "Review Ready (live)" in decl[0] and "Ready for Review (finished)" in decl[0]


def test_workflow_declared_list_carries_the_live_status():
    """WORKFLOW § 4's `Batch status values:` line was the stale declaration —
    it omitted `Review Ready` while two shipped scripts accepted it (Q-014)."""
    text = WORKFLOW.read_text(encoding="utf-8")
    lines = [
        l for l in text.splitlines() if l.startswith("**Batch status values:**")
    ]
    assert len(lines) == 1, "WORKFLOW.md must declare the batch status ladder exactly once"
    for status in CANON:
        assert f"`{status}`" in lines[0], (
            f"WORKFLOW.md batch-status declaration omits `{status}`: {lines[0]}"
        )
    # The definitional blockquote beneath it: the round's BS-2 swapped live and
    # terminal with every token intact — pin the two definitional clauses.
    flat = " ".join(text.split())
    assert "`Review Ready` is **live**" in flat, (
        "WORKFLOW.md's blockquote no longer defines `Review Ready` as live"
    )
    assert "`Ready for Review` is **terminal**" in flat, (
        "WORKFLOW.md's blockquote no longer defines `Ready for Review` as terminal"
    )


def test_claim_task_ladder_has_an_arm_for_review_ready():
    """An explicit claim of a `Review Ready` batch was undefined behaviour — the
    ladder had arms for every status except the one that needs a human. The arm's
    DISPOSITION is pinned too: the round's BS-3 kept the arm and made it claim (the
    regex pinned only the bullet prefix)."""
    text = (SKILLS_DIR / "claim-task" / "SKILL.md").read_text(encoding="utf-8")
    m = re.search(r"^\s*- `Review Ready` →.*$", text, re.MULTILINE)
    assert m, "/claim-task's review-batch status ladder lost its `Review Ready` arm"
    flat = " ".join(m.group(0).split())
    assert "Report exactly that and stop" in flat, (
        f"the Review Ready arm no longer stops: {flat[:200]}"
    )
    assert "claiming it would put an agent on finished work" in flat, (
        f"the Review Ready arm lost its reason — or reversed it: {flat[:200]}"
    )
    for countermand in ("Proceed to claim", "proceed to claim", "the script handles this"):
        assert countermand not in flat, (
            f"the Review Ready arm countermands its own stop: {flat[:200]}"
        )


# The operative fragment of each skip bullet, pinned VERBATIM (whitespace-normalized —
# the Phase 168 precedent, adopted after the round's BS-1 kept every needle and said the
# opposite, and its P1 control showed the line-level detector false-killing a pure
# reflow). Rewording a skip bullet now takes a deliberate edit here too; that is what a
# ratified reader contract should cost.
_SKIP_PINS = {
    "auto-fix": (
        "`Review Ready`, which is **live but not this skill's**: the fix work is done "
        "and the batch is waiting on a human to run `/review-close`"
    ),
    "triage": (
        "`Review Ready`, which is **live but past triage**: it is waiting on "
        "`/review-close`, and re-triaging it would re-open something already reviewed"
    ),
    "auto-judge": (
        "`Review Ready`, which is live but waiting on a human to run `/review-close`, "
        "not on a judgment agent"
    ),
}


def test_orchestrator_skip_lists_name_the_live_status():
    """`/auto-fix`, `/triage` and `/auto-judge` select positively on `Pending`; their
    skip lists must carry the live-status skip WITH its stated direction — presence of
    the name alone accepted its own reversal (round survivor BS-1)."""
    for skill, pin in _SKIP_PINS.items():
        flat = " ".join(
            (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8").split()
        )
        assert pin in flat, (
            f"/{skill}'s Review Ready skip lost its operative wording — if the reword "
            "was deliberate, update _SKIP_PINS in the same commit"
        )


def test_generator_legends_advertise_all_six_values():
    """The legend the generators write into a fresh `review_tasks.md` is the value
    list a new consumer copies from; it advertised four of six."""
    for skill in ("codebase-review", "security-audit"):
        text = (SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
        legend = [l for l in text.splitlines() if l.startswith("- **Batch status**:")]
        assert len(legend) == 1, f"/{skill}: expected one batch-status legend line"
        for status in CANON:
            assert status in legend[0], f"/{skill} legend omits {status!r}: {legend[0]}"


def test_sitrep_cascade_reaches_review_ready():
    """`/sitrep`'s priority-2 row must key on the `Review Ready` header, since the
    survey payload filters to Pending/In Progress and never carries it."""
    text = (SKILLS_DIR / "sitrep" / "SKILL.md").read_text(encoding="utf-8")
    p2 = [l for l in text.splitlines() if l.startswith("| 2 ")]
    assert len(p2) == 1 and "Review Ready" in p2[0], (
        "/sitrep priority 2 no longer routes a `Review Ready` batch to /review-close"
    )


def test_no_skill_knows_one_twin_without_the_other():
    """Class guard: a shipped skill that names either near-identical status must name
    both. A reader aware of only one twin is the seed of the next stranding — that is
    how all four Q-014 gaps started."""
    offenders = []
    for f in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        text = f.read_text(encoding="utf-8")
        has_live = "Review Ready" in text
        # Count terminal mentions that are NOT the substring inside "Review Ready".
        has_terminal = "Ready for Review" in text
        if has_live != has_terminal:
            offenders.append(f"{f.parent.name} (live={has_live}, terminal={has_terminal})")
    assert not offenders, (
        "skills aware of one batch-status twin but not the other: " + ", ".join(offenders)
    )
