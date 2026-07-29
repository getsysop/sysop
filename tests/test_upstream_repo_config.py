"""Drift guards for the give-back family's target-repo config.

Filed 2026-07-24 from GDP's first consumer run of the reporting family. The three
GitHub-touching give-back skills — `/report-issues`, `/contribute-convention`,
`/share-wins` — hardcoded the **public** `getsysop/sysop` as their only default,
overridable per-invocation. Two consequences: friction entries and convention
overlays that quote consumer security context filed to a public repo by default,
and a consumer had no durable way to redirect (skills sit outside the
customization-preservation scope, WORKFLOW § 8.2c — a skill edit does not survive
`--update`).

The build:

- **Resolution** — `--repo` › `<project>/CLAUDE.md § Sysop upstream repo` ›
  `getsysop/sysop`, single-sourced in `_shared/upstream-repo.md` and cited (not
  duplicated) by all three skills. A present-but-unparseable section is a hard
  stop, never a silent fall-back to the public default: falling back is exactly
  the disclosure this config exists to prevent.
- **Visibility** — a read-only `gh repo view --json visibility` probe, advisory
  and non-fatal, with a defined offline fallback (shipped default → PUBLIC by
  definition; anything else → UNKNOWN, never assumed private) and `[verified]` /
  `[assumed]` provenance on every line that reports it.
- **Sensitivity nudge** — a local scan of the bodies about to be filed, fired
  when the destination is public, internal, or unverifiable. A warning, never a
  filter.

Rider, same family, verified independent of the above: `/report-issues` and
`/share-wins` still located the friction log at the bare repo root, which
Phase 128 moved to `sysop/SYSOP_ISSUES.md`. Neither had been touched since before
Phase 128 (`/report-issues` `df35007`, Phase 99.1; `/share-wins` `aff195b`,
Phase 107) — so on a post-128 install both pointed the agent at a path the file is
not at. Guarded here so the path claim cannot re-drift.

These are string-anchor drift guards: they pin the load-bearing wording so a
future edit cannot silently drop a leg.
"""

import json
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SKILLS = _ROOT / "core" / "skills"
_PARTIAL = _SKILLS / "_shared" / "upstream-repo.md"
_WORKFLOW = _ROOT / "core" / "companion" / "docs" / "WORKFLOW.md"
_SETTINGS = _ROOT / "core" / "companion" / ".claude" / "settings.json"
_CONFIG_DOC = _ROOT / "docs" / "configuration.md"

# The three give-back skills. `/pr-dependabot` is deliberately absent: it is the
# one GitHub-touching skill that operates on the consumer's *own* repo, so it has
# no upstream target to resolve.
GIVE_BACK_SKILLS = ("report-issues", "contribute-convention", "share-wins")

# The two that read the friction log. `/contribute-convention` reads the
# `.claude/*.project.*` overlay instead, so the path rider does not apply to it.
FRICTION_LOG_SKILLS = ("report-issues", "share-wins")

# Skills and the partial reference it as `§ Sysop upstream repo`; only the
# WORKFLOW template renders it as a literal `## ` heading.
SECTION_NAME = "Sysop upstream repo"
SECTION_HEADING = "## Sysop upstream repo"
DEFAULT_REPO = "getsysop/sysop"
PROBE = "gh repo view"
VISIBILITY_RULE = "Bash(gh repo view:*)"


def _skill(name):
    return (_SKILLS / name / "SKILL.md").read_text()


class TestSharedPartial:
    def test_partial_exists(self):
        assert _PARTIAL.is_file(), (
            "_shared/upstream-repo.md is the single source of truth for target "
            "resolution — the three skills cite it rather than duplicating it"
        )

    def test_names_all_three_precedence_tiers_in_order(self):
        """Presence is not the property — *precedence* is. A partial that listed
        the default first would pass a presence-only check."""
        text = _PARTIAL.read_text()
        order = [text.index("--repo"), text.index(SECTION_NAME), text.index(DEFAULT_REPO)]
        assert order == sorted(order), (
            "the three tiers must be introduced highest-precedence first"
        )
        assert "Stop at the first that yields a slug." in text

    def test_states_the_default_is_public(self):
        """The whole item exists because the shipped default is public. If that
        stops being stated, the nudge's premise is unsourced."""
        text = _PARTIAL.read_text()
        window = text[text.index(DEFAULT_REPO):text.index(DEFAULT_REPO) + 400]
        assert "public" in window.lower()

    def test_unparseable_section_is_a_hard_stop_not_a_fallback(self):
        """The load-bearing safety property: a consumer who wrote the section
        did so to keep something off the public repo, so a typo must not route
        them back to it."""
        text = _PARTIAL.read_text()
        assert "Refusing to fall back to the public default." in text
        assert re.search(
            r"stop\s*—\s*do not fall back to\s+the default", text, re.I
        ), "the hard-stop rule must be stated as a rule, not only as a message"

    def test_absent_section_is_not_an_error(self):
        """Fail-closed on malformed, but not on absent — the ordinary consumer
        never configured one and must keep working unchanged."""
        assert "An **absent** section is not an error" in _PARTIAL.read_text()

    def test_visibility_probe_is_specified_and_non_fatal(self):
        text = _PARTIAL.read_text()
        assert "--json visibility" in text
        assert "advisory and non-fatal" in text
        assert "404" in text, (
            "a 404 from the probe does not prove the repo is missing — a private "
            "repo you cannot see 404s identically; the prose must say so"
        )

    def test_offline_fallback_never_assumes_private(self):
        """The asymmetry is the point: assuming public costs a redundant
        warning, assuming private costs a disclosure."""
        text = _PARTIAL.read_text()
        assert "Do not assume private." in text
        assert "UNKNOWN" in text

    def test_offline_fallback_treats_shipped_default_as_public(self):
        """Pins the *direction*: default → PUBLIC, everything else → UNKNOWN.
        A guard on the rationale phrase alone survives an edit that inverts the
        asymmetry the whole design rests on."""
        text = _PARTIAL.read_text()
        assert "Not a guess" in text
        block = text[text.index("When the probe fails"):text.index("Carry the provenance")]
        default_clause = block[:block.index("Target is anything else")]
        other_clause = block[block.index("Target is anything else"):]
        assert "**PUBLIC**" in default_clause and "UNKNOWN" not in default_clause, (
            "the shipped-default fallback must resolve PUBLIC, never UNKNOWN"
        )
        assert "**UNKNOWN**" in other_clause, (
            "a non-default target must resolve UNKNOWN, never assumed private"
        )

    def test_carries_provenance_markers(self):
        text = _PARTIAL.read_text()
        assert "[verified]" in text and "[assumed]" in text

    def test_nudge_fires_on_public_internal_and_unknown(self):
        """Scoped to the firing rule itself — a bare tree-wide substring check
        stays green even if the rule is replaced with \"nudge on every run\",
        because the three words survive elsewhere in the file."""
        text = _PARTIAL.read_text()
        rule = text[text.index("Run it **only when"):]
        rule = rule[:rule.index("\n\n")]
        for state in ("PUBLIC", "INTERNAL", "UNKNOWN"):
            assert state in rule, f"{state} missing from the firing rule"
        assert "PRIVATE" in rule, "the suppressing case must be stated in the same rule"

    def test_nudge_is_a_warning_not_a_filter(self):
        """Consent stays the gate; the nudge never silently drops an item."""
        text = _PARTIAL.read_text()
        assert "never a filter" in text
        assert "auto-redact" in text

    def test_bare_severity_words_are_not_triggers(self):
        """Alarm fatigue is the failure mode — HIGH/CRITICAL fire on ordinary
        bug reports and would train the human to skim past the nudge."""
        text = _PARTIAL.read_text()
        assert "deliberately **not** triggers" in text

    def test_keyword_match_is_word_bounded(self):
        """The defect this replaced: an unbounded list. Measured against a real
        friction log, `RCE` matched *source*, *force* and *porcelain* — four
        hits, none real — while `PHI` matched *graphics*. The noise buried the
        one true positive, which is the alarm fatigue the section two rules
        below claims to design against."""
        text = _PARTIAL.read_text()
        assert "**Match on whole words, not substrings.**" in text
        for false_friend in ("source", "force", "porcelain", "graphics"):
            assert false_friend in text, (
                f"the boundary rule must name {false_friend!r} as a concrete "
                f"false match — an abstract 'use word boundaries' reads as "
                f"optional"
            )
        assert "standalone" in text

    def test_keyword_list_is_a_floor_not_the_test(self):
        """A keyword list cannot match a paraphrase, and the most sensitive
        sentence in a friction log is usually plain English."""
        text = _PARTIAL.read_text()
        assert "**The list is a floor, not the test.**" in text
        assert "paraphrase" in text

    def test_security_subject_corpus_gets_a_substituted_question(self):
        """`/contribute-convention --include-security` reads a security map,
        whose *subject* is the keyword vocabulary — so the keyword pass matches
        every item and warns about nothing."""
        text = _PARTIAL.read_text()
        assert "substitute a\ndifferent question" in text or "substituted question" in text.lower()
        assert "survived" in text, (
            "the substituted question is about generalization residue, not "
            "about security vocabulary"
        )
        assert "substituted question" in _skill("contribute-convention").lower()

    def test_titles_are_in_scope(self):
        text = _PARTIAL.read_text()
        assert "**The title is in scope**" in text

    def test_near_miss_heading_does_not_fail_open(self):
        """Exact-match resolution fails *open*: an unmatched heading is
        indistinguishable from no heading and routes to the public default."""
        text = _PARTIAL.read_text()
        assert "near-miss heading" in text
        assert "fails *open*" in text
        assert "Jig upstream repo" in text, (
            "the pre-rename spellings are the concrete near-miss this repo "
            "will actually see"
        )

    def test_internal_visibility_is_not_self_contradictory(self):
        """Shipped once as both 'no loud nudge' and a nudge trigger."""
        text = _PARTIAL.read_text()
        assert "**`INTERNAL` nudges**" in text
        assert "no loud nudge" not in text
        assert "INTERNAL [verified]" in text, "INTERNAL needs its own template"

    def test_visibility_is_printed_with_the_target(self):
        """Otherwise a healthy [verified] PRIVATE run and a degraded
        [assumed] UNKNOWN run print byte-identical output."""
        text = _PARTIAL.read_text()
        assert "visibility: PUBLIC [verified]" in text
        assert "visibility: PRIVATE [verified]" in text
        assert "visibility: PUBLIC [assumed]" in text

    def test_repo_flag_overriding_a_configured_target_is_announced(self):
        text = _PARTIAL.read_text()
        assert "overrides CLAUDE.md" in text

    def test_warning_is_restated_per_consent_batch(self):
        """One warning before a ten-item run is several prompts upstream by the
        time the item it was about comes up."""
        assert "**Keep the warning next to the decision.**" in _PARTIAL.read_text()
        assert "restates the target and its visibility" in _skill("report-issues")

    def test_marker_vocabulary_collision_is_stated_not_claimed_identical(self):
        """Shipped as "the same marker vocabulary as fanout-evidence.md" —
        false: that pair is [verified]/[reported], and its [verified] means "I
        opened the cited file:line", not "GitHub answered"."""
        text = _PARTIAL.read_text()
        assert "without reusing its vocabulary" in text
        assert "[reported]" in text, "the distinction must name the other pair"
        fanout = (_SKILLS / "_shared" / "fanout-evidence.md").read_text()
        assert "[assumed]" not in fanout, (
            "if fanout-evidence ever adopts [assumed], this partial's "
            "'deliberately not its vocabulary' note needs revisiting"
        )

    def test_states_it_is_prose_not_enforcement(self):
        """House precedent (fanout-evidence.md): a self-declared label must say
        it is not a machine-checked guarantee — doubly so for a disclosure
        feature whose every guard is a string-anchor drift guard."""
        text = _PARTIAL.read_text()
        assert "not machine-checked\nguarantees" in text or "not machine-checked" in text
        assert "Nothing in this file executes" in text

    def test_explains_why_the_config_lives_in_claude_md(self):
        text = _PARTIAL.read_text()
        assert "8.2c" in text


class TestSkillsCiteThePartial:
    def test_each_skill_functionally_includes_the_partial(self):
        """Matches the include-directive idiom that
        tests/test_install_loop_mode.py uses to compute the loop closure — a
        bare backtick mention would not ship the partial in loop mode."""
        pat = re.compile(
            r"(?:read|see|per|follow|load)\s+`?_shared/upstream-repo\.md", re.I
        )
        for name in GIVE_BACK_SKILLS:
            assert pat.search(_skill(name)), (
                f"{name} must cite _shared/upstream-repo.md with an include "
                f"directive, not a prose mention"
            )

    def test_each_skill_names_the_claude_md_section(self):
        for name in GIVE_BACK_SKILLS:
            assert SECTION_NAME in _skill(name), (
                f"{name} must name the durable config section so a reader of the "
                f"skill alone can find it"
            )

    def test_each_skill_probes_visibility_in_step_0_6(self):
        """Scoped to Step 0.6 — a whole-file check is satisfied by the
        permission-guard paragraph's mention of the same command."""
        for name in GIVE_BACK_SKILLS:
            text = _skill(name)
            step = text[text.index("## Step 0.6"):]
            step = step[:step.index("\n## Step 1")]
            assert PROBE in step, f"{name} Step 0.6 does not probe visibility"

    def test_repo_flag_is_documented_as_a_per_run_override(self):
        """Before this build the flag *was* the only override. If a future edit
        re-describes it as the sole source, the durable config is orphaned."""
        for name in GIVE_BACK_SKILLS:
            text = _skill(name)
            assert "override the upstream target repo for this run" in text, (
                f"{name}'s --repo bullet must read as a per-run override layered "
                f"on the durable default"
            )

    def test_no_skill_claims_the_default_is_the_only_target(self):
        stale = re.compile(
            r"Default target is \*\*`getsysop/sysop`\*\* — the upstream Sysop repo"
        )
        for name in GIVE_BACK_SKILLS:
            assert not stale.search(_skill(name)), (
                f"{name} still presents the shipped default as the whole story"
            )

    def test_nudge_is_declared_in_step_0_6_and_fired_at_the_consent_gate(self):
        """Two *instructional* sites, not two mentions.

        The first version of this guard counted occurrences of the phrase
        anywhere in the file, and passed on a tree where `/report-issues` had
        no Step 0.6 declaration at all — its second "mention" was an inert
        Design-notes rationale bullet. Anchor on the two instruction forms
        instead, and assert their order.
        """
        for name in GIVE_BACK_SKILLS:
            text = _skill(name)
            decl = "The sensitivity nudge runs later, not here."
            fire = "**Then run the sensitivity nudge**"
            assert decl in text, (
                f"{name} Step 0.6 does not declare the nudge (or the forward "
                f"pointer was reworded)"
            )
            assert fire in text, f"{name} never fires the nudge"
            assert text.index(decl) < text.index(fire), (
                f"{name} fires the nudge before declaring it"
            )
            step06 = text[text.index("## Step 0.6"):]
            assert decl in step06[:step06.index("\n## Step 1")], (
                f"{name}'s declaration is not inside Step 0.6"
            )

    def test_nudge_is_not_ordered_before_its_input_exists(self):
        """The nudge scans the rendered payload. Step 0.6 runs before anything
        is rendered, so a Step 0.6 instruction to *scan now* is unexecutable —
        two agents would resolve it differently (skip, defer, or invent)."""
        for name in GIVE_BACK_SKILLS:
            text = _skill(name)
            step06 = text[text.index("## Step 0.6"):]
            step06 = step06[:step06.index("\n## Step 1")]
            assert "runs later, not here" in step06, name
            assert not re.search(
                r"Run the \*\*sensitivity nudge\*\* \(that partial's § C\) over",
                step06,
            ), f"{name} Step 0.6 instructs the scan at a step where no payload exists"

    def test_each_skill_scans_titles_not_only_bodies(self):
        """The title is composed separately and is the most-read field on an
        issue — a routine-looking body under a revealing title was the gap."""
        for name in GIVE_BACK_SKILLS:
            text = _skill(name).lower()
            assert "title" in text or "heading" in text
            assert re.search(r"titles?\b[^.]*\bnot only the bodies|and their titles|including each win's heading", _skill(name)), (
                f"{name} does not extend the scan beyond the body"
            )

    def test_public_destination_is_stated_conditionally_not_hardcoded(self):
        """Two-sided. Hardcoding "filed publicly" is a false claim once the
        target is configurable — but *dropping* the word without replacing it
        left `/contribute-convention` warning less than before this build, on
        the default (public) path. The replacement is the § B visibility line,
        so require that instead of merely forbidding the old wording."""
        stale = re.compile(r"filed publicly on|posted publicly on")
        for name in GIVE_BACK_SKILLS:
            text = _skill(name)
            assert not stale.search(text), (
                f"{name} asserts a public destination the resolved target may "
                f"not have"
            )
            assert "visibility" in text, (
                f"{name} dropped the unconditional 'publicly' without printing "
                f"the resolved visibility in its place"
            )

    def test_pr_dependabot_is_untouched_by_this_family(self):
        """Guards the boundary: /pr-dependabot operates on the consumer's own
        repo and must not grow an upstream-target concept."""
        text = (_SKILLS / "pr-dependabot" / "SKILL.md").read_text()
        assert SECTION_NAME not in text


class TestFrictionLogPath:
    """Phase-128 rider — the log lives at sysop/SYSOP_ISSUES.md."""

    def test_skills_locate_the_log_under_sysop(self):
        for name in FRICTION_LOG_SKILLS:
            assert "sysop/SYSOP_ISSUES.md" in _skill(name)

    def test_no_skill_claims_the_log_is_at_the_repo_root(self):
        stale = re.compile(r"`SYSOP_ISSUES\.md` at the \*\*consumer-repo root\*\*")
        for name in FRICTION_LOG_SKILLS:
            assert not stale.search(_skill(name)), (
                f"{name} points at the pre-Phase-128 location — a post-128 "
                f"install would find nothing and silently report no work"
            )

    def test_pre_128_installs_still_resolve(self):
        """A consumer who has not re-run the installer keeps working."""
        for name in FRICTION_LOG_SKILLS:
            assert "pre-Phase-128 install" in _skill(name)


class TestDocs:
    def test_workflow_required_sections_table_lists_the_section(self):
        text = _WORKFLOW.read_text()
        row = [
            ln for ln in text.splitlines()
            if ln.startswith(f"| `{SECTION_HEADING}`")
        ]
        assert len(row) == 1, "expected exactly one required-sections table row"
        assert "optional" in row[0]

    def test_workflow_ships_a_template(self):
        text = _WORKFLOW.read_text()
        assert "**`## Sysop upstream repo` template**" in text
        assert "`your-org/sysop`" in text, (
            "the template must model the backticked slug form — that is the "
            "shape the partial's parser is specified against"
        )

    def test_workflow_template_states_the_merge_policy_precedent(self):
        text = _WORKFLOW.read_text()
        start = text.index("**`## Sysop upstream repo` template**")
        block = text[start:start + 2000]
        assert "Merge\n> policy" in block or "Merge policy" in block

    def test_workflow_partial_manifest_lists_every_shipped_partial(self):
        """§ 8.3's manifest is hand-maintained and drifted silently: it read
        "Nine partials are present" with ten on disk and this one unlisted.
        Same failure shape as the § 8.4 script table Phase 145 backfilled — an
        absent row looks exactly like a partial that doesn't exist — so it gets
        the same mechanical guard, in both directions."""
        text = _WORKFLOW.read_text()
        on_disk = {p.name for p in (_SKILLS / "_shared").glob("*.md")}
        block = text[text.index("**Shared partials** live under"):]
        block = block[:block.index("\n### 8.4")]
        listed = set(re.findall(r"^- `([a-z0-9-]+\.md)`", block, re.M))
        assert listed == on_disk, (
            f"§ 8.3 partial manifest out of sync — "
            f"unlisted: {sorted(on_disk - listed)}, dead rows: {sorted(listed - on_disk)}"
        )
        words = {9: "Nine", 10: "Ten", 11: "Eleven", 12: "Twelve"}
        assert f"{words[len(on_disk)]} partials are present:" in block, (
            f"the manifest's count word does not match {len(on_disk)} partials"
        )

    def test_loop_mode_doc_covers_the_config(self):
        """Loop mode ships two of the three give-back skills but deliberately
        does NOT ship WORKFLOW.md — so § 6.1, the only other home for this
        config, is unreadable to a loop consumer."""
        text = (_ROOT / "docs" / "loop-mode.md").read_text()
        assert SECTION_HEADING in text
        assert DEFAULT_REPO in text
        assert "public" in text.lower()
        assert "/share-wins" in text, (
            "the shipped partial names a third skill loop consumers do not "
            "have; the page must say so"
        )

    def test_installer_rule_count_comments_track_the_template(self):
        """16 → 17 was updated in three places and missed a fourth; the
        full-mode count had no guard at all."""
        n = len(json.loads(_SETTINGS.read_text())["permissions"]["allow"])
        install = (_ROOT / "install.sh").read_text()
        assert f"the {n}-rule allow-list" in install, (
            f"install.sh's full-mode rule-count comment disagrees with the "
            f"template's {n} rules"
        )

    def test_public_config_doc_mentions_the_section(self):
        text = _CONFIG_DOC.read_text()
        assert SECTION_NAME in text
        assert "per-run override" in text


class TestPermissions:
    def test_template_allow_list_carries_the_visibility_probe(self):
        """Shipped rather than relying on read-only auto-approval, so the
        primary path works under a restricted set instead of silently degrading
        to the offline fallback on every run."""
        allow = json.loads(_SETTINGS.read_text())["permissions"]["allow"]
        assert VISIBILITY_RULE in allow

    def test_probe_is_not_listed_as_a_required_guard_rule(self):
        """Its absence degrades, it does not stop — so it must not appear in a
        skill's permission-guard required list (_shared/permission-guard.md
        § Notes: don't list read-only ops)."""
        for name in GIVE_BACK_SKILLS:
            text = _skill(name)
            guard = text[text.index("## Pre-flight: Permission Guard"):]
            guard = guard[:guard.index("## Step 0")]
            required = re.findall(r"^- `(Bash\([^`]*\))`", guard, re.M)
            assert VISIBILITY_RULE not in required, (
                f"{name} lists the visibility probe as a required rule — a "
                f"missing read-only probe must never halt the run"
            )


class TestParserSpec:
    """The slug parser is the only reason the live consumer config resolves —
    and it had no guard. These pin the *spec*; the parser itself is prose."""

    def test_backtick_stripping_is_specified(self):
        """The documented template models the backticked form, and the real
        consumer section is written that way, so a bare-word-only parser would
        fail the motivating consumer on day one."""
        text = _PARTIAL.read_text()
        assert "strip surrounding whitespace and backticks" in text
        assert "`owner/name`" in text

    def test_slug_shape_is_specified(self):
        assert r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$" in _PARTIAL.read_text()

    def test_reference_template_matches_the_documented_parser(self):
        """The WORKFLOW template is what a consumer copies. Parse it with the
        partial's own stated rule and assert it yields a slug — if the template
        and the parser spec ever disagree, every consumer who copies it breaks."""
        wf = _WORKFLOW.read_text()
        after = wf[wf.index("**`## Sysop upstream repo` template**"):]
        fence = after.index("```markdown") + len("```markdown")
        fenced = after[fence:after.index("```", fence)]
        body = fenced[fenced.index(SECTION_HEADING) + len(SECTION_HEADING):]
        first = next(ln for ln in body.splitlines() if ln.strip())
        assert re.fullmatch(
            r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", first.strip().strip("`")
        ), f"template's first non-empty line {first!r} is not a parseable slug"

    def test_source_label_is_a_single_value_not_a_menu(self):
        """The first draft printed `(source: --repo | CLAUDE.md § ... | default)`
        — a menu rendered as a slot, which an agent may print verbatim."""
        text = _PARTIAL.read_text()
        assert "(source: --repo | CLAUDE.md" not in text
        assert "exactly one\n`source:` value" in text
