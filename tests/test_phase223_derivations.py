"""Every number Phase 223 published is derived, and this fails when prose drifts.

Phase 221's rule, in the form it applies here: a number quoted from an
uncommitted extraction cannot be checked by anyone, ever. `Q-128`'s whole product
is numbers, and they are published in `docs/configuration.md`, which is
public-facing — the most expensive place in the tree to be wrong. So the
derivation is `tools/phase223_role_census.py` and this module fails when the two
disagree.

`tools/` is mirror-excluded (`tools/make_public_mirror.sh`, pinned by
`tests/test_mirror_leak_gate.py`), so these skip rather than fail where the
modules are absent — the accommodation `tests/test_ledger_stats.py` and
`tests/test_skill_audit_refs.py` both make.
"""
import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CENSUS = REPO_ROOT / "tools" / "phase223_role_census.py"
SWEEP = REPO_ROOT / "tools" / "phase223_oververification_sweep.py"
CONFIG_DOC = REPO_ROOT / "docs" / "configuration.md"


def _load(path: Path, name: str):
    """Import a maintainer-side derivation module.

    The skip is for the MIRROR, where `tools/` is removed wholesale — not for a
    missing file inside a tree that still has `tools/`. A bare `if not exists:
    skip` made every guard here silently vacuous the moment someone deleted a
    spent script, which this repo does by convention (Phase 194 deleted
    `RENAME_PLAN.md` as spent). Measured by the round: removing any one of the
    three inputs turned the suite green with 4-6 skips and no signal, while the
    public doc kept citing numbers nothing pinned any more.
    """
    if not (REPO_ROOT / "tools").is_dir():
        pytest.skip("tools/ is absent — mirror tree, where these are excluded wholesale")
    assert path.exists(), (
        f"{path.name} is missing while tools/ is present. Either it was deleted — in "
        f"which case the numbers it pins in docs/configuration.md are now unbacked and "
        f"must come out — or this is a partial tree. It is not a skip."
    )
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fixture_path() -> Path:
    """The spend fixture, held to the same standard as the modules above."""
    fixture = REPO_ROOT / "tools" / "phase223_gdp_spend.jsonl"
    if not (REPO_ROOT / "tools").is_dir():
        pytest.skip("tools/ is absent — mirror tree")
    assert fixture.exists(), (
        "the spend fixture is missing while tools/ is present — every published "
        "percentage loses its provenance, silently, unless this fails"
    )
    return fixture


def _doc() -> str:
    return CONFIG_DOC.read_text(encoding="utf-8")


# ── the tree census ───────────────────────────────────────────────────────────
def test_the_published_pin_counts_match_the_census():
    c = _load(CENSUS, "phase223_role_census").census()
    doc = _doc()
    assert f"{c['total']} pins" in doc, (
        f"docs/configuration.md must cite the derived pin total ({c['total']})"
    )
    assert f"other {c['reasoning_pins']} are `reasoning`" in doc, (
        f"derived reasoning pins = {c['reasoning_pins']}"
    )
    assert f"carry {c['cheap_tier_pins']} of the {c['total']} pins" in doc, (
        f"derived cheap-tier pins = {c['cheap_tier_pins']} of {c['total']}"
    )


def test_the_cheap_tier_really_is_two_pins():
    """The claim that carries the recommendation: there is no cheap lever hiding
    in the default map, because the cheap roles govern almost nothing."""
    c = _load(CENSUS, "phase223_role_census").census()
    assert c["cheap_tier_pins"] == 2
    assert c["reasoning_pins"] + c["cheap_tier_pins"] == c["total"]


def test_the_loop_mode_counts_are_derived_and_published():
    """The round found `docs/configuration.md` publishing a full-install census as
    a fact about "the tree". Loop mode is the funnel Sysop points newcomers at
    (Phase 132), and it ships neither of the cheap-tier skills — so the reader
    most likely to read this page had a cheap tier governing nothing while the
    page told them it governed two pins.
    """
    mod = _load(CENSUS, "phase223_role_census")
    loop = mod.census("loop")
    doc = _doc()
    assert loop["cheap_tier_pins"] == 0
    assert loop["by_role"] == {"reasoning": loop["total"]}
    assert f"all {loop['total']} pins a loop install carries are `reasoning`" in doc
    assert "On a loop-mode install they carry none at all" in doc
    _assert_no_retraction(doc)
    # The exclusion list is parsed from install.sh, not restated in the census.
    excluded = mod.loop_excluded_skills()
    assert {"auto-fix", "next-task"} <= excluded


def test_inline_governing_roles_are_the_ones_the_docs_constrain():
    """`docs/configuration.md` tells consumers to constrain `reasoning` and
    `mechanical` because those govern inline pins. If a future pin puts a third
    role inline, that sentence is silently wrong and this goes red."""
    c = _load(CENSUS, "phase223_role_census").census()
    assert c["inline_governing_roles"] == ["mechanical", "reasoning"]
    assert "Map `reasoning` and `mechanical` to one of" in _doc()


# ── the spend split ───────────────────────────────────────────────────────────
def test_the_published_percentages_match_the_fixture():
    s = _load(CENSUS, "phase223_role_census").spend()
    _fixture_path()  # absent tools/ skips; absent fixture inside tools/ fails
    assert s["rows"], "the fixture is present but produced no rows"
    doc = _doc()
    for phase in ("exec", "plan", "review"):
        pct = s["pct_of_recorded"][phase]
        assert f"{pct}%" in doc, f"{phase} share {pct}% is not the figure the doc cites"


def test_the_zero_spend_phases_are_disclosed_as_a_gap():
    """The limit that matters most: `fix` and `verify` recorded nothing, so the
    one mechanical-governed pin has no cost evidence. A published split that
    hides that reads as coverage it does not have."""
    s = _load(CENSUS, "phase223_role_census").spend()
    _fixture_path()  # absent tools/ skips; absent fixture inside tools/ fails
    assert s["rows"], "the fixture is present but produced no rows"
    assert "fix" in s["zero_spend_phases"] and "verify" in s["zero_spend_phases"]
    doc = _doc()
    assert "`fix` and `verify` rows recorded no spend" in doc
    assert "not a free phase" in doc
    _assert_no_retraction(doc)


def test_the_doc_attributes_the_shares_to_the_right_phases():
    """Digits are not claims. The round inverted the sentence — "concentrated in
    *review*, not execution", with 63.7% and 14.5% swapped — and every pinned
    substring still appeared, so the suite stayed green while the public page
    said the opposite of its own data. Pin the attribution, not the numerals.
    """
    s = _load(CENSUS, "phase223_role_census").spend()
    _fixture_path()
    assert s["rows"], "the fixture is present but produced no rows"
    doc = _doc()
    largest = max(s["pct_of_recorded"], key=lambda k: s["pct_of_recorded"][k])
    assert largest == "exec"
    # The sentence must name the largest phase as the concentration, and must
    # attach the largest percentage to it rather than to something else.
    assert "concentrated in *execution*, not review" in doc, (
        "the doc no longer attributes the concentration to the phase the data names"
    )
    exec_pct, review_pct = s["pct_of_recorded"]["exec"], s["pct_of_recorded"]["review"]
    assert f"{exec_pct}% of it, against" in doc, (
        f"the leading share in the sentence is not exec's derived {exec_pct}%"
    )
    assert f"and {review_pct}% for review" in doc, (
        f"review's share is not its derived {review_pct}%"
    )
    assert "There is no cheap lever hiding in the default map" in doc, (
        "the recommendation the census supports has been reversed"
    )
    _assert_no_retraction(doc)


# A substring pin says a sentence is PRESENT; it says nothing about whether the
# text around it retracts, negates or historicizes it. Round 2 kept every pinned
# substring and prefixed "It used to be said that …", suffixed "…, but that is
# obsolete", and inserted "NOT" — all green. This is a denylist and therefore
# weak by construction: it catches the shapes that have actually been used
# against these claims and cannot catch a shape nobody has tried. It is here
# because the alternative for a prose claim is nothing, and the strong form —
# deriving the claim, as `advertised == set(legal)` does below — is available for
# only some of them.
_RETRACTION_MARKERS = (
    "used to be said", "is obsolete", "that is obsolete", "has been retired",
    "that reading is wrong", "no longer true", "NOT concentrated",
    "historically", "this note is obsolete", "now rescues",
)


def _assert_no_retraction(text: str) -> None:
    found = [m for m in _RETRACTION_MARKERS if m in text]
    assert not found, (
        f"the page carries retraction language {found} — a pinned claim can be "
        f"present and reversed in the same sentence, which is how round 2 walked "
        f"four of these guards"
    )


def test_the_doc_does_not_re_advertise_the_broken_values():
    """`served_models.yml` got a normalized reversion guard and the public page —
    the surface a consumer actually reads — got none. The round added `best` to
    the alias list and flipped "does not rescue it" to "rescues it", and both
    survived the full suite.

    The alias list is compared against the DERIVED legal set rather than a
    literal, so widening `inline_models:` legitimately widens this too.
    """
    import re as _re

    m = _load(CENSUS, "phase223_role_census")._roles_module()
    legal = m.load_inline_models(
        REPO_ROOT / "core" / "companion" / ".claude" / "served_models.yml", None
    )
    doc = _doc()

    sentence = _re.search(
        r"\*\*Map `reasoning` and `mechanical` to one of ([^*]+)\.\*\*", doc
    )
    assert sentence, "the mapping constraint sentence is gone from the public page"
    advertised = set(_re.findall(r"`([^`]+)`", sentence.group(1)))
    assert advertised == set(legal), (
        f"the page advertises {sorted(advertised)} but the derived legal set is "
        f"{sorted(legal)}"
    )
    assert "Adding the value to `served:` does not rescue it" in doc, (
        "the page no longer says `served:` membership fails to rescue an inline pin — "
        "which is the precise trap Q-220 was filed over"
    )
    assert "breaks every agent spawn in the skills that role governs" in doc
    _assert_no_retraction(doc)


def test_exec_is_the_largest_share():
    """The recommendation rests on this ordering, not on the exact percentages."""
    s = _load(CENSUS, "phase223_role_census").spend()
    _fixture_path()  # absent tools/ skips; absent fixture inside tools/ fails
    assert s["rows"], "the fixture is present but produced no rows"
    assert max(s["pct_of_recorded"], key=s["pct_of_recorded"].get) == "exec"


def test_the_spend_fixture_carries_no_consumer_identifier():
    """The fixture is another project's runtime data. `tools/` is excluded from
    the public mirror by convention rather than by mechanism, so this asserts the
    fixture would be harmless even if that convention broke.

    Asserted structurally — every id matches the opaque token the anonymizer
    emits, and no field carries free text — rather than as a denylist of known
    identifier prefixes. A denylist only catches shapes someone thought to list,
    and writing those literals here would itself leak them into a mirrored file,
    which is how the first cut of this test failed `test_mirror_leak_gate`.
    """
    import json
    import re as _re

    fixture = _fixture_path()

    allowed_keys = {"cycle_id", "task_id", "ts", "phase", "spend_usd"}
    task_re, cycle_re = _re.compile(r"^t\d{4}$"), _re.compile(r"^c\d{4}$")
    rows = 0
    for line in fixture.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        rows += 1
        assert set(row) <= allowed_keys, f"unexpected field(s): {set(row) - allowed_keys}"
        # A null id carries no identifier and is fine; a present one must be opaque.
        for key, pattern in (("task_id", task_re), ("cycle_id", cycle_re)):
            value = row[key]
            assert value is None or pattern.match(value), f"{key} not anonymized: {value!r}"
        assert row["phase"] is None or row["phase"].isalpha()
        # `ts` and `spend_usd` were unchecked, so a string pasted into either
        # passed the identity guard — the two fields most likely to carry
        # free text back from a raw telemetry line.
        assert row["spend_usd"] is None or isinstance(row["spend_usd"], (int, float)), (
            f"spend_usd is {type(row['spend_usd']).__name__}, not a number or null"
        )
        assert row["ts"] is None or _re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T[\d:.]+(?:Z|[+-]\d{2}:\d{2})", row["ts"]
        ), f"ts is not an ISO timestamp: {row['ts']!r}"
    assert rows > 100, "vacuity control: the fixture must not be empty"


def test_a_zero_spend_phase_is_never_reported_as_a_share():
    """`fix` and `verify` recorded nothing. Relaxing the threshold to `>= 0` puts
    them into the share table at 0.0%, which reads as "we measured this phase and
    it was free" rather than "this phase was never measured" — the exact
    misreading the limits paragraph exists to prevent."""
    s = _load(CENSUS, "phase223_role_census").spend()
    _fixture_path()
    assert s["rows"], "the fixture is present but produced no rows"
    overlap = set(s["zero_spend_phases"]) & set(s["pct_of_recorded"])
    assert not overlap, (
        f"{sorted(overlap)} appear both as a telemetry gap and as a measured share"
    )
    assert sum(s["pct_of_recorded"].values()) == pytest.approx(100.0, abs=0.2)


# ── the Q-064 sweep receipt ───────────────────────────────────────────────────
def test_the_bare_self_check_population_stays_adjudicated():
    """`Q-064` closed on a sweep that found no bare same-agent self-check
    instruction. Exactly one line in the shipped tree matches the bare idioms,
    and it was read and cleared: `auto-build/SKILL.md` labels worked-example
    fixtures a "sanity-check reference" — a noun phrase, not an instruction.

    A NEW match is not a defect by itself; it is a site that needs a reader's
    verdict. This goes red so one happens.

    Keyed LINE-FREE, on `(file, matched text)`. A first cut pinned
    `("…/auto-build/SKILL.md", 315)`, and inserting one blank line anywhere above
    reddened the suite with the message "this site changed" when nothing about
    the site had — reversing Phase 163's baseline convention for exactly the
    reason it exists.
    """
    s = _load(SWEEP, "phase223_oververification_sweep").counts()
    assert s["bare_keys"] == [("core/skills/auto-build/SKILL.md", "sanity-check")], (
        f"the adjudicated bare-idiom set changed to {s['bare_keys']} — read each new "
        f"site against the agent-boundary criterion, then update this pin"
    )


def test_extract_never_destroys_the_fixture_it_is_rebuilding(tmp_path):
    """`--extract` opened the destination in "w" mode and read the source inside
    the with-block, so a typo'd path truncated the committed 698-row fixture
    before failing — and a real file carrying no `phase_complete` rows destroyed
    it while reporting success. The fixture is the provenance for every published
    percentage, and losing it turns four of this module's guards into skips.
    """
    mod = _load(CENSUS, "phase223_role_census")
    dest = tmp_path / "fixture.jsonl"
    dest.write_text('{"cycle_id":"c0001","task_id":"t0001","ts":"x","phase":"exec","spend_usd":1}\n')
    before = dest.read_text()

    missing = tmp_path / "does-not-exist.jsonl"
    with pytest.raises((FileNotFoundError, OSError)):
        mod.extract(missing, dest)
    assert dest.read_text() == before, "a missing source truncated the destination"

    empty = tmp_path / "no-matching-rows.jsonl"
    empty.write_text('{"event": "something_else"}\n')
    with pytest.raises(ValueError):
        mod.extract(empty, dest)
    assert dest.read_text() == before, "a source with no matching rows emptied the fixture"


def test_extract_writes_atomically(tmp_path, monkeypatch):
    """Collecting rows first fixes truncate-before-read; it does not by itself
    make the write atomic, and the battery walked a mutation through the gap by
    replacing the temp-file swap with a direct write. A failure part-way through
    then leaves a half-written fixture that still parses — the worst shape for a
    provenance file, because nothing downstream can tell it is short.

    A first cut asserted through `pytest.raises`, which swallowed the very
    AssertionError meant to report the direct write — so the test passed on the
    mutated code. Observe the writes instead of trying to fail inside them.

    A second cut observed `Path.write_text` alone and so measured the
    IMPLEMENTATION rather than the property: an equally atomic
    `open(tmp,'w') … os.replace(tmp, dest)` failed its vacuity assert. Round 2
    called that a false kill, and it was. Both write paths are watched now, and
    what is asserted is the property — the destination is never the target of a
    direct write, and arrives by a replace.
    """
    import builtins

    mod = _load(CENSUS, "phase223_role_census")
    dest = tmp_path / "fixture.jsonl"
    dest.write_text('{"cycle_id":"c0001","task_id":"t0001","ts":"x","phase":"exec","spend_usd":1}\n')
    before = dest.read_text()

    source = tmp_path / "src.jsonl"
    source.write_text(
        '{"event":"phase_complete","cycle_id":"a","task_id":"b","ts":"t","phase":"exec","spend_usd":2}\n'
    )

    real_write, real_open, real_replace = mod.Path.write_text, builtins.open, mod.Path.replace
    written: list = []
    replaced: list = []

    def recording_write(self, *args, **kwargs):
        written.append(Path(self))
        return real_write(self, *args, **kwargs)

    def recording_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            written.append(Path(file))
        return real_open(file, mode, *args, **kwargs)

    def recording_replace(self, target):
        replaced.append(Path(target))
        return real_replace(self, target)

    monkeypatch.setattr(mod.Path, "write_text", recording_write)
    monkeypatch.setattr(builtins, "open", recording_open)
    monkeypatch.setattr(mod.Path, "replace", recording_replace)
    try:
        mod.extract(source, dest)
    finally:
        monkeypatch.setattr(mod.Path, "write_text", real_write)
        monkeypatch.setattr(builtins, "open", real_open)
        monkeypatch.setattr(mod.Path, "replace", real_replace)

    assert written, "vacuity: extract wrote nothing at all"
    assert dest not in written, (
        "the destination was written directly; a failure part-way then leaves a "
        "half-written fixture that still parses. Write elsewhere and replace."
    )
    assert dest in replaced, "the destination did not arrive via an atomic replace"
    assert dest.read_text() != before, "the swap did not land"


def test_the_installer_validates_the_mapping_before_applying_it():
    """The round's HIGH: the arm had no invoker on the one path that creates the
    defect. `install.sh` ran the resolver and never the checker, so `--update`
    after editing `served_models.local.yml` — the remedy the docs prescribe —
    rewrote all 12 inline pins to a value the Agent tool rejects and exited 0.

    Asserted structurally on ordering, because "it runs" is not the property that
    matters: the check has to precede the rewrite, or it certifies damage already
    done. Phase 170's lesson.

    A first cut asserted `"check_skill_models.py" in body`, and the battery walked
    two mutations through it: pointing the path at `/nonexistent/` keeps that
    substring, and renaming the variable leaves the text intact while the
    `[[ -f ]]` test silently skips the gate. Both are rule 1's "a check satisfied
    by a substring is satisfied by an incidental use of it" — worse than a gap,
    because it marks a broken gate compliant. So the wiring is followed instead:
    the variable the existence test guards must be the variable that is assigned
    the real path, and must be the one invoked.
    """
    import re as _re

    text = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    start = text.index("resolve_skill_models() {")
    body = text[start:text.index("\ninstall_semgrep() {", start)]

    # Scoped to the gate's own block — the function has an earlier `-f` test for
    # the local config, and a bare search finds that one instead. A guard keyed to
    # "the first match" is keyed to whatever gets added above it.
    gate = body[body.index("# Phase 223: validate the MAPPING"):]
    guarded = _re.search(r'if \[\[ -f "\$(\w+)" \]\]; then', gate)
    assert guarded, "the checker's existence test is gone"
    var = guarded.group(1)

    assigned = _re.search(rf'local {var}="([^"]+)"', gate)
    assert assigned, f"${var} is guarded but never assigned — the gate cannot fire"
    assert assigned.group(1) == "$TARGET/sysop/scripts/check_skill_models.py", (
        f"${var} points at {assigned.group(1)!r}, not the installed checker"
    )
    assert f'"${var}"' in body[guarded.end():], f"${var} is tested but never invoked"

    assert body.index(f"local {var}=") < body.index("--apply"), (
        "the validation must run BEFORE --apply; after it, the bad pins are already written"
    )
    assert "REFUSED" in body


def test_the_sweep_population_is_not_empty():
    """Vacuity control: a sweep whose net matched nothing would report a clean
    corpus for the wrong reason."""
    s = _load(SWEEP, "phase223_oververification_sweep").counts()
    assert s["files_swept"] > 40
    assert s["union"] > 100
    assert s["imperative"] > 50


def test_the_sweep_covers_the_scope_phase_223_added():
    """`Q-064` was filed over "shipped skills". Phase 223 extended the sweep to
    `docs/` and the installer because those carry agent-facing text too, and the
    receipt claims that coverage. A silent revert to the filed scope would leave
    the claim standing over a population that no longer includes them.

    A first cut guarded only the EXTENSION (`docs/`, `install.sh`) and left the
    half `Q-064` was actually filed over — `core/skills`, `core/companion`,
    `packs` — unpinned. The round dropped two roots, watched the counts fall
    from 60/578/157 to 43/469/88, and every floor still held: they had 33-83%
    slack. Every root is named now, and each must contribute.
    """
    m = _load(SWEEP, "phase223_oververification_sweep")
    expected = {"core/skills", "core/companion", "packs", "docs"}
    assert set(m.DIR_ROOTS) == expected, (
        f"the sweep's roots are {set(m.DIR_ROOTS)}; the receipt claims {expected}"
    )
    assert "install.sh" in m.FILE_ROOTS
    swept = {str(p) for p in m.swept_files()}
    assert any(p.endswith("install.sh") for p in swept)
    per_root = m.counts()["union_per_root"]
    for root in expected | {"install.sh"}:
        assert per_root.get(root, 0) > 0, (
            f"{root} is declared in the sweep's scope but contributes no hits — "
            f"either it is not being read or the receipt overstates its coverage"
        )


def test_the_bare_idiom_detector_is_live():
    """The headline is an ABSENCE — zero bare self-check instructions — and an
    absence claim rests entirely on its detector still matching things. A gutted
    pattern reports the same clean corpus for the opposite reason, so the detector
    is tested against known positives rather than trusted.

    Each positive below **isolates one alternative** — it matches that branch and
    no other. A first cut used natural sentences like "Double-check your work",
    which several branches match at once, so deleting any single branch left the
    test green; the mutation battery walked straight through it.

    The positives are checked against the pattern's OWN alternatives, derived
    from the compiled source — a hand-written list of 11 positives against a
    pattern carrying 14 alternatives leaves three branches free to be deleted,
    and the round deleted them one at a time (`|work|answer` → `|work`,
    `have you (?:checked|verified)` → `verified`, `double-?check` →
    `double-check`) with the test green each time. Any branch without a positive
    fails here, so widening the pattern forces widening the coverage.
    """
    m = _load(SWEEP, "phase223_oververification_sweep")
    isolating = {
        "double-check": "Please double-check.",
        "doublecheck": "Please doublecheck.",
        "sanity check": "Run a sanity check.",
        "sanity-check": "Run a sanity-check.",
        "check your work": "Please check your work.",
        "verify your work": "Please verify your work.",
        "review your output": "Please review your output.",
        "review your work": "Please review your work.",
        "review your answer": "Please review your answer.",
        "be sure": "Be sure.",
        "final check": "One final check.",
        "one more time": "Read it one more time.",
        "before you finish": "Before you finish.",
        "did you check": "Did you check?",
        "have you checked": "Have you checked?",
        "have you verified": "Have you verified?",
    }
    for branch, positive in isolating.items():
        assert m.BARE.search(positive), (
            f"the {branch!r} branch of the bare-idiom detector no longer matches "
            f"{positive!r} — the absence headline rests on this pattern staying live"
        )
    # Every alternative the pattern declares must have a positive above. Derived
    # from the pattern source, so a branch added without coverage fails too.
    declared = _bare_alternatives(m.BARE.pattern)
    assert len(declared) >= 11, f"the pattern declares only {len(declared)} branches"
    uncovered = [
        alt for alt in declared
        if not _some_positive_depends_on(m.BARE.pattern, alt, isolating.values())
    ]
    assert not uncovered, (
        f"these branches of the bare-idiom pattern have no positive that depends on "
        f"them: {uncovered} — each could be deleted with this test still green, and "
        f"an absence headline is only as good as its detector"
    )
    assert not m.BARE.search("Verify the `tasks/` prefix rule resolves."), (
        "the detector must not match a specific, named check"
    )
    # The broad net's case-insensitivity is load-bearing for the 578 denominator.
    assert m.UNION.search("VERIFY THE THING") and m.UNION.search("verify the thing")


def _some_positive_depends_on(pattern: str, alternative: str, positives) -> bool:
    """True when deleting *alternative* stops the pattern matching some positive.

    This is the property that matters, stated directly: a branch nothing depends
    on can be deleted with the test still green, which is how the round narrowed
    five of them one at a time.
    """
    import re as _re

    remaining = [a for a in _bare_alternatives(pattern) if a != alternative]
    without = _re.compile(r"\b(" + "|".join(remaining) + r")\b", _re.IGNORECASE)
    full = _re.compile(pattern, _re.IGNORECASE)
    return any(full.search(p) and not without.search(p) for p in positives)


def _bare_alternatives(pattern: str) -> list[str]:
    """The top-level alternatives inside the pattern's outer group."""
    import re as _re

    inner = _re.sub(r"^\\b\(|\)\\b$", "", pattern.strip())
    out, depth, current = [], 0, ""
    for ch in inner:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "|" and depth == 0:
            out.append(current)
            current = ""
        else:
            current += ch
    if current:
        out.append(current)
    return [a for a in out if a]
