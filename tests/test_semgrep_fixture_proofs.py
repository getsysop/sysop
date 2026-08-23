"""Every shipped semgrep rule is RUN against the fixtures it ships (Phase 217).

Until this module the fixtures were inert. `tests/test_semgrep_rule_authoring.py`
asserts a rule omits `paths:` — a property of the YAML — and
`tests/test_run_checks_semgrep.py` exercises the runner, but nothing executed a
rule against the `_positive.*` / `_negative.*` files sitting beside it. **Ten**
fixture pairs shipped, proving nothing. (This docstring said eight until the
review round counted them — in a module whose whole subject is a proof that
was never run.)

That gap has a cost this phase paid in full. Phase 217's new
`sql-fstring-multiline` rule was written with a `|` YAML block scalar on its
`pattern-regex`, which keeps the trailing newline and lands it INSIDE the regex
as a literal `\\n` after the final `\\b`. The rule then demanded a line break
immediately after the SQL keyword and matched nothing. `semgrep --validate`
reported it clean. It would have shipped present and inert — the exact shape the
author-side pass calls a guard that is wired but tests nothing — and no existing
test could have seen it.

**Both directions are asserted, and the negative one is the point.** A rule that
matches everything passes a positive-only proof. So a `_negative` fixture must
produce ZERO findings from its own rule, and those fixtures deliberately carry
the near misses: English prose beginning "Deleted", a plain docstring containing
`SELECT`, a safe `window.open` wrapped across lines, and a comment containing the
word `noopener`.

Skips when the semgrep binary is absent, which is the honest state for a
contributor who has not installed it — the same posture
`tests/test_run_checks_semgrep.py` takes.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    shutil.which("semgrep") is None,
    reason="semgrep binary not installed — optional for local work",
)


def _rule_files():
    """Every shipped rule file, derived by glob rather than listed.

    Same derivation as `test_semgrep_rule_authoring._shipped_rules`, and for the
    same reason: a new pack's rules are covered the day they land. Deriving the
    population from an index instead of the source of truth is the failure the
    author-side pass names by name.
    """
    roots = [REPO_ROOT / "packs", REPO_ROOT / "core" / "companion" / "semgrep"]
    out = []
    for root in roots:
        for suffix in ("yaml", "yml"):
            out += [
                p for p in root.rglob(f"*.{suffix}")
                if "fixtures" not in p.parts and p.parent.name == "semgrep"
            ]
    return sorted(set(out))


def _rule_ids(rule_file):
    """Every rule id declared inside one rule FILE.

    A file may declare several — `sql_fstring.yaml` ships `sql-fstring` and
    `sql-fstring-multiline`. That is why the polarity check below is keyed per
    ID rather than per file; see `_fixture_pairs`.
    """
    doc = yaml.safe_load(rule_file.read_text(encoding="utf-8")) or {}
    return [str(r.get("id", "")) for r in (doc.get("rules") or []) if r.get("id")]


def _fixture_pairs():
    """(rule_file, rule_id, polarity, fixture_path) for every fixture present.

    **Keyed per RULE ID, not per rule file, and that is the whole point.** The
    first cut asserted per file: "running this YAML against its positive fixture
    finds something". That is satisfied by an *incidental* finding from a sibling
    rule in the same file — the "a check satisfied by a substring is satisfied by
    an incidental use of that substring" failure, one level up. Measured by this
    phase's own mutation battery: reintroducing the `|` block-scalar bug that
    makes `sql-fstring-multiline` inert **SURVIVED** the per-file form, because
    `sql-fstring` still fired three times in the same fixture. Per id, the same
    mutation is killed.

    Keyed off the rule FILE stem for the fixture name, which is the shipped
    naming convention (`sql_fstring.yaml` -> `fixtures/sql_fstring_positive.py`).
    """
    out = []
    for rule in _rule_files():
        fixdir = rule.parent / "fixtures"
        if not fixdir.is_dir():
            continue
        for polarity in ("positive", "negative"):
            for h in sorted(fixdir.glob(f"{rule.stem}_{polarity}.*")):
                for rid in _rule_ids(rule):
                    out.append((rule, rid, polarity, h))
    return out


# Tolerant of the trailing prose the shipped fixtures carry
# (`// ruleid: missing-fetch-redirect — one-arg fetch`). The first cut
# end-anchored the id list and so matched none of them, which read as "these
# fixtures are un-annotated" — over-strictness pretending to be a finding.
_ANNOT = re.compile(r"^\s*(?://|#)\s*ruleid:\s*(?P<ids>[^\u2014\n]*)")


def _annotation_windows(fixture, rule_id):
    '''Windows a fixture declares MUST contain a finding for `rule_id`.

    Returns a list of `(start_line, end_line)` 1-indexed inclusive spans: one
    per `ruleid:` annotation, running from the annotation to just before the
    next annotation (or end of file).

    **A window, not the next line.** The annotation marks the next FINDING, not
    the next line of code, and the shipped fixtures rely on that: one of them
    puts `const slug = "some-slug";` between the annotation and the `fetch(...)`
    it refers to. A next-line rule reported that as a miss — over-strictness on
    nine fixtures this change never touched, which is exactly the direction that
    gets a guard weakened rather than fixed.

    Empty when the fixture declares nothing for this rule, so an un-annotated
    fixture degrades to the weaker `assert mine`; the debt is named by
    `test_positive_fixtures_declare_their_expected_lines` rather than hidden.
    '''
    lines = fixture.read_text(encoding="utf-8").splitlines()
    marks = []
    for i, line in enumerate(lines):
        m = _ANNOT.match(line)
        if m:
            raw = m.group("ids").split(" - ")[0]
            ids = {x.strip() for x in raw.replace(",", " ").split()}
            marks.append((i + 1, ids))
    out = []
    for k, (ln, ids) in enumerate(marks):
        if rule_id not in ids:
            continue
        end = marks[k + 1][0] - 1 if k + 1 < len(marks) else len(lines)
        out.append((ln, end))
    return out


def _run(rule, target):
    """Findings for one rule file against one path, as a list of dicts.

    `check_id` in semgrep's JSON is the config path plus the rule id joined by
    dots, so the rule id is its last dotted component.
    """
    proc = subprocess.run(
        ["semgrep", "--config", str(rule), "--json", "--quiet",
         "--no-git-ignore", str(target)],
        capture_output=True, text=True, timeout=180,
    )
    assert proc.stdout.strip(), (
        f"semgrep produced no JSON for {rule.name} on {target.name}; "
        f"stderr:\n{proc.stderr[-2000:]}"
    )
    return json.loads(proc.stdout).get("results", [])


# The populations, asserted EXACTLY and per pack. A `>=` floor set below the real
# count is not a control: the round dropped `packs/python`'s three rules out of
# the glob entirely and both floors still passed, so all four semgrep tests
# stopped covering a whole pack with nothing red. `p.parent.name == "semgrep"` is
# the only locator, so any pack that nests rules one level deeper vanishes the
# same silent way. Update these deliberately when a rule lands.
EXPECTED_RULE_FILES = 11
EXPECTED_FIXTURE_PAIRS = 24
EXPECTED_PACKS = {"llm", "nextjs-react", "postgres", "python"}


def test_the_rule_population_is_exactly_what_ships():
    files = _rule_files()
    assert len(files) == EXPECTED_RULE_FILES, (
        f"expected {EXPECTED_RULE_FILES} shipped rule files, found {len(files)}: "
        f"{[str(f.relative_to(REPO_ROOT)) for f in files]}. If a rule landed or "
        f"moved, update the constant; if this dropped, a pack has silently "
        f"stopped being proven."
    )


def test_every_pack_with_rules_is_represented():
    """Per pack, so losing one pack cannot hide inside a total."""
    seen = {f.parts[f.parts.index("packs") + 1] for f in _rule_files()
            if "packs" in f.parts}
    assert seen == EXPECTED_PACKS, f"packs covered: {sorted(seen)}"


def test_the_fixture_population_is_exactly_what_ships():
    pairs = _fixture_pairs()
    assert len(pairs) == EXPECTED_FIXTURE_PAIRS, (
        f"expected {EXPECTED_FIXTURE_PAIRS} (rule, id, polarity, fixture) "
        f"tuples, found {len(pairs)}"
    )


def test_a_multi_rule_file_yields_one_pair_per_rule_id():
    """The module's flagship property, which had no guard at all.

    `_fixture_pairs` keys per rule ID; its docstring calls that "the whole
    point". The round reverted it to per-file AND reintroduced the block-scalar
    bug together, and the suite stayed green — the exact defect this module
    exists to catch, returning the moment someone "simplifies" the keying.
    """
    multi = [f for f in _rule_files() if len(_rule_ids(f)) > 1]
    assert multi, "no multi-rule file ships; this guard has no population"
    for f in multi:
        ids = set(_rule_ids(f))
        for polarity in ("positive", "negative"):
            covered = {rid for (r, rid, pol, _fx) in _fixture_pairs()
                       if r == f and pol == polarity}
            assert covered == ids, (
                f"{f.name} declares {sorted(ids)} but only {sorted(covered)} are "
                f"proven against its {polarity} fixture — the keying has "
                f"collapsed to per-file and an inert rule is now invisible"
            )


# Positive fixtures with no `ruleid:` declaration fall back to the weaker
# "found something" assertion. Named rather than left silent; this one is
# pre-existing and was not authored by the phase that added this module.
UNANNOTATED_POSITIVE_DEBT = {
    ("abort_error_setstate.yaml", "abort-error-setstate"),
}


def test_positive_fixtures_declare_their_expected_cases():
    missing = set()
    for rule, rid, polarity, fixture in _fixture_pairs():
        if polarity == "positive" and not _annotation_windows(fixture, rid):
            missing.add((rule.name, rid))
    assert missing == UNANNOTATED_POSITIVE_DEBT, (
        f"un-annotated positive fixtures: {sorted(missing)}. A new rule must "
        f"declare which cases it expects to fire (`ruleid: <id>` above each), or "
        f"it is only proven to match something. Do not grow this set."
    )


@pytest.mark.parametrize("rule", _rule_files(), ids=lambda p: p.stem)
def test_every_rule_file_ships_both_fixtures(rule):
    """A rule with no fixtures cannot be proven, so it may not ship without them."""
    fixdir = rule.parent / "fixtures"
    for polarity in ("positive", "negative"):
        assert sorted(fixdir.glob(f"{rule.stem}_{polarity}.*")), (
            f"{rule.relative_to(REPO_ROOT)} ships no {polarity} fixture. "
            f"Expected {fixdir.name}/{rule.stem}_{polarity}.<ext>."
        )


@pytest.mark.parametrize(
    "rule,rule_id,polarity,fixture",
    _fixture_pairs(),
    ids=lambda v: v.stem if isinstance(v, Path) else str(v),
)
def test_fixture_polarity_holds(rule, rule_id, polarity, fixture):
    """A positive fixture must fire EACH rule id; a negative must silence all.

    The negative direction is what makes this more than a smoke test: a rule
    broadened until it matches everything passes a positive-only proof, and
    over-strictness — the direction the author-side pass calls the one that
    hides — is what the positive direction catches.
    """
    mine = [
        r for r in _run(rule, fixture)
        if str(r.get("check_id", "")).split(".")[-1] == rule_id
    ]
    if polarity == "positive":
        # Per ANNOTATED LINE where the fixture declares which lines must fire.
        # `assert mine` alone only proves the rule matches SOMETHING: the round
        # narrowed rules seven different ways — dropping the single-quoted
        # triple-quote arm, dropping case-insensitivity, dropping five of six
        # SQL keywords, deleting two of four `window.open` arities — and every
        # one survived, because one surviving shape kept the list non-empty.
        # The `ruleid:` convention is already the repo's; these two fixtures
        # were the first to ship without it.
        windows = _annotation_windows(fixture, rule_id)
        if windows:
            got = sorted(r["start"]["line"] for r in mine)
            empty = [w for w in windows if not any(w[0] <= g <= w[1] for g in got)]
            assert not empty, (
                f"{fixture.relative_to(REPO_ROOT)} declares `ruleid: {rule_id}` "
                f"for the case(s) at line(s) {[w[0] for w in empty]} and the rule "
                f"fired nowhere in them. Fired on {got}. A rule narrowed until it "
                f"matches only SOME of its own declared cases still passes a bare "
                f"'found something' assertion — which is why this is per case."
            )
        assert mine, (
            f"{fixture.relative_to(REPO_ROOT)} is a POSITIVE fixture but rule "
            f"`{rule_id}` ({rule.name}) found nothing in it. A rule that matches "
            f"nothing validates clean and gates nothing — see this module's "
            f"docstring for the `|` vs `|-` block-scalar failure that produced "
            f"exactly this state. Note this is asserted PER RULE ID: a sibling "
            f"rule in the same file firing does not prove this one runs."
        )
    else:
        assert not mine, (
            f"{fixture.relative_to(REPO_ROOT)} is a NEGATIVE fixture but rule "
            f"`{rule_id}` reported {len(mine)} finding(s) at line(s) "
            f"{[r['start']['line'] for r in mine]}. Every line in a negative "
            f"fixture is a shape the rule must NOT flag."
        )


def test_every_rule_id_has_a_registry_stub():
    """Each rule id must have a `semgrep-<id>` entry in some pack fragment.

    `run_checks/semgrep.py` builds its check id as `f"semgrep-{rule_id}"`, so a
    rule whose stub is missing produces findings the registry cannot route. This
    is derived from the rule files rather than listed, so adding a second rule to
    an existing YAML — which is what Phase 217 did to `sql_fstring.yaml` — cannot
    silently skip registration.
    """
    # Scoped to the shipped roots, NOT `REPO_ROOT.rglob`. The first cut globbed
    # the whole repo and found 40 fragments here — 35 of them stale copies inside
    # `.claude/worktrees/`, where review agents run. A stub deleted from the real
    # fragment was therefore still "found", in a checkout nobody ships, and the
    # guard passed. The author-side battery caught it only after the worktrees
    # existed, which is luck: on a clean clone the mutation is killed and on a
    # maintainer's machine mid-round it is not. Same roots as `_rule_files()`.
    stubs = set()
    for root in (REPO_ROOT / "packs", REPO_ROOT / "core"):
        for frag in root.rglob("checks.yml.fragment"):
            doc = yaml.safe_load(frag.read_text(encoding="utf-8")) or {}
            for check in doc.get("checks") or []:
                cid = str(check.get("id", ""))
                if cid.startswith("semgrep-"):
                    stubs.add(cid)

    missing = []
    for rule_file in _rule_files():
        doc = yaml.safe_load(rule_file.read_text(encoding="utf-8")) or {}
        for rule in doc.get("rules") or []:
            rid = str(rule.get("id", ""))
            if rid and f"semgrep-{rid}" not in stubs:
                missing.append(f"{rule_file.name}:{rid} -> semgrep-{rid}")
    assert not missing, (
        "semgrep rule(s) with no registry stub — findings would be unroutable:\n  "
        + "\n  ".join(missing)
    )


def test_no_guard_population_reaches_into_a_worktree():
    """Control for the population bug the battery found, in both directions.

    `.claude/worktrees/` holds full checkouts while review agents run, so any
    guard that globs from the repo root reads 8x the shipped tree and can be
    satisfied by a stale copy. This asserts BOTH derivations in this module are
    scoped, and it is written to be meaningful even on a clean clone where no
    worktrees exist — it checks the paths, not the count.
    """
    for p in _rule_files():
        assert ".claude" not in p.parts, p
    for root in (REPO_ROOT / "packs", REPO_ROOT / "core"):
        for frag in root.rglob("checks.yml.fragment"):
            assert ".claude" not in frag.parts, frag
