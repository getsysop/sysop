"""The inline pin and the frontmatter pin do not accept the same values (Phase 223).

`Q-220` filed a suspicion: `served_models.yml`'s own override example told a
consumer to map a role to `best`, and that might break every inline agent spawn.
The entry marked itself UNVERIFIED and said to probe before building. The probe
ran, and then the commands ran: the Agent tool's `model` parameter is a closed
enum, and `best`, `inherit`, and a full model id (`claude-opus-5`) are each
rejected with `InputValidationError`. A skill's *frontmatter* `model:` accepts
all three, so the failure is asymmetric — which is why the guard below is scoped
to `kind == "inline"` and a frontmatter test asserts the opposite.

The blast radius is not hypothetical: the shipped comment block advertised the
broken values, `check_skill_models.py` validated only membership in Sysop's own
`served:` list, and so the documented recipe passed the guard and still broke the
spawn — mid-skill, at call time, in the skills the reasoning role governs.
"""
import re
from pathlib import Path

import pytest

import check_skill_models as c

_SYSOP_ROOT = Path(__file__).resolve().parent.parent
_SYSOP_SKILLS = _SYSOP_ROOT / "core" / "skills"
_SYSOP_CONFIG = _SYSOP_ROOT / "core" / "companion" / ".claude" / "served_models.yml"

# A file whose marker gives inline pins the reasoning role, with one body pin.
INLINE = (
    "---\ntitle: t\n---\n"
    "<!-- sysop:model-roles inline=reasoning -->\n"
    'Spawn an agent with `model`: `"opus"` and review the diff.\n'
)
# A file with a frontmatter pin only.
FRONTMATTER = "---\nmodel: opus\n---\n<!-- sysop:model-roles frontmatter=reasoning -->\n"

CFG = "roles:\n  reasoning: opus\nserved:\n  - opus\n"


def _skill(tmp_path, body, name="s"):
    d = tmp_path / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(body)
    return tmp_path / "skills"


def _cfg(tmp_path, text):
    p = tmp_path / "served_models.yml"
    p.write_text(text)
    return p


def _run(root, cfg, local=None):
    argv = ["--root", str(root), "--config", str(cfg)]
    if local is not None:
        argv += ["--local", str(local)]
    return c.main(argv)


def _run_list(root, cfg):
    return c.main(["--root", str(root), "--config", str(cfg), "--list"])


# ── the asymmetry, both directions ────────────────────────────────────────────
def test_inline_pin_mapped_to_best_is_rejected(tmp_path):
    root = _skill(tmp_path, INLINE)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: best\nserved:\n  - best\n")
    assert _run(root, cfg) == 1


def test_frontmatter_pin_mapped_to_best_is_accepted(tmp_path):
    """The other direction, and the reason the guard is scoped to inline pins.

    Failing this case too would refuse a correct config: a skill's frontmatter
    `model:` takes what `/model` takes, `best` included.
    """
    root = _skill(tmp_path, FRONTMATTER)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: best\nserved:\n  - best\n")
    assert _run(root, cfg) == 0


def test_inline_pin_mapped_to_inherit_is_rejected(tmp_path):
    """`inherit` was advertised beside `best` in the same shipped example."""
    root = _skill(tmp_path, INLINE)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: inherit\nserved:\n  - inherit\n")
    assert _run(root, cfg) == 1


def test_inline_pin_mapped_to_full_model_id_is_rejected(tmp_path):
    """A full id is legal in frontmatter and rejected by the Agent tool's enum."""
    root = _skill(tmp_path, INLINE)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: claude-opus-5\nserved:\n  - claude-opus-5\n")
    assert _run(root, cfg) == 1


def test_inline_pin_mapped_to_an_alias_is_accepted(tmp_path):
    """`fable` is the one-key override the corrected docs steer consumers to."""
    root = _skill(tmp_path, INLINE)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: fable\nserved:\n  - fable\n")
    assert _run(root, cfg) == 0


# ── the escape hatch, and its failure mode ────────────────────────────────────
def test_inline_models_key_widens_the_enum(tmp_path):
    """A consumer on a harness that accepts more WIDENS the list. Written as a
    bare `- best` it would *narrow* it instead, and the literal-value arm is
    right to refuse that — the pin in the tree still holds `opus`, which such a
    config declares illegal. The realistic shape keeps the aliases.
    """
    root = _skill(tmp_path, INLINE)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: best\nserved:\n  - best\n"
                         "inline_models:\n  - opus\n  - sonnet\n  - haiku\n"
                         "  - fable\n  - best\n")
    assert _run(root, cfg) == 0


def test_local_overlay_extends_inline_models(tmp_path):
    """EXTENDS, not replaces — and tested against a base that actually declares
    the key, because with an absent base key the two semantics give the same
    answer and the test proves nothing. Under replace, a consumer adding one
    value silently deletes the four shipped aliases and every pin goes red.
    """
    root = _skill(tmp_path, INLINE)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: best\nserved:\n  - best\n"
                         "inline_models:\n  - opus\n  - sonnet\n  - haiku\n  - fable\n")
    local = tmp_path / "served_models.local.yml"
    local.write_text("inline_models:\n  - best\n")
    assert _run(root, cfg, local) == 0

    import _model_roles as m
    merged = m.load_inline_models(cfg, local)
    assert "best" in merged, "the overlay's addition was dropped"
    for shipped in ("opus", "sonnet", "haiku", "fable"):
        assert shipped in merged, (
            f"the overlay REPLACED the base list instead of extending it — {shipped} "
            f"was silently removed, which would red every pin using it"
        )


def test_an_explicitly_empty_list_is_not_a_fallback(tmp_path):
    """Absent and empty are different answers, and conflating them is a
    fail-open. A missing key means "predates the key" and takes the default; an
    explicit `inline_models: []` means the author declared nothing legal, and
    every inline pin must go red rather than silently inherit the default they
    wrote the key to replace.
    """
    root = _skill(tmp_path, INLINE)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: opus\nserved:\n  - opus\ninline_models: []\n")
    assert _run(root, cfg) == 1


def test_config_without_the_key_still_checks(tmp_path):
    """Absence of `inline_models:` means "config predates the key", not "anything
    goes" — an un-updated consumer config must not silently disarm the check."""
    root = _skill(tmp_path, INLINE)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: best\nserved:\n  - best\n")
    assert "inline_models" not in cfg.read_text()
    assert _run(root, cfg) == 1


def test_served_membership_does_not_rescue_an_inline_pin(tmp_path):
    """The trap exactly as the entry described it: the documented recipe adds the
    value to `served:`, the old guard went green, and the spawn still failed."""
    root = _skill(tmp_path, INLINE)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: best\nserved:\n  - best\n")
    assert _run(root, cfg) == 1


def test_list_marks_an_unspawnable_pin(tmp_path, capsys):
    """`--list` is the operator's inspection path. Without its own mark it
    reported a pin that will fail at spawn as `served`, which is the one word
    that would stop someone looking further."""
    root = _skill(tmp_path, INLINE)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: best\nserved:\n  - best\n")
    assert _run_list(root, cfg) == 0
    assert "NOSPAWN" in capsys.readouterr().out


def test_the_enum_is_case_sensitive(tmp_path):
    """The harness enum is lowercase. Case-folding the comparison would accept
    `Opus`, which the Agent tool rejects — an over-permissive direction that no
    test covered."""
    root = _skill(tmp_path, INLINE)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: Opus\nserved:\n  - Opus\n")
    assert _run(root, cfg) == 1


def test_a_resolved_tree_with_a_full_id_is_still_read(tmp_path):
    """Every consumer who overrides ends up with resolved literals in the tree.
    Narrowing the inline value charset to `[a-z]+` stopped the parser seeing a
    full model id — so the state a real override produces became invisible."""
    import _model_roles as m

    body = (
        "---\ntitle: t\n---\n"
        "<!-- sysop:model-roles inline=reasoning -->\n"
        'Spawn with `model`: `"claude-opus-4-8"` and review.\n'
    )
    pins = m.analyze_text(body)
    assert [p.value for p in pins] == ["claude-opus-4-8"], (
        f"the inline parser no longer reads a resolved full model id: {pins}"
    )
    root = _skill(tmp_path, body)
    cfg = _cfg(tmp_path, CFG)
    assert _run(root, cfg) == 1, "a full id in an inline pin must be refused"


@pytest.mark.parametrize("literal", ["best", "inherit", "opusplan", "claude-opus-5", "Opus"])
@pytest.mark.parametrize("marker,role_line", [
    ("<!-- sysop:model-roles inline=reasoning -->", "roles:\n  reasoning: opus\n"),
    ("<!-- sysop:model-roles inline=undefinedrole -->", "roles:\n  reasoning: opus\n"),
    ("", "roles:\n  reasoning: opus\n"),
])
def test_the_literal_arm_covers_the_space_not_one_point(tmp_path, literal, marker, role_line):
    """The literal-value arm was bound by a single fixture — one hyphenated full
    id, under a legal role, in a non-`_shared` file. Round 2 showed five of six
    axes were free: restricting the arm to hyphenated values reopened it for
    `best` and `inherit` (the two literals `Q-220` was actually filed about),
    case-folding it accepted `Opus`, and adding a `served:` fallback reinstalled
    the exact trap the phase's own docstring says it closed — all with the suite
    green.

    A pin that is un-roled or names an undefined role fails on an earlier arm, so
    those rows assert "caught", not "caught by this arm"; what they pin is that no
    combination of role state and literal slips through entirely.
    """
    body = (
        "---\ntitle: t\n---\n"
        + (marker + "\n" if marker else "")
        + f'Spawn with `model`: `"{literal}"` and review.\n'
    )
    root = _skill(tmp_path, body)
    cfg = _cfg(tmp_path, role_line + "served:\n  - opus\n")
    assert _run(root, cfg) == 1, (
        f"literal {literal!r} under marker {marker!r} was accepted"
    )


def test_the_literal_arm_reads_shared_partials(tmp_path):
    """`_shared/` is not a special case, and the round showed the arm could be
    narrowed to skip it while every population floor still held — losing the one
    pin every review skill inherits."""
    shared = tmp_path / "skills" / "_shared"
    shared.mkdir(parents=True)
    (shared / "partial.md").write_text(
        "<!-- sysop:model-roles inline=reasoning -->\n"
        'Spawn with `model`: `"best"` and review.\n'
    )
    cfg = _cfg(tmp_path, CFG)
    assert _run(tmp_path / "skills", cfg) == 1, "a _shared/ partial escaped the arm"


def test_served_membership_does_not_rescue_a_literal_either(tmp_path):
    """The role arm has this test; the literal arm did not, so the same escape
    hatch could be reopened one arm over."""
    root = _skill(tmp_path, INLINE.replace('"opus"', '"best"'))
    cfg = _cfg(tmp_path, "roles:\n  reasoning: opus\nserved:\n  - opus\n  - best\n")
    assert _run(root, cfg) == 1


# ── the empty-population refusal ──────────────────────────────────────────────
def test_an_empty_skills_tree_is_refused(tmp_path):
    """It had no test at all. A guard that scanned nothing certified everything:
    `--root <empty>` printed OK and exited 0 under any mapping, which is a clean
    bill of health for a consumer whose skills install failed."""
    empty = tmp_path / "skills"
    empty.mkdir()
    cfg = _cfg(tmp_path, "roles:\n  reasoning: best\nserved:\n  - best\n")
    assert _run(empty, cfg) == 2


def test_a_tree_of_files_without_pins_is_also_empty(tmp_path):
    """Counting FILES rather than pins would pass this; the population that
    matters is pins."""
    root = _skill(tmp_path, "---\ntitle: t\n---\nNo pins here at all.\n")
    cfg = _cfg(tmp_path, "roles:\n  reasoning: best\nserved:\n  - best\n")
    assert _run(root, cfg) == 2


def test_a_populated_tree_is_not_refused_as_empty(tmp_path):
    """The over-strict direction: one pin is a population."""
    root = _skill(tmp_path, FRONTMATTER)
    assert _run(root, _cfg(tmp_path, CFG)) == 0


def test_a_quoted_frontmatter_pin_is_not_double_counted(tmp_path):
    """The arm's premise is that the two pin kinds are mutually exclusive. No
    fixture used a QUOTED frontmatter pin, so dropping the `continue` after a
    frontmatter match — which would classify it as inline as well — was asserted
    by nothing."""
    import _model_roles as m

    body = '---\nmodel: "opus"\n---\n<!-- sysop:model-roles frontmatter=reasoning -->\n'
    pins = m.analyze_text(body)
    assert [p.kind for p in pins] == ["frontmatter"], (
        f"a quoted frontmatter pin was classified as {[p.kind for p in pins]}"
    )


def test_failure_names_the_inline_cause_and_the_escape(tmp_path, capsys):
    root = _skill(tmp_path, INLINE)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: best\nserved:\n  - best\n")
    _run(root, cfg)
    out = capsys.readouterr().out
    assert "INLINE pin" in out
    assert "closed enum" in out
    assert "inline_models" in out
    assert "does\n     NOT help" in out or "does NOT help" in out


# ── the shipped config, which is where the defect was authored ────────────────
def test_shipped_config_declares_the_inline_enum():
    """The consumer-facing half of the fix. Without the key in the shipped file a
    consumer inherits the built-in default with no way to widen it and no record
    that the constraint exists — which is the state that produced `Q-220`."""
    import yaml

    data = yaml.safe_load(_SYSOP_CONFIG.read_text(encoding="utf-8"))
    assert data.get("inline_models") == ["opus", "sonnet", "haiku", "fable"]


def test_shipped_config_no_longer_advertises_the_broken_values():
    """A reversion guard, and weak by the rule's own account — it pins text rather
    than behaviour. It earns its place because this text IS the defect: the
    comment block told consumers to map a role to values the spawn rejects, and
    called that "the seam for non-Claude models".

    Matched against a NORMALIZED form — comment markers stripped and whitespace
    collapsed — because the first cut keyed on the literal phrase and a mutation
    that merely re-wrapped the sentence across two comment lines walked through
    it. A guard keyed to a physical line is defeated by reflowing that line,
    which is not adversarial; it is how people edit comment blocks.
    """
    import re

    raw = _SYSOP_CONFIG.read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", re.sub(r"(?m)^\s*#", " ", raw))

    assert "seam for non-Claude models" not in flat, (
        "the unqualified provider-neutral claim is back; inline pins take the four "
        "aliases only"
    )
    assert "CLOSED ENUM" in flat, "the constraint that replaced it is gone"
    for marker in ("historically", "is obsolete", "no longer", "now open",
                   "used to be", "has been retired"):
        assert marker not in flat, (
            f"the config carries retraction language {marker!r} — round 2 kept the\n"
            f"CLOSED ENUM substring and appended a clause reversing it"
        )
    # The old block's worked example mapped an inline-governing role to `best`.
    assert "reasoning: best" not in flat
    assert "mechanical: inherit" not in flat


# ── config shapes a consumer actually writes ──────────────────────────────────
# All four found by the round, all reachable by writing the obvious thing.
def test_a_scalar_inline_models_is_refused_not_iterated(tmp_path):
    """A YAML scalar is a string, and iterating a string yields characters — so
    `inline_models: opus` silently became the legal set {o, p, u, s} and turned
    every inline pin red with a nonsense diagnostic. A single-value scalar is
    idiomatic YAML and no shipped example shows the local file's shape."""
    root = _skill(tmp_path, INLINE)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: opus\nserved:\n  - opus\ninline_models: opus\n")
    assert _run(root, cfg) == 2


def test_a_scalar_in_the_local_overlay_is_refused_too(tmp_path):
    """The overlay is the file the docs actually send a consumer to edit."""
    root = _skill(tmp_path, INLINE)
    cfg = _cfg(tmp_path, CFG)
    local = tmp_path / "served_models.local.yml"
    local.write_text("inline_models: best\n")
    assert _run(root, cfg, local) == 2


def test_a_bare_inline_models_key_counts_as_declared_empty(tmp_path):
    """YAML parses `inline_models:` with no items as null. Keying the fallback on
    `is None` conflated that with absence — and commenting out the list items is
    exactly how a consumer reaches the bare form. Presence of the KEY is the
    test, not truthiness of its value."""
    root = _skill(tmp_path, INLINE)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: opus\nserved:\n  - opus\ninline_models:\n")
    assert _run(root, cfg) == 1


def test_malformed_yaml_is_a_usage_error_not_a_violation(tmp_path):
    """Exit 1 means "a pin failed validation". A stray bracket used to surface as
    a raw traceback with exit 1, so the shipped pre-commit example reported a
    YAML typo to the consumer as a model-pin failure."""
    root = _skill(tmp_path, INLINE)
    assert _run(root, _cfg(tmp_path, "roles:\n  reasoning: [oops\n")) == 2
    assert _run(root, _cfg(tmp_path, "- a\n- b\n")) == 2


# ── the class, not the three sites ────────────────────────────────────────────
# Phase 223's round found the phase had corrected the role-override advice in the
# three files it set out to correct and never swept the class. `auto-fix/SKILL.md`
# still told consumers to set `mechanical: inherit` — on the very line that
# carries the mechanical inline pin, so following it broke the agent the line
# configures, and the phase's own new arm fired on that line. Two more skills
# claimed a per-skill remap key that has never existed.

_ADVICE_ROOTS = ("core/skills", "core/companion/docs", "docs")
# Role names are ENUMERATED here, so a role added to `served_models.yml` is
# invisible to this arm until it is added. Phase 262 added `convention-gate`
# and this line was one of five sites that had baked in the three-role set.
_ROLE_MAPPING = re.compile(r"\b(reasoning|mechanical|quick|convention-gate)\s*:\s*([A-Za-z][\w.:-]*)")


def _advice_files():
    for rel in _ADVICE_ROOTS:
        root = _SYSOP_ROOT / rel
        if root.is_dir():
            yield from sorted(root.rglob("*.md"))


def test_no_shipped_surface_prescribes_an_illegal_value_for_an_inline_role():
    """Decidable without judgment: for every `role: value` a shipped surface
    shows, if that role governs an inline pin the value must be one the Agent
    tool's enum accepts. Roles and the legal set are both derived from the tree,
    not restated here, so a new inline pin on a new role widens this check by
    itself.
    """
    import _model_roles as m

    inline_roles = {
        p.role
        for f in m.iter_skill_files(_SYSOP_SKILLS)
        for p in m.analyze_text(f.read_text(encoding="utf-8"))
        if p.kind == "inline" and p.role
    }
    legal = set(m.load_inline_models(_SYSOP_CONFIG, None))
    assert inline_roles and legal, "vacuity: derived nothing to check against"

    # The guard's own POPULATION, asserted. The battery walked a mutation through
    # this check by dropping `core/skills` from the roots — which is where the
    # finding that produced the check lives, so a narrowed population would let
    # the exact defect back in while the check still reported clean. Rule 1 calls
    # this substitution the worst number-producer it has measured.
    swept = {str(p.relative_to(_SYSOP_ROOT)) for p in _advice_files()}
    assert "core/skills" in _ADVICE_ROOTS, "the class check stopped reading the skills tree"
    assert "core/skills/auto-fix/SKILL.md" in swept, (
        "the site that produced this check is no longer in its population"
    )
    assert len(swept) > 40, f"advice population collapsed to {len(swept)} files"

    offenders = []
    for path in _advice_files():
        for i, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            for role, value in _ROLE_MAPPING.findall(line):
                if role in inline_roles and value not in legal:
                    offenders.append(f"{path.relative_to(_SYSOP_ROOT)}:{i}  {role}: {value}")
    assert not offenders, (
        "a shipped surface maps an inline-governing role to a value the Agent tool's "
        "`model` enum rejects — following this advice breaks the spawn:\n  "
        + "\n  ".join(offenders)
    )


def test_no_shipped_surface_claims_a_per_skill_remap_key():
    """`served_models.local.yml` has `roles:`, `served:` and `inline_models:`. It
    has never had a per-skill key, and two skills told consumers otherwise."""
    offenders = []
    for path in _advice_files():
        for i, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            if "served_models.local.yml" not in line:
                continue
            for claim in ("or this skill specifically", "or this skill)", "this skill specifically"):
                if claim in line:
                    offenders.append(f"{path.relative_to(_SYSOP_ROOT)}:{i}  {claim!r}")
    assert not offenders, (
        "a shipped surface claims a per-skill model override exists; the role is the "
        "unit and there is no per-skill key:\n  " + "\n  ".join(offenders)
    )


# ── against Sysop's own tree ──────────────────────────────────────────────────
def test_sysop_own_tree_is_green_under_the_new_arm():
    assert c.main(["--root", str(_SYSOP_SKILLS), "--config", str(_SYSOP_CONFIG)]) == 0


def test_sysop_tree_has_inline_pins_for_the_arm_to_govern():
    """Vacuity control. Every test above could pass with the arm scanning nothing;
    this asserts the population it governs in the real tree is non-empty, and that
    the roles governing it are the ones the corrected docs constrain."""
    import _model_roles as m

    kinds = [p for f in m.iter_skill_files(_SYSOP_SKILLS)
             for p in m.analyze_text(f.read_text(encoding="utf-8"))]
    inline = [p for p in kinds if p.kind == "inline"]
    assert len(inline) >= 10, f"expected the inline pin population, got {len(inline)}"
    assert {p.role for p in inline} == {"reasoning", "mechanical", "convention-gate"}

    # Named, not just counted. The round narrowed the arm to skip `_shared/` and
    # every floor above still held (13 pins → 12, violations 12 → 11), while the
    # pin that vanished is the one EVERY review skill inherits. A floor with slack
    # in it is not a population check.
    by_file = {
        str(f.relative_to(_SYSOP_ROOT))
        for f in m.iter_skill_files(_SYSOP_SKILLS)
        for p in m.analyze_text(f.read_text(encoding="utf-8"))
        if p.kind == "inline"
    }
    assert "core/skills/_shared/adversarial-review.md" in by_file, (
        "the shared adversarial-review pin — inherited by every review skill — is "
        "not in the inline population the arm governs"
    )
    assert "core/skills/auto-fix/SKILL.md" in by_file, "the sole mechanical pin is missing"


def test_the_shipped_config_numbers_are_derived_not_asserted():
    """`served_models.yml`'s comment publishes "13 inline pins today, 12 of them on
    the `reasoning` role". Under this phase's own rule that every published number
    is derived, that pair was published and pinned by nothing."""
    import _model_roles as m

    pins = [
        p
        for f in m.iter_skill_files(_SYSOP_SKILLS)
        for p in m.analyze_text(f.read_text(encoding="utf-8"))
    ]
    inline = [p for p in pins if p.kind == "inline"]
    reasoning_inline = [p for p in inline if p.role == "reasoning"]
    text = _SYSOP_CONFIG.read_text(encoding="utf-8")
    assert f"{len(inline)} inline pins today" in text, (
        f"the shipped comment's inline-pin count disagrees with the tree ({len(inline)})"
    )
    assert f"{len(reasoning_inline)} of them on the" in text, (
        f"the shipped comment's reasoning-inline count disagrees with the tree "
        f"({len(reasoning_inline)})"
    )


def test_the_documented_recipe_would_break_the_real_tree(tmp_path):
    """The regression that matters: `reasoning: best` over Sysop's OWN skills.

    Asserts a floor rather than an exact count so an added inline pin does not
    false-fail — but a floor of 10 cannot be met by an empty scan, which is the
    failure this guards.
    """
    import _model_roles as m

    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  reasoning: best\nserved:\n  - best\n")
    roles, served = m.load_roles_config(_SYSOP_CONFIG, local)
    inline_models = m.load_inline_models(_SYSOP_CONFIG, local)
    violations = m.find_role_violations(_SYSOP_SKILLS, roles, served, inline_models)
    assert len(violations) >= 10
    assert all("INLINE pin" in reason for _rel, _pin, reason in violations)
