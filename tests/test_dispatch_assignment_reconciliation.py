"""Phase 203 — the routing key must be able to express the coverage question.

`/security-audit` dispatches per OWASP **category**; `/codebase-review` dispatches from a
hand-authored **table** of convention_map section names. Neither key is the thing coverage is
a property of, which is **files** — so both skills can be worked to completion over a manifest
containing files nobody was assigned.

The map-coverage sweeps (Step 2a-1 / 2a-2) cannot see this: they ask whether a file is matched
by *some* section. A file matched by a section nobody audits is matched, and is counted covered.

These guards are **derived**, not pinned. Each builds its population from the shipped maps and
skills and asserts the population is non-empty first, because every invariant here is trivially
satisfiable by an empty set — which is how a coverage guard passes while covering nothing.

What was live when this was written, all four verified by command:
  * `A04` and `A08` appeared under `Check:` in the shipped maps and in no agent's mandate.
  * Two sections carried *only* `Check:` bullets with no category token to route on.
  * Six `§"…"` citations in `/security-audit` and six in `/codebase-review` named no section.
  * 11 of 36 security-map sections and 13 of 28 convention-map sections had no owner.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SECURITY_SKILL = ROOT / "core/skills/security-audit/SKILL.md"
REVIEW_SKILL = ROOT / "core/skills/codebase-review/SKILL.md"

SECTION_RE = re.compile(r"^## (?P<globs>.+?) — (?P<name>.+?)\s*$", re.M)
CITATION_RE = re.compile(r'§"([^"]+)"')

# The OWASP codes. NOT the whole vocabulary — the maps also label bullets with non-OWASP
# category names (`XSS`, `Logging`, `Privacy`, `Resilience`, `LLM Security`), and the first
# version of this module hand-listed those. That allowlist is what the round broke: it omitted
# `Privacy` (owned by Agent 5, so a legal Privacy rule hard-failed CI with "audited by nobody")
# and `Resilience` (owned by nobody, two shipped bullets, invisible to the guard whose whole
# job is finding exactly that). A hardcoded vocabulary in the module that exists to retire
# hardcoded populations — so the vocabulary is now DERIVED from the maps, below.
OWASP_CODES = tuple(f"A{n:02d}" for n in range(1, 11))
BOLD_LEAD = re.compile(r"^\s*-\s+\*\*(?P<label>[^*]+?)\*\*")


def _token_of(bullet: str) -> str | None:
    """The category token a `Check:` bullet opens with, or None if it opens with none.

    A token is the first word of the bold lead-in (`- **A03 Injection**: …` -> `A03`,
    `- **Privacy**: …` -> `Privacy`). Deriving it means an unrecognised label shows up as an
    unowned category rather than as no category at all — visible instead of invisible.
    """
    m = BOLD_LEAD.match(bullet if bullet.lstrip().startswith("-") else f"- {bullet}")
    if not m:
        return None
    label = m.group("label").split(":")[0].split("(")[0].strip()
    return label.split()[0] if label.split() else None


def _map_vocabulary() -> dict[str, list[str]]:
    """token -> the sections that use it, derived across every shipped security map."""
    vocab: dict[str, list[str]] = {}
    for (pack, name), sec in _sections("security_map").items():
        for unit in sec["bullets"]:
            tok = _token_of(unit)
            if tok:
                vocab.setdefault(tok, []).append(f'{pack} §"{name}"')
    return vocab


def _map_files(kind: str) -> list[Path]:
    core = ROOT / f"core/companion/{kind}.md"
    packs = sorted((ROOT / "packs").glob(f"*/companion/{kind}.md"))
    assert core.exists(), f"core/companion/{kind}.md is gone — the derivation is broken"
    assert packs, f"no pack ships a {kind}.md — the derivation is broken"
    return [core, *packs]


# The `Check:` marker ships in four shapes. A bullets-only parse reads one of them and
# silently drops the other three — and a section parsed as having no Check content is
# indistinguishable from one that genuinely has none, so it falls out of every class below.
# Shipped today: `**Check:**` (most), `**Check:** A05 (…)` inline (core §Container Build,
# §Repo Hygiene), `**Check: A01** — …` colon-inside-the-bold (postgres §Database Migrations).
CHECK_MARKER = re.compile(r"\*\*Check\b[^*\n]*\*\*:?|\*\*Check\*\*:?", re.I)
SKIP_MARKER = re.compile(r"\*\*Skip\b", re.I)

# Expected section totals, asserted rather than floored. A floor of 25 against a real 36 left
# eleven sections of slack: a drifted `## X — Y` separator or a renamed `**Check:**` marker
# silently emptied part of the population and every assertion below stayed green. Bump these
# deliberately when a pack is added — that is the point.
EXPECTED_SECTIONS = {"security_map": 36, "convention_map": 28}

# How many sections must parse a non-empty `Check:` region. Without this, renaming the
# marker (`**Check:**` -> `**Checks:**`) empties a section's region, and every routing
# assertion below skips an empty region rather than failing on it — the guard goes quiet
# exactly when the map stops being parseable.
EXPECTED_WITH_CHECK = 36


def _sections(kind: str) -> dict[tuple[str, str], dict]:
    """(pack, name) -> section facts, across every shipped map.

    Keyed on the PAIR, not the name: a name-keyed dict silently deletes a section when two
    packs happen to use the same heading, and the later file in sort order wins. There is no
    collision in the tree today, which is exactly why it would arrive unnoticed.
    """
    out: dict[tuple[str, str], dict] = {}
    per_file: dict[str, int] = {}
    for path in _map_files(kind):
        pack = "core" if "packs" not in path.parts else path.parts[path.parts.index("packs") + 1]
        text = path.read_text(encoding="utf-8")
        matches = list(SECTION_RE.finditer(text))
        assert matches, f"{path}: no `## <globs> — <Name>` section headers parsed"
        per_file[str(path)] = len(matches)
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[m.start():end]
            globs = re.findall(r"`([^`]+)`", m.group("globs"))

            marker = CHECK_MARKER.search(body)
            if marker:
                region = body[marker.end():]
                skip = SKIP_MARKER.search(region)
                region = region[: skip.start()] if skip else region
                # The marker line itself may carry the category (`**Check: A01** — …`), so
                # fold the matched marker text back in rather than discarding it.
                region = marker.group(0) + region
            else:
                region = ""

            bullets = [b.strip() for b in re.findall(r"^\s*-\s+(.*)$", region, flags=re.M) if b.strip()]
            # The inline remainder — everything on the marker line after `Check:` — is a
            # routing unit in its own right when the section has no bullets.
            inline = region.split("\n", 1)[0]
            inline = CHECK_MARKER.sub("", inline).strip(" —-:").strip()

            key = (pack, m.group("name"))
            assert key not in out, f"duplicate section {key} within one map file"
            out[key] = {
                "globs": globs,
                "bullets": bullets,
                "inline": inline,
                "region": region,
                "pack": pack,
                # A section whose globs are ALL `<placeholder>` tokens binds no file on a
                # consumer install, so it needs no auditor until localized.
                "placeholder": bool(globs) and all("<" in g for g in globs),
                # Scoped to the marker line. A whole-body substring test was satisfied by the
                # words "Check:** None" appearing inside an unrelated prose bullet, which
                # carved the entire section out of both routing guards.
                "check_none": bool(re.match(r"(?i)^none\b", inline)),
            }
    assert all(n > 0 for n in per_file.values()), f"a {kind} file parsed to zero sections: {per_file}"
    return out


def _categories_in(sec: dict) -> set[str]:
    """Every category token in the section's Check region — bullet-led or inline.

    The inline shapes matter: `**Check:** A05 (…)` and `**Check: A01** — …` ship today on
    `core §Container Build`, `core §Repo Hygiene` and `postgres §Database Migrations`, and a
    bullets-only read silently drops all three. Two of those bind files on every install.
    """
    toks = {t for t in (_token_of(b) for b in sec["bullets"]) if t}
    # The RAW first line of the region, marker included: `**Check: A01** — …` puts the code
    # inside the bold, so stripping the marker to get `inline` takes the code with it.
    marker_line = sec["region"].split("\n", 1)[0]
    for code in OWASP_CODES:
        if re.search(rf"\b{code}\b", marker_line):
            toks.add(code)
    return toks


def _labelled(bullet: str) -> bool:
    return _token_of(bullet) is not None


def _norm(text: str) -> str:
    """Strip the characters that let a reversal hide between two words.

    The round that produced this found seven variants of one sentence walking through a
    `\\bcoverage contract\\b` screen: markdown emphasis, backticks, a non-breaking space, an
    `&nbsp;` entity, a hard-wrap newline, a double space, and a hyphen. Every one of them is
    invisible to a reader and fatal to a word boundary, so they are normalized away before
    any screen runs — including the *presence* assert, which is where two legal reformats
    (bolding a word, re-wrapping a paragraph) were turning the required check red.
    """
    text = text.replace("&nbsp;", " ").replace(" ", " ").replace("­", "")
    text = re.sub(r"[*_`]", "", text)
    text = re.sub(r"[\s\-‐-―]+", " ", text)
    return text


# --------------------------------------------------------------------------- #
# (1) citation integrity — the drift class, in both skills
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "skill,kind",
    [(SECURITY_SKILL, "security_map"), (REVIEW_SKILL, "convention_map")],
    ids=["security-audit", "codebase-review"],
)
def test_every_cited_section_name_resolves(skill: Path, kind: str) -> None:
    """A `§"Name"` a skill hands an agent must be a name some shipped map carries.

    This is the defect that hid the real multi-assignment count: `/security-audit` cited both
    `§"LLM-using pipeline"` and `§"LLM-using pipeline modules"` — one section, two spellings —
    so a name-keyed parse reported 6 multi-assigned sections where there were 7. Three more
    cited a section's *glob* (`§"Dockerfile"`) where its name (`Container Build`) was wanted,
    and `/codebase-review` cited three **security**-map names from its convention-map table.
    """
    real = {name for _pack, name in _sections(kind)}
    # `/codebase-review` legitimately NAMES security-map sections in prose when it explains the
    # cross-map boundary. Scanning the whole file made that a hard CI failure asserting "an
    # agent was handed a name" — false for prose — and the shipped note had to write
    # `core §Dockerfile` unquoted to get past this module. Citations bind where they are
    # HANDED to an agent: the dispatch table's rows, and the roster's file lists.
    if kind == "convention_map":
        body = "\n".join(
            ln for ln in skill.read_text(encoding="utf-8").splitlines() if ln.startswith("| ")
        )
    else:
        body = skill.read_text(encoding="utf-8")
    assert len(_sections(kind)) == EXPECTED_SECTIONS[kind], (
        f"{kind}: parsed {len(_sections(kind))} sections, expected "
        f"{EXPECTED_SECTIONS[kind]} — a drifted header or Check marker silently shrinks the "
        "population every assertion in this module is derived from"
    )
    cited = set(CITATION_RE.findall(body))
    assert len(cited) >= 15, (
        f"{skill.name}: only {len(cited)} section citations found — the extraction broke, and "
        "an empty population satisfies every assertion below"
    )
    dangling = sorted(cited - real)
    assert not dangling, (
        f"{skill.name}: {len(dangling)} cited section name(s) match no {kind} section: "
        f"{dangling}. An agent handed a name nothing carries receives no bullets, silently."
    )


# --------------------------------------------------------------------------- #
# (2) every section has an owner
# --------------------------------------------------------------------------- #

def _roster_headings() -> str:
    """The agent headings, verbatim — the one place a category's owner is declared.

    Membership is a substring test against these headings and nothing else. The earlier
    version intersected them with a hand-written token list, which meant a category the maps
    used but the list omitted could never be reported as unowned: the guard's blind spot and
    the defect it hunts were the same set.
    """
    text = SECURITY_SKILL.read_text(encoding="utf-8")
    heads = re.findall(r"^### Agent \d+: .+$", text, re.M)
    assert len(heads) >= 5, f"agent-heading extraction found {len(heads)} — derivation broken"
    return "\n".join(heads)


def test_every_owasp_category_the_maps_use_has_an_agent() -> None:
    """The roster must staff every category the shipped maps actually ask for.

    `A04` and `A08` shipped under `Check:` in `packs/beancount` with no agent holding either,
    so four concrete security rules were unroutable by construction — while the skill's own
    Step 3-0 called the roster "the *coverage* contract".
    """
    headings = _roster_headings()

    used = _map_vocabulary()
    for (pack, name), sec in _sections("security_map").items():
        for tok in _categories_in(sec):
            used.setdefault(tok, []).append(f'{pack} §"{name}"')
    assert len(used) >= 10, f"only {sorted(used)} categories found in the maps — derivation broken"

    # Owned == named in some agent's heading. Derived on BOTH sides, so a label the maps
    # invent shows up here instead of falling through a hand-written allowlist.
    unowned = sorted(t for t in used if not re.search(rf"\b{re.escape(t)}\b", headings))
    assert not unowned, (
        "the shipped security maps ask for categories no agent's heading names: "
        + ", ".join(f"{t} (used by {used[t][0]})" for t in unowned)
        + ". A category-keyed dispatch cannot route a category the roster omits, and nothing "
        "downstream reports the omission."
    )


def test_every_convention_map_section_is_named_by_a_dispatch_row() -> None:
    """`/codebase-review` dispatches from a hand table; a section no row names has no reviewer.

    13 of 28 sections had no row when this was written — the whole beancount pack, both LLM
    prompt-template sections, `core §"Skill Markdown Files"`, and more.
    """
    real = {name for _pack, name in _sections("convention_map")}
    assert len(_sections("convention_map")) == EXPECTED_SECTIONS["convention_map"], (
        "convention_map section count drifted from the expected total"
    )

    # Scoped to the 3-pre dispatch table. A whole-file scan over pipe-prefixed lines was
    # satisfied by a SECOND table elsewhere in the file listing sections as consciously NOT
    # reviewed — so a table documenting the debt discharged the guard that the debt exists.
    text = REVIEW_SKILL.read_text(encoding="utf-8")
    table = text.split("### 3-pre. Convention Scoping")[1].split("\nWhen constructing each")[0]
    cited = set()
    rows = 0
    for line in table.splitlines():
        if line.startswith("| ") and '§"' in line:
            rows += 1
            cited.update(CITATION_RE.findall(line))
    assert rows >= 15, f"only {rows} dispatch-table rows parsed — derivation broken"
    assert cited, "no dispatch-table rows parsed — derivation broken"

    orphans = sorted(set(real) - cited)
    assert not orphans, (
        f"{len(orphans)} convention_map section(s) are named by no row of the Step 3-pre "
        f"dispatch table, so their files have no reviewer: {orphans}. The Step 2a-2 coverage "
        "sweep reports these files as covered, because they ARE matched by a section."
    )


def test_every_security_map_section_routes_to_some_agent() -> None:
    """Same invariant on the security side, keyed on categories rather than on row names."""
    headings = _roster_headings()
    sections = _sections("security_map")
    with_check = [k for k, v in sections.items() if v["region"].strip()]
    assert len(with_check) == EXPECTED_WITH_CHECK, (
        f"{len(with_check)} of {len(sections)} security_map sections parsed a `Check:` region, "
        f"expected {EXPECTED_WITH_CHECK}. A renamed or reshaped Check marker empties the region "
        "silently, and every routing assertion here skips an empty region instead of failing."
    )
    assert len(sections) == EXPECTED_SECTIONS["security_map"], (
        f"security_map section count drifted: parsed {len(sections)}"
    )

    unrouted = []
    for (pack, name), sec in sections.items():
        if not sec["region"].strip() or sec["check_none"]:
            continue  # `Check: None` is an explicit, stated decision
        if sec["placeholder"] and not sec["region"].strip():
            continue  # binds no file until the consumer localizes it
        if not any(re.search(rf"\b{re.escape(t)}\b", headings) for t in _categories_in(sec)):
            unrouted.append(f"{pack} §\"{name}\"")
    assert not unrouted, (
        f"{len(unrouted)} security_map section(s) carry Check bullets no agent's categories "
        f"reach: {sorted(unrouted)}. Their files are matched, and audited by nobody."
    )


# --------------------------------------------------------------------------- #
# (3) every Check: bullet is routable at all
# --------------------------------------------------------------------------- #

def test_no_section_is_wholly_unlabelled() -> None:
    """A section whose every `Check:` bullet lacks a category token has no route, by construction.

    Two shipped sections were in this state — `core §"Skill Markdown & Check Registry"` (4 of 4)
    and `python §"Python Type Checker Config"` (1 of 1). This is the purest form of the defect:
    not an overlap, not a gap in a file list, but a rule the routing key cannot express.

    Partially-unlabelled sections are deliberately NOT failed here: their labelled bullets carry
    the section to an agent and the unlabelled ones ride along. Step 3-0b reports those; this
    guard holds the line that costs coverage.
    """
    offenders = {}
    for (pack, name), sec in _sections("security_map").items():
        if sec["check_none"] or not sec["region"].strip():
            continue
        units = sec["bullets"] or ([sec["inline"]] if sec["inline"] else [])
        if not units:
            continue
        # An inline Check counts as labelled when a token appears anywhere on it; a bullet
        # must OPEN with one, which is the shipped convention for bullets.
        ok = any(_labelled(u) for u in units) or bool(_categories_in(sec))
        if not ok:
            offenders[f"{pack} §\"{name}\""] = len(units)
    assert not offenders, (
        "section(s) whose every Check bullet lacks an OWASP category token, so a category-keyed "
        f"dispatch cannot reach them at all: {offenders}"
    )


# --------------------------------------------------------------------------- #
# (4) the step exists, in both skills, and runs BEFORE dispatch
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "skill,dispatch_marker",
    [
        (SECURITY_SKILL, "### Agent 1:"),
        (REVIEW_SKILL, "### 3-pre. Convention Scoping"),
    ],
    ids=["security-audit", "codebase-review"],
)
def test_reconciliation_step_precedes_dispatch(skill: Path, dispatch_marker: str) -> None:
    """Ordering is the whole point: a reconciliation run after dispatch reports a fait accompli.

    Prose asserting an order is not a test of it — this reads the two offsets.
    """
    text = skill.read_text(encoding="utf-8")
    assert "### 3-0b. Assignment reconciliation" in text, (
        f"{skill.name}: lost its Step 3-0b assignment reconciliation"
    )
    assert dispatch_marker in text, f"{skill.name}: dispatch marker {dispatch_marker!r} is gone"
    assert text.index("### 3-0b. Assignment reconciliation") < text.index(dispatch_marker), (
        f"{skill.name}: Step 3-0b sits AFTER dispatch begins — it can only describe a fan-out "
        "that already happened"
    )


def _reconciliation_block(skill: Path) -> str:
    """The step, PLUS the ~12 lines immediately above its heading.

    A block that starts at the heading cannot see the sentence that demotes it, and a banner
    directly above the heading (`> **Optional.** Skip the step below unless the maps changed`)
    is the most natural place a maintainer would put one. It defeated the first version of the
    laundering screen while every other assertion stayed green.
    """
    text = skill.read_text(encoding="utf-8")
    head = text.index("### 3-0b. Assignment reconciliation")
    preamble = "\n".join(text[:head].split("\n")[-12:])

    # End at the FIRST following step-level construct, not merely the next `### ` heading.
    # In `/security-audit` the next `### ` is `### Agent 1:`, so a heading-only bound swept
    # the entire dispatch prose and the do-not-report list into "the block" — which made the
    # laundering screen fire on unrelated pre-existing text and, worse, made it look strong
    # while scanning ~90 lines it has no business asserting over.
    rest = text[head:]
    ends = [i for i in (rest.find("\n### ", 1), rest.find("\n**CRITICAL: Read")) if i > 0]
    return preamble + (rest[: min(ends)] if ends else rest)


def _reconciliation_body(skill: Path) -> str:
    text = skill.read_text(encoding="utf-8")
    return text.split("### 3-0b. Assignment reconciliation")[1].split("\n### ")[0]


@pytest.mark.parametrize(
    "skill,required",
    [
        (SECURITY_SKILL, ("sections with no agent", "categories with no agent",
                          "sections with no category at all")),
        (REVIEW_SKILL, ("cited names with no section", "sections with no row",
                        "globs claimed by >1 row")),
    ],
    ids=["security-audit", "codebase-review"],
)
def test_reconciliation_reports_each_class_by_name(skill: Path, required: tuple) -> None:
    """A step with no report block is a step whose result nobody can read.

    Pinned by **class label**, not by a count of `<N>` placeholders: the first version of this
    guard counted the placeholders, and a mutation that merged two named classes into one
    `unowned things: <N>` line kept the count at three and walked straight through. A number
    that cannot say whether it is a drifted citation or an unaudited section is not a report.
    """
    block = _reconciliation_block(skill)
    # The template must survive as a FENCED block with slots, not as prose that happens to
    # contain the label words: deleting the fence and mentioning the three classes in a
    # sentence ("no need to count them") satisfied the label-only version of this guard while
    # removing the artifact Step 5b consumes.
    fences = re.findall(r"```\n(.*?)```", block, flags=re.S)
    templates = [f for f in fences if "Assignment reconciliation:" in f]
    assert templates, (
        f"{skill.name}: 3-0b's report template is no longer a fenced block — prose naming the "
        "classes is not an artifact the round header can carry"
    )
    template = templates[0]
    assert template.count("<N>") >= 3, (
        f"{skill.name}: the report template lost its count slots"
    )
    missing = [label for label in required if label not in template]
    assert not missing, (
        f"{skill.name}: 3-0b no longer reports {missing} as a named class. Collapsing classes "
        "makes the count unactionable — the reader cannot tell which failure they have."
    )


@pytest.mark.parametrize(
    "skill", [SECURITY_SKILL, REVIEW_SKILL], ids=["security-audit", "codebase-review"]
)
def test_reconciliation_is_not_framed_as_optional(skill: Path) -> None:
    """Laundering screen. A rule can be left byte-perfect and framed as skippable.

    This is the class `_shared/adversarial-review.md` records walking through four guards in an
    earlier round, and it walked through this module's first draft too: the step survived intact
    with its opening line rewritten to "Advisory only — skip it when the map looks settled".
    A blocklist of measured phrasings, honest about being that rather than a proof.
    """
    block = _reconciliation_block(skill)
    demotion = re.compile(
        r"(?i)("
        r"\badvisory\b|\boptional\b|\bskip (?:it|this|the step)\b|\bwhen time allows\b|"
        r"\bnice[ -]to[ -]have\b|\bat your discretion\b|\bonly if you suspect\b|"
        r"\bnot required\b|\bneed not\b|\bmay be omitted\b|\byou may omit\b|"
        r"\bdo not need to run\b|\bdoes not need to run\b|\bdo not have to\b|"
        r"\brecommended, not\b|\bnon[- ]blocking\b|\bbest[- ]effort\b|\binformational\b|"
        r"\bhistorically\b|\bdeprecated\b|\bsuperseded\b|\bretained for reference\b|"
        r"\bfor reference only\b|\bnot an instruction\b|\bno longer (?:required|applies)\b|"
        r"\bin practice most\b|\bskipping it is normal\b|\bconvenience, not\b|"
        r"\brun it only when\b|\bunless the maps changed\b|\bdocs-only rounds\b"
        r")"
    )
    hit = demotion.search(_norm(block))
    assert not hit, (
        f"{skill.name}: Step 3-0b is framed as skippable ({hit.group(0)!r}). The step is the "
        "only check that can see an unowned section; making it discretionary restores the gap "
        "while leaving every other assertion in this module green."
    )
    assert re.search(r"(?i)\brun(s)? on every round\b|every round", block), (
        f"{skill.name}: Step 3-0b no longer states that it runs on every round"
    )
    late = re.search(
        r"(?i)\bafter (?:the )?(?:agents|dispatch|workers|the fan-?out)\b|\bonce the agents\b",
        _norm(block),
    )
    assert not late, (
        f"{skill.name}: Step 3-0b tells itself to run after dispatch ({late.group(0)!r}) while "
        "sitting before it. The offset guard reads position; this reads what the step SAYS, and "
        "an operator follows the sentence."
    )


def test_the_roster_does_not_reclaim_the_coverage_contract() -> None:
    """Reversal guard. The sentence this phase corrected is the one most likely to grow back.

    Step 3-0 called the roster "the *coverage* contract"; it is keyed on categories, and
    coverage is a property of files. A future edit restoring that phrasing re-asserts exactly
    the claim `A04`/`A08` falsified.
    """
    text = _norm(SECURITY_SKILL.read_text(encoding="utf-8"))
    assert "The roster is not a coverage contract" in text, (
        "Step 3-0 lost the correction: the roster is a lens contract, not a coverage one"
    )

    # Screen EVERY mention, not one pinned occurrence: a pin on the corrected sentence is
    # satisfied while its inverse sits in the next paragraph. Synonyms are included because
    # the proposition, not the phrasing, is what must not come back — an independent battery
    # restated it as "the coverage guarantee" and as "establishes coverage" and both walked
    # through a phrase-exact screen.
    claims = re.compile(
        r"(?i)[^.\n]*\b(coverage contract|coverage guarantee|"
        r"roster (?:is what |)establishes coverage|establishes coverage over the manifest)\b[^.\n]*"
    )
    for m in claims.finditer(text):
        clause = m.group(0)
        # The negation must attach to THIS assertion, not merely appear somewhere nearby:
        # "not merely a lens contract — it is the coverage contract" contains `not` and is a
        # reversal, so require the negation to sit within a few words of the phrase and with
        # no intervening "it is"/"but"/"—" that starts a fresh assertion.
        negated = re.search(
            r"\b(?:is|are|was|be)\s+(?:not|never)\s+(?:a|the|its)?\s*"
            r"(?:coverage contract|coverage guarantee)\b"
            r"|\bnot\s+(?:a|the)\s+(?:coverage contract|coverage guarantee)\b",
            clause, re.I,
        )
        assert negated, (
            "an un-negated assertion that the roster establishes coverage survives in "
            f"Step 3-0: {clause.strip()!r}. That is the claim A04 and A08 falsified — four "
            "shipped Check bullets in categories no agent owned — and the reason 3-0b exists."
        )


def test_dispatch_tables_do_not_reclaim_disjointness() -> None:
    """Reversal guard, sibling of the above, on the `/codebase-review` side."""
    text = _norm(REVIEW_SKILL.read_text(encoding="utf-8"))
    # Same treatment as its security-side sibling, and for the same reason: a bare literal
    # pin was defeated by three rewordings that assert exactly the same false thing.
    claims = re.compile(
        r"(?i)[^.\n]*\b(agents? (?:have|has) disjoint|disjoint file scopes?|"
        r"scopes? are disjoint|disjoint by construction|never see the same file|"
        r"agents never overlap|no two agents ever see)\b[^.\n]*"
    )
    for m in claims.finditer(text):
        clause = m.group(0)
        # `never` is deliberately NOT a negation token here: "agents never overlap" and
        # "never see the same file" are ASSERTIONS of disjointness, and treating the word as
        # a negation let both walk through. This is the R06 negation-scope defect again, on
        # the other side of the module, found by re-running the round's own survivors.
        negated = re.search(
            r"\bnot\b|\bmostly\b|\bused to claim\b|\brather than\b|\bis false\b", clause, re.I
        )
        assert negated, (
            "the dispatch bullet re-asserts disjoint agent file scopes: "
            f"{clause.strip()!r} — false as written, because `<app dir>/(auth)/page.tsx` matches "
            "both the Pages & API row (`**/page.tsx`) and the App Shell row (`(auth)/*.tsx`)."
        )


def test_the_dispatch_table_assigns_each_section_once() -> None:
    """The commit that built this table claimed "0 overlap" and nothing checked it.

    Overlap is not a correctness bug — two reviewers on one file duplicate work rather than
    corrupt it — but it is a claim the record makes, and an unguarded claim is the shape this
    phase spent itself on. Overlays are the legitimate case and they compose *within* a row
    (`python §"…" + postgres §"… (overlay)"`), so a section reaching two different rows is
    the thing to catch.
    """
    table = REVIEW_SKILL.read_text(encoding="utf-8").split("### 3-pre. Convention Scoping")[1]
    table = table.split("\nWhen constructing each")[0]
    owners: dict[str, set[str]] = {}
    for line in table.splitlines():
        if line.startswith("| ") and '§"' in line:
            scope = line.split("|")[1].strip()
            for sec in CITATION_RE.findall(line):
                owners.setdefault(sec, set()).add(scope)
    assert owners, "no dispatch-table rows parsed — derivation broken"
    multi = {k: sorted(v) for k, v in owners.items() if len(v) > 1}
    assert not multi, (
        f"section(s) claimed by more than one dispatch row: {multi}. Fold them into one row "
        "the way the Pipeline row folds its overlay, or the 'one accountable owner' the table "
        "is supposed to provide is not what it provides."
    )


def test_the_workflow_spec_roster_matches_the_shipped_agents() -> None:
    """`WORKFLOW.md` § 2.6 restates the roster, and the restatement had drifted.

    It rendered Agent 3 as `(A10, A05)`, dropping `LLM`, and this phase repaired it by hand —
    which is how it drifted in the first place. Every OWASP code an agent heading claims must
    appear in the spec's list, so the next roster edit that skips § 2.6 goes red instead of
    silently re-opening the same gap.
    """
    spec = (ROOT / "core/companion/docs/WORKFLOW.md").read_text(encoding="utf-8")
    block = spec.split("**OWASP-categorized LLM agents**")[1].split("\n4b.")[0]
    assert block.count("\n   - ") >= 5, "the § 2.6 roster list did not parse — derivation broken"

    missing = []
    for m in re.finditer(r"^### Agent \d+: (?P<title>.+)$", SECURITY_SKILL.read_text(encoding="utf-8"), re.M):
        for code in re.findall(r"\bA\d\d\b", m.group("title")):
            if code not in block:
                missing.append((m.group("title").split("(")[0].strip(), code))
    assert not missing, (
        f"WORKFLOW.md § 2.6's roster list omits {missing} — the spec and the skill disagree "
        "about which categories are dispatched, which is the drift this guard exists to stop."
    )
