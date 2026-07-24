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
        assert "git ls-files | awk -F/ '{print $1}' | sort -u" in text, (
            f"{name}: 2a-0's whole-repo enumeration command changed — verify it "
            "still enumerates independently of the map's section globs"
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
    # `git ls-files | awk -F/ '{print $1}'` yields both. "resolves beneath it" is
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
        assert "never a new duplicate section" in block, (
            f"{name}: 2a-0 no longer routes an unlocalized entry to localizing "
            "the existing section — an agent will create a permanent duplicate"
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
        b = b.replace(
            " Since Step 3 dispatch is convention-map-keyed, such a subtree also "
            "receives **no review agent**.", "")
        b = re.sub(r" \((?:the shipped `security_map\.md` keys sections on root files "
                   r"this way — e\.g\. `Dockerfile`, `\.gitignore`|a section glob may name "
                   r"a root-level file directly)\)", " (ROOTEG)", b)
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
