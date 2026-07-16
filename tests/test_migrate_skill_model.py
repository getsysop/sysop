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
