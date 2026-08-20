"""Phase 199 — `/roadmap` surveys both work queues.

`/roadmap` reads `tasks/index.yml` and, as of Phase 199, `review_tasks.md`. The
defect it closes (Sysop's internal tracker #394) was that a project's second work
queue — review batches, including open security findings — never reached the
strategy view at all, even though the `--in-flight` survey already fetched the
data and discarded it.

These guards are deliberately NOT keyword checks. A round in Phase 198 replaced a
guarded doc block with a paragraph asserting the exact opposite of every claim and
watched all three `re.search` clauses stay green, so every check here either

  * derives its expectation from the shipped source of truth and compares
    (`test_the_skill_states_the_same_batch_filter_the_survey_applies`), or
  * pins the *direction* of a claim and carries a reversal canary
    (`test_the_unterminated_fence_rule_is_direction_pinned`).

The `/auto-fix N` guard is the widest one: it is repo-scoped rather than
`/roadmap`-scoped, because the invocation it forbids was proposed in the filing
itself and would silently request an N-way concurrency instead of selecting a
batch.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ROADMAP = REPO_ROOT / "core" / "skills" / "roadmap" / "SKILL.md"
SURVEY = REPO_ROOT / "core" / "companion" / "scripts" / "sitrep_survey.py"
TASKS_README = REPO_ROOT / "core" / "companion" / "tasks" / "README.md"
SKILLS_DIR = REPO_ROOT / "core" / "skills"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ── the cross-file invariant ──────────────────────────────────────

# `_classify_review_batches` drops every batch whose status is outside this set
# before the payload is emitted. The skill's base path has to apply the same
# filter or the two halves of the skill describe different populations.
_SURVEY_FILTER_RE = re.compile(
    r'if\s+b\["status"\]\s+not\s+in\s+[\(\{]([^)}]*)[\)\}]\s*:\s*\n\s*continue'
)


def _classifier_body() -> str:
    """Just `_classify_review_batches`, so a docstring elsewhere cannot decoy us.

    The round's guards lens defeated the first version of this derivation by
    restating the historical filter verbatim in a docstring ABOVE the real one
    and widening the real one — `re.search` takes the first match, so the guard
    kept deriving the old set while the survey emitted a new one. Scoping to the
    function body and rejecting ambiguity closes that; accepting `{...}` as well
    as `(...)` closes the matching over-strictness (a set literal is identical
    semantics and was a false kill).
    """
    text = _read(SURVEY)
    start = text.index("def _classify_review_batches")
    return text[start : text.index("\ndef ", start + 10)]


def _survey_batch_statuses() -> set[str]:
    """The batch statuses `sitrep_survey.py` actually emits, from its source."""
    matches = _SURVEY_FILTER_RE.findall(_classifier_body())
    assert matches, (
        "could not locate the batch-status filter inside "
        "`_classify_review_batches`. If the filter moved or changed shape, this "
        "guard's expectation is stale and the skill's stated filter is no longer "
        "being checked against anything — fix the pattern, do not delete the test."
    )
    assert len(matches) == 1, (
        f"found {len(matches)} status filters in `_classify_review_batches`; "
        f"this derivation cannot tell which one governs. Ambiguity is a failure, "
        f"not something to resolve by taking the first: {matches!r}"
    )
    return set(re.findall(r'"([^"]+)"', matches[0]))


def test_the_survey_filter_is_locatable_and_non_empty():
    """Vacuity control: the derivation below has a real population to compare."""
    statuses = _survey_batch_statuses()
    assert statuses, "derived an empty status set — the guard would pass vacuously"
    assert "Pending" in statuses


# The skill's filter has to be read from the ONE sentence that declares it, not
# from the file at large. A first cut asked only "is this status named anywhere
# in the skill?" and was decorative: the skill names `Merged` in its *excluded*
# list, so widening the survey's own filter to include `Merged` left the guard
# green. Two mutation rows (S01/S02) walked straight through it.
_DECLARED_FILTER_RE = re.compile(
    r"Survey the three LIVE statuses: ((?:`[^`]+`(?:,| and )?\s*)+)\."
)


def _skill_declared_statuses() -> set[str]:
    """The batch statuses `roadmap/SKILL.md` says it surveys, from its own text.

    Ambiguity is rejected rather than resolved by taking the first match: the
    round's guards lens planted an italic "an earlier revision read: …" decoy
    ABOVE the operative sentence — this repo's own house style — and the guard
    happily derived from the decoy.
    """
    matches = _DECLARED_FILTER_RE.findall(_deemphasized(_read(ROADMAP)))
    assert matches, (
        "roadmap/SKILL.md no longer carries a parseable 'Survey the three LIVE "
        "statuses: …' declaration. That sentence is what this guard compares "
        "against sitrep_survey.py — without it nothing checks the skill's "
        "population against the tracker's. Restore it or re-point the pattern; "
        "do not delete the test."
    )
    assert len(matches) == 1, (
        f"found {len(matches)} survey-population declarations in the skill; "
        f"this derivation cannot tell which governs: {matches!r}"
    )
    return set(re.findall(r"`([^`]+)`", matches[0]))


def _tracker_live_statuses() -> set[str]:
    """The statuses `batch_work.sh` DECLARES live — the real source of truth.

    `Review Ready` is live and `Ready for Review` is terminal, despite the
    names, and the script says so in terms. The round found the skill had
    dropped the live one and called it finished — the exact defect class this
    phase exists to close, shipped by the fix for it.
    """
    text = _read(REPO_ROOT / "core" / "companion" / "scripts" / "batch_work.sh")
    m = re.search(r"Declared:\s*(.+?)\s*\(finished\)", text)
    assert m, "could not find batch_work.sh's declared-status line"
    live = m.group(1).split("(live)")[0]
    return {s.strip() for s in live.split("·") if s.strip()}


def test_the_skill_declares_a_parseable_filter():
    """Vacuity control for the equality check below."""
    declared = _skill_declared_statuses()
    assert declared, "parsed an empty declared filter — the guard would be vacuous"


def test_the_skill_surveys_every_status_the_tracker_declares_live():
    """The population is set by the TRACKER, not by the survey.

    The first cut of this guard asserted equality with `sitrep_survey.py`'s
    filter, and that was the wrong source of truth: the survey drops
    `Review Ready`, which `batch_work.sh` declares LIVE and calls "the one
    status that needs someone to act". Matching the survey therefore meant
    dropping a live status from the strategy view — reproducing `Q-192` inside
    its own fix. The skill takes the tracker's declaration; the survey is a
    subset it enriches.
    """
    declared = _skill_declared_statuses()
    live = _tracker_live_statuses()
    assert declared == live, (
        f"roadmap/SKILL.md surveys {sorted(declared)} but batch_work.sh "
        f"declares {sorted(live)} live. "
        f"Only in the skill: {sorted(declared - live)}; "
        f"live but unsurveyed: {sorted(live - declared)}."
    )


def test_the_survey_reaches_a_subset_and_the_skill_says_which_it_misses():
    """`--in-flight` enriches only what the survey emits — state that, don't hide it.

    A reader who is not told will assume every batch row can carry a `state`.
    """
    survey = _survey_batch_statuses()
    declared = _skill_declared_statuses()
    unreachable = declared - survey
    assert unreachable, (
        "the survey now reaches every status the skill surveys — this guard's "
        "premise is stale and the paragraph it protects should be revisited"
    )
    text = _deemphasized(_read(ROADMAP))
    for status in unreachable:
        assert re.search(
            rf"`{re.escape(status)}` batch appears on the base path with no "
            rf"`state`", text
        ), (
            f"the skill surveys `{status}` but the survey drops it, and the "
            f"skill never says those rows cannot be enriched"
        )


# ── the actuator-grammar guard (repo-scoped) ──────────────────────

# `/auto-fix 583` sets a 583-way concurrency cap; the batch selector is
# `--batches`. Both skills say so in their own Step 0. The filing that produced
# Phase 199 proposed the bare-integer form, so this is guarded across every
# shipped skill rather than only in /roadmap.
#
# Scoped to `Run it:` lines on purpose. A first cut of this guard scanned for the
# token anywhere and was OVER-STRICT in two directions at once: it fired on the
# three sentences that exist to *forbid* the form, and on
# `auto-fix/SKILL.md:197`'s `/auto-fix 1`, which is a correct invocation meaning
# concurrency=1. The defect is never a mention — it is an actuator line a human
# is invited to paste, which is exactly the contract `Run it:` carries
# (`roadmap/SKILL.md`: "a copy-pasteable **`Run it:`** actuator line").
# Matches a bare operand in either spelling — a literal integer (`/auto-fix 583`)
# or a placeholder (`/auto-fix <N>`). The placeholder form has to be here: a
# mutation row reintroduced exactly that in the actuator table, and a digits-only
# pattern could not see it — arguably the worse of the two, since a placeholder
# reads as a template to copy. `--batches` is excluded explicitly rather than by
# hoping the operand shape differs.
_BARE_INT_ACTUATOR_RE = re.compile(
    r"/auto-(?:fix|judge)\s+(?!--batches\b)(\d+\b|<[^>]+>)"
)


def _run_it_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if "Run it:" in ln]


def _shipped_markdown() -> list[Path]:
    """Every surface where a prescriptive `Run it:` line could appear.

    Derived from the directories, not from a hand-listed index. The round's
    guards lens landed the foot-gun in three files a curated list had missed —
    `docs/getting-started.md` (the public tutorial), `docs/workflow.html` (the
    monograph, which THIS PHASE edited), and `core/companion/tasks/schema.md`
    (installed into every consumer beside the README that was scanned). Rule 1:
    derive the population from the source of truth, not from an index of it.
    """
    paths = sorted(SKILLS_DIR.rglob("*.md"))
    paths += sorted((REPO_ROOT / "core" / "companion" / "docs").rglob("*.md"))
    paths += sorted((REPO_ROOT / "core" / "companion" / "tasks").rglob("*.md"))
    paths += sorted((REPO_ROOT / "docs").glob("*.md"))
    paths += sorted((REPO_ROOT / "docs").glob("*.html"))
    paths += [REPO_ROOT / "README.md"]
    return [p for p in dict.fromkeys(paths) if p.is_file()]


def test_the_shipped_population_is_non_empty():
    """Vacuity control for the two scans below."""
    files = _shipped_markdown()
    assert len(files) > 20, f"only {len(files)} files — the scan would be near-vacuous"
    assert ROADMAP in files


@pytest.mark.parametrize("path", _shipped_markdown(), ids=lambda p: p.name)
def test_no_run_it_line_prescribes_a_bare_integer_batch_actuator(path: Path):
    """`/auto-fix <N>` requests N-way concurrency; it does not select batch N."""
    hits = [
        ln.strip()
        for ln in _run_it_lines(_read(path))
        if _BARE_INT_ACTUATOR_RE.search(ln)
    ]
    assert not hits, (
        f"{path.relative_to(REPO_ROOT)} has a Run it: line prescribing the "
        f"bare-integer form: {hits!r}. A bare integer is the concurrency cap "
        f"for these skills — use `--batches <N>`. Both auto-fix/SKILL.md and "
        f"auto-judge/SKILL.md state this in their own Step 0."
    )


def test_the_run_it_scan_reaches_a_real_population():
    """Vacuity control: /roadmap really does carry Run it: lines to scan."""
    lines = _run_it_lines(_read(ROADMAP))
    assert len(lines) >= 5, (
        f"only {len(lines)} Run it: lines in roadmap/SKILL.md — if the actuator "
        f"lines were renamed, the guard above scans nothing"
    )


def test_the_bare_integer_guard_would_catch_the_form_the_filing_proposed():
    """Non-vacuity + over-strictness controls for the pattern itself."""
    # Fires on the form the filing proposed, in both spellings...
    assert _BARE_INT_ACTUATOR_RE.search("Run it: /auto-fix 583")
    assert _BARE_INT_ACTUATOR_RE.search("Run it: `/auto-judge 567`")
    assert _BARE_INT_ACTUATOR_RE.search("| triaged | `/auto-fix <N>` |")
    # ...and not on the correct selector form, in any spelling.
    assert not _BARE_INT_ACTUATOR_RE.search("/auto-fix --batches 583")
    assert not _BARE_INT_ACTUATOR_RE.search("/auto-judge --batches 563,570,580-584")
    assert not _BARE_INT_ACTUATOR_RE.search("/auto-fix --batches <N>")
    # Over-strictness controls: these are legitimate and must not be flagged.
    # A concurrency invocation (auto-fix/SKILL.md:197) is correct usage, and the
    # sentences forbidding the batch reading are not Run it: lines at all.
    assert not _run_it_lines("invoke `/auto-fix 1` to force concurrency=1")
    assert not _run_it_lines("so `/auto-fix 563` would set a 563-way cap")


def test_the_roadmap_batch_actuators_use_the_selector_flag():
    """/roadmap must emit the selector form for both routable batch states."""
    text = _read(ROADMAP)
    for skill in ("auto-fix", "auto-judge"):
        assert re.search(rf"/{skill}\s+--batches", text), (
            f"roadmap/SKILL.md never shows the `/{skill} --batches <N>` form, "
            f"so nothing pins the grammar its Run it: lines must emit"
        )


def test_roadmap_carries_the_bare_integer_form_only_where_it_forbids_it():
    """A count-and-identity rule, because scoping to `Run it:` was too narrow.

    Mutation L02 reintroduced `/auto-fix <N>` one row above a `Run it:` line —
    in the batch-actuator table, which is every bit as prescriptive — and the
    Run-it-scoped guard could not see it. `/roadmap` never sets concurrency, so
    it has exactly one legitimate reason to write the bare-integer form: the
    sentence explaining why not to. Anything else is a defect, whatever section
    it sits in.
    """
    # Counted per OCCURRENCE, not per line. `re.search` yields one hit per line,
    # so the round's guards lens appended a prescriptive `hand the human
    # /auto-fix 583` to the prohibition paragraph itself: the count stayed 1 and
    # the identity check still found "Never write" on that line.
    hits = [
        (ln.strip(), m.group(0))
        for ln in _read(ROADMAP).splitlines()
        for m in _BARE_INT_ACTUATOR_RE.finditer(ln)
    ]
    stray = [(ln, m) for ln, m in hits if "Never write" not in ln]
    assert not stray, (
        f"bare-operand actuator form outside the prohibition sentence: {stray!r}"
    )
    # The exact count is pinned, not just the location. Identity alone let the
    # round's lens append a prescriptive `hand the human /auto-fix 583` to the
    # prohibition line itself — same line, identity intact, foot-gun restored.
    # The three legitimate occurrences are the sentence's two placeholders
    # (`/auto-fix <N>`, `/auto-judge <N>`) and its one illustrative integer
    # (`/auto-fix 583`). A fourth is an addition, wherever it sits.
    assert len(hits) == 3, (
        f"expected exactly 3 bare-operand occurrences in roadmap/SKILL.md, all "
        f"inside the prohibition sentence (two placeholders + one illustrative "
        f"integer), but found {len(hits)}: {[m for _, m in hits]!r}. If you "
        f"legitimately reworded the prohibition, update this count deliberately "
        f"— it is the only thing standing between the sentence and a "
        f"prescriptive occurrence hidden in the same paragraph."
    )


# ── the payload contract, derived from the survey ─────────────────
#
# The round's guards lens landed 12 of 12 independent mutations, and the sharpest
# structural point was this: the phase built a cross-file derivation guard for the
# status filter and left the *payload-key contract* on the same page ungated. A
# `sitrep_survey.py` key rename makes the skill's Step 2a wrong with a green
# suite. Same for the `state` vocabulary. Both are derived here rather than
# restated.


def _survey_payload_keys() -> set[str]:
    """The per-batch keys `sitrep_survey.py` actually emits, from `_rb`."""
    text = _read(SURVEY)
    start = text.index("def _rb(r: ReviewBatchState)")
    end = text.index("\n    def _d(", start)
    keys = set(re.findall(r'^\s+"([a-z_]+)":', text[start:end], re.M))
    assert keys, (
        "could not parse `_rb`'s emitted keys from sitrep_survey.py. That "
        "function is the payload contract roadmap/SKILL.md Step 2a documents; "
        "without it nothing checks the skill against the real shape."
    )
    return keys


def _survey_batch_states() -> set[str]:
    """The `state` vocabulary `_classify_review_batches` can emit."""
    text = _read(SURVEY)
    start = text.index("def _classify_review_batches")
    end = text.index("\ndef ", start + 10)
    states = set(re.findall(r'state\s*=\s*"([^"]+)"', text[start:end]))
    assert states, "could not parse the batch `state` vocabulary from the survey"
    return states


def test_the_payload_contract_derivations_are_non_vacuous():
    """Vacuity controls for the two guards below."""
    assert len(_survey_payload_keys()) >= 10
    assert len(_survey_batch_states()) >= 4


def test_the_skill_documents_every_payload_key_the_survey_emits():
    """Step 2a tells the agent what it may consume; that list must be complete.

    An incomplete list silently narrows what `--in-flight` uses. A list naming a
    key the survey does not emit sends the agent looking for a field that will
    never arrive.
    """
    text = _read(ROADMAP)
    documented = {k for k in _survey_payload_keys() if f"`{k}`" in text}
    missing = _survey_payload_keys() - documented
    assert not missing, (
        f"sitrep_survey.py's `_rb` emits keys roadmap/SKILL.md never names: "
        f"{sorted(missing)}"
    )


def test_the_skill_lists_exactly_the_batch_states_the_survey_can_emit():
    """Set equality, both directions — an invented `state` value is as wrong as
    a missing one, and only the second is visible by reading the skill alone."""
    survey = _survey_batch_states()
    text = _deemphasized(_read(ROADMAP))
    named = {s for s in survey if f"`{s}`" in text}
    assert named == survey, (
        f"batch `state` values the survey emits but the skill never names: "
        f"{sorted(survey - named)}"
    )
    # The other direction: no invented state presented as one the survey emits.
    quoted = set(re.findall(r"`(pending \(not claimed\)|claimed, no branch|"
                            r"empty batch|in progress|ready for /review-close|"
                            r"[a-z]+ \(not [a-z]+\))`", text))
    invented = quoted - survey
    assert not invented, (
        f"roadmap/SKILL.md presents batch states the survey cannot emit: "
        f"{sorted(invented)}"
    )


# ── the design calls the round found unguarded ────────────────────


def test_the_batch_read_is_on_the_base_path_not_behind_the_flag():
    """The phase's whole subject, and it was unguarded.

    The reported failure happened on a DEFAULT run, so a fix reachable only under
    `--in-flight` would not have fixed it. A mutation moving the read back behind
    the flag is the single highest-value reversion here.
    """
    text = _read(ROADMAP)
    step1 = text.split("## Step 1")[1].split("## Step 2")[0]
    assert "review_tasks.md" in step1, "the tracker read left Step 1"
    assert not re.search(
        r"(?:only|solely)\s+(?:under|with)\s+`?--in-flight`?[^.\n]*"
        r"`review_tasks\.md`",
        text, re.I,
    ), "the skill now gates the tracker read behind --in-flight"
    # And the design note must still carry the reason, not just the behaviour.
    assert re.search(
        r"reported failure happened on a \*\*default\*\* run", text
    ), "the rationale for base-path reading is gone; only the behaviour remains"


def test_precedence_is_roadmap_first_and_not_reversed():
    text = _deemphasized(_read(ROADMAP))
    assert re.search(r"[Rr]ank batches alongside tasks, roadmap-first on ties", text), (
        "the stated precedence is gone"
    )
    m = re.search(r"[Rr]ank batches (?:first|ahead of|before)\b", text)
    assert not m, f"precedence reversed: {m.group(0)!r}"


def test_no_batch_id_is_minted():
    """`claim_task.sh` refuses `BATCH-`-shaped ids; inventing one in /roadmap
    would manufacture a value other skills would be tempted to accept."""
    text = _deemphasized(_read(ROADMAP))
    assert re.search(r"do \*?\*?not\*?\*? invent one|no invented `BATCH-|"
                     r"must not invent", text, re.I), (
        "the prohibition on minting a BATCH-<N> id is gone"
    )
    # Every mention of minting must sit on a line that NEGATES it. A first cut
    # forbade the phrase outright and fired on the design note that exists to
    # prohibit it — the same over-strictness that already caught this module
    # twice (the sentences forbidding `/auto-fix <N>`, and the legitimate
    # `/auto-fix 1` concurrency invocation).
    minting = re.compile(r"(?:synthesi[sz]e|mint|assign)\w*\s+a\s+`?BATCH-", re.I)
    negation = re.compile(r"\b(?:not|never|no|without|refuses?|forbid\w*)\b", re.I)
    unnegated = [
        ln.strip()
        for ln in text.splitlines()
        if minting.search(ln) and not negation.search(ln)
    ]
    assert not unnegated, (
        f"the skill mints a batch id on a line that does not negate it: "
        f"{unnegated!r}"
    )


def test_next_action_is_never_emitted_as_a_command():
    text = _deemphasized(_read(ROADMAP))
    assert re.search(r"[Nn]ever emit the survey's `next_action`", text), (
        "the prohibition on printing next_action verbatim is gone"
    )
    m = re.search(r"(?:feel free to|you may|it is fine to)\s+"
                  r"(?:emit|print|use)[^.\n]*`?next_action`?", text, re.I)
    assert not m, f"the skill now licenses emitting next_action: {m.group(0)!r}"


def test_the_malformed_header_blindness_is_stated():
    """The status filter is not the only population gate.

    The survey drops any batch whose header its strict pattern rejects, so such a
    batch is invisible to `--in-flight`, `/sitrep`, `/triage`, `/auto-fix` and
    `/auto-judge`. The base path is the only thing that can see it. The first cut
    of this skill claimed the status filter was what kept the two paths
    describing the same population — which was false, and the counterexample was
    a security batch.
    """
    text = _deemphasized(_read(ROADMAP))
    assert re.search(r"Status is not the only gate", text), (
        "the malformed-header blindness is no longer stated"
    )
    m = re.search(r"filter[^.\n]*keeps the base path and `--in-flight` "
                  r"describing the \*?same\*? population", text)
    assert not m, (
        "the refuted 'same population' claim has returned: header-rejected "
        "batches are dropped by a second, independent gate"
    )


def test_a_security_batch_can_be_the_offered_routing_move():
    """Step 5 offers ONE move, and its first bullet used to fire on any ready
    task — so on the 195-task queue that produced the filing, the flagged
    security batch could be described and still never be the move offered."""
    text = _read(ROADMAP)
    step5 = text.split("## Step 5")[1].split("## Output shape")[0]
    bullets = [ln for ln in step5.splitlines() if ln.lstrip().startswith("- ")]
    assert bullets, "Step 5's routing cascade has no bullets"
    assert "security" in bullets[0].lower(), (
        "Step 5's FIRST routing bullet no longer reaches a security batch, so "
        f"a ready task always wins and the batch is never offered: {bullets[0]!r}"
    )


def test_step_1_names_the_review_queue_as_a_read():
    """Wiring: Step 1's numbered read list must actually include the tracker.

    Mutation D01 renamed it and nothing noticed — the skill can describe batch
    handling at length while never telling the agent to open the file.
    """
    text = _read(ROADMAP)
    step1 = text.split("## Step 1")[1].split("## Step 2")[0]
    assert re.search(r"^\d+\.\s+\*\*`review_tasks\.md`\*\*", step1, re.M), (
        "Step 1's numbered list of files to read does not name "
        "`review_tasks.md`, so nothing instructs the agent to open it"
    )


# ── direction-pinned prose guards, each with a reversal canary ────

# A `re.search` for keywords is satisfied by a sentence denying the claim —
# Phase 198's round demonstrated exactly that against three clauses at once. Each
# rule below therefore pairs a required assertion with a forbidden inversion.
def _deemphasized(text: str) -> str:
    """Normalize emphasis and typographic punctuation before matching.

    Without this the guards are keyed to bold/italic placement and to which
    apostrophe the author typed, rather than to the claim — so re-wrapping a
    phrase in `**`, or an editor swapping `'` for `’`, silently disarms them.
    That is the over-strict direction, and the one that reads as a passing test.
    This repo's prose uses typographic punctuation throughout, so the second
    substitution is load-bearing, not cosmetic.

    Only `*` is stripped, never `_`: underscore is emphasis in CommonMark but in
    this repo it is overwhelmingly part of an identifier, and a first cut of this
    helper stripped it — turning `review_tasks.md` into `reviewtasks.md` and
    making the one guard that names that file unsatisfiable.
    """
    text = re.sub(r"\*+", "", text)
    return text.replace("’", "'").replace("‘", "'")


_DIRECTION_RULES = [
    pytest.param(
        r"unterminated\s+fence\s+must\s+be\s+ignored",
        r"unterminated\s+fence\s+must\s+be\s+honou?red",
        "unterminated-fence",
        id="unterminated_fence_is_ignored_not_honoured",
    ),
    pytest.param(
        r"level-2\s+\(`##\s*`\)\s+heading\s+closes\s+the\s+open\s+batch",
        r"level-2[^.\n]*heading\s+(?:does\s+not|never)\s+close",
        "level-2-closer",
        id="level_2_heading_closes_the_batch",
    ),
    # The round's lens 1 killed the original form of this rule. The skill used to
    # say "Read the main checkout's `review_tasks.md`" — an instruction the base
    # path CANNOT follow, because resolving the main checkout needs
    # `git rev-parse --git-common-dir` and the base path ships no git and no
    # scripts. Worse, the same commit added a portability note asserting the file
    # is read "at the repo root", so the two added lines named different files.
    # What ships now is the honest version: the base path reads the tree it is
    # in, the divergence is declared as a limitation, and `--in-flight` prefers
    # the payload's `main_root`. This rule pins THAT, and its inversion is the
    # old unfollowable instruction coming back.
    pytest.param(
        r"base path reads whatever tree it is invoked in",
        r"(?:^|\n)\s*Read the main checkout'?s?\s+`review_tasks\.md`",
        "worktree-divergence-declared",
        id="the_worktree_divergence_is_declared_not_wished_away",
    ),
    pytest.param(
        r"prefer the payload",
        r"ignore the payload'?s?\s+`?main_root`?",
        "in-flight-prefers-main-root",
        id="in_flight_prefers_the_payloads_main_root",
    ),
]


@pytest.mark.parametrize("required,inversion,label", _DIRECTION_RULES)
def test_the_parsing_rule_is_stated(required: str, inversion: str, label: str):
    text = _deemphasized(_read(ROADMAP))
    assert re.search(required, text, re.I), (
        f"roadmap/SKILL.md no longer states the {label} rule. It is one of the "
        f"shapes sitrep_survey.py's own parser was hardened against, and a "
        f"prose-instructed reader has none of that hardening."
    )


@pytest.mark.parametrize("required,inversion,label", _DIRECTION_RULES)
def test_the_parsing_rule_cannot_be_satisfied_by_its_own_negation(
    required: str, inversion: str, label: str
):
    """Reversal canary — the guard above must not pass on an inverted claim."""
    text = _deemphasized(_read(ROADMAP))
    m = re.search(inversion, text, re.I)
    assert not m, (
        f"roadmap/SKILL.md states the {label} rule backwards: {m.group(0)!r}"
    )


# ── absence handling: the dominant install shape ──────────────────


def test_absence_of_review_tasks_is_documented_as_ordinary():
    """`install.sh` never seeds `review_tasks.md`.

    It first exists after the project's first `/codebase-review` or
    `/security-audit`, so a consumer who installed and ran `/intake` has no
    review queue — the most common shape, and it must not read as broken.
    """
    text = _read(ROADMAP)
    assert re.search(
        r"`review_tasks\.md`\s+absent[^\n]*\*\*this is the common case", text, re.I
    ), "the absent-file path is not documented as the ordinary case"


def test_install_sh_still_does_not_seed_review_tasks():
    """Pins the premise the absence guard above rests on.

    If a future phase makes `install.sh` seed the tracker, the 'common case'
    framing becomes false and should be revisited rather than left standing.
    """
    # The first cut was `^[^#\n]*>\s*"?\$\{?TARGET\}?/review_tasks\.md` and the
    # round's guards lens walked FOUR shapes through it: `cat > "$dst"` (the
    # idiom install.sh uses for every file it actually seeds), `cp`, the
    # `"$TARGET"/review_tasks.md` quoting, and — worst — any line carrying a `#`
    # before the redirect, because the `[^#\n]*` prefix blinded it. It fired on
    # exactly one shape the file never uses.
    #
    # So: look for the FILENAME anywhere on a line that also carries a write
    # verb, and let the vacuity control below prove the pattern can still fire.
    install = _read(REPO_ROOT / "install.sh")
    write_verb = re.compile(r"(?:^|[;&|]|\s)(?:cat|cp|printf|echo|tee|install)\b|>\s*\"?[^\"\s]*")
    writes = [
        ln.strip()
        for ln in install.splitlines()
        if "review_tasks.md" in ln
        and not ln.lstrip().startswith("#")
        and write_verb.search(ln)
    ]
    assert not writes, (
        "install.sh now appears to write review_tasks.md; roadmap/SKILL.md's "
        f"absence-handling paragraph calls that absence 'the common case': {writes!r}"
    )


@pytest.mark.parametrize(
    "shape",
    [
        'cat > "$TARGET/review_tasks.md" <<EOF',
        'cp "$src" "$TARGET/review_tasks.md"',
        'printf \'# Review Tasks\\n\' > "$TARGET/review_tasks.md"',
        'echo x > "$TARGET"/review_tasks.md',
        '  local rt="$TARGET/review_tasks.md"; cat > "$rt" <<EOF',
    ],
    ids=["cat-heredoc", "cp", "printf-with-hash", "quote-before-slash", "local-var"],
)
def test_the_seeding_pin_fires_on_every_shape_install_sh_actually_uses(shape: str):
    """Non-vacuity, per shape — each of these defeated the first pattern."""
    write_verb = re.compile(r"(?:^|[;&|]|\s)(?:cat|cp|printf|echo|tee|install)\b|>\s*\"?[^\"\s]*")
    assert "review_tasks.md" in shape and write_verb.search(shape), (
        f"the seeding pin would not fire on {shape!r}"
    )


# ── doc currency ──────────────────────────────────────────────────


def test_the_tasks_readme_skill_table_lists_both_queues_for_the_read_side():
    """`tasks/README.md` states each skill's inputs as data, not prose.

    Both `/roadmap` and `/next-task` read `review_tasks.md`; the table omitted it
    for both until Phase 199.
    """
    text = _read(TASKS_README)
    for skill in ("/roadmap", "/next-task"):
        row = next(
            (ln for ln in text.splitlines() if ln.startswith(f"| `{skill}`")), None
        )
        assert row is not None, f"no {skill} row in the tasks/README.md skill table"
        assert "review_tasks.md" in row, (
            f"the {skill} row does not list review_tasks.md among its reads, "
            f"though the skill reads it: {row!r}"
        )


def test_the_skill_no_longer_assigns_review_batches_to_sitrep_alone():
    """The boundary sentence contradicted itself and was corrected.

    It listed 'review batches' as `/sitrep`'s territory while its own next clause
    defined `/roadmap`'s subject as the backlog — and an unclaimed `Pending`
    batch is backlog, which is why the survey classifies it `pending (not
    claimed)`.
    """
    # Keyed to the CLAIM, not to a phrasing. The round's lens reintroduced the
    # regression twice — once with the list reordered, once with the italics
    # dropped — and this was the one prose guard that never called
    # `_deemphasized`, so the exact failure that helper exists to prevent was
    # live at this site. Now: any sentence describing what `/sitrep` surveys and
    # naming review batches among the things it enumerates.
    text = _deemphasized(_read(ROADMAP))
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if "/sitrep" not in sentence:
            continue
        if not re.search(r"surveys\s+execution state", sentence, re.I):
            continue
        assert "review batches" not in sentence.lower(), (
            "the boundary sentence has regressed to the self-contradicting "
            "form — it enumerates review batches as `/sitrep`'s territory "
            "while its own next clause makes the backlog `/roadmap`'s "
            f"subject: {sentence.strip()[:220]!r}"
        )


def test_the_base_path_read_is_not_licensed_away_in_prose():
    """Naming the file in Step 1 is not the same as reading it.

    The round's guards lens reinstalled the phase's own defect while staying
    green: keep `4. **review_tasks.md**` in the read list and add "do not read
    it on the base path; consumed only under `--in-flight`". The read-list guard
    checks the file is *named*.
    """
    text = _deemphasized(_read(ROADMAP))
    m = re.search(
        r"(?:do not|don't|never)\s+read\s+(?:it|`?review_tasks\.md`?)"
        r"[^.\n]*base path",
        text, re.I,
    )
    assert not m, f"the skill licenses skipping the base-path read: {m.group(0)!r}"
    m = re.search(
        r"`review_tasks\.md`[^.\n]*consumed only under\s+`?--in-flight`?",
        text, re.I,
    )
    assert not m, f"the tracker read is gated behind the flag: {m.group(0)!r}"


def test_the_two_doc_currency_edits_cannot_revert_silently():
    """`WORKFLOW_GUIDE.md` and `docs/workflow.html` were edited by this phase and
    guarded by nothing — the round reverted both to their pre-phase text with a
    green suite."""
    guide = _read(REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW_GUIDE.md")
    assert "review_tasks.md" in guide and re.search(
        r"/roadmap.{0,400}both.{0,80}queues", guide, re.S | re.I
    ), "WORKFLOW_GUIDE.md's /roadmap bullet no longer says it reads both queues"

    html = _read(REPO_ROOT / "docs" / "workflow.html")
    assert re.search(
        r"<code>/roadmap</code>.{0,500}both.{0,300}queues", html, re.S | re.I
    ), "docs/workflow.html's /roadmap sentence no longer says it reads both queues"


def test_the_ordering_bound_agrees_across_every_surface_that_states_it():
    """I raised the bound from 1–3 to 1–4 in the skill and left both doc
    surfaces saying three — drift introduced by the round's own fix."""
    surfaces = {
        "roadmap/SKILL.md": _read(ROADMAP),
        "WORKFLOW_GUIDE.md": _read(
            REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW_GUIDE.md"
        ),
        "docs/workflow.html": _read(REPO_ROOT / "docs" / "workflow.html"),
    }
    stale = {
        name: m.group(0)
        for name, text in surfaces.items()
        if (m := re.search(r"(?:1[–-]3|one to three)\s+(?:proposed\s+)?ordering",
                           text, re.I))
    }
    assert not stale, (
        f"surfaces still stating the old 1–3 ordering bound: {stale!r}"
    )


# ── Phase 204 / Q-211: the population restated away from its declaration ──
#
# `:62`'s declaration was already pinned, three ways, by the guards at the top of
# this module — the filing that produced this section claimed no such test
# existed and was wrong about that. What was NOT pinned is every OTHER site that
# restates the population. Two had drifted to the survey's narrower pair, and one
# of them was Step 3's definition of "Outstanding", which governs the report's
# totals on EVERY run rather than only under `--in-flight`.
#
# Two guards, because the two defects are not the same shape and the first
# cannot see the second.

# Widened Phase 204 (round, F5): the code-span form was the only one recognised,
# so writing the population in bold (`**Pending**`) or in quotes ("Pending") made
# the site invisible to the scan entirely. Both are ordinary markdown here.
_STATUS_TOKEN = re.compile(
    r'(?:`|\*\*|")(Pending|In Progress|Review Ready)(?:`|\*\*|")'
)

# A sentence may legitimately name only the survey's subset when it is explicitly
# about the survey or the payload — that is what makes `:64` correct. Anywhere
# else, naming the subset as the population silently drops a live status.
_FLAG_SCOPED = re.compile(r"--in-flight|payload|_classify_review_batches|enrich", re.I)


# Clause boundaries, not line boundaries. The first version of this scan was
# line-scoped, and the author-side battery walked two defects straight through
# it: this file's paragraph-lines are long, so ANY mention of `Review Ready` or
# of the payload anywhere in the paragraph exempted the whole line — including a
# clause several sentences away that stated the population as the narrow pair.
# A guard whose scope is "the paragraph" is satisfied by a paragraph that
# contradicts itself, which is precisely the shape Q-211 filed.
_CLAUSE_SPLIT = re.compile(r"(?<=[.;])\s+|\s+—\s+")


def _states_the_subset_as_the_population(
    clause: str, survey: set[str], unreachable: set[str]
) -> bool:
    """The predicate itself, hoisted so the guard and its control share it.

    The round cut six wires in these tests — emptying `_population_sites()`,
    short-circuiting the condition, blanking a pin lookup — and every one
    survived, because the "does the guard fire" control had its OWN copy of this
    logic and could not observe the real guard being disabled. A control that
    re-implements its subject tests the re-implementation.
    """
    names = {m.group(1) for m in _STATUS_TOKEN.finditer(clause)}
    if len(names) < 2:
        return False
    return bool(names >= survey and not (names & unreachable) and not _FLAG_SCOPED.search(clause))


def _population_sites() -> list[tuple[int, str]]:
    """Clauses that name two or more batch statuses — i.e. that state a population.

    Returns (line number, clause) so a failure names a place a human can open.
    """
    out: list[tuple[int, str]] = []
    for i, line in enumerate(_read(ROADMAP).splitlines(), 1):
        for clause in _CLAUSE_SPLIT.split(line):
            names = {m.group(1) for m in _STATUS_TOKEN.finditer(clause)}
            if len(names) >= 2:
                out.append((i, clause))
    return out


def test_the_population_site_scan_is_not_vacuous():
    """Vacuity + reach control for the guard below.

    A file count is not a match count, and an empty scan passes every downstream
    assertion. This asserts the scan finds real sites AND that it reaches the
    declaration sentence itself — if it cannot see `:62`, it cannot see a site
    that contradicts `:62` either.
    """
    sites = _population_sites()
    assert len(sites) >= 3, f"population scan found only {len(sites)} sites"
    declared = _skill_declared_statuses()
    reaches_declaration = any(
        {m.group(1) for m in _STATUS_TOKEN.finditer(line)} == declared
        for _, line in sites
    )
    assert reaches_declaration, (
        "the population scan never matched a site naming the full declared set "
        f"({sorted(declared)}) — it is not reading the sentence it is keyed to"
    )


def test_every_site_that_states_the_batch_population_names_the_live_set():
    """The guard the filing asked for by the wrong name.

    Both populations are derived, never spelled: the survey's from
    `sitrep_survey.py`'s own filter, the skill's from its declaration sentence.
    So this cannot go stale against a filter change — it re-derives what
    "the subset" means each run.

    **What this guard does NOT reach**, stated because a guard that hides its
    blind spot is the failure this module exists to catch: a site that names the
    subset *and* carries a flag/payload qualifier passes here by construction —
    the qualifier is exactly what makes naming the subset legal. The falsehood
    that lived inside such a sentence is the next guard's job.
    """
    survey = _survey_batch_statuses()
    declared = _skill_declared_statuses()
    unreachable = declared - survey
    assert unreachable, (
        "the survey now reaches every status the skill surveys — this guard's "
        "premise is stale and the sites it protects should be revisited"
    )

    offenders = [
        f"  {i}: {line.strip()[:140]}"
        for i, line in _population_sites()
        if _states_the_subset_as_the_population(line, survey, unreachable)
    ]
    assert offenders == [], (
        "a site states the batch population as the survey's subset "
        f"({sorted(survey)}) without naming {sorted(unreachable)} and without "
        "scoping itself to the payload. A reader following it drops a status "
        "the tracker declares LIVE:\n" + "\n".join(offenders)
    )


def test_the_population_guard_fires_on_the_shape_that_shipped():
    """Control, in both directions, against the real pre-fix text.

    The `Q-211` defect verbatim as Step 3 carried it, and the corrected form.
    Without this the guard above could be satisfied by an empty offender list it
    arrives at for the wrong reason.
    """
    survey = _survey_batch_statuses()
    declared = _skill_declared_statuses()
    unreachable = declared - survey

    def offends(line: str) -> bool:
        return _states_the_subset_as_the_population(line, survey, unreachable)

    shipped = (
        '"Outstanding" = every roadmap task with `status` in `{open, in_progress}`, '
        "plus every `Pending` / `In Progress` review batch from Step 1."
    )
    assert offends(shipped), "the guard does not fire on the text that shipped"

    corrected = (
        '"Outstanding" = every roadmap task, plus every `Pending`, `In Progress` '
        "and `Review Ready` review batch from Step 1."
    )
    assert not offends(corrected), "the guard false-fires on the corrected text"

    legal_subset = (
        "The `--in-flight` payload filters to `Pending` / `In Progress` before "
        "emitting `review_batches`."
    )
    assert not offends(legal_subset), (
        "the guard false-fires on a payload-scoped sentence, which is the one "
        "place naming the subset is correct"
    )


def test_step_3s_outstanding_definition_names_every_live_status():
    """The generic scan cannot see this site's worst failure, so it is pinned.

    `_population_sites` only considers a clause that names TWO or more statuses.
    The round's sharpest population mutation named just ONE — dropping two live
    statuses instead of one — and the scan never classified it as a site at all.
    A threshold of 2 is right for the generic sweep (every mention of `Pending`
    alone is not a population claim) and wrong for the one sentence whose whole
    job is to state the population.

    So this site is pinned by name, and its expectation is DERIVED from the
    skill's own declaration rather than spelled — drop a status from `:62` and
    `test_the_skill_surveys_every_status_the_tracker_declares_live` reds first.
    """
    declared = _skill_declared_statuses()
    text = " ".join(_deemphasized(_read(ROADMAP)).split())
    m = re.search(r'"Outstanding" = ([^\n]{0,600}?)(?:\n|\Z|Classify each)', text)
    assert m, (
        'roadmap/SKILL.md no longer carries a parseable \'"Outstanding" = …\' '
        "definition. That sentence governs Step 3's grouping and the report's "
        "totals; without it nothing checks the population the report counts."
    )
    sentence = m.group(1)
    missing = sorted(s for s in declared if s not in sentence)
    assert not missing, (
        f"Step 3's \"Outstanding\" definition omits {missing} — a live status the "
        "skill says at :62 that it surveys. A reader following it drops that "
        "work from the strategy view on every run, not just under --in-flight."
    )


def test_the_outstanding_pin_is_not_vacuous():
    """It must actually find the sentence, and actually fire when one is dropped."""
    text = " ".join(_deemphasized(_read(ROADMAP)).split())
    m = re.search(r'"Outstanding" = ([^\n]{0,600}?)(?:\n|\Z|Classify each)', text)
    assert m and len(m.group(1)) > 40, "the Outstanding pin matched nothing usable"
    declared = _skill_declared_statuses()
    assert len(declared) >= 3, f"derived only {declared} — the check would be thin"
    stripped = m.group(1).replace("Review Ready", "")
    assert any(s not in stripped for s in declared), (
        "removing a status from the sentence does not change the verdict"
    )


def test_the_two_halves_are_not_claimed_to_cover_the_same_batches():
    """The defect that lived INSIDE a correctly-scoped sentence.

    `:96` read: the flag "adds depth, not breadth: it is the same batches (both
    paths filter to `Pending` / `In Progress`), with cells the base path cannot
    compute". The parenthetical was true — the payload really does filter to two
    — and the equality around it was false, because the base path surveys three.
    A reader carries the equality into Step 3, which is where it did damage.

    Positive and negative together: the subset relation must be stated, and the
    equality must not be. Pinning only the absence lets the claim come back
    reworded; pinning only the presence lets both sentences coexist.
    """
    # Whitespace-normalised as well as de-emphasised: the round found this guard
    # keyed to hard single spaces against a ~700-character source line, so any
    # future author who reflowed the paragraph would have reddened the suite for
    # a legal edit. The sibling module's `_flat` had this right; `_deemphasized`
    # alone does not normalise runs of whitespace.
    text = " ".join(_deemphasized(_read(ROADMAP)).split())

    assert re.search(
        r"the base path is the broader view, and the two halves do not cover "
        r"the same batches",
        text,
        re.I,
    ), (
        "roadmap/SKILL.md no longer states that the payload reaches a SUBSET of "
        "the base path's batches. That relation is the whole reason Step 3 must "
        "not take its population from the flag."
    )

    for inversion in (
        r"it is the same batches",
        r"both paths filter to",
        r"the flag adds breadth",
    ):
        m = re.search(inversion, text, re.I)
        assert not m, (
            f"roadmap/SKILL.md claims the two halves cover the same batches: "
            f"{m.group(0)!r}. The payload is a strict subset — "
            f"`Review Ready` is surveyed and never enriched."
        )
