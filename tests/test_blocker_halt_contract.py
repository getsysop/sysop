"""The Classification Rubric's `blocker` arm is a **halt**, and every consumer must honour it.

Phase 176. `_shared/adversarial-review.md` § Classification Rubric defines `blocker` as
"requires human input the agent cannot produce … Action: halt — do not call `ExitPlanMode`,
do not execute, surface the question to the human." Two of the three skills that consume the
rubric said so. `/plan-review` gave `blocker` the *`fixable`* action at four sites and then
called `ExitPlanMode` anyway — and it is the only rubric consumer that reaches `ExitPlanMode`
while a classification is still live, so the rubric's one explicitly-named prohibition was
violated at the only site where it binds. (`/claim-task` never enters plan mode; `/auto-build`
does instruct an `ExitPlanMode` call in its Phase 6e executor prompt, but only after every
blocker is parked and that task's execution skipped.)

The contradiction was *created by an extraction*: `/plan-review` Step 5 has said "for each
blocker → modify" since `94dc48e` (2026-04-11), the commit that added the skill, and never
carried a rubric of its own. Phase 26 (`2a360e8`, 2026-05-20) pointed its Step 3 at a shared
rubric defining `blocker` as halt, editing this very file in the same commit without
reconciling Step 5. (`5076074` is a *pure rename* of the file — 0 insertions, 0 deletions —
so a path-scoped `git log -S` without `--follow` reports it and is wrong; the phase's own
first draft made exactly that mistake.)

**Why this file exists rather than an addition to `test_adversarial_review_gate.py`.** That
module pins the *partial*. Its consumer-facing tests — `test_the_procedure_does_not_contradict_
the_skills_that_consume_it` and `test_compound_findings_heading_resolves_for_its_citers` —
cover the `isolation` carve-out and a heading-resolution population respectively. Neither
touches a disposition, so the class *"a consuming skill contradicts a rubric disposition"* had
no guard at all, and this defect shipped underneath a test whose *name* covers it.

## The two mechanisms, and why there are two

Phase 176's first guard was a regex screen alone. An independent reviewer's battery ran 21
defect mutations against it and **all 21 survived**, because a whitelist of determiners and
verbs loses to ordinary English: `"For **`blocker`** findings, modify the relevant plan step"`
reintroduces the original defect one comma away from the string that shipped. Six of its eight
negative controls also reddened, including `"For every `blocker`, surface its one-line
question to the human"` — pure halt-side prose — because the shape matched a determiner and a
token with no reference to any action at all.

So:

1. **Verbatim disposition pins** (`DISPOSITION_PINS`) — the load-bearing clauses are short,
   stable, and rarely edited, so they are pinned byte-for-byte. Any *rewording* of a
   disposition trips its pin, which is what a synonym-tolerant screen cannot do. This is
   Phase 168's precedent: it pinned a subsection verbatim after a 19-character softening
   killed a ratchet. The cost is deliberate — a legitimate reword reddens and gets re-pinned
   on purpose, by someone who has read this paragraph.
2. **An absorb screen** (`ABSORB_SHAPES`) over a wide population — pins cannot see an absorb
   instruction *added somewhere new*, which is how six of the reviewer's mutations worked
   (a fresh bullet, an appended rider, a line in `README.md`). Every shape requires an
   absorb **verb**, not merely the token: `"For every `blocker`, surface its one-line
   question to the human"` assigns no absorb action and stays green, where the first draft's
   determiner-only shape reddened it.

Neither is sufficient; the pairing is the design, and **the screen's narrowness is
deliberate and bounded** — see the comment above `ABSORB_SHAPES` for the measurement that
forced it. An absorb instruction phrased in a construction not listed there is not caught
by the screen; it is caught by a pin only if it *replaces* a pinned disposition rather than
being added alongside one. That residual is declared rather than papered over.

Note for anyone extending this: the defect strings appear as *fixtures* below, and the
maintainer-side files that narrate the defect (`PHASE_LOG.md`, `REVIEW_CHECKLIST.md`,
`tools/`) are deliberately outside the scanned population — they legitimately quote what
shipped. Widening the population must account for that.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "core" / "skills"
DOCS_DIR = REPO_ROOT / "core" / "companion" / "docs"
PUBLIC_DOCS = REPO_ROOT / "docs"
PACKS_DIR = REPO_ROOT / "packs"
PARTIAL = SKILLS_DIR / "_shared" / "adversarial-review.md"
PLAN_REVIEW = SKILLS_DIR / "plan-review" / "SKILL.md"
GUIDE = DOCS_DIR / "WORKFLOW_GUIDE.md"


def _flat(text: str) -> str:
    """Collapse whitespace so a wrapped clause is not invisible to a line-scoped regex.

    Phase 173's scout found `"at the repo\\nroot"` hiding from its own sweep this way and
    reported 2 sites where there were 5. Every pattern here runs against flattened text.
    """
    return re.sub(r"\s+", " ", text)


# ============================================================ 1. verbatim disposition pins
#
# file -> (label, exact string that must appear verbatim, why it is load-bearing)
#
# Each is the sentence that assigns an action to a classification. Reword one and its pin
# reddens; that is the point. When a reword is genuinely wanted, update the pin in the same
# commit and say so in the phase record — an unexplained pin edit is the thing to catch.

DISPOSITION_PINS: list[tuple[Path, str, str, str]] = [
    (
        PARTIAL, "rubric-blocker-action",
        "Action: halt — do not call `ExitPlanMode`, do not execute, surface the question to the human.",
        "the ground truth every other assertion in this module depends on",
    ),
    (
        PARTIAL, "rubric-fixable-action",
        "Action: incorporate the fix into the plan and continue.",
        "the contrasting arm; widening it to swallow blockers is the same defect inverted",
    ),
    (
        PARTIAL, "rubric-clean-pass",
        "the planner records `Adversarial review: no blockers found` explicitly in the plan",
        "the wording `/plan-review` reproduces; if the rubric's side drifts the two disagree silently",
    ),
    (
        PLAN_REVIEW, "plan-review-halt",
        "**5b — If any finding is `blocker`, halt.** Do not emit a revised plan, do not call "
        "`EnterPlanMode` or `ExitPlanMode`, do not execute, and do not proceed to Steps 6–8.",
        "the halt arm this phase added — the whole subject",
    ),
    (
        PLAN_REVIEW, "plan-review-delegation",
        "**5a — Classify.** Apply the Classification Rubric in "
        "`.claude/skills/_shared/adversarial-review.md` to each finding in `RAW_FINDINGS`: "
        "exactly one of `fixable` or `blocker`.",
        "without the delegation the disposition has no definition to be bound by",
    ),
    (
        PLAN_REVIEW, "plan-review-fixable-bullet",
        "- For each **fixable** finding you accept → modify the relevant plan step so the "
        "issue is resolved.",
        "the site that carried the original defect; a one-word edit puts it back",
    ),
    (
        PLAN_REVIEW, "plan-review-incorporated-record",
        "listing each finding that was accepted and what changed in response",
        "said `each blocker that was accepted` before this phase",
    ),
    (
        PLAN_REVIEW, "plan-review-summary-row",
        "| Findings incorporated | N |",  # flattened — the source pads the columns
        "read `Blockers incorporated` before this phase — reported absorbing blockers as diligence",
    ),
    (
        SKILLS_DIR / "claim-task" / "SKILL.md", "claim-task-halt",
        "**If any finding is `blocker` — park. Do not spawn the executor.**",
        "the sibling disposition; invertible with nothing else in the suite going red",
    ),
    (
        SKILLS_DIR / "auto-build" / "SKILL.md", "auto-build-halt",
        "- **`blocker`** — halt and park.",
        "the sibling disposition; the reviewer inverted this one and the whole suite stayed green",
    ),
    (
        GUIDE, "guide-halt",
        "**Any `blocker` halts instead**",
        "the catalogue entry names both arms, so it owes the halt",
    ),
]


@pytest.mark.parametrize(
    "path,label,pin,why",
    DISPOSITION_PINS,
    ids=[label for _, label, _, _ in DISPOSITION_PINS],
)
def test_disposition_pins_hold(path: Path, label: str, pin: str, why: str):
    assert path.exists(), f"{path.relative_to(REPO_ROOT)} is gone"
    if pin not in _flat(path.read_text(encoding="utf-8")):
        raise AssertionError(
            f"{path.relative_to(REPO_ROOT)}: the `{label}` disposition no longer matches its "
            f"pin verbatim.\n  expected: {pin!r}\n  why pinned: {why}\n"
            f"A reworded disposition is exactly what a synonym-tolerant screen misses — an "
            f"independent battery inverted three of these and nothing in the suite noticed. "
            f"If the reword is intended, update the pin in the same commit and say so in the "
            f"phase record."
        )


def test_the_pins_are_not_trivially_satisfiable():
    """A pin whose text is empty, or short enough to occur by accident, guards nothing."""
    for _, label, pin, _ in DISPOSITION_PINS:
        assert len(pin) >= 25, f"{label}: pin is {len(pin)} chars — too short to be distinctive"
    labels = [label for _, label, _, _ in DISPOSITION_PINS]
    assert len(labels) == len(set(labels)), "duplicate pin labels"


def rubric_consumers() -> list[Path]:
    """Skills that consume the Classification Rubric, derived from the tree.

    Citing the partial is not enough: `/codebase-review`, `/security-audit` and
    `/review-close` cite it for § *Running more than one reviewer* and dimension #9 and
    never classify a plan finding — none of the three uses the word `blocker` at all, which
    is why the token is the discriminator rather than the citation.
    """
    out = []
    for path in sorted(SKILLS_DIR.rglob("SKILL.md")):
        text = path.read_text(encoding="utf-8")
        if "_shared/adversarial-review.md" in text and re.search(r"\bblockers?\b", text, re.I):
            out.append(path)
    return out


def test_every_rubric_consumer_has_a_pinned_disposition():
    """The new-consumer tripwire, and the one survivor of the round's re-run.

    A reviewer added a plausible fourth consumer — a `plan-lint` skill citing the partial,
    writing `**blocker**` unbacktickeded, describing a happy path only — and every assertion
    here stayed green because the pins name three files and the screen matched none of its
    phrasings. Deriving the population from the tree and requiring each member to carry a
    pin means a fourth consumer cannot arrive unnoticed: adding one fails this test until
    its disposition is pinned above.
    """
    consumers = rubric_consumers()
    assert consumers, "no skill consumes the rubric — the derivation is broken"
    pinned = {path for path, _, _, _ in DISPOSITION_PINS}
    for consumer in consumers:
        assert consumer in pinned, (
            f"/{consumer.parent.name} consumes the Classification Rubric but no entry in "
            f"DISPOSITION_PINS covers it, so nothing checks that it honours the halt. Add "
            f"its disposition clause to the pin table."
        )
    for required in ("plan-review", "claim-task", "auto-build"):
        assert any(c.parent.name == required for c in consumers), (
            f"/{required} no longer reads as a rubric consumer — it either stopped citing "
            f"the partial or stopped using the token, both of which silently unenforce this"
        )


def test_the_rubric_pins_are_the_ones_the_consumers_delegate_to():
    """Ground truth and its citers must be the same file. If `/plan-review` starts citing a
    different partial, the pins above still pass while the skill is bound by nothing."""
    for consumer in ("plan-review", "claim-task", "auto-build"):
        text = (SKILLS_DIR / consumer / "SKILL.md").read_text(encoding="utf-8")
        assert "_shared/adversarial-review.md" in text, (
            f"/{consumer} no longer cites the partial these pins are taken from"
        )


# ================================================================ 2. the absorb screen
#
# Pins cannot see an absorb instruction ADDED somewhere new. Six of the reviewer's twenty-one
# mutations worked that way: a fresh bullet in Step 5c, a rider appended after the Step 8
# note, a line planted in `README.md`.
#
# The screen fires on a clause that (a) names a blocker, (b) contains an absorb verb, and
# (c) contains no halt word. Requiring the *verb* is what fixes the over-strictness the
# reviewer found: "For every `blocker`, surface its one-line question to the human" assigns
# no absorb action and stays green, where the first draft's determiner-only shape reddened it.

# A first rewrite tried the general form — any clause naming a blocker near an absorb verb,
# minus a halt word. Run against the tree it produced **eleven hits and all eleven were
# correct prose**: `/auto-build`'s instruction to the human resuming a parked task ("resolve
# the blocker … then continue the work manually"), `/claim-task`'s "do not decide whether the
# work proceeds", the guide's `/next-task` entry using the *dependency* sense of the word,
# and this skill's own sentence explaining that revising around a blocker is not available.
# The separation between those and a real defect is semantic, not lexical.
#
# So the screen is deliberately narrow and its bound is stated rather than implied: **it
# recognises specific dispositional constructions, and an absorb instruction phrased in a
# form not listed here is not caught.** That residual is real and is why the pins above
# exist — a reworded disposition trips a pin even when no shape matches it.

_B = r"\**`?blockers?`?\**"
_ABSORB = r"(?:incorporat|absorb|fold|swallow|modif|revis|updat|adjust|amend|fix|address|handle)\w*"

ABSORB_SHAPES: dict[str, re.Pattern[str]] = {
    # "For each **blocker** finding → modify the relevant plan step"        (shipped :86)
    # Needs a determiner AND an absorb verb: "For every `blocker`, surface its question to
    # the human" is halt-side prose and must stay green — the first draft reddened it.
    # The determiner is optional — the shipped string had "each", but the reviewer's M01
    # dropped it entirely ("For **`blocker`** findings, modify …") and walked through a
    # version that required one. The absorb verb is what carries the shape.
    "per-blocker-action": re.compile(
        rf"\bfor\s+(?:each|every|any|all|the|a|an)?\s*{_B}(?:\s+findings?)?\b[^.]{{0,60}}?{_ABSORB}",
        re.I,
    ),
    # "Incorporate `blocker` findings into the revised plan"    (verb first — reviewer M03)
    "absorb-verb-then-blocker": re.compile(rf"\b{_ABSORB}\s+{_B}\s+findings?", re.I),
    # "Blockers should be folded into the revised plan"      (passive — reviewer M04, M11)
    "blocker-passively-absorbed": re.compile(
        rf"{_B}(?:\s+findings?)?\s+(?:are|is|get|gets|should be|can be|may be|will be|"
        rf"are to be)\s+\w*\s*{_ABSORB}",
        re.I,
    ),
    # "listing each blocker that was accepted"                              (shipped :93)
    # Present-tense imperatives only — this repo does narrate retired wording inside shipped
    # files (`adversarial-review.md` § The reviewer-executor variant is retired), so "once
    # listed each blocker that was accepted" is ordinary work and must stay green.
    "blocker-accepted": re.compile(
        rf"\b(?:listing|list|noting|note|record|recording|enumerate|enumerating)\s+"
        rf"(?:each|every|all)\s+{_B}[^.]{{0,40}}?\baccepted\b",
        re.I,
    ),
    # "If the sub-agent returned **zero blockers**, append this line instead"  (shipped :102)
    "clean-pass-keyed-on-blockers": re.compile(
        rf"\bzero\s+{_B}[^.]{{0,60}}?\b(?:append|instead|proceed)\b", re.I
    ),
    # "| Blockers incorporated | N |"                                       (shipped :119)
    "blockers-absorbed-row": re.compile(
        rf"\|\s*blockers?\s+(?:{_ABSORB}|accepted|resolved)\s*\|", re.I
    ),
    # "- **`blocker`** — incorporate and continue."   (the disposition bullet, inverted)
    # Clause-bounded so `claim-task`'s definition bullet — which names no action and says
    # "revising the plan" two sentences later — stays green.
    "blocker-bullet-absorb": re.compile(rf"{_B}\s*[—:-]\s*[^.]{{0,60}}?{_ABSORB}", re.I),
    # "note it in classification.md and spawn the executor anyway"          (reviewer M10)
    # `[^.]` is wrong here: the reviewer's M10 put `classification.md` between the token and
    # the verb, and the period in a filename stopped the span dead. Text is flattened, so
    # `.` cannot cross a line; 120 chars keeps it inside one instruction.
    "blocker-then-proceed-anyway": re.compile(
        rf"{_B}.{{0,120}}?\b(?:anyway|regardless|all the same|even so)\b", re.I
    ),
    # "always ending in a revised plan presented for approval"              (reviewer M14)
    "blocker-always-revised": re.compile(
        rf"{_B}[^.]{{0,60}}?\balways\b[^.]{{0,60}}?\brevis\w*", re.I
    ),
}


def absorb_hits(text: str) -> list[str]:
    """Shape names that fire on `text`. Narrow by construction — see the comment above."""
    flat = _flat(text)
    return sorted(name for name, rx in ABSORB_SHAPES.items() if rx.search(flat))


# A halt arm can also be neutralised without any absorb verb at all, by attaching a
# condition to it. The reviewer did this twice — an escape hatch spliced into 5b ("unless
# every blocker can be answered from the plan's own context") and a rider appended after
# the Step 8 note ("if the human has already said to proceed, treat that as the answer").
# Neither touches a pinned string and neither names an absorb verb.
SOFTENERS = [
    "unless", "except when", "except where", "may call", "you may proceed",
    "treat that as", "already said to proceed", "at your discretion", "if you judge",
]


def softener_hits(text: str) -> list[str]:
    low = _flat(text).lower()
    return [s for s in SOFTENERS if s in low]


def _scan_population() -> list[Path]:
    """Shipped content, wide. NOT `tools/`, `PHASE_LOG.md` or `REVIEW_CHECKLIST.md` — those
    are maintainer-side and legitimately narrate the defect in its own words.

    The reviewer planted the literal shipped defect string in `README.md` and nothing fired,
    because the first draft read `core/skills/` and `core/companion/docs/` only.
    """
    paths = sorted(SKILLS_DIR.rglob("*.md"))
    paths += sorted(DOCS_DIR.rglob("*.md"))
    paths += sorted(PACKS_DIR.rglob("*.md"))
    paths += sorted(PUBLIC_DOCS.rglob("*.md"))
    paths += [REPO_ROOT / "README.md", REPO_ROOT / "CONTRIBUTING.md"]
    return [p for p in paths if p.exists()]


def test_the_scan_population_covers_the_places_the_defect_can_appear():
    """`parametrize` over an empty list generates zero tests and reports green."""
    population = _scan_population()
    assert len(population) > 30, f"only {len(population)} docs found — scan is broken"
    for required in (PARTIAL, PLAN_REVIEW, GUIDE, DOCS_DIR / "WORKFLOW.md",
                     REPO_ROOT / "README.md"):
        assert required in population, f"{required} is outside the screened population"


@pytest.mark.parametrize(
    "path", _scan_population(), ids=lambda p: str(p.relative_to(REPO_ROOT))
)
def test_no_shipped_doc_gives_a_blocker_an_absorb_action(path: Path):
    hits = absorb_hits(path.read_text(encoding="utf-8"))
    assert not hits, (
        f"{path.relative_to(REPO_ROOT)} tells a reader to absorb a `blocker` instead of "
        f"halting. The rubric's `blocker` arm is halt — see `_shared/adversarial-review.md` "
        f"§ Classification Rubric.\nOffending clause(s):\n  " + "\n  ".join(hits)
    )


# ================================================== 3. the halt is stated where it must be
#
# Scoped to the clause that must carry it, never file-wide. The author-side battery ran four
# mutations that broke a claim at the step that must carry it and all four survived a
# file-level assertion, because the same words appear elsewhere for unrelated reasons.


def _slice(path: Path, start: str, end: str) -> str:
    text = path.read_text(encoding="utf-8")
    assert start in text, f"anchor {start!r} is gone from {path.name}"
    assert end in text, f"anchor {end!r} is gone from {path.name}"
    i, j = text.index(start), text.index(end)
    assert i < j, f"anchors out of order in {path.name}: {start!r} must precede {end!r}"
    body = text[i:j]
    assert body.strip(), "slice is empty"
    return _flat(body)


HALT_ARM = ("**5b — If any finding is `blocker`, halt.**", "**5c — Otherwise every finding")


def test_the_slicer_fails_closed():
    """A slicer returning '' on a missing anchor turns every assertion below green."""
    for bad in [(HALT_ARM[0], "## Step 99:"), ("## Nonexistent", HALT_ARM[1]),
                (HALT_ARM[1], HALT_ARM[0])]:
        with pytest.raises(AssertionError):
            _slice(PLAN_REVIEW, *bad)


def test_the_halt_arm_carries_its_own_terms_and_no_escape_hatch():
    """Scoped to 5b. Token presence alone is not enough — a reviewer mutation kept all four
    required tokens while instructing the defect ("the rubric's advice … applies only when
    the human is unreachable; normally, revise the plan around the blocker and proceed"), so
    the arm is also screened for absorb clauses and for conditional softeners."""
    arm = _slice(PLAN_REVIEW, *HALT_ARM)
    for term, why in [
        ("`blocker`", "the arm no longer names the classification it dispositions"),
        ("halt", "the arm no longer uses the rubric's word for the action"),
        ("ExitPlanMode", "the arm no longer names the rubric's one explicit prohibition"),
        ("do not execute", "the arm no longer forbids execution"),
    ]:
        assert term.lower() in arm.lower(), f"/plan-review 5b: {why}"
    assert not absorb_hits(arm), (
        "/plan-review 5b contains a clause telling the reader to absorb a blocker:\n  "
        + "\n  ".join(absorb_hits(arm))
    )
    assert not softener_hits(arm), (
        f"/plan-review 5b carries a conditional escape hatch ({softener_hits(arm)}). The "
        f"rubric's halt arm is unconditional; a rider inside the arm is how it gets "
        f"neutralised without any pin moving."
    )


def test_the_step_8_note_has_no_softening_rider():
    """The `ExitPlanMode` call site is the furthest point from the step that decided the
    halt, and a reviewer neutralised the gate by appending a rider here rather than by
    editing anything pinned."""
    # Scoped to the note itself, not to all of Step 8: the step's closing line legitimately
    # reads "do not loop back into another adversarial review unless explicitly asked", and
    # a step-wide softener screen reddens on it.
    note = _slice(PLAN_REVIEW, "**Reachable only when no finding was classified `blocker`**",
                  "Present `REVISED_PLAN` using the standard plan-mode approval flow")
    assert not absorb_hits(note), (
        "Step 8 carries a clause licensing a blocker through to `ExitPlanMode`:\n  "
        + "\n  ".join(absorb_hits(note))
    )
    assert not softener_hits(note), (
        f"Step 8 carries a conditional rider ({softener_hits(note)}) — the reviewer's M21 "
        f"neutralised the gate here without editing anything pinned."
    )


def test_the_guide_entry_states_the_halt_as_an_action_not_a_reference():
    """`WORKFLOW_GUIDE.md`'s catalogue entry names both arms of the classification, so it
    owes the halt. Reading only the first physical line was a bug — a reviewer reddened this
    with an ordinary markdown list continuation — so the entry is read to the next bullet."""
    text = GUIDE.read_text(encoding="utf-8")
    start = text.index("- **`/plan-review`**")
    nxt = re.search(r"\n- \*\*`/", text[start + 5:])
    entry = _flat(text[start:start + 5 + nxt.start()] if nxt else text[start:])
    assert "`blocker`" in entry
    assert not absorb_hits(entry), (
        "the guide's `/plan-review` entry describes absorbing a blocker:\n  "
        + "\n  ".join(absorb_hits(entry))
    )


def test_the_clean_pass_condition_is_zero_findings():
    """Keying the clean-pass line on *blockers* did not merely mislabel: `/plan-review`
    appends it **instead of** the Incorporated Changes section, so on the rubric's dominant
    path — findings returned, all `fixable`, all incorporated — the audit record of the pass
    was replaced by the words "no blockers found"."""
    text = _flat(PLAN_REVIEW.read_text(encoding="utf-8"))
    # "no findings" as well as "zero findings": the rubric's own § Recording a clean pass
    # says "If the sub-agent returns no findings", and a guard that reddens when the skill
    # converges on the ground truth's phrasing is punishing the right answer. An independent
    # reviewer caught the first version doing exactly that.
    assert re.search(
        r"\b(?:zero|no)\s+\**findings\**[^.]{0,80}?\bappend\b", text, re.I
    ), "/plan-review's clean-pass arm is no longer keyed on the absence of *findings*"
    assert not re.search(
        r"\bzero\s+\**`?blockers?`?\**[^.]{0,60}?\b(?:append|instead|proceed)\b", text, re.I
    ), "/plan-review's clean-pass arm is keyed on zero *blockers* again"


def test_a_failed_review_cannot_be_recorded_as_a_clean_one():
    """The failure route used to exit through the clean-pass stamp: nothing checked that the
    reviewer returned a findings list, so an error or a refusal yielded nothing classifiable,
    the zero-findings arm fired, and the plan was stamped "no blockers found" before
    `ExitPlanMode`. A review that never ran became indistinguishable from a clean one — the
    #220 shape. `/claim-task` requires an explicit `findings: []` / `CLEAN` verdict for
    exactly this reason; `/plan-review`'s reviewer emits no verdict token, so the arm below
    is the only thing standing in the way."""
    text = _flat(PLAN_REVIEW.read_text(encoding="utf-8"))
    assert "Adversarial Review — Did Not Run" in text, (
        "/plan-review has no arm for a malformed or errored reviewer return"
    )
    assert re.search(
        r"not a findings list[^.]{0,200}?the review did not run", text, re.I
    ), "the did-not-run arm no longer states its trigger condition"
    assert re.search(
        r"do not classify, do not append the clean-pass line", text, re.I
    ), "the did-not-run arm no longer forbids the clean-pass stamp"


# ============================================================================== controls
#
# Positive controls: every shipped defect string, and every mutation an independent reviewer
# got past the first draft, must redden. Negative controls: correct prose a lazier screen
# punishes must stay green — six of the first draft's eight controls reddened.

@pytest.mark.parametrize(
    "label,fixture",
    [
        # The four strings that actually shipped.
        ("shipped-86", "- For each **blocker** finding → modify the relevant plan step so the issue is resolved."),
        ("shipped-93", "Append a section listing each blocker that was accepted and what changed in response:"),
        ("shipped-102", "- If the sub-agent returned **zero blockers**, append this line to the plan instead:"),
        ("shipped-119", "| Blockers incorporated                 | N     |"),
        # Reviewer mutations M01-M04, M08, M11, M21, M23 — all survived the first draft.
        ("M01-comma-no-determiner", "- For **`blocker`** findings, modify the relevant plan step so the issue is resolved."),
        ("M02-the-and-fix", "- For the **blocker** finding → fix the relevant plan step so the issue is resolved."),
        ("M03-verb-first", "- Incorporate `blocker` findings into the revised plan the same way and continue."),
        ("M04-passive-synonym", "- Blockers should be folded into the revised plan rather than escalated."),
        ("M08-absorbed-synonym", "| Blockers absorbed                     | N     |"),
        ("M11-auto-build-inversion", "- **`blocker`** findings are folded into the plan and execution continues."),
        ("M23-noting", "revised plan noting each blocker that was accepted and what changed in response"),
        ("M10-claim-task-inversion", "**If any finding is `blocker`, note it in `classification.md` and spawn the executor anyway.**"),
        ("M14-workflow-altitude", "`/plan-review` (ad-hoc plans; findings classified `fixable`/`blocker`, always ending in a revised plan presented for approval)"),
    ],
)
def test_every_known_defect_string_reddens(label: str, fixture: str):
    assert absorb_hits(fixture), f"{label} walks through the screen"


@pytest.mark.parametrize(
    "label,fixture",
    [
        # The two the reviewer's NC1/NC6 proved the first draft punished.
        ("halt-side-imperative", "For every `blocker`, surface its one-line question to the human."),
        ("halt-side-park-note", "For any `blocker`, the park marker records the question."),
        # The rubric's action-free definition bullet — the halt is 60+ lines later.
        ("definition-bullet", "- **`blocker`** — requires human input the agent cannot produce."),
        # The correct dispositions, in several phrasings.
        ("correct-halt-terse", "- **`blocker`** — halt and park."),
        ("correct-halt-verbose", "- **`blocker`** — park the task immediately; do not spawn the executor."),
        ("correct-halt-plan-review", "**If any finding is `blocker`, halt.** Do not emit a revised plan."),
        # The correct `fixable` action, which shares every verb with the defect.
        ("correct-fixable", "- For each **fixable** finding you accept → modify the relevant plan step."),
        # Referential, and shipped in `adversarial-review.md` today.
        ("blocker-referential", "its executor keeps `BLOCKER_QUESTION:` for a blocker discovered during implementation."),
        # NC3: a negated, quoted mention of the retired label.
        ("negated-quoted-mention", "The row reads `Findings incorporated`; it must never read `Blockers incorporated`, which was the defect."),
        # NC5: the rubric's own phrasing for the clean-pass condition.
        ("rubric-clean-pass-wording", "If the sub-agent returns no findings, the planner records the clean-pass line."),
        # Narrating the retired wording, as `adversarial-review.md` does for the reviewer-executor.
        ("historical-narration", "This step once said *zero blockers*; both arms gave a blocker the fixable action, and it was retired."),
        # The dependency sense of the word, used throughout `/roadmap` and `/next-task`.
        ("dependency-sense", "Name the blockers and their status; a deferred dependency is not satisfied."),
    ],
)
def test_correct_prose_stays_green(label: str, fixture: str):
    hits = absorb_hits(fixture)
    assert hits == [], (
        f"the screen punishes correct prose ({label}) — over-strictness is this guard's own "
        f"failure mode, and six of the first draft's eight controls reddened.\n  " + "\n  ".join(hits)
    )


@pytest.mark.parametrize(
    "label,fixture",
    [
        ("M05-halt-arm-escape-hatch",
         "…and stop — unless every blocker can be answered from the plan's own context, in "
         "which case revise the plan and continue to Step 8."),
        ("M21-step8-rider",
         "(If a `blocker` was found but the human has already said to proceed, treat that "
         "as the answer and continue below.)"),
        ("M06-advice-framing",
         "The rubric's advice — do not call `ExitPlanMode`, do not execute — applies only "
         "when the human is unreachable; you may proceed otherwise."),
    ],
)
def test_conditional_riders_redden(label: str, fixture: str):
    """These carry no absorb verb and touch no pinned string. The softener screen is the
    only thing between them and a neutralised halt."""
    assert softener_hits(fixture), f"{label} walks through the softener screen"


def test_the_screen_is_not_vacuous():
    """Reconstruct the pre-Phase-176 Step 5 and prove the screen fires on it."""
    shipped = (
        "## Step 5: Incorporate Findings into Revised Plan\n"
        "- For each **blocker** finding → modify the relevant plan step.\n"
        "- Append a section listing each blocker that was accepted.\n"
        "| Blockers incorporated | N |\n"
    )
    assert len(absorb_hits(shipped)) >= 3, (
        f"the reconstructed pre-Phase-176 Step 5 trips only {len(absorb_hits(shipped))} clauses"
    )


def test_the_screen_reads_wrapped_text():
    """Phase 173's lesson, as a control rather than a comment: a clause split across lines
    must be screened identically to the same clause on one line."""
    one_line = "- Incorporate `blocker` findings into the revised plan and continue."
    wrapped = "- Incorporate `blocker` findings\n  into the revised plan and continue."
    assert absorb_hits(one_line) and absorb_hits(wrapped)
