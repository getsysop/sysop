"""Drift guards for Phase 138 — two-tier fan-out attestation.

Ratified as Option 1 (commit `86b7e8a`): closes leg (c) of the 2026-07-19
`/test-audit` reference-cell item (the `[verified]`/`[reported]` provenance
marker) together with the 2026-07-20 fan-out-attestation item.

- **Tier 1 — provenance marker (universal).** Every finding in `/codebase-review`,
  `/security-audit`, and `/test-audit` carries `[verified]` / `[reported]`. Ships
  on every run, inline or fan-out. A *self-declared honesty label, not a
  machine-checked guarantee* — the prose must say so, so `[verified]` is never
  read as verification.
- **Tier 2 — evidence footer + orchestrator sampling (fan-out only).** Sub-agents
  return files-opened-vs-assigned + tool mix; the orchestrator flags a low-opened
  batch (mandatory) and samples 2–3 claims (advisory) before merging; the round
  summary carries a provenance class, never a bare %.

The single-sourced contract lives in `_shared/fanout-evidence.md`; the skills cite
it (they do not duplicate it). These are string-anchor drift guards — they pin the
load-bearing wording so a future edit cannot silently drop a leg.
"""

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TESTS_DIR = _REPO_ROOT / "tests"
_SKILLS = _REPO_ROOT / "core" / "skills"
_SHARED = _SKILLS / "_shared"

_PARTIAL = (_SHARED / "fanout-evidence.md").read_text(encoding="utf-8")
_CODEBASE = (_SKILLS / "codebase-review" / "SKILL.md").read_text(encoding="utf-8")
_SECURITY = (_SKILLS / "security-audit" / "SKILL.md").read_text(encoding="utf-8")
_TEST_AUDIT = (_SKILLS / "test-audit" / "SKILL.md").read_text(encoding="utf-8")

_FANOUT_SKILLS = {"codebase-review": _CODEBASE, "security-audit": _SECURITY}
_ALL_SKILLS = {**_FANOUT_SKILLS, "test-audit": _TEST_AUDIT}

# The disclaimer that must accompany the marker everywhere it is defined, so
# `[verified]` is never over-read as machine verification.
_DISCLAIMER = "self-declared honesty label, not a machine-checked guarantee"


# --- The shared contract exists and defines both tiers -----------------------

def test_partial_exists_and_defines_tier1_marker():
    assert "# Fan-out evidence & finding provenance" in _PARTIAL
    assert "`[verified]`" in _PARTIAL and "`[reported]`" in _PARTIAL
    # The universal-floor framing and the anti-overclaim disclaimer.
    assert _DISCLAIMER in _PARTIAL, "the marker's honesty-label disclaimer is gone"


def test_partial_defines_the_evidence_footer():
    """The footer (files-opened-vs-assigned) is the load-bearing mechanism — it is
    what makes the 8-of-82 over-attestation *falsifiable*. Pin its shape."""
    assert "EVIDENCE FOOTER" in _PARTIAL
    assert "Assigned:" in _PARTIAL and "Opened:" in _PARTIAL
    assert "Tools:" in _PARTIAL
    # And the honest framing that the footer is itself self-reported.
    assert "commitment device, not a guarantee" in _PARTIAL


def test_partial_defines_merge_discipline_with_correct_teeth():
    """Cheap parts mandatory, expensive part advisory (the ratified cost guard) —
    and the teeth bound to the RIGHT leg. Asserting MANDATORY/ADVISORY appear
    *somewhere* would stay green if a regression flipped them; bind each to its leg."""
    assert "Low-opened-ratio flag — MANDATORY" in _PARTIAL
    assert "Sample re-read — ADVISORY" in _PARTIAL
    assert "Provenance class in the round summary — MANDATORY" in _PARTIAL
    assert "never a bare" in _PARTIAL
    # Sampling reads INWARD (re-opens the cited site); it is NOT the outward
    # amplification read. Guard the correction of the false "same read" claim that a
    # first-pass review talked us into — amplification greps outward for siblings and
    # never re-opens the cited file:line, so "the read you already do" verifies nothing.
    assert "reads *inward*" in _PARTIAL and "reads *outward*" in _PARTIAL
    assert "the read you already do IS the verification" not in _PARTIAL, (
        "the false 'sampling == amplification' claim is back"
    )


def test_partial_defines_the_reported_consumer_story():
    """A marker with no consumer is decoration. `[reported]` must route to a
    re-read before any fix is applied — never auto-apply blind."""
    assert "re-read the site before applying a fix to a" in _PARTIAL
    assert "never auto-apply blind" in _PARTIAL


# --- Tier 1: the marker + disclaimer land in ALL THREE skills' output ---------

def test_tier1_marker_present_in_every_skill_output():
    # Two review skills use the `[verified|reported]` slot on the finding row.
    for name, text in _FANOUT_SKILLS.items():
        assert "`[verified|reported]`" in text, f"{name} lost the Tier-1 row marker"
    # test-audit composes the marker with its existing confidence bracket, and shows
    # both provenance values (incl. the coverage-artifact [reported] lead).
    assert "[high] [verified]" in _TEST_AUDIT
    assert "[low] [reported]" in _TEST_AUDIT, (
        "test-audit must illustrate the [reported] case (a coverage-artifact lead "
        "on a module it did not open)"
    )


def test_tier1_disclaimer_present_in_every_skill():
    """`[verified]` must never be oversold as machine-verified — the disclaimer
    ships next to the marker in every skill, not only in the shared partial."""
    for name, text in _ALL_SKILLS.items():
        assert _DISCLAIMER in text, f"{name} defines the marker without the disclaimer"


def test_every_skill_cites_the_single_sourced_partial():
    for name, text in _ALL_SKILLS.items():
        assert "fanout-evidence.md" in text, f"{name} does not cite the shared contract"


# --- Tier 2: fan-out skills carry the footer/sampling wiring ------------------

def test_fanout_skills_define_the_sub_agent_return_contract():
    """Dispatch prompts say what to CHECK; the return contract says what to RETURN
    (a footer attaches to a defined return shape, not to thin air)."""
    for name, text in _FANOUT_SKILLS.items():
        assert "Sub-agent return contract" in text, f"{name} has no return contract"
        assert "evidence footer" in text, f"{name} dispatch omits the evidence footer"


def test_fanout_row_defaults_to_reported_until_orchestrator_reads():
    """The load-bearing leg both diff reviewers flagged as unstated in the first
    build: the merge blocks gave only the UPGRADE (sampled → verified) and never the
    DEFAULT, so a sub-agent's self-`[verified]` (incl. the 8-of-82 liar's) would
    launder onto the row unchallenged — the exact over-attestation this phase exists
    to stop. Pin the merge-time default and the two-layer emitter rule."""
    for name, text in _FANOUT_SKILLS.items():
        assert "Row provenance (mandatory)" in text, f"{name} states no merge-time default"
        assert "did **not** itself re-read carries `[reported]`" in text, (
            f"{name} does not default an un-re-read fan-out finding to [reported]"
        )
    # The partial states the two-layer rule: sub-agent self-declares (input); the
    # orchestrator is the emitter at merge and must not copy self-[verified] through.
    assert "the emitter changes at merge" in _PARTIAL
    assert "onto the row unchallenged" in _PARTIAL


def test_fanout_skills_audit_coverage_before_merging():
    for name, text in _FANOUT_SKILLS.items():
        assert "Low-opened-ratio flag (mandatory" in text, (
            f"{name} does not flag a hollow batch as a coverage gap"
        )
        # The provenance/coverage line in the post-scan report block.
        assert "Fan-out coverage:" in text and "Provenance:" in text, (
            f"{name} round summary lost its provenance class"
        )


# --- test-audit: Tier 1 always, Tier 2 only if it fans out -------------------

# --- Phase 205: the enumerated Opened field -----------------------------------
#
# The defect: `Opened` permitted `or "anchored in findings above"`, which defines
# the opened set BY REFERENCE to the findings — so leg (b) ("a `[verified]`
# finding whose cited file is not in `Opened`") and the sampling priority arm
# were both trivially true and could never fire, while reading as live checks.
#
# READ THIS BEFORE TRUSTING THE SECTION. Phase 205's round put 51 independently
# designed bypasses through these guards and 48 walked through; a first cut of
# them also false-killed 10 of 23 legal reformats. What is left here is scoped
# to what it can actually do:
#
#   * the ratio/field-set check is STRUCTURAL and is the one that would have
#     caught the original defect. Phase 205 left it `xfail(strict=True)` because
#     leg (a) still named an operand the footer did not collect; Phase 206
#     closed that (leg (a) reads `Opened` against `Assigned` and sums nothing),
#     so the check is live, and the field set itself is now pinned separately.
#   * the by-reference check is a REVERSION guard and is labelled as one. It
#     catches the retired wording coming back, and it does NOT catch a synonym.
#     That is not a gap to paper over with a longer blocklist — a wider list
#     bought a new false-fire class every time this repo tried it. The general
#     problem is filed.
#
# Claiming more than that in a docstring is how the first cut of this section
# shipped two false headline claims.


def _footer_block(text: str) -> str:
    """The fenced EVIDENCE FOOTER template, derived from the file.

    Bounded to its OWN fence marker. The first cut scanned for any leading
    triple-backtick, so retyping the fence as `~~~` walked the block from 5
    lines to 97 and swallowed the whole section.
    """
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() != "EVIDENCE FOOTER":
            continue
        start = i
        while start > 0 and not _is_fence(lines[start - 1]):
            start -= 1
        if start == 0:
            raise AssertionError("EVIDENCE FOOTER is not inside a fence")
        marker = lines[start - 1].strip()[:3]
        end = i
        while end < len(lines) and not lines[end].strip().startswith(marker):
            end += 1
        return "\n".join(lines[start:end])
    raise AssertionError("no fenced EVIDENCE FOOTER block in the shared contract")


def _is_fence(line: str) -> bool:
    return line.strip().startswith("```") or line.strip().startswith("~~~")


def _footer_fields(block: str) -> set[str]:
    """The field labels the footer template collects.

    ANY label shape counts. The first cut matched one capitalised word, so
    `Grepped files:` walked it; the second still required a leading capital and
    space-separated words, so `Grep_files:` and `GREPPED:` walked it too. Each
    narrowing was found by an independent battery designing labels the regex
    had not been written for — which is the argument for matching the *slot*
    (a label, a colon, at line start) rather than enumerating label spellings.

    What it still cannot see, stated rather than implied: a field mandated in
    PROSE BESIDE the fence instead of inside the template. That is not a label
    shape, and no widening of this regex reaches it.
    """
    return {m.group(1).strip()
            for m in re.finditer(r"^\s*([A-Za-z][\w .-]*?)\s*:", block, re.M)}


_FENCE = re.compile(r"^\s*(?:```|~~~)")


def _outside_fences(lines: list[str]) -> list[bool]:
    """Per-line mask: True where the line is NOT inside a fenced block.

    Fence-blindness was a measured false-fire: a fenced *illustration* of a
    pinned bullet tripped the uniqueness assertion below, so documenting the
    rule reddened the guard for it.
    """
    out, inside, marker = [], False, ""
    for ln in lines:
        if _FENCE.match(ln):
            tok = ln.strip()[:3]
            if not inside:
                inside, marker = True, tok
            elif tok == marker:
                inside = False
            out.append(False)
            continue
        out.append(not inside)
    return out


def _paragraph(text: str, marker: str) -> str:
    """The whole blank-line-delimited block carrying `marker`, outside fences.

    The first cut returned one physical line and asserted exactly one hit.
    Both were measured false-fire sources: reflowing a paragraph — a legal
    edit that renders identically — hid half of it from the guard, and quoting
    the marker anywhere else in the file (including inside a fenced example)
    broke the uniqueness assertion. Blocks, not lines; fences excluded.

    **This definition shipped dead.** Phase 206 wrote it, and in the same commit
    left the superseded physical-line version defined LOWER in the module, which
    Python binds — so every call got the broken helper and both false-fire
    classes above stayed open at five call sites. Nothing caught it: there is no
    lint gate in CI, and a duplicate `def` is not a syntax error. It was also
    placed above the module docstring, which made that docstring inert.
    Restored to a helper position by Phase 207. If you move it, move it here.
    """
    lines = text.splitlines()
    ok = _outside_fences(lines)
    blocks, cur, cur_ok = [], [], False
    for i, ln in enumerate(lines):
        if not ln.strip():
            if cur:
                blocks.append(("\n".join(cur), cur_ok))
            cur, cur_ok = [], False
        else:
            cur.append(ln)
            cur_ok = cur_ok or ok[i]
    if cur:
        blocks.append(("\n".join(cur), cur_ok))
    hits = [blk for blk, vis in blocks if vis and marker in blk]
    assert len(hits) == 1, (
        f"expected one unfenced paragraph carrying {marker!r}, got {len(hits)}"
    )
    return hits[0]


# A list lead-in: `-`, `*`, `+` or `1.`, then bold in either CommonMark form.
# The first cut allowed only `-`/`*`/`N.` and only `**`; a `+` bullet and a
# `__strong__` lead-in each raised a collection error that reddened all 21
# tests at once, which is a guard failing loudly on a legal document edit.
def _lead_re(marker: str) -> re.Pattern:
    return re.compile(rf"^(?:[-*+]|\d+\.)\s+(?:\*\*|__){re.escape(marker)}")


def _list_item(text: str, marker: str) -> str:
    """The WHOLE list item led by `marker`, continuation paragraphs included.

    `_bullet` below reads one physical line, which this repo's round found is
    walkable: move the rule to an indented continuation paragraph and the guard
    stops seeing it while the document reads identically.

    Three things this got wrong on the first cut, all found by the round's
    independent battery and each verified before fixing:

      * it returned the FIRST match, so a decoy item planted earlier won
        silently. It now requires exactly one, outside fences.
      * it stopped at the first blank line whose successor was also blank, so
        inserting **one extra blank line** before a continuation dropped it
        from every guard's view with the suite green — a whitespace edit
        blinding the guard, with no signal.
      * it was fence-blind and marker-narrow (see `_lead_re`).
    """
    lines = text.splitlines()
    ok = _outside_fences(lines)
    lead = _lead_re(marker)
    starts = [i for i, ln in enumerate(lines) if ok[i] and lead.match(ln.lstrip())]
    assert len(starts) == 1, (
        f"expected exactly one list item leading with {marker!r} outside a "
        f"fence, got {len(starts)}"
    )
    start = starts[0]
    # Walk forward, tolerating any run of blank lines: the item ends at the
    # first NON-blank line that is neither indented nor inside a fence opened
    # within the item.
    end = start + 1
    last_content = start + 1
    while end < len(lines):
        ln = lines[end]
        if ln.strip() and not ln.startswith((" ", "\t")):
            break
        end += 1
        if ln.strip():
            last_content = end
    return "\n".join(lines[start:last_content])


# `_bullet` lived here until Phase 207 and is deliberately gone. It read one
# physical line and returned the FIRST match — two limits its own docstring
# declared and left, which meant a decoy item planted earlier in the file won
# silently and a legal soft-wrap truncated the text out from under the guard.
# `_list_item` above fixes both and was already used everywhere else; its one
# remaining caller now uses it too. Do not reintroduce a line-reading variant:
# the reflow false-kill is the single most-measured defect in this module's
# history, and a second helper with the old semantics is how it came back the
# first time.


_FOOTER = _footer_block(_PARTIAL)
_FIELDS = _footer_fields(_FOOTER)
# The WHOLE leg, not its first physical line. `_bullet` reads one line, so
# reflowing the bullet onto a continuation — a legal Markdown edit that changes
# nothing — false-killed every assertion keyed to `_LEG_A`. Caught by the
# author-side battery's control set (C04).
_LEG_A = _list_item(_PARTIAL, "Low-opened-ratio flag — MANDATORY")


def test_the_footer_derivation_is_not_vacuous():
    """Control for the tests below.

    Only the clauses that can actually fail. The first cut had five, two of
    which held by construction of the helpers they were checking — a control
    that cannot fail is the thing it exists to detect.
    """
    assert len(_FIELDS) >= 3, f"footer field derivation collapsed: {_FIELDS}"
    assert _FOOTER.count("\n") >= 3, "footer block collapsed to a stub"
    # NOT a length threshold. Leg (a)'s lead-in line alone is ~1,400 chars, so
    # `len > 200` was 7x satisfied by the lead-in and could not detect the
    # collapse it named — the round demonstrated it staying green after the
    # whole continuation was deleted. What matters is that the continuation is
    # still IN VIEW: `_list_item` truncated silently on a blank-line run, so a
    # whitespace edit blinded every guard keyed to it.
    assert "\n" in _LEG_A, (
        "leg (a) resolved to its lead-in line only — either the continuation "
        "paragraph is gone, or `_list_item` stopped reaching it"
    )
    assert "account, not a verdict" in _unmarked(_LEG_A), (
        "leg (a)'s continuation is not in view; every assertion scoped to the "
        "whole leg is now reading half a rule"
    )


def test_the_footer_collects_exactly_the_known_field_set():
    """Pin the template's field set, so adding one is a decision, not a drift.

    This replaces the re-arming half of the `Q-218` xfail. That half **did**
    work, for one label: measured on the pre-206 tree, pasting a bare
    `Grepped:` into the template flipped the strict xfail to XPASS and the
    module went red, exactly as its reason text promised. What it could not see
    is any *other* label — the old guard reddened only when a new field's
    capitalised name matched leg (a)'s current lowercase sum operand, so
    `Searched:` was invisible. An earlier draft of this docstring said the
    re-arming half "did not work" and that a bare label "turned it green";
    both were wrong, and the round measured them.

    This pin is keyed to the field set instead, so any label reds it.

    A field added here reds this test on the label alone. Whoever adds one has
    to come to this file, which is where the objections to a bare count are
    written down (see `test_the_mandatory_ratio_reads_only_fields_the_footer_collects`).
    """
    assert _FIELDS == {"Assigned", "Opened", "Tools"}, (
        f"the evidence footer's field set changed: {sorted(_FIELDS)}. A new "
        "field is not a formatting change — `_shared/fanout-evidence.md` "
        "§ Tier 2 forbids a bare count in this template, and Phase 205's "
        "`Grepped: <G>` was reverted by its own round for being one. If the "
        "addition is deliberate, update leg (a) and this pin together."
    )


def test_the_mandatory_ratio_reads_only_fields_the_footer_collects():
    """The structural check: every operand of the MANDATORY ratio must be a
    field the template actually returns.

    `Q-218`, closed by Phase 206. Leg (a) read `opened + grepped` in *files*
    while the footer collected `Tools: grep=<n>`, an invocation count — so the
    one mandatory check named an operand that did not exist, and then withdrew
    its own formula three clauses later in the same bullet. Leg (a) now reads
    `Opened` against `Assigned` and sums nothing.

    Three ways the previous form of this guard could be walked, all of which
    this one closes:

      * it required a literal `x + y`, so the *fix* (drop the sum) left it
        failing on `assert sums` — indistinguishable from the defect;
      * its operand regex was lowercase-only, so `Opened + Grepped` matched
        nothing at all;
      * it read one physical line, so the rule could move to a continuation
        line and vanish from the guard's view.
    """
    item = _list_item(_PARTIAL, "Low-opened-ratio flag — MANDATORY")

    # Scoped to clause (a) ITSELF, not the leg. The leg restates the threshold
    # in its continuation paragraph, so a file- or leg-wide search is satisfied
    # by the restatement while the rule the orchestrator reads first has been
    # gutted — a survivor the author-side battery found (M06).
    m = re.search(r"[*_]{2}\((?:a|1)\)[^*_]*[*_]{2}(.*?)[*_]{2}\((?:b|2)\)", item, re.S)
    assert m, "clause (a) is no longer a labelled clause of the mandatory leg"
    clause = _unmarked(m.group(1))

    # The rule must still STATE a threshold. A leg that quietly loses its
    # boundary is the same defect as one that names a phantom operand.
    # Glyph OR ASCII: writing the same fraction `1/3` is a legal edit and
    # false-killed the first cut. The rule is the threshold, not its spelling.
    assert ("⅓" in clause or "1/3" in clause), (
        f"clause (a) states no coverage threshold — the mandatory check lost "
        f"its rule: {clause!r}"
    )

    # Every field-shaped name in clause (a) has to be one the footer returns.
    # Matched on markup-stripped text and case-insensitively, because the
    # defect does not care how the operand is capitalised or fenced (M04).
    named = {w.capitalize() for w in re.findall(r"\b([A-Za-z]{4,})\b", clause)}
    for field in ("Opened", "Assigned", "Tools", "Grepped", "Manifest", "Searched"):
        if field in named:
            assert field in _FIELDS, (
                f"clause (a) reads {field!r}, which the footer does not "
                f"collect (fields: {sorted(_FIELDS)}): {clause!r}"
            )

    # And nowhere in the leg may two field-shaped words be summed unless BOTH
    # are collected — the generalised form of the original assertion: markup
    # stripped first (so `Opened` + `grepped` is visible) and case-insensitive.
    for left, right in re.findall(r"\b([A-Za-z]+)\s*\+\s*([A-Za-z]+)\b",
                                  _unmarked(item)):
        for operand in (left, right):
            assert operand.capitalize() in _FIELDS, (
                f"leg (a) sums {operand!r}, which the footer does not collect "
                f"(fields: {sorted(_FIELDS)}). This is the `Q-218` defect "
                f"returning: the sum was removed because its second operand "
                f"was never a footer field."
            )


def test_opened_is_enumerated_and_bound_to_its_own_count():
    """Enumeration alone is dodged by listing only the files the findings cite,
    which reproduces the original vacuity — so `<M>` must equal what the list
    resolves to, turning that dodge into a self-reported low-coverage number."""
    opened = next(ln for ln in _FOOTER.splitlines() if ln.lstrip().startswith("Opened:"))
    assert "list the paths" in opened, "the Opened field stopped requiring paths"
    assert "must equal what the list resolves to" in _PARTIAL, (
        "the arity binding between <M> and the listed paths is unstated"
    )
    assert "short list" in _LEG_A, "nothing checks the arity binding at merge"


def test_the_retired_by_reference_form_has_not_been_restored():
    """A REVERSION guard, and only that.

    WHAT IT CATCHES: the retired wording, and the two tokens any near-paraphrase
    of it has used so far, on the template line.

    WHAT IT DOES NOT CATCH, demonstrated rather than supposed: a synonym. The
    round put "or simply the set your report cites" onto the template line and
    the full suite stayed green. Seven further routes exist — a continuation
    line inside the fence, a second `Opened:` line, a worked example outside it,
    a retyped fence. Do not read a pass here as "the hatch cannot come back";
    read it as "the hatch has not come back the way it went out." Closing the
    general case is a normalized-claim problem, filed with `Q-214`.
    """
    opened = next(ln for ln in _FOOTER.splitlines() if ln.lstrip().startswith("Opened:"))
    assert not any(t in opened.lower() for t in ("finding", "above", "cite")), opened
    assert "anchored in findings" not in _PARTIAL
    # The paragraph stating WHY the form is void, which is the part a future
    # editor has to delete before re-adding the form in good conscience.
    # Scoped to the paragraph this assertion exists to pin. Phase 206 added a
    # second, incidental "by construction" to the Tier-0 bullet, which made the
    # file-wide form satisfiable from text that has nothing to do with the
    # by-reference hatch — a pre-existing guard weakened as a side effect of an
    # unrelated edit, found by the round.
    why = _unmarked(_paragraph(_PARTIAL, "There is no by-reference form"))
    assert "by construction" in why and "trivially true" in why


def test_the_sampling_arm_has_an_invoker_in_both_fanout_skills():
    """The arm — 'any finding whose cited file is absent from its `Opened` list'
    — existed only in the shared contract; both merge bullets restated the
    sample re-read without it, so restoring it in the contract alone would have
    restored a rule nothing calls (the Phase 166 shape)."""
    assert "absent from its `Opened` list" in _PARTIAL
    for name, text in _FANOUT_SKILLS.items():
        sampling = _list_item(text, "Sample re-read (advisory)")
        assert re.search(r"(absent from|not (?:present )?in) its `Opened` list", sampling), (
            f"{name}'s sample re-read does not prioritise unopened cited files"
        )


def test_test_audit_tier2_is_conditional_not_unconditional():
    """test-audit runs single-agent inline, so it gets the Tier-1 marker
    unconditionally but the fan-out footer only *if* it fans out. Guard the
    conditional framing so a future edit can't turn it into an unconditional
    (and false) fan-out step.

    This docstring used to call that "the `--all` sub-auditor case", which the
    skill itself contradicts: `--all` chunks per module *within one agent* and
    spawns nothing. The observed sub-auditor run was a cross-harness one. The
    queue entry that filed the missing paste instruction inherited the same
    wrong attribution from here, so both are corrected together.
    """
    assert "If you fan out" in _TEST_AUDIT
    assert "§ Tier 2" in _TEST_AUDIT
    assert "the single-agent base path above has no fan-out" in _TEST_AUDIT


# --- Phase 206: the derivation (Q-215) and the third consumer (Q-216) --------
#
# Two gaps Phase 205's round left open, closed together because they are the
# same shape: a contract that states a rule where the actor who must obey it
# never reads it.
#
#   * Q-215 — nothing said how a fan-out round derives its Tier-0 `opened <M>`.
#     Four shipped consumers already compute on that number.
#   * Q-216 — `/test-audit` cited the Tier-2 legs by reference and never told
#     the orchestrator to paste anything, so a sub-auditor could be spawned
#     with no footer template and no adjudication pair.
#
# HONEST LIMITS, stated because this file's last section overstated itself and
# its round proved it: these are presence checks over prose. They catch the
# rule being deleted or reverted. They do not catch it being contradicted
# elsewhere, and they cannot tell whether any agent obeyed it.


def _unmarked(text: str) -> str:
    """`text` with emphasis and code markup stripped, whitespace collapsed.

    Phrase pins in this repo have twice false-killed *correct* edits — Phase
    205's first cut killed 10 of 23 legal reformats, several of them nothing
    more than bolding a different word inside a pinned sentence. Matching the
    prose rather than its markup removes that whole false-fire class. It buys
    no extra reach against a synonym, and is not claimed to.
    """
    return re.sub(r"\s+", " ", text.replace("*", "").replace("`", ""))


def test_the_round_level_opened_states_its_derivation():
    """Q-215. The round figure had no stated arithmetic, and the two readings
    differ by the whole fan-out.

    The union reading is not a preference: `sitrep_survey.py`, `self_check.sh`
    and both skills' Step-5f receipt writers all gate on `opened + grepped`
    against the manifest, and every one of those gates is `Full`-only. Under an
    orchestrator-only reading every honest fan-out round is `Sampled` and
    therefore exempt from all four — the ~1% failure Tier 0 exists to end,
    reintroduced by a definition.
    """
    # Scoped to the `Opened <M>` bullet and its sub-bullets. A file-wide search
    # is satisfied from anywhere in the contract — the author-side battery
    # gutted this bullet and stayed green off an incidental later use (M09).
    flat = _unmarked(_list_item(_PARTIAL, "Opened `<M>`"))
    # The DEFINITIONAL clause, not the phrase. Scoping to the bullet was not
    # enough: a later sub-bullet recounts two archived rounds, one of which
    # "aggregat[ed] by deduplicated union", so gutting the definition left the
    # phrase present and the guard green (M09).
    assert "<M> is the deduplicated union" in flat, (
        "Tier 0 no longer defines `opened <M>` as the deduplicated union — the "
        "derivation is what this bullet exists to state"
    )
    # Both wrong readings must stay explicitly excluded. Either one returning
    # silently is how the field goes ambiguous again.
    assert "not a sum of the footers" in flat, (
        "the non-deduplicated sum — the arithmetic one real round actually "
        "used — is no longer ruled out"
    )
    assert "not the orchestrator's own reads alone" in flat, (
        "the orchestrator-only reading is no longer ruled out, and it is the "
        "one that silently exempts every fan-out round from the Full gates"
    )
    # The three ways the union under- or over-counts by accident.
    assert "no footer contributes nothing" in flat
    assert "outside the round's manifest, do not count" in flat
    # And the Tier-0/Tier-1 boundary the union must not blur: a worker's read
    # counts toward round coverage and never toward a row's [verified].
    assert "never counts toward a row's [verified]" in flat


def test_both_review_skills_point_opened_at_the_union_not_at_you():
    """Q-215's write-side half. A REVERSION guard, and only that.

    Both skills localised `opened` to "files whose bodies you read", which is
    what made the field read as orchestrator-only at the one place a round
    actually fills it in. It catches that phrasing coming back. It does not
    catch a synonym, and a round can still write any number it likes.
    """
    for name, text in _FANOUT_SKILLS.items():
        line = _unmarked(_paragraph(text, "The coverage line is MANDATORY"))
        assert "opened = files whose bodies you read" not in line, (
            f"{name}: the orchestrator-only phrasing of `opened` is back"
        )
        assert "deduplicated union" in line, (
            f"{name}: the coverage-line instruction does not say how `opened` "
            f"is derived on a fan-out round"
        )


def test_test_audit_hands_the_contract_to_its_sub_auditors():
    """Q-216. `/test-audit` is the contract's third consumer and the only one
    that cited the Tier-2 legs without ever telling the orchestrator to paste
    them — so on its fan-out branch the merge legs it *does* cite would have
    had nothing to read.

    Scoped to the fan-out paragraph on purpose: the instruction must be
    unreachable on the single-agent base path, which does not dispatch and owes
    no footer. A file-wide substring check would pass with the sentence sitting
    in the solo path, which is the failure it is meant to prevent.
    """
    fanout = _unmarked(_paragraph(_TEST_AUDIT, "**If you fan out**"))
    # Scoped to the sentence that carries the instruction, not the paragraph.
    # The paragraph mentions § Adjudication twice for two different reasons, so
    # a paragraph-wide check stayed green with the paste clause deleted — the
    # incidental-substring class, found by the author-side battery (M18).
    instruction = next(
        (s for s in re.split(r"(?<=\.)\s+", fanout) if "verbatim" in s), None
    )
    assert instruction, (
        "test-audit's fan-out branch does not tell the orchestrator to paste "
        "the contract into the sub-auditor's prompt — a bare reference reaches "
        "the orchestrator, not the agent that owes the footer"
    )
    # Both payloads, named in the SAME sentence. The footer template alone
    # leaves the sub-auditor adjudicating its own findings with no evidence
    # standard, which is the half the queue entry did not name.
    assert "footer template" in instruction, (
        f"the footer template is not among what must be pasted: {instruction!r}"
    )
    assert "Adjudication" in instruction, (
        f"the § Adjudication kill/keep pair is not among what must be pasted — "
        f"`fanout-evidence.md` requires it alongside the footer for the same "
        f"reason: {instruction!r}"
    )
    # The third payload. The contract's MUST names it in the same breath as the
    # footer block, and both review skills carry it as clause (1) of their
    # return contract. The first cut of this test asserted only the two above,
    # so the phase shipped an instruction missing a third of the contract and
    # pinned the omission in place — found by the round, then by M22.
    assert "self-tag" in instruction and "file:line" in instruction, (
        f"the per-finding `file:line` + `[verified]`/`[reported]` self-tag "
        f"requirement is not among what the sub-auditor is handed. Without it "
        f"the agent returns untagged findings and merge leg (b) — a "
        f"`[verified]` finding whose cited file is absent from `Opened` — has "
        f"nothing to read: {instruction!r}"
    )
    # Control, over the WHOLE skill minus the fan-out paragraph. The first cut
    # inspected a single Step-2 paragraph ~90 lines away, so the instruction
    # could leak onto any other solo-path text and stay green — a control
    # pointed at one place cannot establish absence everywhere.
    rest = _unmarked(_TEST_AUDIT).replace(fanout, "")
    assert "paste" not in rest or "verbatim" not in rest, (
        "a verbatim-paste instruction appears outside the fan-out paragraph. "
        "The solo base path dispatches nothing and writes no footer, so a "
        "paste obligation there is an instruction with no actor"
    )


def test_both_merge_bullets_require_an_account_not_a_nudge():
    """The load-bearing half of the `Q-218` re-cut, and the half nothing pinned.

    Leg (a)'s sparse carve-out used to read "do not flag an honestly sparse
    review" — unfalsifiable, claimable by any batch, so the one MANDATORY leg
    cost nothing to satisfy. It now obliges the orchestrator to record WHICH
    case a low ratio is and what decided it. The author-side battery demoted
    that back to "a low ratio is a prompt to look" in both executing skills and
    the whole suite stayed green: nothing pinned the merge bullets' text beyond
    the words "Low-opened-ratio flag (mandatory" (M20, M21).

    Presence check over prose, and that is all. It catches the requirement
    being deleted or softened back to a nudge. It cannot tell whether any
    orchestrator wrote the account, and does not claim to.
    """
    for name, text in _FANOUT_SKILLS.items():
        # `_list_item`, not `_bullet`: the same one-physical-line fragility this
        # module fixed for `_LEG_A` was reintroduced here in the first cut, and
        # the round found it — reflowing the consequence clause onto a legal
        # Markdown continuation reddened the guard.
        bullet = _unmarked(_list_item(text, "Low-opened-ratio flag (mandatory"))
        assert "account you owe" in bullet, (
            f"{name}: the low-look signal is no longer stated as an account "
            f"the orchestrator owes — a flag that may be declined is the "
            f"unfalsifiable exemption this replaced"
        )
        assert "unaccounted-for is itself the coverage-gap line" in bullet, (
            f"{name}: nothing says what happens when the account is not given, "
            f"so the requirement has no consequence"
        )
        # And the ratio must not have re-acquired a second operand here either.
        for left, right in re.findall(r"\b([A-Za-z]+)\s*\+\s*([A-Za-z]+)\b", bullet):
            for operand in (left, right):
                assert operand.capitalize() in _FIELDS, (
                    f"{name}: the merge bullet sums {operand!r}, which the "
                    f"footer does not collect"
                )


# --- Phase 206 round: presence pins for the normative source ------------------
#
# The round's guards lens designed 45 bypasses and 43 walked. Most were the
# English problem this repo has filed as a design item (a pinned phrase kept
# inside a sentence asserting the opposite), and widening a blocklist against
# that has bought a new false-fire class every time it has been tried here —
# the same lens measured 9 false kills in 19 legal edits against the first cut.
#
# What is closable is narrower and worth closing: several NORMATIVE paragraphs
# this phase wrote had no coverage at all, so deleting them outright was free.
# These pin existence, and only existence.
#
# WHAT THEY CATCH: deletion, and gutting to a stub.
# WHAT THEY DO NOT CATCH, measured rather than supposed: inversion, a negating
# wrapper, or a trailing qualifier that retires the rule. Do not read a pass
# here as "the rule holds"; read it as "the rule is still on the page."

def test_the_normative_paragraphs_this_phase_wrote_still_exist():
    flat = _unmarked(_PARTIAL)
    for label, needle in [
        ("leg (a)'s account, not a verdict",
         "What (a) fires is an account, not a verdict"),
        ("the Tier-2 twin asymmetry", "<G> is a Tier-0 field and has no Tier-2 twin"),
        ("the three-field statement",
         "The evidence footer collects Assigned, Opened and Tools, and nothing else"),
        ("leg (a) sums nothing",
         "Leg (a) below therefore reads Opened against Assigned and sums nothing"),
        ("the bare-count objection", "has to survive the same enumeration test"),
        ("the MUST-paste rule", "The orchestrator MUST paste this exact footer block"),
        ("the account's landing place", "the one-line account that leg obliges"),
    ]:
        assert needle in flat, f"the normative paragraph for {label} is gone: {needle!r}"


def test_the_arithmetic_asymmetry_comment_survives_in_the_survey():
    """`sitrep_survey.py`'s constant comment is the phase's own record of why
    Tier 0 sums and Tier 2 does not. It had cited Tier 2 as the source of the
    sum, which was never true of any footer it could read. Reverting it to that
    false attribution was free — nothing read it."""
    survey = (Path(__file__).resolve().parent.parent / "core" / "companion"
              / "scripts" / "sitrep_survey.py").read_text(encoding="utf-8")
    block = survey[survey.index("LOW_LOOK_RATIO = 3"):][:900]
    assert "they no longer share an arithmetic" in block.replace("\n", " ").replace("#", "").replace("  ", " ") or \
           "no longer share an" in " ".join(block.split()), (
        "the LOW_LOOK_RATIO comment no longer records that the two tiers share "
        "a threshold and not an arithmetic"
    )
    assert "Tier 2's `opened + grepped`, unchanged" not in block, (
        "the false cross-tier identity is back in the constant's comment"
    )


def test_the_paragraph_corpus_runs_in_ci():
    """`_paragraph` is a state machine over Markdown too, and it had no corpus.

    `_list_item` got one; `_paragraph` did not, and the round measured the cost:
    four independent weakenings walked the whole module — dropping the fence
    mask, relaxing uniqueness from exactly-one to at-least-one, adding a
    physical-line fast path, and dropping `~~~` from the fence pattern. Each is
    a way to reintroduce the reader this phase just deleted.

    Same precedent as the corpus above: it lives here, where CI opens it.
    """
    # The whole block, not the first line — the reflow case.
    assert "second" in _paragraph("start here\nsecond line\n\nafter\n", "start here")
    # Blocks are blank-line delimited; a later block is not part of this one.
    assert "after" not in _paragraph("start here\nsecond line\n\nafter\n", "start here")
    # A fenced illustration of the marker is not a second block — this is the
    # exact false fire the shadowed reader produced at three call sites.
    assert "real" in _paragraph("```\nMARK decoy\n```\n\nMARK real text\n", "MARK")
    # `~~~` is a legal CommonMark fence too, and dropping it from the mask was a
    # surviving mutation.
    assert "real" in _paragraph("~~~\nMARK decoy\n~~~\n\nMARK real text\n", "MARK")
    # Two REAL unfenced blocks carrying the marker is a loud red, never a silent
    # pick of the first — relaxing this to `>= 1` was a surviving mutation.
    import pytest as _pytest

    with _pytest.raises(AssertionError):
        _paragraph("MARK one\n\nMARK two\n", "MARK")
    # An unterminated fence runs to EOF rather than being dropped: the
    # conservative answer on input that never closes.
    with _pytest.raises(AssertionError):
        _paragraph("```\nMARK only inside an unclosed fence\n", "MARK")


def test_the_list_item_corpus_runs_in_ci():
    """`_list_item` is a state machine over Markdown other writers produce, so
    it gets a hostile corpus — and the corpus lives HERE, not in `tools/`.

    The first cut put it in the author-side battery script, which nothing
    imports and CI never runs: the case that would have caught the blank-run
    truncation was one blank line from failing, in a file no gate opens. This
    repo's precedent is an in-suite corpus.
    """
    doc = "1. **Target** lead\n2. **Other** second\n"
    assert "second" not in _list_item(doc, "Target")           # sibling
    assert "only" in _list_item("1. **Target** only", "Target")  # EOF
    assert "After" not in _list_item("1. **Target** a\n\nAfter.\n", "Target")
    assert "cont" in _list_item("1. **Target** a\n\n   cont\n\nAfter.\n", "Target")
    assert "nested" in _list_item("1. **Target** a\n   - nested\n2. **Other**\n", "Target")
    # A RUN of blank lines must not truncate the item. This is the one the
    # tools/-only corpus missed, and it blinded every guard keyed to `_LEG_A`.
    assert "cont" in _list_item("1. **Target** a\n\n\n   cont\n", "Target")
    # Alternate legal markers: `+` bullet, `__strong__` lead-in.
    assert "x" in _list_item("+ **Target** x\n", "Target")
    assert "x" in _list_item("- __Target__ x\n", "Target")
    # A fenced illustration of the same bullet is not a second item.
    assert "real" in _list_item("```\n- **Target** decoy\n```\n\n- **Target** real\n", "Target")
    # Two REAL items with one lead-in is a red, not a silent pick of the first.
    for bad in ("1. **Target** a\n\nx\n\n1. **Target** b\n",):
        try:
            _list_item(bad, "Target")
            raise AssertionError("a decoy item was silently picked")
        except AssertionError as e:
            assert "exactly one" in str(e), e
    # And the shipped rule resolves, continuation included.
    assert "account, not a verdict" in _unmarked(
        _list_item(_PARTIAL, "Low-opened-ratio flag — MANDATORY"))


def test_the_derivation_reached_every_site_that_states_the_field():
    """Q-215's population was "both review skills", and that was two of four.

    The round found the other two by looking rather than by reading the entry:
    `/test-audit` states its own Tier-0 `opened` (and this phase is the one
    that gave it a fan-out branch, so leaving it orchestrator-only was an
    inconsistency the phase itself introduced), and `WORKFLOW.md` — the
    authoritative spec — carries the definition a consumer reads. The phase's
    own thesis is that the derivation must be stated where a round fills the
    field in; these are two of those places.
    """
    ta = _unmarked(_paragraph(_TEST_AUDIT, "Record that as the Tier-0 coverage ledger"))
    assert "opened the ones whose bodies you read" not in ta, (
        "test-audit's Tier-0 line is orchestrator-only again, on a skill that "
        "now documents a fan-out branch"
    )
    assert "deduplicated union" in ta, (
        "test-audit states no derivation for `opened` on its fan-out branch"
    )
    spec = (Path(__file__).resolve().parent.parent / "core" / "companion"
            / "docs" / "WORKFLOW.md").read_text(encoding="utf-8")
    line = _unmarked(_paragraph(spec, "Round metadata — the coverage ledger"))
    assert "deduplicated union" in line, (
        "WORKFLOW.md § 6.1 — the authoritative spec, and one of the places a "
        "round fills this field in — still defines `opened` with no fan-out "
        "derivation"
    )
    assert "not the orchestrator's reads alone" in line, (
        "the spec does not exclude the reading that exempts every fan-out "
        "round from the low-look gate"
    )


def test_no_module_in_the_test_tree_shadows_its_own_helper():
    """Phase 206 shipped a fix that was dead on arrival, and nothing saw it.

    `_paragraph` was defined twice in THIS module, in one commit — the repaired
    fence-aware reader and the superseded physical-line one — and Python binds
    the later definition, so every call got the broken helper for a whole phase
    while the record claimed the fix had landed.

    Phase 207 fixed the instance and, on a first pass, shipped no guard on the
    grounds that the population was one. The round then re-appended the old
    definition at module end and the suite stayed green at 119 passed: the
    *class* was fully reopenable, and it only reds once someone ALSO makes the
    legal edit the shadowed helper mishandles — which is exactly why it survived
    undetected the first time. A defect that needs a second, unrelated edit
    before it becomes visible is the kind a guard has to catch directly.

    Scoped to a duplicate top-level binding, which is unambiguous and needs no
    linter. Whether this repo wants a real linter in CI is a larger decision
    with a real cost, filed separately rather than smuggled in here.
    """
    import ast

    offenders = []
    for path in sorted(_TESTS_DIR.rglob("test_*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - parse bail
            continue
        seen: dict[str, int] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name in seen:
                    offenders.append(
                        f"{path.relative_to(_TESTS_DIR.parent)}: {node.name} defined at "
                        f"line {seen[node.name]} and again at line {node.lineno} "
                        f"— line {node.lineno} wins"
                    )
                seen[node.name] = node.lineno

    assert offenders == [], (
        "a top-level name is defined twice in a test module. The later "
        "definition silently wins, so the earlier one is dead code — and when "
        "the earlier one is the repaired version, the repair never runs while "
        "the record says it shipped.\n  " + "\n  ".join(offenders)
    )


def test_the_shadowing_guard_is_not_vacuous():
    """Control for the guard above — it must actually parse and inspect files.

    An empty corpus, a swallowed parse error, or an rglob that matches nothing
    all leave the assertion trivially true while reporting a clean sweep. This
    pins that the sweep reaches a real population and that its detection works
    on a document that genuinely carries the defect.
    """
    import ast

    modules = list(_TESTS_DIR.rglob("test_*.py"))
    assert len(modules) >= 100, (
        f"the shadowing sweep reads only {len(modules)} test modules — its "
        "corpus has collapsed and it is certifying breadth it does not have"
    )

    planted = ast.parse("def _helper():\n    return 1\n\n\ndef _helper():\n    return 2\n")
    seen: dict[str, int] = {}
    dupes = []
    for node in planted.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in seen:
                dupes.append(node.name)
            seen[node.name] = node.lineno
    assert dupes == ["_helper"], (
        "the duplicate-detection logic no longer flags a module that defines "
        f"the same top-level name twice: {dupes}"
    )
