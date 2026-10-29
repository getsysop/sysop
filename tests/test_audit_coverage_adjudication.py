"""Drift guards for Phase 141 — the `/security-audit` coverage + adjudication bundle
(steal-list #1 + #2 + the reachability-triage discipline, re-ranked by the 2026-07-23
`claude-security` head-to-head).

Three defects the head-to-head measured, three guards. Numbers here are stated as the
primary record states them — an adversarial pass caught this file's first draft
overstating all three.

1. **Unmapped subtrees were structurally invisible.** Step 2a-1/2a-2 derive their
   enumeration roots FROM the maps' own section globs, so a top-level entry no
   section names is never enumerated and never reported — permanently, and its
   silence is indistinguishable from a clean result. **Three of the six findings the
   audit missed landed in exactly such subtrees**, which is what the completeness
   invariant is credited with catching. Step 2a-0 now enumerates the repo
   independently of the map. (A fourth miss sat in a root-level docs file; 2a-0
   reports unmapped *root-level files* as their own class, but a docs-only file is
   a weaker claim than a whole unmapped subtree — the docstring does not conflate
   them.)

2. **Dismissals rested on unread mitigations.** Two of the three findings the audit
   filed and later had refuted failed on an unexamined reachability assumption. The
   universal adjudication rule now demands located-and-read evidence in BOTH
   directions, defaults to keeping a finding when neither can be established, and —
   the load-bearing branch a reviewer caught missing — still lets a **falsified
   premise** refute a finding outright, so the rule cannot shelter fabrications.

3. **Dependency narratives were materially wrong more often than right** (three of
   five), and one refuted finding would have caused a production outage if applied
   as filed — via an ignore-file change, not a version bump. Agent 6 now demands a
   traced chain or an explicit `Reachability: unassessed`, plus a remediation
   checked against current usage: one rule per measured failure mode.

These are string-anchor drift guards — they pin the load-bearing wording so a
future edit cannot silently re-open any of the three holes. They cannot pin that
the mechanism *works* (there is no executable mechanism), only that it is stated.
"""

import difflib
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SKILLS = _ROOT / "core" / "skills"

_CODEBASE = (_SKILLS / "codebase-review" / "SKILL.md").read_text(encoding="utf-8")
_SECURITY = (_SKILLS / "security-audit" / "SKILL.md").read_text(encoding="utf-8")
_TESTAUDIT = (_SKILLS / "test-audit" / "SKILL.md").read_text(encoding="utf-8")
_FANOUT = (_SKILLS / "_shared" / "fanout-evidence.md").read_text(encoding="utf-8")
_WORKFLOW = (_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md").read_text(
    encoding="utf-8"
)
_INSTALL = (_ROOT / "install.sh").read_text(encoding="utf-8")

_REVIEW_SKILLS = {"codebase-review": _CODEBASE, "security-audit": _SECURITY}


# Phase 230 / `Q-296`. Written as character CLASSES rather than literals because the
# first cut matched a bare ASCII "map-keyed" and its own battery walked two mutations
# through. An independent lens then walked EIGHT more through the widened class.
#
# **The adversary model, stated, because the fraction is meaningless without it.** These
# guards defend against an AUTHOR honestly re-introducing a retired term — the way Q-296
# actually happened. They do NOT defend against someone deliberately evading them: a
# zero-width space, a soft hyphen or a U+2012 figure dash all render as `map-keyed` and
# all pass, and chasing that zoo invites the next form. What IS in the model is every way
# an ordinary edit produces the token, and the line wrap below was named in this guard's
# own first rationale and then not tested — an independent lens had to find it.
_MAP_KEYED_RE = re.compile(
    r"map[-\u2010\u2011\u2012\u2013\u2014\u00ad\u200b\u00a0 \t\r\n]{0,2}keyed",
    re.IGNORECASE,
)

# The retirement's own SENTENCE. Matched on SHAPE and LENGTH-BOUNDED, for two measured
# reasons. Byte-exact: the first cut pinned the literal opener, so a legal reword
# ("This sentence previously used the phrase ...") failed a guard while the retirement
# stood — over-strictness, and the phase's own battery scored that row as a KILL under
# "vacuity". Unbounded: `[^.]*\.` lets the writer choose the sentence's end, so extending
# it (or deleting its period) swallows an arbitrary amount of following prose, including
# a live premise, before the stray scan ever sees it.
_RETIREMENT_SENTENCE_RE = re.compile(
    r"[^.\n]{0,120}?"
    r"(?:earlier version of this sentence|sentence previously|this sentence used to)"
    r"[^.\n]{0,200}?map[-\u2011 ]?keyed[^.\n]{0,200}\.",
    re.IGNORECASE,
)

# **The token-free paraphrase residual — declared, NOT closed, and the story of why it is
# declared is the point.**
#
# Round 1 called this residual impossible to close in kind, on the reasoning that a guard
# which tried "would false-fire on the honest mechanism sentence, which is about maps
# throughout". A lens falsified that by building a predicate in six lines and measuring
# ZERO false fires on the shipped tree, so the predicate shipped.
#
# Round 2 measured it against the thing that actually matters — the class of LEGAL EDITS,
# not one frozen tree — and it false-fired on **19 of 24** legal sentences (79%). It has no
# polarity, so `Step 3 dispatch is **not** keyed on the maps` fires; so does
# `Do not write that dispatch is keyed on the maps`; so does a sentence describing this
# very retirement in the past tense. And "map" is overloaded across this repo — rule map,
# weight map, role map, allow-rule map, paths map — so nine of the nineteen were about
# entirely different machinery. It was reverted.
#
# Three things worth keeping from that round trip:
#   * **The original declaration was right, for the right reason.** It was abandoned
#     because a lens produced a number, and the number was measured against the wrong
#     population. "Zero false fires on the current tree" is not "zero false fires".
#   * **The phase's own over-strictness control could not fire.** It was written in the one
#     word order the predicate was structurally blind to — a control the verifier cannot
#     see, which `mutation_battery.py`'s docstring exists to name.
#   * The predicate was also trivially bypassable in nine ways, so it was simultaneously
#     too broad and too narrow. That is the signature of the wrong instrument, not of a
#     pattern needing one more character class.
#
# So: a shipped surface CAN still state the retired model in words that avoid the token,
# and no guard here catches it. That is a real gap, honestly named, and the reason
# `Q-296` was found by reading rather than by a guard in the first place.

# The sanctioned dispatch divergence in codebase-review's 2a-0 block, matched on shape
# and LENGTH-BOUNDED — an unbounded tail lets the divergence sentence be extended with
# arbitrary content that is then stripped before the mirror comparison sees it.
_DISPATCH_DIVERGENCE_RE = re.compile(
    r" Since Step 3 dispatch [^.]{0,200}?\*\*no review agent\*\*[^.]{0,160}\."
)
def _block_2a0(text: str) -> str:
    start = text.index("### 2a-0. Top-level inventory completeness")
    return text[start : text.index("### 2a-1. Files not matched by")]


# --- (1) Inventory completeness invariant — both review skills ------------------

def test_both_skills_ship_the_2a0_inventory_step():
    for name, text in _REVIEW_SKILLS.items():
        assert "### 2a-0. Top-level inventory completeness" in text, (
            f"{name}: Step 2a-0 (inventory completeness) is gone — unmapped "
            "subtrees are structurally invisible again"
        )


def test_2a0_enumerates_independently_of_the_map():
    # THE CRUX. If the enumeration is ever re-derived from the map's own section
    # globs, the check becomes a no-op: it could only find gaps inside territory
    # the map already names, which is precisely 2a-1's job.
    for name, text in _REVIEW_SKILLS.items():
        # Phase 188: this used to pin the `awk -F/ '{print $1}'` form — i.e. a shipped
        # guard was asserting the presence of the defect. The skill runner rewrites a bare
        # positional in a skill body before any shell sees it (upstream #360), so under a
        # two-word invocation that awk became `{print <argument>}` and printed one empty
        # line, and 2a-0 then reported complete coverage over an empty inventory. `cut` has
        # no such collision. Do not restore the awk form to make this pass.
        assert "git ls-files | cut -d/ -f1 | sort -u" in text, (
            f"{name}: 2a-0's whole-repo enumeration command changed — verify it "
            "still enumerates independently of the map's section globs, and do NOT "
            "reintroduce an awk positional (see tests/test_skill_positional_substitution.py)"
        )
        # Independent of the pin above, because this phase's battery showed the pin can be
        # relaxed to a bare `git ls-files` with everything green. This half states the
        # thing that must never come back rather than the thing that must be present.
        assert "awk -F/" not in text, (
            f"{name}: the awk field-splitting form is back in 2a-0. The skill runner "
            "rewrites its positional with an argument word before bash sees it, and the "
            "step then reports complete coverage over an empty inventory (upstream #360)"
        )
        assert "authored, not derived" in text, (
            f"{name}: 2a-0 lost the rationale (the map is authored, not derived) "
            "that explains why a map-rooted enumeration cannot find this class"
        )


def test_2a0_runs_every_round_not_full_scans_only():
    # Regression guard for a defect the adversarial pass caught in the first
    # draft: gating 2a-0 on "full scans only" made it unreachable, because Step 1
    # auto-detects INCREMENTAL at <=7 days — so a weekly-cadence project never
    # reaches a full scan and never runs the check at all.
    for name, text in _REVIEW_SKILLS.items():
        block = _block_2a0(text)
        assert "Runs every round" in block, (
            f"{name}: 2a-0 is gated on scan mode again — Step 1 makes a "
            "<=7-day cadence permanently incremental, so this makes it a no-op"
        )
        assert "Full scans only" not in block, (
            f"{name}: the full-scan-only gate returned to 2a-0"
        )
        assert "unchanged since Round N-1" in block, (
            f"{name}: 2a-0 lost its repeat-compression escape, so it will be "
            "noisy every round and get ignored"
        )


def test_2a0_states_the_three_branch_invariant_with_a_required_reason():
    for name, text in _REVIEW_SKILLS.items():
        block = _block_2a0(text)
        assert "with a stated one-line reason" in block, (
            f"{name}: 2a-0 no longer requires a reason on an exclusion entry — an "
            "unexplained exclusion silences a whole subtree by accident"
        )
        assert "reason not stated" in block
        assert "**(c) unlocalized**" in block, (
            f"{name}: 2a-0 lost the third disposition — a partly-localized install "
            "will have placeholder-covered subtrees reported as genuine gaps"
        )


def test_2a0_reasonless_entries_are_surfaced_not_blocking():
    # Back-compat: consumer lists authored before this convention carry bare globs.
    for name, text in _REVIEW_SKILLS.items():
        assert "surface it, don't block on it" in _block_2a0(text), (
            f"{name}: 2a-0's reasonless-entry handling became blocking — that "
            "breaks every consumer list authored before the reason convention"
        )


def test_2a0_does_not_inherit_2a1_per_file_exclusions():
    # Both reviewers converged here. 2a-1 excludes *.yml/*.sql/*.md because ONE
    # such file inside a mapped area has negligible surface. Inheriting that
    # per-subtree exempts .github/ (CI integrity) and migrations/ (privilege
    # grants) — the highest-value subtree classes — from the check built to end
    # subtree invisibility.
    for name, text in _REVIEW_SKILLS.items():
        block = _block_2a0(text)
        assert "do NOT inherit 2a-1's per-file exclusions wholesale" in block, (
            f"{name}: 2a-0 inherits 2a-1's per-file exclusion classes again — "
            "config-only and docs-only subtrees become invisible to it"
        )
        assert "is **still reported**, at note severity" in block
        # The 2a-0-specific exclusion class must stay narrow.
        assert "lockfiles, generated or vendored output, and binary assets" in block


def test_2a0_partitions_directories_from_root_level_files():
    # `git ls-files | cut -d/ -f1` yields both. "resolves beneath it" is
    # false for a section glob that NAMES a root file (the shipped security_map
    # keys sections on `Dockerfile` and `.gitignore`), so an unpartitioned check
    # false-flags them on the shipping default.
    for name, text in _REVIEW_SKILLS.items():
        block = _block_2a0(text)
        assert "both directories and root-level files" in block, (
            f"{name}: 2a-0 no longer partitions root-level files from directories"
        )
        assert "matches it directly" in block, (
            f"{name}: root-level files are judged by 'resolves beneath' again — "
            "a section glob naming a root file will be false-flagged as unmapped"
        )
    # The concrete example is only claimed where it is true: security_map.md ships
    # root-file-keyed sections, convention_map.md does not.
    assert "`Dockerfile`, `.gitignore`" in _block_2a0(_SECURITY)
    assert "`Dockerfile`, `.gitignore`" not in _block_2a0(_CODEBASE)


def test_2a0_guards_partial_localization_and_routes_to_localizing():
    for name, text in _REVIEW_SKILLS.items():
        block = _block_2a0(text)
        assert "check per entry, not globally" in block, (
            f"{name}: 2a-0's placeholder guard is all-or-nothing again — a "
            "partly-localized install (the normal case) emits false gaps"
        )
        # Phase 179 (upstream #280) replaced the remedy twice. The original routed
        # to "localizing that section's glob (or its `substitutions.project.yml`
        # token)" — unreachable for markdown. The first replacement said the
        # overlay was "the only durable write target", which the round showed
        # contradicts `_shared/promotion-write-target.md` § Why not overlay-only:
        # skills read the BASE maps, so an overlay-only write is inert until the
        # next update. The rule is dual-write, and that is what must be routed to.
        assert "dual-write" in block and ".project.md" in block, (
            f"{name}: 2a-0 no longer routes an unlocalized entry to the dual-write "
            "(base + .project.md overlay) — the only remedy that both takes effect "
            "this round and survives the next update"
        )
        assert "second section with a **concrete** glob" in block, (
            f"{name}: 2a-0 lost the duplicate-section prohibition — an agent will "
            "create a permanent double-cover over an already-covered subtree"
        )
    assert "security_map.md not localized for this project" in _SECURITY
    assert "convention_map.md not localized for this project" in _CODEBASE


def test_2a0_keys_each_skill_to_its_own_dispatch_map():
    assert "at least one `convention_map.md` section glob resolves beneath it" in _CODEBASE
    assert "at least one `security_map.md` section glob resolves beneath it" in _SECURITY


def test_2a0_handles_rootless_globs():
    for name, text in _REVIEW_SKILLS.items():
        assert "has nothing to resolve beneath and does **not** establish coverage" in _block_2a0(text), (
            f"{name}: 2a-0 lost the root-less-glob rule — `**/*.py` has two "
            "readings with opposite outcomes and no guidance between them"
        )


def test_2a0_composes_with_rather_than_subsumes_2a1():
    for name, text in _REVIEW_SKILLS.items():
        assert "Neither check subsumes the other" in _block_2a0(text), (
            f"{name}: 2a-0 lost the composition note — a future author may delete "
            "2a-1 as redundant, losing per-file gaps inside mapped subtrees"
        )


def test_2a0_routes_into_the_fix_step():
    for name, text in _REVIEW_SKILLS.items():
        assert "For **unmapped top-level entries** (2a-0):" in text, (
            f"{name}: 2a-0's findings are no longer routed into the inline-fix step"
        )
        assert "Unmapped top-level entries:" in text


def test_2a0_blocks_stay_mirrored_across_the_two_skills():
    # The two blocks are generated from one body with the map name, sibling skill,
    # staleness cross-ref and verb parameterized, plus two deliberate divergences.
    # Without this, one skill gets hardened and the other silently rots.
    def normalise(text: str, own: str, other: str) -> str:
        b = _block_2a0(text)
        # strip the two sanctioned divergences
        # Phase 230: this was a BYTE-EXACT literal, and its own battery scored it a
        # FALSE KILL — any legal reword of the sentence (retired model still gone,
        # mechanism still stated) left the strip unmatched, so the sentence survived
        # normalisation on one side only and this test failed with a diff pointing at
        # the mirrored block rather than at the edit. That is how it bit the phase that
        # found it. Match the sentence's SHAPE, and assert the strip actually fired so
        # a deleted divergence cannot pass by making both sides equally empty.
        # HIGH-1's guard. The round's single surviving mutation was restoring the FALSE
        # INFERENCE — "no section names it, so no row can cite one" — which carries
        # neither the retired token nor a paraphrase of it, so every other guard here is
        # blind to it. It is false because a 3-pre row needs no section citation to
        # dispatch: the shipped `Infra & Config` row cites `*(none)*` and covers
        # `.github/workflows/*.yml`, which no convention_map section names. Pin the TRUE
        # condition instead — the row's Files column — inside the one sentence the strip
        # matches, so an addition cannot dodge it the way it dodges a file-wide anchor.
        divergence = _DISPATCH_DIVERGENCE_RE.search(b)
        if own == "convention_map.md":
            # Accepts any wording that makes a ROW's file list the condition — the first
            # cut pinned the literal "Files column" and a round showed it both ways: a
            # sentence can NAME the column while DENYING it ("no 3-pre row's Files column
            # can cite one"), and stating the true condition differently ("names it
            # directly under **Files**") was a FALSE KILL. So: require the row-and-files
            # shape, and reject the negated form explicitly.
            span = divergence.group(0) if divergence else ""
            names_the_condition = re.search(
                r"row'?s?\b[^.]{0,40}?\bFiles\b|\bFiles\b[^.]{0,40}?\brow", span, re.I
            )
            # `[\w'-]+`, not `\w+`: the round's bypass was "no 3-pre row's Files column
            # can cite one", and `\w+` cannot cross the hyphen in `3-pre`, so the first
            # cut of this negation check let the exact demonstrated bypass through.
            denies_it = re.search(r"\bno\s+(?:[\w'-]+\s+){0,3}row\b", span, re.I)
            assert divergence and names_the_condition and not denies_it, (
                "codebase-review's 2a-0 dispatch sentence no longer says an unmapped "
                "subtree gets an agent when a 3-pre row's FILES COLUMN names it. "
                "Without that condition the sentence reverts to reasoning from section "
                "citations — 'no section names it, so no row can cite one' — which is "
                "false: `Infra & Config` cites no section and dispatches over "
                "`Dockerfile`, `.dockerignore` and `.github/workflows/*.yml`. Replacing "
                "a false premise with a false inference is what this guard exists to "
                "stop; it was a round's surviving mutation, and the first anchor for it "
                "could be satisfied by a sentence that named the Files column while "
                "denying it.\n  got: " + (span.strip()[:200] if span else "<no match>")
            )
        b, fired = _DISPATCH_DIVERGENCE_RE.subn("", b)
        expected = 1 if own == "convention_map.md" else 0
        assert fired == expected, (
            f"the sanctioned dispatch-divergence strip fired {fired} time(s) on the "
            f"{'codebase-review' if own == 'convention_map.md' else 'security-audit'} "
            f"side, expected {expected}. Both directions matter and only one was "
            "asserted before: on the codebase-review side a 0 means the divergence was "
            "deleted or reworded past this shape; on the security-audit side a 1 means "
            "a NEW divergence was introduced there and then silently stripped before "
            "comparison, so this test would pass over a real divergence. The old "
            "byte-exact literal could not match in security-audit at all — the shape "
            "regex can, which is a hole the widening introduced."
        )
        b = re.sub(r" \((?:the shipped `security_map\.md` keys sections on root files "
                   r"this way — e\.g\. `Dockerfile`, `\.gitignore`|a section glob may name "
                   r"a root-level file directly)\)", " (ROOTEG)", b)
        # The `.project.md` overlay sibling is parameterised the same way the map
        # name is (Phase 179) — longer token first, or `own` would not match it.
        b = b.replace(own.replace(".md", ".project.md"), "OWNOVERLAY")
        b = b.replace(own, "OWNMAP").replace(other, "OTHERMAP")
        b = b.replace("/codebase-review", "SIBLING").replace("/security-audit", "SIBLING")
        b = b.replace("2a-3(a)", "STALEREF").replace("2a-4(a)", "STALEREF")
        return b.replace("audited", "VERB").replace("reviewed", "VERB")

    a = normalise(_SECURITY, "security_map.md", "convention_map.md")
    c = normalise(_CODEBASE, "convention_map.md", "security_map.md")
    if a != c:
        diff = "\n".join(list(difflib.unified_diff(
            a.splitlines(), c.splitlines(),
            fromfile="security-audit/2a-0", tofile="codebase-review/2a-0", lineterm=""
        ))[:40])
        raise AssertionError(
            "the two skills' 2a-0 blocks have diverged beyond their sanctioned "
            f"parameterisation — harden both or neither:\n{diff}"
        )


# --- (2) Adjudication — evidence in both directions -----------------------------

def test_fanout_partial_carries_the_adjudication_section():
    assert "## Adjudication — evidence in both directions (UNIVERSAL)" in _FANOUT
    assert "Adjudication — evidence in both directions." in _FANOUT, (
        "the partial's header summary no longer lists the adjudication rule "
        "alongside the two tiers"
    )


def test_a_falsified_premise_still_refutes_outright():
    # THE hole the adversarial pass caught: as first written, a finding could die
    # only on a located mitigation — so a finding with a fabricated premise (no
    # mitigation exists to locate) could never be dismissed. The rule sheltered
    # exactly the hallucinations the sample re-read exists to catch, and directly
    # contradicted the merge bullet above it.
    assert "A falsified premise refutes a finding outright" in _FANOUT
    assert "that read is the refutation" in _FANOUT
    assert "never a premise you checked and found false" in _FANOUT, (
        "the survival default no longer excludes falsified premises — it now "
        "protects fabricated findings"
    )
    for name, text in _REVIEW_SKILLS.items():
        assert "the sample re-read above **is** the premise check" in text, (
            f"{name}: the merge mirror no longer reconciles the adjudication rule "
            "with the sample re-read — two adjacent bullets give opposite verdicts"
        )


def test_adjudication_binds_the_kill_direction():
    assert "locate and read the mitigation" in _FANOUT
    assert "If you cannot name where the protection lives" in _FANOUT


def test_adjudication_binds_the_keep_direction():
    assert "To keep or escalate a finding, trace the path." in _FANOUT
    assert "explicitly unassessed" in _FANOUT


def test_adjudication_makes_no_unsourced_frequency_claim():
    # The first draft called the keep-direction "the one measured more often in
    # practice" — an uncheckable comparative in the canonical universal contract,
    # sitting two bullets from a rule that deliberately biases the other way.
    assert "measured more often in practice" not in _FANOUT


def test_adjudication_defaults_to_survival_with_its_rationale():
    assert "Default to survival, not dismissal." in _FANOUT
    # The rationale is load-bearing: it is WHY this loop inverts the default a
    # standalone scanner's verifier uses. Without it a future author "fixes" the
    # asymmetry back to default-refute.
    assert "a filed task gets another reader" in _FANOUT
    assert "while a dismissal gets none" in _FANOUT


def test_adjudication_is_not_pushed_onto_hunters():
    # The category error this phase deliberately avoided: a skeptical HUNTER
    # reports less, suppressing real findings before anyone adjudicates them.
    assert "This is an adjudication rule, not a hunting rule." in _FANOUT
    assert "Hunters report; adjudicators demand evidence." in _FANOUT


def test_dispatch_prompts_carry_the_adjudication_pair_and_its_disclaimer():
    # Replaces a first-draft test that asserted the ABSENCE of a phrase nobody
    # had written (it passed against the pre-change tree, and would have failed
    # the correct fix). The real risk is the opposite: agents set their own
    # severity but never read the shared partial, so the rule must be pasted in —
    # and pasted in WITH the not-a-licence-to-report-less disclaimer.
    for name, text in _REVIEW_SKILLS.items():
        assert "**Also paste the § Adjudication kill/keep pair**" in text, (
            f"{name}: the adjudication rule claims to bind agents' own severity "
            "calls but is never delivered to them (they never read the partial)"
        )
        assert "**not** a licence to report less" in text, (
            f"{name}: the dispatch paste lost its disclaimer — an adjudication "
            "rule handed to a hunter reads as permission to suppress"
        )


def test_both_skills_mirror_the_adjudication_rule_at_merge():
    for name, text in _REVIEW_SKILLS.items():
        assert "Adjudicate on read evidence, both directions (mandatory" in text
        assert "**the finding survives** with the open question recorded" in text, (
            f"{name}: the merge mirror lost the default-to-survival clause"
        )


def test_dedup_reconciles_with_the_survival_default():
    # codebase-review's dedup says "when in doubt, skip" — the inverse default,
    # at a site § Adjudication explicitly claims. The reconciliation (a dedup skip
    # is not a dismissal) must be stated or an agent has to guess which wins.
    assert "A dedup skip is not a dismissal" in _SECURITY
    assert "a dedup skip is not a dismissal" in _CODEBASE
    for name, text in _REVIEW_SKILLS.items():
        assert "skip only on a match you can point at" in text, (
            f"{name}: dedup no longer inherits the adjudication evidence standard"
        )


def test_adjudication_composes_with_both_legs_of_compound_findings():
    # The first draft claimed the composition was complete ("in that order") while
    # carrying only the decompose leg and silently dropping the second-pass leg.
    assert "decompose the finding into its clauses **first**" in _FANOUT
    assert "second leg binds here too" in _FANOUT, (
        "the composition carries only the decomposition leg again — an agent will "
        "believe it satisfied the compound-findings rule at half compliance"
    )
    assert "satisfies half the rule while appearing to satisfy all of it" in _FANOUT
    for name, text in _REVIEW_SKILLS.items():
        assert "the compound rule's second leg also binds" in text, (
            f"{name}: the merge mirror dropped the second-pass leg"
        )


def test_test_audit_applies_adjudication_on_every_path():
    # The header claims "Tier 1 and adjudication always". test-audit's own text
    # previously said only Tier 1 applied to its base path — an agent follows its
    # skill file, not a claim in a partial it is not told to read.
    assert "§ Adjudication applies on every path, fan-out or not" in _TESTAUDIT
    assert "never retire on an assumed duplicate" in _TESTAUDIT


def test_security_severity_downgrade_requires_a_located_control():
    assert "you located and read at a specific `file:line`" in _SECURITY
    assert "is not a mitigation" in _SECURITY
    # Must not say "stays High": High is already the skill-wide default, and read
    # unscoped it would inflate every defense-in-depth hardening item.
    assert "**stays at its filed severity and is not downgraded on that basis**" in _SECURITY


def test_low_severity_is_not_an_evidence_bypass():
    # Medium now costs a located control; Low costs nothing. Without this clause
    # the cheapest way past the evidence bar is to file lower than you believe.
    assert "**Low is a *kind*, not a downgrade**" in _SECURITY
    assert "to sidestep the evidence bar above" in _SECURITY


def test_severity_block_is_not_scoped_to_agent_6():
    # It sits after Agent 6's content; the new dependency paragraphs deepened the
    # misreading that it is a dependency rule.
    assert "### Severity assignment" in _SECURITY
    assert "not only Agent 6 — it is skill-global" in _SECURITY


# --- (3) Dependency reachability triage ----------------------------------------

def test_agent6_requires_a_traced_chain_or_an_unassessed_marker():
    assert "**State the reachability chain, or mark it unassessed.**" in _SECURITY
    assert "`Reachability: unassessed`" in _SECURITY


def test_agent6_states_the_measured_error_rate_accurately():
    # The first draft claimed the errors "ran one way". The record shows three of
    # five wrong, two inflating and one UNDERSTATING affected call sites — so the
    # directional law was false, and pinned by a drift guard.
    assert "three of that round's five dependency narratives were materially wrong" in _SECURITY
    assert "inflating severity by asserting runtime reachability that did not exist" in _SECURITY
    assert "*understating*" in _SECURITY, (
        "the counterexample is gone — the guidance implies a one-way error "
        "direction the record contradicts"
    )
    assert "the narrative can be wrong in either direction" in _SECURITY
    assert "the errors ran one way" not in _SECURITY


def test_agent6_still_files_unassessed_findings():
    # The rule must not become a filter — an untraced dependency finding is real
    # and the next reader can trace it. Only the ASSERTED chain is the defect.
    assert "an unassessed dependency finding is still worth filing" in _SECURITY


def test_agent6_checks_remediation_against_current_usage():
    assert "**Check the remediation against current usage before recommending it.**" in _SECURITY
    assert "production outage" in _SECURITY
    # The outage came from an ignore-file change on a container-config finding,
    # not a dependency upgrade. Stating it inside Agent 6 without that scope reads
    # as "a dependency bump caused an outage", which is false.
    assert "an *ignore-file* change, not an upgrade" in _SECURITY
    assert "the class is remediation blast radius, wherever it appears" in _SECURITY


# --- Consumer-authoring surfaces stay in sync ----------------------------------

def test_workflow_documents_the_exclusion_reason_convention():
    assert "Give each entry a one-line reason" in _WORKFLOW
    assert "never blocking" in _WORKFLOW
    # Must carry 2a-0's actual scope, or a consumer reads silence as coverage.
    assert "every top-level entry holding tracked code" in _WORKFLOW
    assert "is still reported" in _WORKFLOW


def test_workflow_partial_manifest_lists_adjudication():
    assert "**§ Adjudication** (universal, Phase 141)" in _WORKFLOW, (
        "WORKFLOW.md's shared-partial manifest still describes fanout-evidence.md "
        "as two tiers — the adjudication rule is undiscoverable from the manifest"
    )


def test_installer_stub_shows_reasons_on_its_examples():
    assert "one-line reason: Step 2a-0 checks that every top-level entry holding" in _INSTALL
    assert "generated by the ORM, reviewed at the model layer" in _INSTALL


def test_installer_stub_attribution_is_not_loop_mode_only():
    # seed_claude_md_stub has run in BOTH modes since Phase 131; a full-mode
    # consumer reading "(loop mode)" may treat the stub as deletable cruft.
    assert "Seeded by Sysop (loop mode)" not in _INSTALL


# --- (4) Phase 230 / `Q-296` — a term retired in prose, held by prose -----------
#
# `codebase-review/SKILL.md:174` retires "map-keyed": dispatch is keyed on the
# hand-authored 3-pre table, which cites map sections BY NAME, and is not computed
# from the maps. The same file then used the retired model as a load-bearing premise
# twice more, at 2a-0 and in the inline-fix step. Both surviving conclusions happened
# to hold for their narrow case, which is what let them sit there — the Phase-210
# shape, a skill stating two positions in one file.
#
# Prose retired the term and prose did not hold it. These two guards do, and they
# pull in OPPOSITE directions on purpose: the first stops the term coming back to
# codebase-review, the second stops a naive class sweep destroying security-audit's
# use of it, which is TRUE. `security-audit`'s dispatch genuinely is map-keyed —
# Phase 229's round refuted the suggested twin, and a sweep that "fixed" both files
# would be the over-strictness direction closing a correct statement.

def test_no_shipped_surface_states_the_retired_map_keyed_model():
    """`Q-296` + Phase 230's battery: the filed 2 sites were 3, and the third is the spec.

    The filing scoped itself to `codebase-review/SKILL.md`. `WORKFLOW.md`'s § 6.1
    audit-skill-section table carried the same claim in a row covering BOTH skills,
    which made it half-true — correct for `/security-audit`, false for
    `/codebase-review`. A guard that reads one file could never have found that, which
    is the `where it looks` class: derive the population from the shipped tree, not
    from the filing.
    """
    assert _MAP_KEYED_RE.search(_CODEBASE), (
        "codebase-review/SKILL.md no longer mentions `map-keyed` at all — including "
        "the sentence that RETIRES it. Without that sentence the term reads as live "
        "vocabulary and the premise re-enters on the next edit, which is exactly how "
        "Q-296 happened. This guard is not asking you to delete the word."
    )
    assert _RETIREMENT_SENTENCE_RE.search(_CODEBASE), (
        "codebase-review/SKILL.md lost the sentence retiring `map-keyed`"
    )

    # Population: every shipped skill body and the workflow spec. `security-audit` is
    # excluded and pinned separately by the counterpart guard below — there the term is
    # TRUE, and a sweep that took it out would be the over-strictness direction.
    surfaces = {
        path.relative_to(_ROOT).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(_SKILLS.rglob("*.md"))
        if path != _SKILLS / "security-audit" / "SKILL.md"
    }
    # The first cut's population was `core/skills/` plus the one file the phase happened
    # to touch, while its own docstring said "derive the population from the shipped
    # tree, not from the filing". An independent lens named five shipped surfaces it
    # excluded. Two of them are the point:
    #   * `install.sh` seeds a consumer `CLAUDE.md` stub — that text is written into
    #     EVERY downstream project, the largest blast radius in the repo;
    #   * `docs/packs.md` is the public page that ALREADY carried this exact false claim
    #     about /codebase-review once and had to be corrected (Phase 203).
    # The one file with a proven history of the defect was outside the guard written to
    # stop it.
    # ENFORCED, not best-effort. The first widening used `if path.exists()`, which a round
    # showed was silently droppable: rename `docs/` away and the guard still passes green,
    # having quietly stopped covering it. Phase 113 moved content into `docs/` exactly like
    # that, so this is a real reorg, not a hypothetical. `docs/` is rglob, not glob — the
    # first version was non-recursive and missed `docs/analysis/`.
    roots = {
        "docs": sorted((_ROOT / "docs").rglob("*.md")),
        "core/companion": sorted((_ROOT / "core" / "companion").rglob("*.md")),
        "packs": sorted((_ROOT / "packs").rglob("*.md")),
    }
    for label, found in roots.items():
        assert found, (
            f"the guard's population expected shipped markdown under `{label}/` and found "
            "none. Either the tree was reorganised and this list needs updating, or the "
            "widening this guard depends on has silently stopped covering that root — "
            "which is the failure mode that made it `if path.exists()`-shaped before."
        )
    singles = [_ROOT / "README.md", _ROOT / "install.sh", _ROOT / "CONTRIBUTING.md"]
    for path in singles:
        assert path.exists(), f"expected shipped file missing from the population: {path}"
    for path in [*singles, *(q for v in roots.values() for q in v)]:
        surfaces[path.relative_to(_ROOT).as_posix()] = path.read_text(encoding="utf-8")
    # WORKFLOW.md joins the population WHOLE. It used to join minus one exempted row,
    # and that exemption was the hiding place: it was line-scoped and token-triggered,
    # so any line carrying the token self-exempted, and the guard that read the row
    # took the FIRST match and could be fed a decoy. The fix was not a better exemption
    # — it was removing the need for one. The row now states /security-audit's dispatch
    # as "the OWASP categories a matching section lists under `Check:`" instead of the
    # retired shorthand, so no shipped surface outside security-audit/SKILL.md and the
    # retirement sentence uses the term at all, and the scan can be uniform.
    surfaces["core/companion/docs/WORKFLOW.md"] = _WORKFLOW
    assert len(surfaces) > 1, "population went empty — this guard would pass by finding nothing"

    stray = []
    for name, text in surfaces.items():
        # Cheap pre-filter first. A round measured this test at 7.7s of the module's 7.8s
        # — a ~110x regression — because both bounded regexes ran over every byte of a
        # population that now includes all of `packs/`, `docs/` and `core/companion/`. A
        # file with no `keyed` in it cannot contain the token, so the expensive
        # sentence-strip never needs to run on it. The scan is unchanged; only the work is.
        if "keyed" not in text.lower():
            continue
        # Strip the retirement SENTENCE, not its paragraph.
        residue = _RETIREMENT_SENTENCE_RE.sub("", text)
        for m in _MAP_KEYED_RE.finditer(residue):
            lo = residue.rfind("\n", 0, m.start()) + 1
            hi = residue.find("\n", m.end())
            stray.append(f"{name}: ...{residue[lo:hi if hi != -1 else len(residue)][:200]}")

    assert not stray, (
        "the retired `map-keyed` dispatch model is stated as live on a shipped surface. "
        "`/codebase-review` keys Step 3 on the hand-authored 3-pre table, which cites "
        "convention-map sections BY NAME and is not computed from the maps — a section "
        "the table does not name has no agent OF ITS OWN — though a path is still "
        "reviewed if some row's Files column reaches it, as `Infra & Config` does. State "
        "the mechanism instead of the retired shorthand:\n  " + "\n  ".join(stray)
    )


def test_security_audit_keeps_map_keyed_because_there_it_is_true():
    # The counterpart, and the direction that hides. security-audit's Step 3 dispatch
    # IS keyed on security-map section membership; the file says so and then
    # immediately says why map-keyed is still not the same as covered. A class sweep
    # that treats `map-keyed` as globally retired deletes a correct statement and the
    # distinction built on top of it.
    assert re.search(
        r"Step 3 dispatch[^.]{0,40}?(?<!never )(?<!not )map[-\u2011 ]?keyed", _SECURITY, re.I
    ), (
        "security-audit/SKILL.md lost its `map-keyed` dispatch statement. Unlike "
        "codebase-review, that skill's dispatch really is map-keyed — Q-296 says so "
        "explicitly and Phase 229's round refuted the suggested twin. This looks like "
        "a class sweep applied one file too wide."
    )
    assert re.search(
        r"map[-\u2011 ]?keyed is not the same as (?:being )?covered", _SECURITY, re.I
    ), (
        "security-audit/SKILL.md lost the distinction that makes its map-keyed "
        "dispatch safe to state: a section whose categories no agent owns is matched "
        "and unaudited, and Step 3-0b is the only check that can see it"
    )


def test_the_workflow_spec_distinguishes_the_two_dispatch_mechanisms():
    """The § 6.1 row covers BOTH skills, so one claim about dispatch is false for one.

    **Two guards were tried here and both are retired, by measurement — this is the third
    shape and the first that three independent attacks did not walk through.**

    1. A 120-character *attribution* rule (every use of the term must have `security-audit`
       nearby). Defeated three ways: the row's own applies-to column literally reads
       `codebase-review, security-audit` and ends 3 chars before the description, so it
       supplies the "attribution" for free; any incidental cross-reference does the same;
       and a row asserting BOTH skills are map-keyed satisfied it outright. It also
       false-killed legal edits.
    2. A *positive* anchor on each true statement. This survives inversion but not
       ADDITION: a reviewer appended the false claim while the true statement stood
       further along the row, and the anchor found the true half and passed. That is the
       both-positions defect — the exact shape `Q-296` is an instance of — for the third
       time in one phase.

    The fix was not a better pattern. It was **removing the need for one**: the row no
    longer uses the retired shorthand at all, so `WORKFLOW.md` joins the stray scan whole,
    with no exemption to hide in. Any re-introduction — inverted, prepended, appended or
    on a decoy line — is now a stray, caught by the scan rather than by a bespoke rule
    here. What is left for this test is the one thing the scan cannot check: that the row
    still says the two things it must.
    """
    rows = [l for l in _WORKFLOW.splitlines() if "`## Map coverage exclusions`" in l]
    assert len(rows) == 1, (
        f"expected exactly one line naming `## Map coverage exclusions`, found {len(rows)}"
    )
    row = rows[0]

    assert re.search(
        r"`?/?security-audit`?[^|]{0,120}?categories[^|]{0,80}?`Check:`", row, re.IGNORECASE
    ), (
        "WORKFLOW.md § 6.1's `## Map coverage exclusions` row no longer states how "
        "/security-audit dispatches: on the OWASP categories a matching security-map "
        "section lists under `Check:`. Do NOT restore the word 'map-keyed' here — the "
        "row covers both skills, the term is false for /codebase-review, and stating the "
        "mechanism instead is what lets the stray scan cover this file with no exemption."
    )
    assert re.search(
        r"`?/?codebase-review`?[^|]{0,80}?keys on[^|]{0,60}?3-pre table", row, re.IGNORECASE
    ), (
        "WORKFLOW.md § 6.1's `## Map coverage exclusions` row no longer states that "
        "/codebase-review keys Step 3 on the hand-authored 3-pre table. Without this the "
        "row is silent about the skill the retired shorthand was false for."
    )
