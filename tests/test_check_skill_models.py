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


# ─────────────────────────────────────────────────────────────────────────────
# Phase 244 (`Q-346` leg 1): a file this check cannot decode is not a verdict.
# ─────────────────────────────────────────────────────────────────────────────

LATIN1 = "# Notas del café, año 2026\n".encode("latin-1")


def test_an_undecodable_file_does_not_crash_the_check(tmp_path):
    """The reported shape: a consumer's own latin-1 `.md` under `.claude/skills/`
    — Claude Code's standard USER skill directory — raised `UnicodeDecodeError`,
    Python exited 1, and `install.sh` reads 1 as "your mapping is invalid". The
    consumer had no override at all."""
    root = _skill(tmp_path, GOOD)
    (root / "s" / "NOTES.md").write_bytes(LATIN1)
    cfg = _cfg(tmp_path, CFG)
    assert c.main(["--root", str(root), "--config", str(cfg)]) == 0


def test_the_skipped_file_is_reported_and_named(tmp_path, capsys):
    """Skipping silently would turn a partial scan into a clean bill of health.
    The count reaches the OK line, so a green result states its own scope, and
    the path reaches stderr so the reader can tell WHICH file."""
    root = _skill(tmp_path, GOOD)
    (root / "s" / "NOTES.md").write_bytes(LATIN1)
    cfg = _cfg(tmp_path, CFG)
    assert c.main(["--root", str(root), "--config", str(cfg)]) == 0
    out = capsys.readouterr()
    assert "NOTES.md" in out.err, "the skipped file was not named"
    assert "1 unreadable file(s) skipped" in out.out, (
        "a green result did not state that its scan was partial"
    )


def test_an_undecodable_file_does_not_hide_a_real_violation(tmp_path):
    """The over-permissive direction. The read guard must skip the one file it
    cannot decode, not stop finding violations in the ones it can."""
    root = _skill(tmp_path, GOOD)
    (root / "s" / "NOTES.md").write_bytes(LATIN1)
    bad = root / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text(
        "---\nmodel: opus\n---\n<!-- sysop:model-roles frontmatter=bogus -->\n")
    cfg = _cfg(tmp_path, CFG)
    assert c.main(["--root", str(root), "--config", str(cfg)]) == 1


def test_a_tree_of_only_undecodable_files_is_not_a_passing_check(tmp_path):
    """The empty-population guard must still fire when skipping is what emptied
    it. Otherwise the read guard converts "scanned nothing" into "all good"."""
    root = tmp_path / "skills" / "s"
    root.mkdir(parents=True)
    (root / "NOTES.md").write_bytes(LATIN1)
    cfg = _cfg(tmp_path, CFG)
    assert c.main(["--root", str(tmp_path / "skills"), "--config", str(cfg)]) == 2


def test_list_mode_marks_an_undecodable_file(tmp_path, capsys):
    """`--list` had the same unguarded read, one branch earlier."""
    root = _skill(tmp_path, GOOD)
    (root / "s" / "NOTES.md").write_bytes(LATIN1)
    cfg = _cfg(tmp_path, CFG)
    assert c.main(["--root", str(root), "--config", str(cfg), "--list"]) == 0
    assert "UNREAD" in capsys.readouterr().out


def test_an_undecodable_config_is_a_usage_error_not_a_traceback(tmp_path):
    """`Q-346` leg 1's class, one input over: a config saved in a non-UTF-8
    encoding escaped the `YAMLError` catch as a traceback, which `install.sh`
    then printed as a verdict. It is exit 2, like every other config the check
    cannot read."""
    root = _skill(tmp_path, GOOD)
    cfg = tmp_path / "served_models.yml"
    cfg.write_bytes("roles:\n  reasoning: opus  # café\nserved:\n  - opus\n".encode("latin-1"))
    assert c.main(["--root", str(root), "--config", str(cfg)]) == 2


def test_an_unreadable_config_is_a_usage_error_not_a_traceback(tmp_path):
    """The round's § Medium, and the other half of the catch this phase added.

    `read_skill_text` guards `(UnicodeDecodeError, OSError)`; the config loader's
    first cut guarded only the decode. `load_roles_config` gates on `is_file()`,
    which a mode-000 file passes, so an unreadable `served_models.local.yml` —
    the documented, never-overwritten override file — raised `PermissionError`,
    exited 1, and `install.sh` printed `REFUSED (invalid mapping)` with the
    traceback under it. Byte for byte the shape this phase says it closed.
    """
    import os
    import pytest

    if os.geteuid() == 0:
        pytest.skip("root reads a mode-000 file, so the fixture cannot reproduce")
    root = _skill(tmp_path, GOOD)
    cfg = _cfg(tmp_path, CFG)
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  reasoning: opus\n")
    local.chmod(0o000)
    try:
        assert c.main(["--root", str(root), "--config", str(cfg),
                       "--local", str(local)]) == 2
    finally:
        local.chmod(0o600)


def test_the_skipped_count_is_a_count_and_not_a_literal(tmp_path, capsys):
    """The guards lens pinned three separate `len(unreadable)` interpolations to a
    hardcoded `1` and every one survived, because every fixture in the suite wrote
    exactly one undecodable file. A count asserted only at n=1 is not asserted."""
    root = _skill(tmp_path, GOOD)
    for name in ("NOTES.md", "OTHER.md"):
        (root / "s" / name).write_bytes(LATIN1)
    cfg = _cfg(tmp_path, CFG)
    assert c.main(["--root", str(root), "--config", str(cfg)]) == 0
    out = capsys.readouterr()
    assert "2 unreadable file(s) skipped" in out.out, (
        "the green line's scope count is a literal, not a count"
    )
    assert "skipped 2 file(s)" in out.err, (
        "the stderr note's count is a literal, not a count"
    )
    assert "NOTES.md" in out.err and "OTHER.md" in out.err, (
        "the note names fewer files than it skipped"
    )


# ── `Q-295` (Phase 441): the Fix line names the file a consumer's edit survives in ──────
# It named served_models.yml, which every update replaces, so a consumer who followed it
# lost the edit and met the same refusal on the next update.

def _fix_lines(out: str) -> list[str]:
    lines = out.splitlines()
    i = next(n for n, ln in enumerate(lines) if ln.startswith("Fix:"))
    return lines[i:]


def test_the_fix_line_names_the_override_file_even_when_absent(tmp_path, capsys):
    root = _skill(tmp_path, GOOD)
    cfg = _cfg(tmp_path, "roles:\n  reasoning: opus\nserved:\n  - sonnet\n")
    local = tmp_path / "served_models.local.yml"           # never created
    assert c.main(["--root", str(root), "--config", str(cfg), "--local", str(local)]) == 1
    fix = _fix_lines(capsys.readouterr().out)
    assert fix[0].startswith(f"Fix: map the role under `roles:` in {local} (create it if absent)."), fix
    assert f"{cfg} is Sysop's own mapping and every update replaces it" in fix[0], fix
    # Round 1, lens B: each remedy prints for its own reason only.
    assert not any(ln.lstrip().startswith(("An undefined role", "A pin with no role",
                                            "A pin judged by its own literal")) for ln in fix), fix
    assert "repoint the role in served_models.yml" not in "\n".join(fix), fix


def test_an_undefined_role_gets_the_marker_remedy(tmp_path, capsys):
    root = _skill(tmp_path, "---\nmodel: opus\n---\n<!-- sysop:model-roles frontmatter=bogus -->\n")
    cfg = _cfg(tmp_path, CFG)
    assert c.main(["--root", str(root), "--config", str(cfg)]) == 1
    out = capsys.readouterr().out
    assert "no `roles:` entry in served_models.yml or the local override" in out, out
    assert any("in a skill of your own, remove the marker" in ln for ln in _fix_lines(out)), out
    # Each remedy is printed for its own reason only.
    assert "a marker governs every pin on its line" not in out, out
    assert "A pin with no role" not in out, out


def test_a_consumer_pin_on_a_marked_line_gets_the_move_it_remedy(tmp_path, capsys):
    """`Q-700`'s shape: a consumer copies a Sysop-marked line and adds a pin of its own on it,
    so the line's marker governs that pin and its literal is judged."""
    cfg = _cfg(tmp_path, "roles:\n  executor: sonnet\nserved:\n  - sonnet\n")
    root = _skill(tmp_path, 'spawn `model: "sonnet"` <!-- sysop:role=executor --> and my own `model: "best"`\n')
    assert c.main(["--root", str(root), "--config", str(cfg), "--managed-only"]) == 1
    out = capsys.readouterr().out
    assert "INLINE pin holds the literal value 'best'" in out, out
    fix = "\n".join(_fix_lines(out))
    assert "a marker governs every pin on its line" in fix, fix
    assert "Put a pin of your own on a line, in a file, that no Sysop marker governs." in fix, fix
    assert "remove the marker" not in fix and "per-pin" not in fix, fix
    # Round 1, lens A: a role remedy cannot clear a literal failure, and printing one beside
    # it sent the consumer to an edit that left the refusal standing.
    assert "map the role" not in fix and "For the INLINE failures" not in out, out
    assert fix.startswith("Fix: A pin judged by its own literal"), fix


def test_a_role_that_governs_an_inline_pin_still_gets_the_enum_remedy(tmp_path, capsys):
    cfg = _cfg(tmp_path, "roles:\n  executor: best\nserved:\n  - best\n")
    root = _skill(tmp_path, 'spawn `model: "sonnet"` <!-- sysop:role=executor -->\n')
    assert c.main(["--root", str(root), "--config", str(cfg), "--managed-only"]) == 1
    out = capsys.readouterr().out
    assert "governs an INLINE pin" in out, out
    assert "For the INLINE failures above" in out, out
    assert "A pin judged by its own literal" not in out, out


def test_in_a_sysop_source_tree_the_fix_names_the_shipped_mapping(tmp_path, capsys):
    """Round 1, lens A: a maintainer's run named an override path relative to `core/`,
    which no file there holds; in the source tree the shipped mapping is what to edit."""
    core = tmp_path / "core"
    root = _skill(core, GOOD)                               # core/skills/s/SKILL.md
    (core / "companion" / ".claude").mkdir(parents=True)
    cfg = core / "companion" / ".claude" / "served_models.yml"
    cfg.write_text("roles:\n  reasoning: opus\nserved:\n  - sonnet\n")
    assert c.main(["--root", str(root), "--config", str(cfg)]) == 1
    fix = _fix_lines(capsys.readouterr().out)
    assert fix[0].startswith(f"Fix: repoint the role in {cfg} (and update served:)"), fix
    assert "served_models.local.yml" not in "\n".join(fix), fix


def test_an_unroled_pin_gets_the_per_pin_marker_remedy(tmp_path, capsys):
    root = _skill(tmp_path, "---\nmodel: opus\n---\n<!-- sysop:model-roles inline=reasoning -->\n")
    cfg = _cfg(tmp_path, CFG)
    assert c.main(["--root", str(root), "--config", str(cfg)]) == 1
    out = capsys.readouterr().out
    assert "pin has no governing" in out, out
    assert any("give it a per-pin `<!-- sysop:role=… -->`" in ln for ln in _fix_lines(out)), out


def test_ok_and_list_print_no_fix_line(tmp_path, capsys):
    root = _skill(tmp_path, GOOD)
    cfg = _cfg(tmp_path, CFG)
    assert c.main(["--root", str(root), "--config", str(cfg)]) == 0
    assert c.main(["--root", str(root), "--config", str(cfg), "--list"]) == 0
    assert "Fix:" not in capsys.readouterr().out


def test_an_effort_literal_gets_no_role_remedy(tmp_path, capsys):
    """Round 1, lens B: an effort the enum rejects got the role remedy and the alias line,
    neither of which can change a literal."""
    cfg = _cfg(tmp_path, "roles:\n  executor: sonnet\nserved:\n  - sonnet\n")
    root = _skill(tmp_path, 'spawn `model: "sonnet"`, `effort: "turbo"` <!-- sysop:role=executor -->\n')
    assert c.main(["--root", str(root), "--config", str(cfg), "--managed-only"]) == 1
    out = capsys.readouterr().out
    assert "INLINE pin carries the effort 'turbo'" in out, out
    assert "map the role" not in out and "For the INLINE failures" not in out, out
