"""Drift guards for Phase 179 — upstream #280: a placeholder-glob map section
carries no Check/Skip authority, and the remedy the review skills prescribe must
be one a consumer can actually reach.

GDP reported that a consumer's assembled `.claude/security_map.md` permanently
carries pack sections whose globs are still in `<…>` placeholder form, and that
each such section's `**Skip:**` line is a *negative routing decision* the
`/security-audit` fan-out is told to honour — pointed at files it does not match,
and in two measured cases contradicting the consumer's own localized overlay
section. `install.sh`'s `apply_substitutions()` is hard-gated to `*/checks.yml`
(deliberately — Phase 55 reverted markdown substitution after it rewrote section
headers into junk), so the placeholders never resolve.

**This module was rebuilt after its own adversarial round.** The first version
pinned *fragments* with `in <whole file>`, and an independent reviewer ran 79
mutations against it: 32 of 62 defect mutations survived (52%), including a
simultaneous reversal of all three legs with the full suite green. The guards
detected deletion and nothing else. The rebuild follows that reviewer's own
prescription, and each class below names the mutation family it exists to kill:

  * **whole sentences, never fragments** — every pinned fragment was satisfiable
    by a sentence asserting the opposite around it ("It is a myth that a
    placeholder-glob section matches nothing and excludes nothing").
  * **scoped to the block that governs** — a file-level `in` cannot tell Step 4
    dispatch from an appendix at EOF, so the paragraph could be moved out of the
    step it governs and still pass.
  * **rendered text only** — `_rendered()` strips HTML comments and fenced
    blocks, because both were used to satisfy a pin with text no agent ever acts
    on.
  * **typography-insensitive absence checks** — the dead remedy was revivable by
    dropping its parentheses or swapping one ASCII apostrophe for a curly one.
  * **shape-matched Skip detection** — `**Skip:**`, `**Skip**:`, `- **Skip**:`
    and a bare `Skip:` all carry the same weight; pinning one spelling let the
    others in. Matching bare `Skip\\b` instead is wrong in the other direction —
    it reddens on "Skip generated migration files…", ordinary prose in a
    conventions document.
  * **the assembled artifact, not just the sources** — every guard read source
    files, so a dedup filter in `install_security_map()` stripped the note from
    every consumer install with the whole suite green. That is the artifact #280
    is actually about.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SKILLS = _ROOT / "core" / "skills"
_INSTALL_SH = _ROOT / "install.sh"

_SECURITY = (_SKILLS / "security-audit" / "SKILL.md").read_text(encoding="utf-8")
_CODEBASE = (_SKILLS / "codebase-review" / "SKILL.md").read_text(encoding="utf-8")
_REVIEW_SKILLS = {"codebase-review": _CODEBASE, "security-audit": _SECURITY}
_OWN_MAP = {"codebase-review": "convention_map", "security-audit": "security_map"}


# --------------------------------------------------------------------------- #
# text primitives
# --------------------------------------------------------------------------- #

def _rendered(text: str) -> str:
    """Drop HTML comments and fenced code blocks — what a reader acts on.

    Both were used by the round to satisfy a pin with text that renders to
    nothing or reads as a sample rather than an instruction.
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"^```.*?^```", "", text, flags=re.DOTALL | re.MULTILINE)
    return text


def _norm(text: str) -> str:
    """Fold typography so an absence check cannot be evaded by punctuation."""
    for curly, plain in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"')):
        text = text.replace(curly, plain)
    text = re.sub(r"[()]", "", text)
    return re.sub(r"\s+", " ", text).lower()


def _block(text: str, start: str, end: str, label: str) -> str:
    """The rendered span from `start` up to `end`. Both anchors must be unique."""
    body = _rendered(text)
    assert body.count(start) == 1, f"{label}: start anchor x{body.count(start)}"
    i = body.index(start)
    j = body.find(end, i)
    assert j != -1, (
        f"{label}: end anchor {end!r} not found after the start anchor — a heading "
        "was renamed. Update this block's bounds; the guards below are not "
        "asserting anything until you do"
    )
    return body[i:j]


def _2a0_end(text: str) -> str:
    """The next `### 2a-` heading that is not a 2a-0 sub-check.

    A bare `\n### 2a-` end anchor made inserting a `### 2a-0a.` sub-check red two
    tests — a false alarm on an ordinary structural edit.
    """
    body = _rendered(text)
    i = body.index("### 2a-0.")
    for m in re.finditer(r"\n### 2a-[^\n]*", body[i:]):
        if not m.group(0).startswith("\n### 2a-0"):
            return m.group(0)
    raise AssertionError("no 2a- heading follows 2a-0")


def _dispatch_block(text: str) -> str:
    return _block(
        text,
        "**CRITICAL: Read `.claude/security_map.md` before launching agents.**",
        "### Agent 1:",
        "Step 4 dispatch",
    )


def _do_not_report_block(text: str) -> str:
    return _block(
        text,
        "**Do-not-report list (dispatch-side FP guard",
        "### Agent 1:",
        "do-not-report list",
    )


def _2a0_block(text: str) -> str:
    return _block(text, "### 2a-0.", _2a0_end(text), "2a-0 invariant")


def _maps(kind: str) -> dict[str, str]:
    """Every shipped map of `kind`, discovered rather than listed.

    An authored list that omits a surface never flags the omission — the
    reporter's own stated reason for deriving their test. Core is named
    explicitly because there is exactly one core map and it is not under
    `packs/`; every *pack* is discovered, so a pack added later inherits the
    rule or fails here.
    """
    paths = [_ROOT / "core" / "companion" / f"{kind}.md"]
    paths += sorted((_ROOT / "packs").glob(f"*/companion/{kind}.md"))
    return {str(p.relative_to(_ROOT)): p.read_text(encoding="utf-8") for p in paths}


def _sections(text: str) -> list[tuple[str, list[str], str]]:
    """(header, backticked globs, body) for each `## ` section."""
    out = []
    parts = re.split(r"^(## .*)$", text, flags=re.MULTILINE)
    for i in range(1, len(parts), 2):
        out.append((parts[i], re.findall(r"`([^`]+)`", parts[i]), parts[i + 1]))
    return out


def _is_placeholder(glob: str) -> bool:
    return bool(re.search(r"<[^>]+>", glob))


# A *Skip list* is a labelled negative-routing block: an optional bullet, optional
# bold, the word Skip, then a colon. That shape catches `**Skip:**`, `**Skip**:`,
# `- **Skip**:` and bare `Skip:` — and does NOT catch "Skip generated migration
# files when applying the rule above.", which is ordinary imperative prose.
_SKIP_LIST = re.compile(r"(?im)^\s*[-*]*\s*\**\s*Skip\**\s*:")

# Targeted polarity backstop. Each alternative is a reversal the round actually
# ran; a generic negation detector over prose is not achievable, so this is
# honest about being a blocklist of measured attacks rather than a proof.
_REVERSALS = re.compile(
    r"(?i)"
    r"skip[^.\n]{0,120}?\b(still\s+(?:honou?r|applies|binding)|always\s+grounds|"
    r"regardless\s+of|whether\s+or\s+not\s+its\s+globs)"
    r"|\bis\s+a\s+myth\s+that\b"
    r"|\blet\s+a\s+placeholder\s+skip\s+stand\b"
    r"|\b(?:localized|placeholder)\s+or\s+not\b"
    r"|\btreat\s+every\s+`?skip"
    r"|\bediting\s+the\s+assembled\s+\S*map\S*\s+in\s+place\s+is\s+simpler\b"
    r"|\bwhatever\s+the\s+agent\s+judges\s+best\b"
    r"|\bno\s+longer\s+required\b"
    r"|\btry\s+the\s+token\s+first\b"
)


# A rule can be left byte-perfect and simply framed as non-authoritative — a
# "Superseded, do not follow:" banner above it, an "Editorial aside, not an
# instruction:" prefix, a "Do NOT assume the following:" lead-in, a "(Historically
# …, no longer required)" wrapper. Four of the round's survivors were this class
# and nothing else in this module can see it.
_DEMOTION = re.compile(
    r"(?i)\b(superseded|do not follow|no longer (?:required|applies|in force)|"
    r"retained for history|historical(?:ly)?|editorial aside|not an instruction|"
    r"do not assume|deprecated|for reference only)\b"
)


def _assert_starts_a_line(haystack: str, sentence: str, label: str) -> None:
    """The rule must begin its own line — not trail a prefix that reframes it."""
    i = haystack.index(sentence)
    prefix = haystack[:i].rsplit("\n", 1)[-1]
    assert prefix.strip() == "", (
        f"{label}: the rule no longer starts its own line — it trails "
        f"{prefix.strip()[:60]!r}, which reframes it without touching its bytes"
    )


# --------------------------------------------------------------------------- #
# the pinned rules — whole sentences
# --------------------------------------------------------------------------- #

_SCOPE_NOTE = (
    "> **Scope note — a section binds only the files its globs actually match.** "
    "A glob still in placeholder form (`<api module>/`) matches nothing until you "
    "localize it, so such a section scopes no checks and authorises no exclusion "
    "on any file: never read one as coverage, and never read a `Skip:` line under "
    "a placeholder glob as a reason to stop looking — not even where a section you "
    "localized in the `.project.md` overlay covers the same subject and says the "
    "opposite. A section whose glob list mixes concrete and placeholder globs "
    "binds exactly what its concrete globs match."
)

_DISPATCH_RULE = (
    "**Both lists bind only the files a section's globs actually match** (the "
    "map's own § Scope note). A pack section still in placeholder form — a header "
    "like `## <evals module>/*.py` — matches nothing on a consumer install, so it "
    "authorizes **no skip on any file**, including files a localized "
    "`.project.md` section covers with the opposite verdict."
)

# The operational half of leg (b). The round deleted exactly this and nothing
# reddened: it is the only sentence in the leg that tells the orchestrator what
# to *do*.
_DISPATCH_ACTION = (
    "Hand each agent the Check/Skip lists of the sections whose globs resolved to "
    "that agent's files; never pass a placeholder section's lists, and never let "
    "one stand as the reason a category went unaudited."
)

_DO_NOT_REPORT_RULE = (
    "This applies only to a Skip entry on a section whose globs **match that "
    "file** — a placeholder-glob section matches nothing and excludes nothing, so "
    "it is never grounds for withholding a finding."
)

_DEAD_REMEDY = _norm(
    "localizing that section's glob (or its `substitutions.project.yml` token)"
)


def _remedy(stem: str) -> str:
    return (
        "**The fix there is to localize that section, dual-write, per "
        "`_shared/promotion-write-target.md`.** In a **consumer install** "
        f"(`.claude/sysop.lock` present) write the localized section to the assembled "
        f"`.claude/{stem}.md` **and** to `.claude/{stem}.project.md`: the base write is "
        "what this round actually reads — the review-time parses (Step 2 / Step 2a) read "
        "the **base** maps only, and the `.project.*` siblings reach them by being merged "
        "into the base at install/update time — and the overlay "
        "write is what survives the next `sysop-update.sh`, which regenerates the base. "
        "Writing **only** the overlay leaves the section inert for this round and "
        "reproduces the placeholder's own symptom: localized, and still nothing "
        "changes. In a **source repo** (no lock) there is no overlay — write the base "
        "and stop. `substitutions.project.yml` cannot do this either way: it localizes "
        "`checks.yml` `paths:` only, never markdown (Phase 55 reverted markdown "
        "substitution deliberately). The placeholder original stays in the assembled "
        "file, and that is **not** the duplicate this rule forbids — a placeholder glob "
        "matches no file, so the section binds nothing. What is forbidden is a second "
        "section with a **concrete** glob over a subtree an existing concrete section "
        "already covers, which would permanently double-cover it."
    )


# --------------------------------------------------------------------------- #
# (a) the § Scope note — presence, position, containment, polarity
# --------------------------------------------------------------------------- #

def test_every_security_map_carries_the_scope_note():
    maps = _maps("security_map")
    assert len(maps) >= 6, "map discovery broke — expected core + 5 populated packs"
    for name, text in maps.items():
        # Trailing newline is load-bearing: without it, a follow-on sentence
        # appended to the note's own line reverses the rule with the guard green.
        assert _SCOPE_NOTE + "\n" in _rendered(text), (
            f"{name}: the § Scope note is missing, reworded, commented out, fenced, "
            "or has text appended to its line — a placeholder `Skip:` line becomes "
            "authoritative again, which is the #280 defect"
        )


def test_scope_note_precedes_every_section():
    for name, text in _maps("security_map").items():
        body = _rendered(text)
        if _SCOPE_NOTE not in body:
            pytest.fail(f"{name}: § Scope note absent — see the presence guard")
        assert body.index(_SCOPE_NOTE) < body.index("\n## "), (
            f"{name}: the § Scope note moved below the first section — a reader "
            "meets an authoritative-looking `Skip:` line before the rule"
        )


def test_no_map_preamble_reinstates_skip_authority():
    # Kills the reversal-as-a-neighbour family: a "Correction:" paragraph after
    # the note, a "Superseded — do not follow:" banner before it, or a second
    # line inside its own blockquote. The note stayed byte-perfect in all three.
    for name, text in _maps("security_map").items():
        preamble = _rendered(text).split("\n## ")[0].replace(_SCOPE_NOTE, "")
        hit = _REVERSALS.search(preamble)
        assert not hit, (
            f"{name}: preamble text reinstates Skip authority ({hit.group(0)!r}) — "
            "the § Scope note is contradicted by its own neighbourhood"
        )
        demoted = _DEMOTION.search(preamble)
        assert not demoted, (
            f"{name}: the § Scope note is framed as non-authoritative "
            f"({demoted.group(0)!r}) — byte-perfect and told not to be followed"
        )
        _assert_starts_a_line(_rendered(text), _SCOPE_NOTE, name)


# --------------------------------------------------------------------------- #
# (b) /security-audit's Skip-authority statements — scoped to their blocks
# --------------------------------------------------------------------------- #

def test_dispatch_block_scopes_both_lists_to_matching_globs():
    block = _dispatch_block(_SECURITY)
    assert _DISPATCH_RULE in block, (
        "Step 4 dispatch lost or reversed its glob-scoping rule. Pinned as a whole "
        "sentence inside the dispatch block: a fragment pin was satisfied by a "
        "sentence saying the opposite, and a file-level pin was satisfied by the "
        "paragraph relocated to an appendix"
    )
    assert _DISPATCH_ACTION in block, (
        "Step 4 dispatch lost its operational instruction — the only sentence in "
        "the leg telling the orchestrator what to hand each agent"
    )


def test_do_not_report_block_excludes_placeholder_sections():
    block = _do_not_report_block(_SECURITY)
    assert _DO_NOT_REPORT_RULE in block, (
        "the do-not-report guard treats every Skip entry as settled triage again, "
        "or its qualifier moved out of the exclusion list it governs — an agent "
        "can withhold a real finding on a section matching no file"
    )


def test_dispatch_and_do_not_report_carry_no_reversal():
    for label, block in (("dispatch", _dispatch_block(_SECURITY)),
                         ("do-not-report", _do_not_report_block(_SECURITY))):
        rest = block.replace(_DISPATCH_RULE, "").replace(_DISPATCH_ACTION, "")
        rest = rest.replace(_DO_NOT_REPORT_RULE, "")
        hit = _REVERSALS.search(rest)
        assert not hit, (
            f"{label} block contains a statement reinstating placeholder Skip "
            f"authority ({hit.group(0)!r}) — two adjacent paragraphs now contradict"
        )
        demoted = _DEMOTION.search(rest)
        assert not demoted, (
            f"{label} block frames its own rule as non-authoritative "
            f"({demoted.group(0)!r})"
        )
    _assert_starts_a_line(_dispatch_block(_SECURITY), _DISPATCH_RULE, "dispatch rule")


# --------------------------------------------------------------------------- #
# (c) the remedy — whole sentence, in the block that governs, dead form absent
# --------------------------------------------------------------------------- #

def test_both_skills_route_to_a_reachable_remedy():
    for name, text in _REVIEW_SKILLS.items():
        block = _2a0_block(text)
        assert _remedy(_OWN_MAP[name]) in block, (
            f"{name}: the 2a-0 remedy was reworded, gutted, demoted to a historical "
            "aside, or moved out of 2a-0. It must prescribe the dual-write "
            "(`_shared/promotion-write-target.md`) and say why substitution and "
            "overlay-only are not available, or #280's dead end returns"
        )


def test_neither_skill_revives_the_unreachable_remedy():
    # Normalised: the committed form was evadable by dropping the parentheses or
    # swapping one ASCII apostrophe for a curly one.
    for name, text in _REVIEW_SKILLS.items():
        assert _DEAD_REMEDY not in _norm(text), (
            f"{name}: the unreachable remedy is back. `substitutions.project.yml` "
            "localizes checks.yml `paths:` only; editing the assembled map alone is "
            "erased on update — a consumer following this gets the identical "
            "finding next round (#280)"
        )


def test_remedy_is_not_relicensed_nearby():
    for name, text in _REVIEW_SKILLS.items():
        rest = _2a0_block(text).replace(_remedy(_OWN_MAP[name]), "")
        hit = _REVERSALS.search(rest) or _DEMOTION.search(rest)
        assert not hit, (
            f"{name}: 2a-0 re-licenses or demotes the prescribed remedy "
            f"({hit.group(0)!r}) — the fix and its neighbourhood disagree"
        )
        # No line-start assertion here: unlike the § Scope note and the dispatch
        # rule, the remedy is legitimately a sentence *inside* 2a-0's
        # "Un-localized sections" paragraph. `_DEMOTION` covers the reframing
        # attacks for this site instead.


# --------------------------------------------------------------------------- #
# the premises the scoping rests on
# --------------------------------------------------------------------------- #

def test_the_scope_note_is_not_vacuous():
    hazardous = [
        (name, header)
        for name, text in _maps("security_map").items()
        for header, globs, body in _sections(text)
        if globs and all(_is_placeholder(g) for g in globs) and _SKIP_LIST.search(body)
    ]
    assert hazardous, (
        "no shipped security_map section is both wholly-placeholder and "
        "Skip-carrying — the § Scope note no longer describes a live hazard"
    )


def test_mixed_glob_sections_exist_so_the_last_sentence_stays_load_bearing():
    # core ships `## `Dockerfile`, `<datajobs Dockerfile>`, `.dockerignore``. It
    # resolves through `Dockerfile` and its Check/Skip lists legitimately bind
    # that file — so a "header contains a `<…>` token" predicate would condemn
    # it, and the note's closing sentence is what prevents that read. This is the
    # correction owed to the reporter, whose planned mitigation uses exactly that
    # predicate.
    mixed = [
        (name, header)
        for name, text in _maps("security_map").items()
        for header, globs, _ in _sections(text)
        if any(_is_placeholder(g) for g in globs) and any(not _is_placeholder(g) for g in globs)
    ]
    assert mixed, (
        "no shipped section mixes concrete and placeholder globs — the scope "
        "note's mixed-glob sentence is now unexercised and may be retired"
    )


def test_convention_maps_carry_no_skip_lists():
    # The premise the security-map-only scoping rests on. Shape-matched, so the
    # three ordinary spellings all count — and so ordinary prose beginning "Skip
    # …" does not, which a bare `skip\b` rule wrongly reddened on.
    for name, text in _maps("convention_map").items():
        hit = _SKIP_LIST.search(text)
        assert not hit, (
            f"{name}: a convention map grew a Skip list ({hit.group(0)!r}) — the "
            "#280 hazard is no longer security-map-specific; ship the § Scope note "
            "here too and re-scope the phase's premise"
        )


# --------------------------------------------------------------------------- #
# the artifact the consumer's security gate actually reads
# --------------------------------------------------------------------------- #

def test_scope_note_survives_into_the_assembled_map(tmp_path):
    """The delivery guard. Every other test reads sources; the round showed a
    dedup filter in `install_security_map()` could strip the note from every
    consumer install with the whole suite green — restoring the exact #280
    condition in the only file that matters."""
    target = tmp_path / "consumer"
    target.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=target, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "seed", "--allow-empty"],
                   cwd=target, check=True, capture_output=True)

    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    r = subprocess.run(
        ["bash", str(_INSTALL_SH), str(target), "--packs", "python,postgres", "--yes"],
        capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, f"install failed:\n{r.stdout}\n{r.stderr}"

    assembled = (target / ".claude" / "security_map.md").read_text(encoding="utf-8")
    body = _rendered(assembled)

    assert _SCOPE_NOTE in body, (
        "the § Scope note did not survive assembly — the consumer's security gate "
        "reads this file, and without the note its placeholder `Skip:` lines are "
        "authoritative again (#280)"
    )
    assert body.index(_SCOPE_NOTE) < body.index("\n## "), (
        "the assembled map presents a section before the note that governs it"
    )
    # And the hazard the note exists for is really present in the artifact.
    placeholder_headers = [h for h, g, _ in _sections(assembled)
                           if g and any(_is_placeholder(x) for x in g)]
    assert placeholder_headers, (
        "no placeholder-glob section survived into the assembled map — either "
        "assembly changed or the packs were localized; the note's premise is gone"
    )


# --------------------------------------------------------------------------- #
# the swept sites — reversion pins
#
# Round 2 reverted each of the nine scoped sites to its pre-phase wording and
# every one passed: the sweep the commit message headlines ("the filed 2 were 9")
# shipped guarded at two. These are deliberately *reversion* pins, not rule
# guards — they detect the clause going away, which for a doc site is the drift
# that actually happens. They do not detect reversal; § Known limits in
# PHASE_LOG records why that is filed rather than chased.
# --------------------------------------------------------------------------- #

_SWEPT_SITES = {
    "core/skills/security-audit/SKILL.md": [
        "do not mentally substitute its header into the path you think it means",
        "never a placeholder section's Skip list, which matches nothing and excludes nothing",
    ],
    "core/skills/auto-fix/SKILL.md": [
        "neither adds a check nor authorises a skip",
    ],
    "core/companion/docs/WORKFLOW.md": [
        "a section still in placeholder form matches nothing and so tells an auditor nothing",
        "both **glob-scoped** — a section binds only the files its globs actually match",
        "never to the subject in general",
        "so its Skip list excludes nothing",
    ],
    "core/companion/docs/WORKFLOW_GUIDE.md": [
        "so a section still in placeholder form confers neither",
    ],
    "packs/python/companion/convention_map.md": [
        "Localized sections are therefore **dual-written**",
    ],
    "docs/packs.md": [
        "Both skills treat a placeholder section as binding nothing",
        "So write it to both",
    ],
}


def test_every_swept_site_keeps_its_scoping_clause():
    for rel, clauses in _SWEPT_SITES.items():
        # Raw, not _rendered(): WORKFLOW.md §6.3's blank security-map template is
        # deliberately inside a ```markdown fence, and stripping fences would hide
        # the very clause this pin exists to hold.
        body = (_ROOT / rel).read_text(encoding="utf-8")
        for clause in clauses:
            assert clause in body, (
                f"{rel}: lost its Phase-179 scoping clause ({clause[:52]!r}). This "
                "site states, to a consumer or a sub-agent, that a Skip list or a "
                "map section applies — unqualified, it reinstates #280"
            )


def test_public_docs_do_not_readvertise_the_retired_paths():
    # Two specific retired claims, both of which survived the first fix pass in
    # docs/packs.md and were found by two independent lenses.
    packs = _rendered((_ROOT / "docs" / "packs.md").read_text(encoding="utf-8"))
    assert "by inference for the security audit" not in packs, (
        "docs/packs.md again claims /security-audit resolves placeholders by "
        "inference — the public statement of the #280 defect"
    )
    assert "Don't localize there" not in packs, (
        "docs/packs.md again prescribes overlay-only localization in the section "
        "headed 'where localization lands' — the inert remedy"
    )
