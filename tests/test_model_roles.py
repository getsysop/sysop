"""Tests for _model_roles.py — marker parsing, resolution, config, validation.

Sysop-original (Phase 69): the role-indirection layer has no gdp counterpart.
Covers the load-bearing invariants — default config is a byte-for-byte no-op,
a remap rewrites, a mixed-role file resolves per-pin, and the three validation
failure modes (un-roled / undefined / unserved) each fire.
"""
import _model_roles as mr

# A minimal skill with a frontmatter pin + an inline pin, both reasoning.
FM = (
    "---\nname: x\nmodel: opus\n---\n"
    "<!-- sysop:model-roles frontmatter=reasoning inline=reasoning -->\n\n"
    "body\n- `model: \"opus\"`\n"
)


def test_parse_file_roles_both():
    assert mr.parse_file_roles(
        "<!-- sysop:model-roles frontmatter=reasoning inline=mechanical -->"
    ) == ("reasoning", "mechanical")


def test_parse_file_roles_frontmatter_only():
    assert mr.parse_file_roles("<!-- sysop:model-roles frontmatter=quick -->") == ("quick", None)


def test_parse_file_roles_missing():
    assert mr.parse_file_roles("no marker here") == (None, None)


def test_analyze_frontmatter_and_inline():
    got = {(r.kind, r.role, r.value) for r in mr.analyze_text(FM)}
    assert ("frontmatter", "reasoning", "opus") in got
    assert ("inline", "reasoning", "opus") in got


def test_analyze_per_pin_override():
    text = (
        "<!-- sysop:model-roles inline=reasoning -->\n"
        "- `model: \"opus\"` <!-- sysop:role=mechanical -->\n"
        "- `model: \"opus\"`\n"
    )
    roles = {(r.lineno, r.role) for r in mr.analyze_text(text)}
    assert (2, "mechanical") in roles  # per-pin override wins
    assert (3, "reasoning") in roles   # file default


def test_analyze_unroled_pin_is_none():
    recs = mr.analyze_text("no marker\n- `model: \"opus\"`\n")
    assert len(recs) == 1 and recs[0].role is None


def test_resolve_default_is_noop():
    new, changes = mr.resolve_text(FM, {"reasoning": "opus"})
    assert changes == [] and new == FM


def test_resolve_override_rewrites_both_pins():
    new, changes = mr.resolve_text(FM, {"reasoning": "sonnet"})
    assert "model: sonnet" in new           # frontmatter
    assert '`model: "sonnet"`' in new        # inline
    assert len(changes) == 2


def test_resolve_mixed_roles_per_pin():
    text = (
        "<!-- sysop:model-roles inline=reasoning -->\n"
        "- `model: \"opus\"` <!-- sysop:role=mechanical -->\n"
        "- `model: \"opus\"`\n"
    )
    new, _ = mr.resolve_text(text, {"reasoning": "opus", "mechanical": "sonnet"})
    lines = new.splitlines()
    assert '"sonnet"' in lines[1]  # mechanical pin rewritten
    assert '"opus"' in lines[2]    # reasoning pin unchanged


def test_resolve_accepts_full_model_id():
    new, changes = mr.resolve_text(FM, {"reasoning": "claude-opus-4-8"})
    assert "model: claude-opus-4-8" in new
    assert '`model: "claude-opus-4-8"`' in new
    assert len(changes) == 2


def test_resolve_is_idempotent():
    once, _ = mr.resolve_text(FM, {"reasoning": "sonnet"})
    twice, ch2 = mr.resolve_text(once, {"reasoning": "sonnet"})
    assert twice == once and ch2 == []


def test_resolve_leaves_unroled_pin_untouched():
    # A pin with no governing marker → role is None → the first disjunct of the
    # skip guard. (Renamed from ...unroled_and_undefined...: its data only ever
    # exercised the role-None half, never the undefined-role half below.)
    text = "no marker\n- `model: \"opus\"`\n"
    new, changes = mr.resolve_text(text, {"reasoning": "sonnet"})
    assert new == text and changes == []


def test_resolve_leaves_undefined_role_untouched():
    # A pin whose role IS defined in the marker ("mechanical") but is absent
    # from the roles mapping → the *second* disjunct (`r.role not in roles`).
    # Dropping it would make `target = roles[r.role]` raise KeyError.
    text = "---\nmodel: opus\n---\n<!-- sysop:model-roles frontmatter=mechanical -->\n"
    new, changes = mr.resolve_text(text, {"reasoning": "sonnet"})  # no "mechanical"
    assert new == text and changes == []


def test_load_config_base_only(tmp_path):
    base = tmp_path / "served_models.yml"
    base.write_text("roles:\n  reasoning: opus\n  quick: haiku\nserved:\n  - opus\n  - haiku\n")
    roles, served = mr.load_roles_config(base)
    assert roles == {"reasoning": "opus", "quick": "haiku"}
    assert served == ["opus", "haiku"]


def test_load_config_local_override_layers(tmp_path):
    base = tmp_path / "served_models.yml"
    base.write_text("roles:\n  reasoning: opus\n  quick: haiku\nserved:\n  - opus\n  - haiku\n")
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  reasoning: fable\nserved:\n  - fable\n")
    roles, served = mr.load_roles_config(base, local)
    assert roles["reasoning"] == "fable"   # local wins
    assert roles["quick"] == "haiku"        # base preserved
    assert "fable" in served and "opus" in served


def _one_skill(tmp_path, body):
    d = tmp_path / "skills" / "a"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(body)
    return tmp_path / "skills"


def test_violations_undefined_role(tmp_path):
    root = _one_skill(tmp_path, "---\nmodel: opus\n---\n<!-- sysop:model-roles frontmatter=bogus -->\n")
    v = mr.find_role_violations(root, {"reasoning": "opus"}, ["opus"])
    assert len(v) == 1 and "undefined role" in v[0][2]


def test_violations_unserved_sunset(tmp_path):
    root = _one_skill(tmp_path, "---\nmodel: opus\n---\n<!-- sysop:model-roles frontmatter=reasoning -->\n")
    v = mr.find_role_violations(root, {"reasoning": "opus"}, ["sonnet"])  # opus retired
    assert len(v) == 1 and "not in served" in v[0][2]


def test_violations_unroled_pin(tmp_path):
    root = _one_skill(tmp_path, "---\nmodel: opus\n---\nno marker here\n")
    v = mr.find_role_violations(root, {"reasoning": "opus"}, ["opus"])
    assert len(v) == 1 and "no governing" in v[0][2]


def test_violations_clean(tmp_path):
    root = _one_skill(tmp_path, "---\nmodel: opus\n---\n<!-- sysop:model-roles frontmatter=reasoning -->\n")
    assert mr.find_role_violations(root, {"reasoning": "opus"}, ["opus"]) == []
