"""Tests for check_skill_models.py — role-resolution guard (Phase 69).

Phase 65b shipped this as a flat served-alias allowlist guard; Phase 69 evolves
it to validate the role-indirection layer: every skill pin must be governed by a
`<!-- sysop:model-roles … -->` marker, name a defined role, and resolve to a served
model. The sysop-original guard at the bottom (`test_sysop_own_skills_all_roles_served`)
is the real CI value — it goes red if Sysop's own core/skills/ ever pins an
un-roled, undefined, or unserved (sunset) model. See tests/PORT_LOG.md.
"""
from pathlib import Path

import check_skill_models as c

# Sysop source-tree roots (this test file lives at <repo>/tests/).
_SYSOP_ROOT = Path(__file__).resolve().parent.parent
_SYSOP_SKILLS = _SYSOP_ROOT / "core" / "skills"
_SYSOP_CONFIG = _SYSOP_ROOT / "core" / "companion" / ".claude" / "served_models.yml"

GOOD = "---\nmodel: opus\n---\n<!-- sysop:model-roles frontmatter=reasoning -->\n"
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


def test_main_ok_when_role_resolves(tmp_path):
    root = _skill(tmp_path, GOOD)
    cfg = _cfg(tmp_path, CFG)
    assert c.main(["--root", str(root), "--config", str(cfg)]) == 0


def test_main_fail_on_undefined_role(tmp_path):
    root = _skill(tmp_path, "---\nmodel: opus\n---\n<!-- sysop:model-roles frontmatter=bogus -->\n")
    cfg = _cfg(tmp_path, CFG)
    assert c.main(["--root", str(root), "--config", str(cfg)]) == 1


def test_main_fail_on_sunset_unserved(tmp_path):
    root = _skill(tmp_path, GOOD)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: opus\nserved:\n  - sonnet\n")  # opus retired
    assert c.main(["--root", str(root), "--config", str(cfg)]) == 1


def test_main_fail_on_unroled_pin(tmp_path):
    root = _skill(tmp_path, "---\nmodel: opus\n---\nno marker\n")
    cfg = _cfg(tmp_path, CFG)
    assert c.main(["--root", str(root), "--config", str(cfg)]) == 1


def test_main_missing_config_is_usage_error(tmp_path):
    root = _skill(tmp_path, GOOD)
    assert c.main(["--root", str(root), "--config", str(tmp_path / "nope.yml")]) == 2


def test_list_exits_0_and_shows_resolution(tmp_path, capsys):
    root = _skill(tmp_path, GOOD)
    cfg = _cfg(tmp_path, CFG)
    assert c.main(["--root", str(root), "--config", str(cfg), "--list"]) == 0
    assert "reasoning -> opus" in capsys.readouterr().out


def test_local_override_extends_served(tmp_path):
    # reasoning remapped to fable via local; base served lacks fable, local adds it.
    root = _skill(tmp_path, GOOD)
    cfg = _cfg(tmp_path, CFG)
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  reasoning: fable\nserved:\n  - fable\n")
    assert c.main(["--root", str(root), "--config", str(cfg), "--local", str(local)]) == 0


def test_meta_value_is_not_exempt_from_served(tmp_path):
    # SF1 regression: a role mapped to a meta-value (`inherit`/`best`/…) is NOT
    # exempt — it must appear in served: or the guard goes red (the trap the
    # served_models.yml override example hit). Resolver writes it happily; the
    # checker is what enforces the served allowlist, with no special cases.
    root = _skill(tmp_path, GOOD)  # reasoning role
    cfg = _cfg(tmp_path, CFG)
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  reasoning: inherit\n")  # inherit NOT added to served
    assert c.main(["--root", str(root), "--config", str(cfg), "--local", str(local)]) == 1
    local.write_text("roles:\n  reasoning: inherit\nserved:\n  - inherit\n")  # now served
    assert c.main(["--root", str(root), "--config", str(cfg), "--local", str(local)]) == 0


# ── sysop-original guard (the real CI value) ─────────────────────────────
def test_sysop_own_skills_all_roles_served():
    """Every model pin in Sysop's own core/skills/ is roled and resolves to a served model.

    Red CI if a future edit introduces an un-roled pin, an undefined role, or a
    sunset leaves a role mapped to a model dropped from served_models.yml.
    """
    assert _SYSOP_SKILLS.is_dir(), f"expected Sysop skills at {_SYSOP_SKILLS}"
    assert _SYSOP_CONFIG.is_file(), f"expected role config at {_SYSOP_CONFIG}"
    assert c.main(["--root", str(_SYSOP_SKILLS), "--config", str(_SYSOP_CONFIG)]) == 0
