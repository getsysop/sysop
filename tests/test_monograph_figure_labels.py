"""The monograph's figure labels must describe the shipped architecture — Phase 177.

Why this exists. Phase 171 retired the "reviewer-executor" shape (one sub-agent that
reviewed its own plan, self-classified the findings, then implemented and committed) and
replaced it with an orchestrator: a planner, an independent reviewer, classification held
by the orchestrator, an executor. The prose in `docs/workflow.html` was updated in the same
phase and correctly narrates the old shape in the past tense. **Its figure labels were
not**, and they drew the retired architecture as current for five more phases with the
whole suite green, because nothing read them. `tests/test_doc_currency.py` could not catch
it: Phase 118 inverted that module into a no-count ratchet asserting the monograph is never
*ahead* of `PHASE_LOG.md`, never that any of its content is current.

Why it is scoped to labels and not to the file. Phase 176 built a general regex screen over
prose for a defect of this family, measured it against the tree, and got eleven hits of
which all eleven were correct prose — the separation between a stale claim and an accurate
historical note is semantic, not lexical. A *label* is different in kind: a handful of words
with no room for a tense marker or a retirement clause, so a retired term in one is a defect
unconditionally. `test_prose_narrating_the_retired_shape_is_not_flagged` pins that boundary.

What the adversarial round changed, since every fix below is shaped by it:

- **The population was `<text>` and nothing else**, so the same defect planted in an SVG
  `aria-label`, `<title>`, `<desc>`, a `<figcaption>`, or in `docs/index.html` was invisible.
  All are now read. A caption is not where history belongs, so including captions is
  deliberate: if one ever needs the past tense, the prose blocks are where it goes.
- **The vocabulary was three literals over a raw substring test**, so a non-breaking hyphen,
  an en dash, an HTML entity, or an ordinary two-line wrapped label all walked through.
  Labels are normalized before matching.
- **`:1366` — the `/claim-task` glossary entry, which this phase's own record calls the most
  load-bearing of the four sites it fixed — was covered by nothing.** It is prose, so a
  screen is the wrong tool; `test_the_claim_task_glossary_describes_the_orchestrator` makes
  a *positive* assertion about it instead.
- **`claim_task_step_labels` pooled `/claim-task` nodes across all nine figures**, so adding
  an accurate `step 4 · claim the lock` annotation to the *lifecycle* figure reddened the
  *convention-map* figure's guard. Scoped to the figure the claim is about.
- **A step that merely mentioned the map counted as a step that reads it**, so a
  cross-reference reddened the guard. A reading verb is now required.
- **Two controls hardcoded the very literals they existed to prove were not hardcoded** —
  including one named `..._reads_the_skill_not_a_hardcoded_list`. Both derive now.

**Declared residual, not an oversight:** a label can still evade this by paraphrase — *"the
sub-agent grades its own findings"* names the retired property without any term in the
vocabulary. Closing that needs semantics, not a pattern, so it is out of reach in kind
rather than unattempted. The positive assertions (`test_the_claim_task_glossary_...`, the
derived step set) are the partial answer: they check that the *right* thing is said, which a
paraphrase of the wrong thing cannot satisfy.

`docs/workflow.html`, `docs/index.html` and the skill are all shipped, so this module runs
in the sterilized mirror too.
"""

import html
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MONOGRAPH = REPO_ROOT / "docs" / "workflow.html"
INDEX = REPO_ROOT / "docs" / "index.html"
CLAIM_TASK = REPO_ROOT / "core" / "skills" / "claim-task" / "SKILL.md"

# Vocabulary the shipped `_shared/adversarial-review.md` section
# "The reviewer-executor variant is retired" names as retired. Deliberately short: every
# entry must be a term that cannot appear innocently in a few-word diagram label.
RETIRED_IN_A_LABEL = (
    "reviewer-executor",
    "reviewer executor",
    "self-classif",
)

SVG_BLOCK_RE = re.compile(r"<svg\b.*?</svg>", re.S)
TEXT_EL_RE = re.compile(r"<(text|title|desc)\b[^>]*>(.*?)</\1>", re.S)
FIGCAPTION_RE = re.compile(r"<figcaption\b[^>]*>(.*?)</figcaption>", re.S)
ARIA_RE = re.compile(r'<svg\b[^>]*\baria-label="([^"]*)"')
NODE_G_RE = re.compile(r'<g class="node"[^>]*>(.*?)</g>', re.S)
STEP_TOKEN_RE = re.compile(r"\bstep (\d+[a-z]?)\b", re.I)
# The figure whose /claim-task node annotates where the convention map is read.
MAP_FIGURE_ARIA = "Convention promotion loop"


def _monograph() -> str:
    return MONOGRAPH.read_text(encoding="utf-8")


def normalize(raw: str) -> str:
    """Strip tags, unescape entities, fold dash variants, collapse whitespace, and close up
    spaces around hyphens — so a wrapped `<tspan>reviewer-</tspan> <tspan>executor</tspan>`
    reads the same as the one-line label. Every one of these was a round survivor."""
    s = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    s = s.translate({c: "-" for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212)})
    s = re.sub(r"\s+", " ", s)
    return re.sub(r"\s*-\s*", "-", s).strip().lower()


def figure_labels(html_text: str) -> list[str]:
    """Every label-like string: SVG `<text>`/`<title>`/`<desc>` bodies, SVG accessible
    names, and figure captions. Not body prose — see the module docstring."""
    labels = []
    for svg in SVG_BLOCK_RE.findall(html_text):
        labels += [normalize(body) for _, body in TEXT_EL_RE.findall(svg)]
    labels += [normalize(a) for a in ARIA_RE.findall(html_text)]
    labels += [normalize(c) for c in FIGCAPTION_RE.findall(html_text)]
    return [s for s in labels if s]


def retired_shape_labels(html_text: str) -> list[str]:
    out = []
    for label in figure_labels(html_text):
        if any(term in label for term in RETIRED_IN_A_LABEL):
            out.append(label)
        elif re.search(r"sub-?agent", label) and re.search(r"phase 29\b", label):
            # The retired provenance pairing. `/auto-build`'s `orchestrator · phase 29` is
            # correct and names no sub-agent, so it is not caught — see the control.
            out.append(label)
    return out


def claim_task_step_labels(html_text: str) -> list[tuple[str, str]]:
    """(step token, label) for `step N` cited in a `/claim-task` node of the convention-map
    figure — scoped to that figure, because other figures may legitimately annotate other
    steps of the same skill."""
    found = []
    for svg in SVG_BLOCK_RE.findall(html_text):
        aria = ARIA_RE.search(svg)
        if not aria or MAP_FIGURE_ARIA.lower() not in aria.group(1).lower():
            continue
        for group in NODE_G_RE.findall(svg):
            bodies = [normalize(b) for _, b in TEXT_EL_RE.findall(group)]
            if "/claim-task" not in bodies:
                continue
            for body in bodies:
                for token in STEP_TOKEN_RE.findall(body):
                    found.append((token.lower(), body))
    return found


def claim_task_steps() -> set[str]:
    return {
        m.group(1).lower()
        for m in re.finditer(
            r"^#{2,3} Step (\d+[a-z]?)\b", CLAIM_TASK.read_text(encoding="utf-8"), re.M
        )
    }


def steps_that_read_the_convention_map() -> set[str]:
    """Steps whose bodies actually READ `convention_map.md`, derived by locating each read
    and walking back to its enclosing `Step N` heading.

    Existence is the wrong test and the author-side battery proved it: the defect this guard
    exists for was the figure citing `step 6`, and Step 6 **is** a defined step — it is just
    no longer the one that reads the map. A reading verb is required because the round showed
    a bare cross-reference ("conventions live in `.claude/convention_map.md`") otherwise
    enrolled an unrelated step and reddened the guard on a legitimate edit.
    """
    text = CLAIM_TASK.read_text(encoding="utf-8")
    headings = [
        (m.start(), m.group(1).lower())
        for m in re.finditer(r"^#{2,3} Step (\d+[a-z]?)\b", text, re.M)
    ]
    steps = set()
    for hit in re.finditer(r"convention_map\.md", text):
        line_start = text.rfind("\n", 0, hit.start()) + 1
        line = text[line_start : text.find("\n", hit.start())]
        if not re.search(r"\b(read|reads|look up|looks up|scan|scans|consult|consults)\b",
                         line, re.I):
            continue
        enclosing = [name for pos, name in headings if pos < hit.start()]
        if enclosing:
            steps.add(enclosing[-1])
    return steps


# --- the guards -------------------------------------------------------------------


def test_no_figure_label_names_the_retired_shape():
    for path in (MONOGRAPH, INDEX):
        if not path.is_file():
            continue
        offenders = retired_shape_labels(path.read_text(encoding="utf-8"))
        assert offenders == [], (
            f"{path.name}: figure labels still draw the retired reviewer-executor "
            f"architecture: {offenders}. A label has no room to mark something as history — "
            "if the shape is being narrated as past, that belongs in prose."
        )


def test_the_claim_task_glossary_describes_the_orchestrator():
    """The site this phase's record calls the most load-bearing of the four, and the one no
    guard covered until the round said so. A positive assertion rather than a screen: the
    entry must name the split, which a reversion to "a single sub-agent owns the adversarial
    review, the implementation, the verification, and the commit" cannot satisfy."""
    m = re.search(r"<dt>/claim-task.*?<dd>(.*?)</dd>", _monograph(), re.S)
    assert m, "the /claim-task glossary entry is gone; this guard's anchor needs revisiting"
    entry = normalize(m.group(1))
    missing = [r for r in ("planner", "reviewer", "executor") if r not in entry]
    assert not missing, (
        f"the /claim-task glossary entry no longer names {missing} — Phase 171 split the "
        "work across a planner, an independent reviewer, an orchestrator-held classification "
        f"and an executor, and this entry is a reader's definition of the skill. Entry: {entry!r}"
    )
    assert not re.search(r"a single sub-agent|one sub-agent (owns|does|handles)", entry), (
        "the /claim-task glossary entry has reverted to describing one sub-agent that owns "
        "review, implementation, verification and the commit — the retired shape"
    )


def test_every_claim_task_step_a_figure_cites_exists_in_the_skill():
    defined = claim_task_steps()
    assert defined, "no '## Step N' headings found in claim-task/SKILL.md"
    cited = claim_task_step_labels(_monograph())
    assert cited, "no '/claim-task' node in the map figure cites a step — anchor needs revisiting"
    stale = [(tok, label) for tok, label in cited if tok not in defined]
    assert stale == [], (
        f"the monograph cites /claim-task steps the shipped skill does not define: {stale}. "
        f"Defined: {sorted(defined)}."
    )


def test_the_map_figure_cites_the_steps_that_actually_read_the_map():
    """The stronger half. The figure's `/claim-task` node annotates *where the convention map
    is read*, so the cited steps must be exactly the steps that read it."""
    expected = steps_that_read_the_convention_map()
    assert expected, (
        "no `convention_map.md` read found under any Step heading in claim-task/SKILL.md — "
        "this guard's anchor needs revisiting before it can mean anything"
    )
    cited = {tok for tok, _ in claim_task_step_labels(_monograph())}
    assert cited == expected, (
        f"the convention-map figure cites /claim-task steps {sorted(cited)}, but the steps "
        f"that actually read `convention_map.md` are {sorted(expected)}. Citing a step that "
        "merely exists is not enough — Phase 171 renumbered this skill and the figure kept "
        "pointing at steps that had stopped doing the thing it describes."
    )


# --- controls ---------------------------------------------------------------------


def test_prose_narrating_the_retired_shape_is_not_flagged():
    """THE control. The monograph correctly narrates the retired shape in past-tense prose,
    and that must never trip this guard — an over-strict version would push the project to
    delete honest history to go green."""
    text = _monograph()
    assert "reviewer-executor" in text.lower(), (
        "the monograph no longer narrates the retired shape anywhere — this control has "
        "nothing to protect, which most likely means the history was deleted to satisfy "
        "the guard above"
    )
    assert retired_shape_labels(text) == [], (
        "prose mentioning the retired shape leaked into the label population — the guard "
        "has stopped being scoped to labels"
    )


def test_correct_phase_29_provenance_is_not_flagged():
    """`/auto-build` really does date to Phase 29 and its node says so. The retired-pairing
    rule must catch `sub-agent · phase 29` without catching `orchestrator · phase 29`."""
    assert "orchestrator · phase 29" in _monograph(), "anchor gone; control needs re-pointing"
    assert retired_shape_labels(_monograph()) == []
    assert retired_shape_labels(
        '<svg><text>single sub-agent · phase 29</text></svg>'
    ), "the retired provenance pairing was not caught"


def test_the_label_guard_survives_ordinary_label_authoring():
    """Round survivors A1-A4: a non-breaking hyphen, an en dash, an HTML entity and a
    two-line wrapped label are all how people really write SVG labels."""
    for variant in (
        "<svg><text>reviewer‑executor</text></svg>",
        "<svg><text>reviewer–executor</text></svg>",
        "<svg><text>reviewer&#45;executor</text></svg>",
        '<svg><text><tspan>reviewer-</tspan>\n   <tspan dy="14">executor sub-agent</tspan></text></svg>',
        "<svg><title>reviewer-executor sub-agent</title></svg>",
        "<svg><desc>the reviewer-executor finishes</desc></svg>",
        '<svg aria-label="the reviewer-executor sub-agent finishes"><text>x</text></svg>',
        "<figcaption>The reviewer-executor self-classifies.</figcaption>",
    ):
        assert retired_shape_labels(variant), f"evaded the guard: {variant!r}"


def test_the_label_guard_is_not_vacuous():
    """Derives its own anchor rather than hardcoding a label literal — the round reddened
    the first version simply by rewording the label this control pinned."""
    text = _monograph()
    m = re.search(r'(<text\b[^>]*>)([^<]{6,40})(</text>)', text)
    assert m, "no simple <text> label found to mutate"
    planted = text.replace(m.group(0), f"{m.group(1)}reviewer-executor{m.group(3)}", 1)
    assert planted != text
    assert retired_shape_labels(planted), "a retired term planted in a label was not caught"
    in_prose = text.replace("</body>", "<p>reviewer-executor self-classified.</p></body>", 1)
    assert retired_shape_labels(in_prose) == [], (
        "the guard flagged prose — it is reading the file rather than the label population"
    )


def test_the_step_guard_is_not_vacuous():
    text = _monograph()
    _, label = claim_task_step_labels(text)[0]
    m = re.search(re.escape(label.split(" ·")[0]).replace(r"\ ", r"\s+"), text, re.I)
    assert m, f"could not re-find the label {label!r} in the source"
    broken = text[: m.start()] + "step 99" + text[m.end():]
    stale = [t for t, _ in claim_task_step_labels(broken) if t not in claim_task_steps()]
    assert "99" in stale, "drifting a cited step number was not detected"


def test_the_step_guard_reads_the_skill_not_a_hardcoded_list():
    """Negative control in the other direction — and the round caught this very test
    hardcoding ('7','7a','7e'), the literals its name promises it does not use. It now
    asserts only the *relationship*: whatever the skill says, the figure must agree."""
    expected = steps_that_read_the_convention_map()
    cited = {tok for tok, _ in claim_task_step_labels(_monograph())}
    assert expected and cited and cited == expected, (
        f"figure cites {sorted(cited)}, skill reads the map at {sorted(expected)}"
    )
    assert expected <= claim_task_steps(), (
        "a map-reading step is not a defined step heading — the derivation is broken"
    )
