"""Tests for resolve_skill_models.py — the install/update-time role resolver CLI.

Sysop-original (Phase 69). The load-bearing guarantees: default config writes
nothing (zero divergence), a remap actually rewrites, a structural error writes
NOTHING (graceful degrade — never half-apply), and a local override layers.
"""
import resolve_skill_models as rs

SKILL = "---\nname: s\nmodel: opus\n---\n<!-- sysop:model-roles frontmatter=reasoning -->\nbody\n"
CFG_DEFAULT = "roles:\n  reasoning: opus\nserved:\n  - opus\n"
CFG_OVERRIDE = "roles:\n  reasoning: sonnet\nserved:\n  - sonnet\n"


def _skill(tmp_path, body=SKILL):
    d = tmp_path / "skills" / "s"
    d.mkdir(parents=True)
    p = d / "SKILL.md"
    p.write_text(body)
    return p


def _cfg(tmp_path, text):
    p = tmp_path / "served_models.yml"
    p.write_text(text)
    return p


def test_dryrun_does_not_write(tmp_path):
    p = _skill(tmp_path)
    cfg = _cfg(tmp_path, CFG_OVERRIDE)
    rc = rs.main(["--root", str(p.parent.parent), "--config", str(cfg)])
    assert rc == 0
    assert "model: opus" in p.read_text()  # unchanged in dry-run


def test_apply_writes_override(tmp_path):
    p = _skill(tmp_path)
    cfg = _cfg(tmp_path, CFG_OVERRIDE)
    rc = rs.main(["--root", str(p.parent.parent), "--config", str(cfg), "--apply"])
    assert rc == 0
    assert "model: sonnet" in p.read_text()


def test_apply_default_is_byte_noop(tmp_path):
    p = _skill(tmp_path)
    before = p.read_text()
    cfg = _cfg(tmp_path, CFG_DEFAULT)
    rc = rs.main(["--root", str(p.parent.parent), "--config", str(cfg), "--apply"])
    assert rc == 0 and p.read_text() == before


def test_undefined_role_exits_1_and_writes_nothing(tmp_path):
    p = _skill(tmp_path, SKILL.replace("frontmatter=reasoning", "frontmatter=bogus"))
    before = p.read_text()
    cfg = _cfg(tmp_path, CFG_DEFAULT)
    rc = rs.main(["--root", str(p.parent.parent), "--config", str(cfg), "--apply"])
    assert rc == 1 and p.read_text() == before  # nothing half-applied


def test_local_override_layers(tmp_path):
    p = _skill(tmp_path)
    cfg = _cfg(tmp_path, CFG_DEFAULT)
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  reasoning: sonnet\nserved:\n  - sonnet\n")
    rc = rs.main(["--root", str(p.parent.parent), "--config", str(cfg),
                  "--local", str(local), "--apply"])
    assert rc == 0 and "model: sonnet" in p.read_text()


def test_missing_config_is_usage_error(tmp_path):
    p = _skill(tmp_path)
    rc = rs.main(["--root", str(p.parent.parent), "--config", str(tmp_path / "nope.yml")])
    assert rc == 2


def test_missing_root_is_usage_error(tmp_path):
    cfg = _cfg(tmp_path, CFG_DEFAULT)
    rc = rs.main(["--root", str(tmp_path / "nope"), "--config", str(cfg)])
    assert rc == 2


# ─────────────────────────────────────────────────────────────────────────────
# Phase 244 (`Q-346` leg 1), and the half that was found by RUNNING the checker's
# fix rather than by reading the filing: with the gate no longer crashing on a
# consumer's own non-UTF-8 file, the EXECUTOR crashed on it instead, and the whole
# resolution was reported as "skipped".
# ─────────────────────────────────────────────────────────────────────────────

LATIN1 = "# Notas del café, año 2026\n".encode("latin-1")


def test_an_undecodable_file_does_not_abort_the_resolution(tmp_path):
    p = _skill(tmp_path)
    (p.parent / "NOTES.md").write_bytes(LATIN1)
    cfg = _cfg(tmp_path, CFG_OVERRIDE)
    rc = rs.main(["--root", str(p.parent.parent), "--config", str(cfg), "--apply"])
    assert rc == 0
    assert "model: sonnet" in p.read_text(), (
        "the override did not land: one undecodable file took the whole run down"
    )


def test_the_resolver_reports_the_file_it_skipped(tmp_path, capsys):
    """"Never half-applies" is this script's stated contract, so a file it
    silently declined to consider would weaken the claim without saying so."""
    p = _skill(tmp_path)
    (p.parent / "NOTES.md").write_bytes(LATIN1)
    cfg = _cfg(tmp_path, CFG_OVERRIDE)
    rs.main(["--root", str(p.parent.parent), "--config", str(cfg), "--apply"])
    assert "NOTES.md" in capsys.readouterr().err


def test_an_undecodable_file_is_not_treated_as_an_unmarked_pin(tmp_path):
    """The survey that runs BEFORE the rewrite had the same unguarded read. A
    file this script cannot decode carries no discoverable marker, so it belongs
    in the same bucket as an unmarked file — not in the "structural error, write
    nothing" bucket, which would refuse a valid override forever."""
    p = _skill(tmp_path)
    (p.parent / "NOTES.md").write_bytes(LATIN1)
    cfg = _cfg(tmp_path, CFG_OVERRIDE)
    assert rs.main(["--root", str(p.parent.parent), "--config", str(cfg)]) == 0


def test_the_resolvers_skipped_count_is_a_count(tmp_path, capsys):
    """Same shape as the checker's: the guards lens replaced `len(unreadable)`
    with a literal `1` and nothing noticed, because no fixture had two."""
    p = _skill(tmp_path)
    for name in ("NOTES.md", "OTHER.md"):
        (p.parent / name).write_bytes(LATIN1)
    cfg = _cfg(tmp_path, CFG_OVERRIDE)
    rs.main(["--root", str(p.parent.parent), "--config", str(cfg), "--apply"])
    err = capsys.readouterr().err
    assert "skipped 2 file(s)" in err, "the count is a literal, not a count"
    assert "NOTES.md" in err and "OTHER.md" in err
