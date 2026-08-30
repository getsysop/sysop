"""Tests for migrate_skill_model.py — tier-safe model-pin migration.

Ported from gdp `5c25516b` (test_migrate_skill_model.py). Sysop divergence:
the gdp `os.environ.setdefault("APP_ENV", "test")` + `sys.path.insert` boilerplate
is dropped — Sysop's pyproject.toml sets `pythonpath = ["core/companion/scripts"]`,
so the script imports by bare name and takes no DB/--env. See tests/PORT_LOG.md.
"""
import migrate_skill_model as m


def test_extract_pins_frontmatter_unquoted():
    pins = m.extract_model_pins("---\nname: x\nmodel: fable\n---\n")
    assert len(pins) == 1
    assert (pins[0].alias, pins[0].kind, pins[0].lineno) == ("fable", "frontmatter", 3)


def test_extract_pins_inline_both_backtick_shapes():
    text = (
        'MUST set `model: "fable"` here.\n'
        '- `model`: `"fable"`\n'
    )
    pins = m.extract_model_pins(text)
    assert [p.alias for p in pins] == ["fable", "fable"]
    assert all(p.kind == "inline" for p in pins)


def test_extract_pins_ignores_prose_word():
    # Bare "Fable" in prose is not a pin.
    assert m.extract_model_pins("up to N concurrent Fable agents") == []


def test_extract_pins_ignores_unrelated_identifiers():
    # A config import / MODEL_TIER_PRO constant must not be mistaken for pins.
    assert m.extract_model_pins("from myapp.config import MODEL_TIER_PRO") == []


def test_migrate_frontmatter_unquoted():
    new, edits, _ = m.migrate_text("model: fable\n", "fable", "opus")
    assert new == "model: opus\n"
    assert edits == [(1, "model: fable", "model: opus")]


def test_migrate_inline_quoted_preserves_quote_style():
    new, edits, _ = m.migrate_text('set `model: "fable"` now\n', "fable", "opus")
    assert new == 'set `model: "opus"` now\n'
    assert len(edits) == 1


def test_migrate_is_tier_safe_for_other_aliases():
    # from=fable must leave sonnet / haiku pins entirely untouched.
    src = 'model: sonnet\n- `model: "haiku"`\n'
    new, edits, flagged = m.migrate_text(src, "fable", "opus")
    assert new == src
    assert edits == []
    assert flagged == []


def test_migrate_flags_prose_without_editing():
    src = "up to N concurrent Fable agents per task\n"
    new, edits, flagged = m.migrate_text(src, "fable", "opus")
    assert new == src  # prose is NOT rewritten
    assert edits == []
    assert flagged == [(1, src.rstrip("\n"))]


def test_migrate_flags_stale_rationale_line():
    # The load-bearing case: a comment that becomes factually wrong post-migrate.
    src = 'the session default is now Fable, which erases the cheap tier\n'
    _, edits, flagged = m.migrate_text(src, "fable", "opus")
    assert edits == []  # no quoted pin on the line
    assert len(flagged) == 1  # surfaced for human rewording


def test_migrate_line_can_be_both_edited_and_flagged():
    # An inline pin sitting in a sentence that also names the model in prose.
    src = 'pin `model: "fable"` because Fable is the review tier\n'
    new, edits, flagged = m.migrate_text(src, "fable", "opus")
    assert '"opus"' in new
    assert len(edits) == 1
    assert len(flagged) == 1  # the trailing "Fable" prose word still flagged


def test_migrate_rejects_identical_from_to(capsys):
    rc = m.main(["--from", "opus", "--to", "opus"])
    assert rc == 2
    assert "identical" in capsys.readouterr().err


# ─────────────────────────────────────────────────────────────────────────────
# Phase 244 (`Q-346` leg 1), swept across the family rather than fixed at the one
# filed site: the migrator walks the same `.claude/skills/` tree with the same
# unguarded read, so a consumer's own non-UTF-8 file aborted a bulk migration.
# ─────────────────────────────────────────────────────────────────────────────

def test_read_skill_text_returns_none_on_an_undecodable_file(tmp_path):
    p = tmp_path / "NOTES.md"
    p.write_bytes("# Notas del café\n".encode("latin-1"))
    assert m.read_skill_text(p) is None


def test_read_skill_text_returns_none_on_a_missing_file(tmp_path):
    assert m.read_skill_text(tmp_path / "nope.md") is None


def test_read_skill_text_returns_the_text_of_a_normal_file(tmp_path):
    """The positive control. Without it a helper that returned None
    unconditionally would satisfy both assertions above."""
    p = tmp_path / "OK.md"
    p.write_text("# fine\n")
    assert m.read_skill_text(p) == "# fine\n"


def test_an_undecodable_file_does_not_abort_a_migration(tmp_path, capsys):
    """The end-to-end half of `read_skill_text`'s migrator site. Without this the
    helper's unit tests above pass while the migrator's own loop is reverted —
    the author battery's `RD06` was written to find exactly that, and did."""
    d = tmp_path / "skills" / "s"
    d.mkdir(parents=True)
    good = d / "SKILL.md"
    good.write_text("---\nname: s\nmodel: opus\n---\nbody\n")
    (d / "NOTES.md").write_bytes("# Notas del café\n".encode("latin-1"))

    rc = m.main(["--root", str(tmp_path / "skills"), "--from", "opus",
                 "--to", "sonnet", "--apply"])

    assert rc == 0
    assert "model: sonnet" in good.read_text(), (
        "one undecodable file took the whole migration down"
    )
    assert "NOTES.md" in capsys.readouterr().err, (
        "the skipped file was not disclosed"
    )
