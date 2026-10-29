"""Pins the three registry checks Phase 215 converged with the consumer's overlay.

WHY THIS MODULE EXISTS. Phase 215's pre-build execution lens applied all three
fixes and ran the full suite: **4039 passed, 0 failed**. Nothing in the tree
pinned the narrow `grant-sensitive-table` structure, the `getenv(`-only
`app-env-default-prod`, or the bare-word `window-open-noopener` negative — so
each fix was unguarded in both directions, and a revert would have been silent.

Each matrix below is the measurement that justified the fix, not a restatement
of the regex. A row that fails is a claim in `PHASE_LOG.md` § Phase 215 that has
stopped being true.

ENGINE NOTE, load-bearing. `pattern` is executed by shell `grep -rn -E`
(POSIX ERE, no lookbehind); `negative_pattern` is applied with Python
`re.search` in `grep.py`. That asymmetry is why the `window-open-noopener`
negative can use `(?<![-\\w])` and the patterns cannot. These tests compile
`pattern` with Python `re` too, which is *weaker* than the shipped path — it
would accept a pattern ERE rejects. `test_patterns_are_posix_ere_executable`
closes that by running the real `grep -E`.
"""
import re
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[1]


def _check(pack: str, cid: str) -> dict:
    frag = REPO_ROOT / "packs" / pack / "companion" / "checks.yml.fragment"
    for c in yaml.safe_load(frag.read_text(encoding="utf-8"))["checks"]:
        if c["id"] == cid:
            return c
    raise AssertionError(f"{cid} not found in {frag}")


# --- Q-249 -----------------------------------------------------------------
# 16 cases (8 must-match + 8 must-not). The tight form was wrong on 6 of
# them; the shipped form on 0. The count is asserted below, because an
# earlier draft said 22 while pointing at this list.
GRANT_MUST_MATCH = [
    "GRANT SELECT ON users TO app_reader;",
    "GRANT SELECT ON public.users TO app_reader;",          # schema-qualified
    "GRANT SELECT ON users, orders TO app_reader;",         # multi-table
    "GRANT SELECT ON orders, users TO app_reader;",         # multi-table, 2nd
    "GRANT SELECT ON TABLE users TO app_reader;",           # ON TABLE
    'GRANT SELECT ON "users" TO app_reader;',               # quoted ident
    "GRANT UPDATE ON myschema.payments TO app_writer;",
    "GRANT ALL ON stripe_events TO app_writer;",
]
GRANT_MUST_NOT_MATCH = [
    "GRANT SELECT ON orders TO app_reader;",                # unlisted table
    "GRANT SELECT ON v_public_users TO app_reader;",        # the remediation
    "GRANT SELECT ON public.v_public_users TO app_reader;",
    "GRANT SELECT ON users_archive TO app_reader;",         # \b holds: _ is \w
    "GRANT SELECT ON archived_users TO app_reader;",
    "GRANT SELECT ON payments_summary TO app_reader;",
    "GRANT SELECT ON users TO admin_role;",                 # not an app_ role
    "-- GRANT SELECT ON users TO app_reader;",              # commented out
]


@pytest.mark.parametrize("line", GRANT_MUST_MATCH)
def test_grant_sensitive_table_catches_ordinary_spellings(line):
    """Schema-qualified and multi-table grants are ordinary Postgres.

    The pre-Phase-215 pattern required the table immediately after `ON` and
    immediately before `TO`, so both slipped a `blocking: true`,
    `severity: critical` gate.
    """
    assert re.search(_check("postgres", "grant-sensitive-table")["pattern"], line), line


@pytest.mark.parametrize("line", GRANT_MUST_NOT_MATCH)
def test_grant_sensitive_table_stays_quiet_on_the_remediations(line):
    """Widening with `.*` must not fire on the fix the finding recommends.

    `v_public_*` views and `*_archive` tables are what a consumer is told to
    move to; flagging those would make the gate unusable.
    """
    assert not re.search(_check("postgres", "grant-sensitive-table")["pattern"], line), line


def test_grant_sensitive_table_names_every_gap_it_claims_to_name():
    """Each disclosure is asserted on its own — no `or`, no bare substring.

    Phase 215's round walked the first cut of this test twice: the `or` disjunct
    was satisfied by a neighbouring sentence, so the disclosure it guarded could
    be deleted, and a bare-substring assert elsewhere was satisfied by an
    unrelated earlier occurrence in the same block. A prose guard has to pin the
    sentence, not a word that happens to appear near it.
    """
    notes = _check("postgres", "grant-sensitive-table").get("notes", "")
    assert "false positive" in notes.lower()
    assert "no-check: grant-sensitive-table" in notes
    for gap in (
        "wrapped across lines",          # 1: no alternation can see it
        "ALL TABLES IN SCHEMA",          # 2: grants everything, names nothing
        "lowercase",                     # 3: ordinary in migrations
        "view or synonym",               # 4
    ):
        assert gap in notes, f"the notes stopped naming the gap: {gap!r}"
    assert "security_map.md" in notes, "the pointer must name the doc that has the material"
    assert "convention map" not in notes.split("security_map.md")[0], (
        "an earlier draft pointed at the convention map, which contains no `grant`"
    )


# --- Q-250 -----------------------------------------------------------------
APP_ENV_MUST_MATCH = [
    'os.getenv("APP_ENV", "prod")',
    "os.getenv('APP_ENV', 'prod')",
    'os.environ.get("APP_ENV", "prod")',
    "os.environ.get('APP_ENV', 'prod')",
    'environ.get("APP_ENV",  "prod")',
]
APP_ENV_MUST_NOT_MATCH = [
    'os.getenv("APP_ENV", "staging")',
    'os.environ.get("APP_ENV", "staging")',
    'os.environ["APP_ENV"]',
    'os.getenv("OTHER_ENV", "prod")',
]


@pytest.mark.parametrize("line", APP_ENV_MUST_MATCH)
def test_app_env_default_prod_catches_both_spellings(line):
    """`environ.get(` was invisible before Phase 215 — half the idiom.

    Measured 1,336 `environ.get(` vs 1,139 `getenv(` across 39,295 `.py` files,
    so the missing arm was the more common one in 4 of 5 corpora.
    """
    assert re.search(_check("python", "app-env-default-prod")["pattern"], line), line


@pytest.mark.parametrize("line", APP_ENV_MUST_NOT_MATCH)
def test_app_env_default_prod_is_strictly_additive(line):
    """The widening added an alternation arm and nothing else."""
    assert not re.search(_check("python", "app-env-default-prod")["pattern"], line), line


# --- Q-251 -----------------------------------------------------------------
# (line, is_a_real_finding). The bare-word negative was wrong on 2 of these 8.
WINDOW_OPEN_CASES = [
    ('window.open(u, "_blank", "noopener");', False),
    ('window.open(u, "_blank", "noopener,noreferrer");', False),
    ("window.open(u, '_blank', 'noopener')", False),
    ("window.open(u, `_blank`, `noopener`)", False),
    ('window.open(u, "_blank");', True),
    ("window.open(u);", True),
    # the two the bare word got wrong: the rule's own id contains `noopener`
    ('window.open(u, "_blank"); // see window-open-noopener', True),
    ('window.open(u, "_blank"); // TODO add noopener', True),
]


@pytest.mark.parametrize("line,is_finding", WINDOW_OPEN_CASES)
def test_window_open_noopener_requires_the_token_inside_a_string(line, is_finding):
    """`noopener` must sit in a string literal to clear a line.

    The bare word suppressed a real finding whenever the token appeared
    anywhere on the line — including in a comment naming this very rule, whose
    id *contains* the substring. That is a security check silently clearing
    itself on its own name.
    """
    c = _check("nextjs-react", "window-open-noopener")
    hit = re.search(c["pattern"], line) and not re.search(c["negative_pattern"], line)
    assert bool(hit) is is_finding, line


def test_window_open_noopener_stays_per_line_and_says_why():
    """File-level was measured WORSE and the reason is pinned, not remembered.

    `invert_file_check: true` reads a file of six deliberately-bad calls as
    CLEAN **under the bare negative the consumer still ships** — one match of
    the negative anywhere clears the whole file, and the rule's own id supplies
    it. (With the tightened negative below, file-level flags that file — but as
    ONE finding for six calls, and it still clears any file holding a single
    correct call. The CLEAN result belongs to the bare form; the
    one-good-call-clears-the-file defect belongs to file-level itself.) Trading a waivable false
    positive for a silent miss on a security check is the wrong direction.
    """
    c = _check("nextjs-react", "window-open-noopener")
    assert c.get("invert_file_check") is not True, (
        "window-open-noopener must stay per-line — see PHASE_LOG.md § Phase 215"
    )
    notes = c.get("notes", "")
    # BOTH directions, each pinned to its own sentence. The round found the
    # first cut's `"per-line" in notes` satisfied by an unrelated earlier
    # occurrence, and the note naming only the false-POSITIVE direction on a
    # check whose own argument is that a missed call is worse.
    assert "FALSE NEGATIVE:" in notes, (
        "the notes must name the false-negative direction, not only the cheap one"
    )
    assert notes.count("FALSE POSITIVE") >= 2, "both FP classes must be named"
    assert "Q-262" in notes, "the real fix (a per-call semgrep rule) must be routed"
    assert "self-selected" in notes, (
        "the 8/8 figure is the author's own matrix and the note must say so"
    )


# --- engine reality check --------------------------------------------------
@pytest.mark.parametrize("pack,cid", [
    ("postgres", "grant-sensitive-table"),
    ("python", "app-env-default-prod"),
    ("nextjs-react", "window-open-noopener"),
])
def test_patterns_are_posix_ere_executable(pack, cid, tmp_path):
    """`pattern` runs through shell `grep -E`, which Python `re` does not model.

    A pattern using a Python-only construct compiles fine above and then fails
    at runtime for every consumer. `grep` exits 0 on match, 1 on no match, and
    **2 on a bad pattern** — 2 is the failure this asserts against.
    """
    probe = tmp_path / "probe.txt"
    probe.write_text("nothing to match here\n", encoding="utf-8")
    r = subprocess.run(
        ["grep", "-rn", "-E", _check(pack, cid)["pattern"], str(probe)],
        capture_output=True, text=True,
    )
    assert r.returncode in (0, 1), (
        f"{cid}: grep -E rejected the pattern (rc={r.returncode}): {r.stderr.strip()}"
    )


def test_window_open_notes_state_where_the_waiver_goes():
    """A waiver instruction without a placement is inert for the wrapped case.

    `grep.py` waives only on the line the finding CITES. For a wrapped call
    that is the `window.open(` opening line, so the natural placement — the
    line above — waives nothing. Phase 215's round caught this note prescribing
    the remedy without saying where, for the exact case the note is about.
    """
    notes = _check("nextjs-react", "window-open-noopener").get("notes", "")
    assert "no-check: window-open-noopener" in notes
    assert "line the finding" in notes.lower() or "cites" in notes.lower()
    assert "above" in notes.lower(), (
        "the note must say the line ABOVE does not work — that is the whole finding"
    )


def test_the_matrix_sizes_match_what_the_record_claims():
    """The stated denominator must equal the list, in both directions.

    Phase 215's round found "22-case labelled matrix" written at five sites —
    one of them a shipped `notes:` block — pointing at a 16-case list, and a
    "seven deliberately-bad calls" figure at eight sites that was the
    pattern-match count rather than the call count (the seventh match is a
    header comment saying `window.opener`). Both are the wrong-population
    shape the phase's own record says it exists to catch. A number in prose
    drifts silently; this asserts it against the thing it counts.
    """
    grant_cases = len(GRANT_MUST_MATCH) + len(GRANT_MUST_NOT_MATCH)
    assert grant_cases == 16
    assert len(WINDOW_OPEN_CASES) == 8

    notes = _check("postgres", "grant-sensitive-table").get("notes", "")
    assert f"{grant_cases}-case" in notes, (
        f"the shipped notes claim a matrix size that is not {grant_cases}"
    )


@pytest.mark.parametrize("line,is_finding", [
    # exercises the RIGHT boundary `(?![-\w])` — without it this is cleared
    ('window.open(u, "_blank", "resizable,noopenerX");', True),
    # exercises the LEFT boundary `(?<![-\w])` independently of the backref:
    # a closed literal whose content is the rule id must NOT clear the call
    ('window.open(u, "window-open-noopener");', True),
])
def test_window_open_negative_boundaries_are_load_bearing(line, is_finding):
    """Each construct in the negative pattern earns its place.

    Phase 215's round mutated the lookbehind away and the character class to
    `.*` and both survived — the two shipped comment cases were being killed by
    the `\1` backref alone, so the boundaries had zero coverage. These cases
    fail if either boundary or the class is relaxed.
    """
    c = _check("nextjs-react", "window-open-noopener")
    hit = re.search(c["pattern"], line) and not re.search(c["negative_pattern"], line)
    assert bool(hit) is is_finding, line


def test_the_negative_pattern_does_not_backtrack_catastrophically():
    """`[^'"`\n]*` earns its place on backtracking, NOT on correctness.

    Phase 215's round mutated the class to `.*` and the mutation survived every
    behavioural guard — correctly, because on 10 realistic lines the two forms
    give identical answers. The construct is load-bearing for a different
    reason, and this is the guard that says which: with `.*` and the `\1`
    backref, an adversarial line (many quoted tokens, no closing match after
    the token) backtracks for ~1.9 SECONDS; the bounded class returns in under
    a millisecond. `grep.py` applies this per hit with no timeout of its own,
    so a minified bundle is a plausible source of such a line.

    Asserting the property rather than the literal: any negative pattern that
    finishes this in well under the (generous) budget is acceptable.
    """
    import time

    c = _check("nextjs-react", "window-open-noopener")
    evil = 'window.open(u, ' + '"x", ' * 4000 + 'noopener' + ' y' * 4000
    start = time.perf_counter()
    re.search(c["negative_pattern"], evil)
    elapsed = time.perf_counter() - start
    assert elapsed < 0.25, (
        f"negative_pattern took {elapsed:.3f}s on a {len(evil) // 1000}KB line — "
        "an unbounded `.*` before a backreference backtracks catastrophically"
    )

