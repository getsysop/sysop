"""Phase 172 — a shipped grep check may not anchor on ONE quote style.

WHAT THIS CLASS IS
------------------
Every check in a `checks.yml.fragment` is a regex run over source. Python, JS/TS and
SQL all accept `'` and `"` interchangeably, so a pattern that hard-codes one of them
matches half its own subject and reports a clean zero over the other half. The failure
is silent in both directions the runner offers:

  - A `pattern:` that misses simply produces no finding. `sql-fstring` is
    `severity: critical` and missed every single-quoted SQL f-string in every python /
    postgres consumer — and the single-quoted form is not an edge case, it is what you
    reach for when the statement embeds `"quoted identifiers"`, i.e. exactly the
    interpolated-identifier shape the check exists to catch.
  - A `position_check:` that misses is worse, because `_run_position_check` skips the
    whole FILE when either regex fails to match. `test-app-env-before-syspath`'s
    `earlier` was double-quote-only; measured against one real corpus, 59 of the 182
    test files it was scoped to used the single-quoted form exclusively, so the
    ordering invariant was never evaluated on a third of its own population.

Upstream #235 filed two sites. The class sweep that produced this guard found three in
the fragments plus a fourth in `WORKFLOW.md`'s § 6.5 format example — the doc that
teaches the shape.

WHY THE GUARD IS SHAPED THIS WAY
--------------------------------
1. **Zero-invariant over the whole registry, not three pinned sites.** The population is
   every pattern-bearing field in every shipped fragment; the assertion is `== 0`. A
   guard naming `sql-fstring` would pass the day someone adds a fourth site.
2. **The predicate is exercised in both directions.** `bare_quote_literals` has negative
   controls (a both-quotes character class, a backtick, a quote-free pattern) and
   positive ones (the pre-fix regexes, verbatim). A guard that only ever sees clean
   input cannot be shown to detect anything.
3. **The escape hatch is pinned empty.** A pattern over a format where only one quote is
   legal (JSON keys) would be a legitimate exemption. `_EXEMPT` is the only cheap way to
   silence this guard, so it is pinned — adding a member is a visible diff that has to
   argue for itself.
4. **Section 2 executes the shipped patterns.** Reading a regex and believing it matches
   is how this class shipped. These tests load the real fragments, build a fixture from
   the forms real writers emit in BOTH quote styles, and run the real `run_check`
   (`_shared/adversarial-review.md` § *Before you spawn anyone*, rule 3).
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

import pytest
import yaml

from run_checks.grep import run_check
from tests import shape_lib as S

FRAGMENTS = sorted(
    [S.REPO_ROOT / "core" / "companion" / "checks.yml.fragment"]
    + list((S.REPO_ROOT / "packs").glob("*/companion/checks.yml.fragment"))
)

# Pattern-bearing fields a check may carry. `position_check` is nested, so it is
# flattened to `position_check.earlier` / `.later` by `_pattern_fields`.
_SCALAR_FIELDS = ("pattern", "negative_pattern")
_POSITION_FIELDS = ("earlier", "later")

# Legitimate single-quote-style anchors, if any ever exist: a pattern over a format
# where only one quote character is legal (a JSON object key, say) is correctly
# written with a bare `"`. EMPTY today. Each entry is `(check_id, field)` and must
# carry a comment naming the format that forbids the other quote. The hatch is
# guarded two ways rather than by pinning it empty (see the tests below): an entry
# must name a real field, and that field must actually be flagged — so a stale
# exemption fails loudly instead of silently covering nothing.
_EXEMPT: frozenset[tuple[str, str]] = frozenset()


def anchored_quote_style(regex: str) -> str | None:
    """The single quote style `regex` anchors on, or None if it is quote-agnostic.

    The rule is deliberately about *mention*, not about syntax: a regex that names
    only `"` (or only `'`) anchors on that style; one that names both has had the
    question put to it, however the author chose to express the answer.

    THIS REPLACED A HAND-ROLLED BRACKET SCANNER, and the reason is the point. The
    scanner only recognised agnosticism written as one character class holding both
    quotes, so it reported FALSE POSITIVES on four correct idioms a maintainer could
    reasonably write — `(?:"|')(SELECT)`, `[[:alnum:]"']` (it exited the bracket at
    the `]` closing `[:alnum:]`, so both quotes read as outside any class),
    `f["](S)|f['](S)`, and `("|')prod\\1`. Over-strictness is the direction that
    hides: a guard that reds on a legitimate rewrite gets weakened or deleted, and
    this one also reddened its own escape hatch. The mention rule has no bracket
    parsing at all, so none of that class exists.

    Backticks are never reported. A JS template literal has no single/double-quote
    form, so `fetch\\(`` is not a member of this class; widening it would be a scope
    change, not a fix.

    KNOWN LIMIT, stated rather than left implied: a pattern that mentions both
    styles but anchors them MISMATCHED — `getenv\\(["]APP_ENV["],\\s*[']prod[']\\)` —
    reads as agnostic here. That is a rarer authoring error than the idioms above,
    and trading a rare false negative for a whole class of false positives is the
    trade this predicate makes on purpose.
    """
    present = {ch for ch in regex if ch in "\"'"}
    return present.pop() if len(present) == 1 else None


def _pattern_fields() -> list[tuple[str, str, str, str]]:
    """`(fragment_name, check_id, field, regex)` for every shipped pattern."""
    rows = []
    for frag in FRAGMENTS:
        data = yaml.safe_load(frag.read_text(encoding="utf-8")) or {}
        for check in data.get("checks") or []:
            cid = check.get("id", "?")
            for field in _SCALAR_FIELDS:
                if check.get(field):
                    rows.append((frag.parent.parent.name, cid, field, check[field]))
            for field in _POSITION_FIELDS:
                value = (check.get("position_check") or {}).get(field)
                if value:
                    rows.append(
                        (frag.parent.parent.name, cid, f"position_check.{field}", value)
                    )
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
# 1. The invariant
# ═══════════════════════════════════════════════════════════════════════════════


def _offenders(rows) -> list[str]:
    """The invariant's decision, factored out so the floor below runs the REAL one.

    A floor that re-implements the comprehension inline cannot fail for any change
    to the shipped one — the trap `tests/test_phantom_shell_vars.py` names as its
    property 2.
    """
    return [
        f"{pack}/{cid}.{field}: {regex!r} → anchors on {style}"
        for pack, cid, field, regex in rows
        if (style := anchored_quote_style(regex)) and (cid, field) not in _EXEMPT
    ]


def test_no_shipped_pattern_anchors_on_one_quote_style():
    offenders = _offenders(_pattern_fields())
    assert offenders == [], (
        "A grep check anchored on one quote style scans half its subject and reports "
        "the other half clean:\n  " + "\n  ".join(offenders)
    )


# ── the detection floor ───────────────────────────────────────────────────────
#
# The assertion above is `== []`, which is exactly as true when it is scanning
# nothing, when `_offenders` returns a truncated list, and when the population is
# empty. Reverting one of the phase's own three fixes reds it — but that only shows
# it is live TODAY against a site that already exists. The round found five separate
# mutations (`and False`, `offenders[:0]`, inverting the `_EXEMPT` test, swapping the
# key to `(field, cid)`, keying on `(cid,)`) that made it permanently vacuous with
# the suite green. So the floor PLANTS known-bad rows and requires each to be caught.


_PLANTED = [
    ("postgres", "planted-a", "pattern", 'f"(SELECT|INSERT)'),
    ("python", "planted-b", "pattern", 'getenv\\("APP_ENV",\\s*"prod"\\)'),
    ("python", "planted-c", "position_check.earlier", "setdefault\\(\"APP_ENV\""),
    ("core", "planted-d", "negative_pattern", "'staging'"),
    ("nextjs-react", "planted-e", "pattern", '["]live["]'),
]


@pytest.mark.parametrize("row", _PLANTED, ids=lambda r: r[1])
def test_floor_every_planted_violation_is_detected(row):
    """Detection, not complaint-counting: each plant must reach `_offenders`."""
    assert len(_offenders([row])) == 1, row


def test_floor_planted_violations_survive_the_real_population():
    """…and must still be caught when mixed into the live rows, not just alone."""
    mixed = _pattern_fields() + _PLANTED
    assert len(_offenders(mixed)) == len(_PLANTED)


def test_floor_a_clean_row_is_not_detected():
    """The other direction — the floor must not pass by flagging everything."""
    assert _offenders([("postgres", "clean", "pattern", "f['\"](SELECT)")]) == []


# ── the escape hatch, guarded rather than frozen ───────────────────────────────
#
# Pinning `_EXEMPT == frozenset()` reddened the hatch the moment anyone used it,
# which is a guard that punishes its own documented procedure. These two pin what
# actually matters: an entry must name a REAL field, and that field must actually
# be flagged — so a stale or misspelled exemption fails instead of silently
# covering nothing, and the `(check_id, field)` key order is load-bearing.


def test_every_exemption_names_a_real_field():
    known = {(cid, field) for _, cid, field, _ in _pattern_fields()}
    assert set(_EXEMPT) <= known, set(_EXEMPT) - known


def test_every_exemption_covers_a_pattern_that_is_actually_flagged():
    stale = [
        (cid, field)
        for _, cid, field, regex in _pattern_fields()
        if (cid, field) in _EXEMPT and not anchored_quote_style(regex)
    ]
    assert stale == [], f"exemptions covering nothing: {stale}"


def test_exempt_key_order_is_check_id_then_field():
    """Swapping the key to `(field, cid)` silently exempts nothing — pin the shape."""
    probe = [("postgres", "probe-id", "pattern", 'f"(SELECT)')]
    assert len(_offenders(probe)) == 1
    import unittest.mock as _mock
    with _mock.patch(f"{__name__}._EXEMPT", frozenset({("probe-id", "pattern")})):
        assert _offenders(probe) == []
    with _mock.patch(f"{__name__}._EXEMPT", frozenset({("pattern", "probe-id")})):
        assert len(_offenders(probe)) == 1


# ── vacuity twins: the invariant above must be scanning something ──────────────


def test_population_matches_what_the_installer_concatenates():
    """Derive the population from the source of truth, not from the test's own glob.

    `install.sh` assembles `.claude/checks.yml` from the core fragment plus one per
    selected pack; if a pack ships a fragment this module's glob cannot see, the
    invariant silently stops covering it.
    """
    shipped = {p for p in (S.REPO_ROOT / "packs").glob("*/companion/checks.yml.fragment")}
    shipped.add(S.REPO_ROOT / "core" / "companion" / "checks.yml.fragment")
    assert set(FRAGMENTS) == shipped, set(FRAGMENTS) ^ shipped
    assert all(p.exists() for p in FRAGMENTS)


def test_population_covers_every_shipped_fragment():
    assert len(FRAGMENTS) == 5, FRAGMENTS
    packs = {row[0] for row in _pattern_fields()}
    assert packs == {"core", "python", "postgres", "nextjs-react"}, packs


def test_no_pattern_bearing_check_escapes_the_sweep():
    """DERIVED, not a magic number — the property is "nothing escapes".

    `>= 25` was lowerable to 1, and a mutation narrowing the sweep to drop every
    `severity: critical` check — i.e. `sql-fstring` itself — walked through it. An
    exact count kills those but reddens on any legitimate new check, which is a
    guard that punishes ordinary work. So this re-derives the expected set from the
    fragments independently and compares, which has no number to edit and no
    tolerance for a check going missing.

    The duplicated extraction below is DELIBERATE and is the one place in this
    module where re-implementing is right: it is a differential control, so a
    narrowing added to `_pattern_fields` (a severity filter, a dropped field, a
    skipped fragment) shows up as a set difference. Elsewhere — `_offenders` — the
    guard calls the production predicate for the opposite reason.
    """
    expected = set()
    for frag in FRAGMENTS:
        data = yaml.safe_load(frag.read_text(encoding="utf-8")) or {}
        for check in data.get("checks") or []:
            cid = check.get("id", "?")
            for field in ("pattern", "negative_pattern"):
                if check.get(field):
                    expected.add((cid, field))
            for field in ("earlier", "later"):
                if (check.get("position_check") or {}).get(field):
                    expected.add((cid, f"position_check.{field}"))
    actual = {(cid, field) for _, cid, field, _ in _pattern_fields()}
    assert actual == expected, expected ^ actual
    assert expected, "no pattern-bearing field found at all — the sweep is vacuous"
    # …and the three sites this phase fixed are inside it, by name.
    assert ("sql-fstring", "pattern") in actual
    assert ("app-env-default-prod", "pattern") in actual
    assert ("test-app-env-before-syspath", "position_check.earlier") in actual
    assert any(f == "negative_pattern" for _, f in actual)


# ── predicate negative + positive controls ────────────────────────────────────


@pytest.mark.parametrize(
    "regex",
    [
        "f['\"](SELECT|INSERT)",                       # the shipped fix
        'APP_ENV.*(==|!=).*["\']prod["\']',            # the pre-existing sibling
        "ROW_NUMBER\\(\\)",                            # no quotes at all
        "fetch\\(`",                                   # backtick: no quote-style twin
        "logger\\.(debug|info)\\(f['\"]",
        "[^\"']+",                                     # negated class holding both
        # The four the round proved were FALSE POSITIVES under the old scanner.
        # Every one is a correct way to write a quote-agnostic pattern.
        '(?:"|\')(SELECT)',                            # alternation, not a class
        '[[:alnum:]"\']',                              # POSIX class inside the bracket
        'f["](S)|f[\'](S)',                            # two classes, one per branch
        '("|\')prod\\1',                               # backreference
    ],
)
def test_predicate_accepts_quote_agnostic_patterns(regex):
    """Over-strictness is the direction that hides — these must NOT be flagged."""
    assert anchored_quote_style(regex) is None, regex


@pytest.mark.parametrize(
    "regex",
    [
        'f"(SELECT|INSERT|UPDATE|DELETE|ALTER|DROP)',   # sql-fstring, pre-fix
        'getenv\\("APP_ENV",\\s*"prod"\\)',             # app-env-default-prod, pre-fix
        'os\\.environ\\.setdefault\\("APP_ENV"',        # position_check.earlier, pre-fix
        "sql = '",                                      # bare single quote
        '["]prod["]',                                   # class holding only one style
        '\\["]',                                        # escaped bracket, then a quote
        '[\\]"]',                                       # literal ] member, then a quote
        '\\"prod\\"',                                   # ESCAPED quotes still anchor
        "\\'prod\\'",
    ],
)
def test_predicate_flags_single_quote_style_patterns(regex):
    assert anchored_quote_style(regex) is not None, regex


def test_predicate_reports_which_style_it_found():
    assert anchored_quote_style('f"(SELECT)') == '"'
    assert anchored_quote_style("sql = '") == "'"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. The shipped patterns, executed
# ═══════════════════════════════════════════════════════════════════════════════
#
# Section 1 reads regexes. This section runs them, because "the regex looks right"
# is precisely the reading that shipped the defect. Every check dict comes from the
# shipped fragment verbatim — only `paths:` is localized onto the fixture, which is
# what the installer does for a real consumer.


def _shipped_check(check_id: str) -> dict:
    for frag in FRAGMENTS:
        data = yaml.safe_load(frag.read_text(encoding="utf-8")) or {}
        for check in data.get("checks") or []:
            if check.get("id") == check_id:
                return dict(check)
    raise AssertionError(f"{check_id} is not in any shipped fragment")


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    """Both quote styles of each form, written the way real code writes them."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "queries.py").write_text(
        textwrap.dedent(
            '''\
            double = f"SELECT * FROM {table}"
            single = f'SELECT COUNT(*) FROM "{table}";'
            raw_single = rf'DROP DATABASE IF EXISTS "{db}";'
            env_double = os.getenv("APP_ENV", "prod")
            env_single = os.getenv('APP_ENV', 'prod')
            '''
        )
    )
    tests_dir = tmp_path / "t"
    tests_dir.mkdir()
    (tests_dir / "test_double.py").write_text(
        'import sys\nsys.path.insert(0, ".")\nos.environ.setdefault("APP_ENV", "test")\n'
    )
    (tests_dir / "test_single.py").write_text(
        "import sys\nsys.path.insert(0, '.')\nos.environ.setdefault('APP_ENV', 'test')\n"
    )
    return tmp_path


def _run(check_id: str, root: Path, paths: list[str]) -> dict[str, str]:
    """`{file_line: the source line it cites}` — keyed by line, valued by CONTENT.

    Asserting on line numbers alone is how the first version of these tests went
    vacuous: gut the fixture's single-quoted forms and every `":2" in hits` still
    passed, because line 2 still existed and still matched in the *other* style.
    The assertions below read what actually matched.
    """
    check = _shipped_check(check_id)
    check["paths"] = paths
    check.pop("exclude", None)  # the fixture names files `test_*` on purpose
    out = {}
    for _, file_line, _ in run_check(check, str(root)):
        path, _, lineno = file_line.rpartition(":")
        out[file_line] = (root / path).read_text().splitlines()[int(lineno) - 1]
    return out


def test_fixture_carries_both_quote_styles_of_every_form(corpus):
    """Vacuity twin: a fixture quietly normalised to one style proves nothing."""
    queries = (corpus / "src" / "queries.py").read_text()
    for form in ('f"SELECT', "f'SELECT", 'getenv("APP_ENV"', "getenv('APP_ENV'"):
        assert form in queries, form
    assert 'setdefault("APP_ENV"' in (corpus / "t" / "test_double.py").read_text()
    assert "setdefault('APP_ENV'" in (corpus / "t" / "test_single.py").read_text()
    # The embedded-identifier shape is not decoration — it is the whole reason the
    # single-quoted form matters (you reach for `'` when the SQL contains `"…"`).
    # Pinning only the `f'SELECT` prefix let a mutation replace this line with a
    # plain `f'SELECT COUNT(*) FROM t'` and stay green.
    assert '''f'SELECT COUNT(*) FROM "{table}";' ''' .strip() in queries
    assert '''rf'DROP DATABASE IF EXISTS "{db}";' ''' .strip() in queries


def test_sql_fstring_fires_on_both_quote_styles(corpus):
    hits = _run("sql-fstring", corpus, ["src/"])
    matched = "\n".join(hits.values())
    assert 'f"SELECT' in matched, "double-quoted f-string SQL (the old behaviour)"
    assert "f'SELECT" in matched, "single-quoted f-string SQL embedding identifiers"
    assert "rf'DROP" in matched, "rf'' prefix form"
    assert set(hits) == {f"src/queries.py:{n}" for n in (1, 2, 3)}


def test_app_env_default_prod_fires_on_both_quote_styles(corpus):
    hits = _run("app-env-default-prod", corpus, ["src/"])
    matched = "\n".join(hits.values())
    assert 'getenv("APP_ENV", "prod")' in matched
    assert "getenv('APP_ENV', 'prod')" in matched


def test_position_check_evaluates_single_quoted_files(corpus):
    """The failure here is a skipped FILE, not a missed line — assert both are judged."""
    hits = _run("test-app-env-before-syspath", corpus, ["t/"])
    assert set(hits) == {"t/test_double.py:2", "t/test_single.py:2"}
    assert all("sys.path.insert" in line for line in hits.values())


def test_widening_is_strictly_additive(corpus):
    """Old ⊂ new: nothing the pre-fix regexes caught may have been dropped.

    Re-derived rather than adopted from the filing — measured on a real corpus at
    fix time as 21→33 / 4→5 / 123→182 file hits with zero lost in all three.
    """
    for check_id, paths, old_pattern in (
        ("sql-fstring", ["src/"], 'f"(SELECT|INSERT|UPDATE|DELETE|ALTER|DROP)'),
        ("app-env-default-prod", ["src/"], 'getenv\\("APP_ENV",\\s*"prod"\\)'),
    ):
        new_hits = set(_run(check_id, corpus, paths).keys())
        old_check = _shipped_check(check_id)
        old_check["paths"] = paths
        old_check["pattern"] = old_pattern
        old_check.pop("exclude", None)
        old_hits = {fl for _, fl, _ in run_check(old_check, str(corpus))}
        assert old_hits, f"{check_id}: pre-fix control matched nothing — vacuous"
        assert old_hits <= new_hits, f"{check_id} lost {old_hits - new_hits}"
        assert new_hits > old_hits, f"{check_id} did not widen"


_WORKFLOW = S.REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md"
_DOC_PATTERN_RE = re.compile(
    r"^\s*(pattern|negative_pattern|earlier|later):\s*(.+?)\s*(?:#.*)?$", re.M
)


def _workflow_pattern_examples() -> list[tuple[str, str]]:
    """`(field, regex)` for every pattern-shaped line in WORKFLOW.md's examples.

    The YAML scalar is unwrapped the way `yaml.safe_load` would, so `''` collapses
    to one `'` and the doc example is compared as the regex a consumer would get.
    """
    out = []
    for field, raw in _DOC_PATTERN_RE.findall(_WORKFLOW.read_text(encoding="utf-8")):
        raw = raw.strip()
        if len(raw) >= 2 and raw[0] == raw[-1] == "'":
            out.append((field, raw[1:-1].replace("''", "'")))
        elif len(raw) >= 2 and raw[0] == raw[-1] == '"':
            out.append((field, raw[1:-1]))
    return out


def test_workflow_examples_never_teach_a_single_quote_style_anchor():
    """§ 6.5's example is the doc that licenses the belief — Phase 165's class.

    Swept as a class, not pinned as one literal line: the first version asserted
    one string was present and one absent, which is the exact failure this module's
    own docstring disclaims — it passed the day someone added a FIFTH bad example.
    """
    examples = _workflow_pattern_examples()
    assert len(examples) >= 4, examples
    offenders = [
        f"{field}: {regex!r} → anchors on {style}"
        for field, regex in examples
        if (style := anchored_quote_style(regex))
    ]
    assert offenders == [], (
        "WORKFLOW.md § 6.5 teaches consumers how to write a check — an example that "
        "anchors on one quote style ships the defect to everyone who copies it:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize(
    "line,expected",
    [
        ("    pattern: 'f\"(SELECT)'", ("pattern", 'f"(SELECT)')),
        ("    negative_pattern: '\"staging\"'", ("negative_pattern", '"staging"')),
        ("      earlier: 'setdefault(\"APP_ENV\"'", ("earlier", 'setdefault("APP_ENV"')),
        ("    pattern: 'f[''\"](SELECT)'   # trailing comment",
         ("pattern", "f['\"](SELECT)")),
    ],
)
def test_workflow_extractor_reads_a_pattern_line(line, expected):
    """Floor for the sweep: the extractor must SEE the shapes, not just find none.

    A sweep whose regex matches nothing reports a clean doc forever. Each case here
    is a line the doc could plausibly grow; the last also pins that a trailing
    comment does not end up inside the extracted regex and that YAML's `''` is
    unwrapped to one quote before the predicate sees it.
    """
    assert _DOC_PATTERN_RE.findall(line + "\n"), line
    field, raw = _DOC_PATTERN_RE.findall(line + "\n")[0]
    raw = raw.strip()
    unwrapped = raw[1:-1].replace("''", "'") if raw[0] == "'" else raw[1:-1]
    assert (field, unwrapped) == expected


def test_workflow_sweep_flags_a_planted_bad_example():
    """…and the predicate must then flag the bad ones and clear the good one."""
    assert anchored_quote_style('f"(SELECT)') == '"'
    assert anchored_quote_style('"staging"') == '"'
    assert anchored_quote_style('setdefault("APP_ENV"') == '"'
    assert anchored_quote_style("f['\"](SELECT)") is None


def test_workflow_still_shows_the_sql_fstring_example():
    """The sweep is satisfied by deleting every example — keep the teaching one."""
    assert ("pattern", "f['\"](SELECT|INSERT|UPDATE|DELETE)") in _workflow_pattern_examples()
