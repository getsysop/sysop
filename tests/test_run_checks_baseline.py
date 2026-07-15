"""Unit tests for run_checks/baseline.py's load_baseline `#`-header round-trip
(Phase 105).

The baseline file write_baseline emits opens with a 5-line `#` comment header +
a blank line; load_baseline must skip every `#`-header and blank line and return
exactly the `check_id|path:line` key set. This round-trip had no coverage (there
is no other baseline test file; the `baseline` hits elsewhere are the English
word). Pure file I/O — no subprocess.
"""
import run_checks.baseline as baseline


def test_load_baseline_skips_comments_and_blank_lines(tmp_path):
    p = tmp_path / "baseline.txt"
    p.write_text("# header comment\n\ncheck-a|src/x.py:1\ncheck-b|src/y.py:9\n")
    keys = baseline.load_baseline(str(p))
    assert keys == {"check-a|src/x.py:1", "check-b|src/y.py:9"}
    # Load-bearing: no `#`-header line leaked into the key set.
    assert all(not k.startswith("#") for k in keys)


def test_write_then_load_roundtrip_ignores_header(tmp_path):
    # write_baseline emits a `#` header block + blank line; load_baseline must
    # drop all of it and return only the key. (dirname must be non-empty —
    # write_baseline os.makedirs it.)
    p = str(tmp_path / ".sysop" / "baseline.txt")
    baseline.write_baseline(p, [("chk", "src/a.py:3", "msg")], blocking_ids={"chk"})
    assert baseline.load_baseline(p) == {"chk|src/a.py:3"}


def test_load_baseline_missing_file_is_empty_set(tmp_path):
    assert baseline.load_baseline(str(tmp_path / "nope.txt")) == set()
