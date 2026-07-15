"""Tests for ``core/companion/scripts/_log.py`` — the shared log sanitizer.

``_sanitize_log`` is the single-source helper the ``run_checks`` package,
``backfill_completed_dates.py``, and (via inline copies) ``validate_tasks.py``
/ ``next_task.py`` apply to every exception message and externally-derived
string before printing. It has three jobs: strip terminal escape sequences,
strip control characters, and cap length so a runaway message can't flood the
log. Prior coverage exercised only the ANSI/control-strip paths; these tests
pin the newline/CR/NUL collapse (log-injection defense) and the truncation
(DoS-mitigation) branch that were unpinned — a regression in either would let
a crafted path or subprocess stderr corrupt the terminal or forge a log line.
"""

import _log


def test_strips_ansi_color_escapes():
    """A colorized string is reduced to its visible text."""
    assert _log._sanitize_log("\x1b[31mred\x1b[0m alert") == "red alert"


def test_strips_control_characters():
    """Bell (0x07) and DEL (0x7f) — terminal-affecting control chars — are removed."""
    assert _log._sanitize_log("a\x07b\x7fc") == "abc"


def test_preserves_ordinary_printable_text():
    """Plain text (incl. tabs, which are not in the control-strip class) is untouched."""
    assert _log._sanitize_log("path/to/file.py: ok\t(done)") == "path/to/file.py: ok\t(done)"


def test_collapses_newlines_carriage_returns_and_nulls_to_spaces():
    """CR/LF/NUL become spaces so a multi-line value can't forge a second log line.

    This is the log-injection defense: an exception message or path containing
    an embedded newline must not be able to inject what looks like an
    independent warning line into the operator's output.
    """
    assert _log._sanitize_log("line1\nline2\rline3\x00tail") == "line1 line2 line3 tail"


def test_truncates_beyond_default_max_len():
    """A value longer than the 500-char default is cut to 500 chars plus an ellipsis."""
    result = _log._sanitize_log("x" * 600)
    assert result == "x" * 500 + "..."
    assert len(result) == 503


def test_does_not_truncate_at_exactly_max_len():
    """A value of exactly max_len characters keeps every char and gains no ellipsis.

    Pins the boundary (``len > max_len``, not ``>=``) so the else-path is exercised.
    """
    exact = "y" * 500
    result = _log._sanitize_log(exact)
    assert result == exact
    assert not result.endswith("...")


def test_honors_custom_max_len():
    """The truncation length is configurable; the ellipsis is appended past the cap."""
    assert _log._sanitize_log("abcdefghij", max_len=4) == "abcd..."


def test_coerces_non_string_values():
    """Non-str inputs (an int, an exception object) are stringified before sanitizing."""
    assert _log._sanitize_log(42) == "42"
    assert _log._sanitize_log(FileNotFoundError("missing\nfile")) == "missing file"


def test_truncation_applies_after_control_strip():
    """Stripping happens before the length cap, so escape bytes don't consume budget.

    A 600-char run of ANSI escapes collapses to empty text — well under the cap —
    rather than being truncated while still full of control bytes.
    """
    noisy = "\x1b[0m" * 150  # 600 chars, all escape sequences
    assert _log._sanitize_log(noisy) == ""
