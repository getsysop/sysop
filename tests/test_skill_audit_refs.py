"""Guards for the skill audit's mechanical referent pre-pass (Phase 162).

THE MIRROR BOUNDARY, WHICH IS WHY THIS MODULE SKIPS RATHER THAN FAILS
--------------------------------------------------------------------
``tools/*`` is removed from the public mirror (``tools/make_public_mirror.sh``, pinned
by ``tests/test_mirror_leak_gate.py``), so ``tools/skill_audit_refs.py`` does not exist
in the sterilized tree. The public repo runs ``pytest`` as a required check, so a module
that imported it unconditionally would fail there and redden the next snapshot PR —
exactly what happened at the Phase-160 cut, where three tests reading the
mirror-excluded ``CLAUDE.md`` raised ``FileNotFoundError`` on the sterilized tree.

The skip is correct rather than convenient: the script genuinely is not part of what
ships. It is explicit and states its reason, so it can never read as a pass. This
mirrors ``tests/test_adversarial_review_gate.py``'s guard, which established the shape.

The open § Medium item asks for a CI job that builds the mirror and runs its suite, so
this class is caught every phase rather than every cut. Until that exists, the guard is
the floor — and note it is the *skip* that keeps the public suite green, not luck.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "skill_audit_refs.py"
INSTALL_SH = REPO_ROOT / "install.sh"


def _mod():
    """Import the checker, or skip with a stated reason on the sterilized tree."""
    if not SCRIPT.is_file():
        pytest.skip(
            "tools/skill_audit_refs.py is maintainer-side and excluded from the "
            "public mirror; the skill-audit pre-pass guards only apply in the "
            "source repo"
        )
    spec = importlib.util.spec_from_file_location("skill_audit_refs", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # Register before exec: ``@dataclass`` resolves string annotations through
    # ``sys.modules[cls.__module__]``, which is None for an unregistered module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# --------------------------------------------------------------------------------------
# The drift guard that matters most: the corpus definition is duplicated from install.sh.
# --------------------------------------------------------------------------------------


def test_loop_skills_matches_install_sh_complement():
    """``LOOP_SKILLS`` is a literal copy of a set install.sh defines by *exclusion*.

    Two sources of truth for one fact is a drift bug waiting to happen — and a skewed
    corpus is the worst kind, because the sweep would report full coverage of the wrong
    five skills. This recomputes the complement from ``LOOP_EXCLUDE_SKILLS`` and pins it.
    """
    mod = _mod()
    if not INSTALL_SH.is_file():
        pytest.skip("install.sh absent")
    text = INSTALL_SH.read_text(encoding="utf-8")
    match = re.search(r'^LOOP_EXCLUDE_SKILLS="([^"]+)"', text, re.MULTILINE)
    assert match, "LOOP_EXCLUDE_SKILLS not found in install.sh — the guard cannot resolve"
    excluded = set(match.group(1).split())
    on_disk = {p.parent.name for p in (REPO_ROOT / "core" / "skills").glob("*/SKILL.md")}
    assert set(mod.LOOP_SKILLS) == on_disk - excluded


def test_corpus_loop_only_is_the_five_skills_plus_partials():
    mod = _mod()
    names = [p.name if p.parent.name == "_shared" else p.parent.name
             for p in mod.corpus(loop_only=True)]
    assert set(mod.LOOP_SKILLS) <= set(names)
    for excluded in ("claim-task", "auto-build", "review-close", "sitrep"):
        assert excluded not in names
    assert "adversarial-review.md" in names, "partials ride along with the skills"


def test_loop_excluded_shared_matches_install_sh():
    """The partial half of the corpus, pinned the same way the skill half is.

    The first run of this checker scanned all ten partials under ``--loop-only`` while
    its own procedure doc documented six — coverage reported over a bundle no loop
    consumer holds. Two sources of truth for one derived set, caught by the tool's own
    first pass over its own documentation.
    """
    mod = _mod()
    if not INSTALL_SH.is_file():
        pytest.skip("install.sh absent")
    text = INSTALL_SH.read_text(encoding="utf-8")
    match = re.search(r'^LOOP_EXCLUDE_SHARED="([^"]+)"', text, re.MULTILINE)
    assert match, "LOOP_EXCLUDE_SHARED not found in install.sh"
    expected = {f"{stem}.md" for stem in match.group(1).split()}
    assert set(mod.LOOP_EXCLUDE_SHARED) == expected


def test_loop_only_corpus_excludes_the_non_loop_partials():
    mod = _mod()
    names = {p.name for p in mod.corpus(loop_only=True) if p.parent.name == "_shared"}
    for excluded in mod.LOOP_EXCLUDE_SHARED:
        assert excluded not in names, f"{excluded} is not shipped by loop mode"
    assert len(names) == 6, f"the loop bundle is six partials, got {sorted(names)}"


def test_procedure_doc_audits_itself():
    """SKILL_AUDIT.md states it is in its own first corpus; the tool must honor that."""
    mod = _mod()
    for loop_only in (True, False):
        names = [p.name for p in mod.corpus(loop_only=loop_only)]
        assert "SKILL_AUDIT.md" in names, f"loop_only={loop_only} skipped the procedure doc"


def test_corpus_full_includes_lifecycle_skills():
    mod = _mod()
    names = [p.parent.name for p in mod.corpus(loop_only=False)]
    assert "claim-task" in names and "auto-build" in names


# --------------------------------------------------------------------------------------
# Check 3 — retired vocabulary, the list that grows.
# --------------------------------------------------------------------------------------


def test_retired_referent_is_a_defect(tmp_path, monkeypatch):
    mod = _mod()
    doc = _write(
        tmp_path, "SKILL.md", "Spawn an Agent with `run_in_background: false` here.\n"
    )
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    report = mod.Report()
    mod.check_file(doc, report)
    assert [d["check"] for d in report.defects] == ["retired-referent"]
    assert report.defects[0]["line"] == 1


def test_retired_referent_does_not_fire_outside_its_tool_context(tmp_path, monkeypatch):
    """``run_in_background`` is dead on ``Agent`` and ALIVE on ``Bash``.

    The first version of this check matched the bare substring and stamped every hit
    `certain defect` — the verdict most likely to be acted on without reading the site.
    A skill documenting a backgrounded Bash call would have been told to delete a
    correct parameter.
    """
    mod = _mod()
    doc = _write(
        tmp_path,
        "SKILL.md",
        "Run the migration with the Bash tool, `run_in_background: true`, so it\n"
        "keeps going across turns.\n",
    )
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    report = mod.Report()
    mod.check_file(doc, report)
    assert report.defects == []


def test_retired_referent_context_matches_across_the_lookback_window(tmp_path, monkeypatch):
    """The spawn sentence names the tool; the parameter list is several lines below.

    Three of the eleven live sites are shaped exactly this way, so a same-line context
    test would silently drop them — a guard that passes while covering less.
    """
    mod = _mod()
    doc = _write(
        tmp_path,
        "SKILL.md",
        "Spawn the reviewers via parallel `Agent` tool calls. Each call:\n"
        "\n"
        "- `subagent_type`: `\"general-purpose\"`\n"
        "- `model`: `\"opus\"`\n"
        "- `run_in_background`: `true`\n",
    )
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    report = mod.Report()
    mod.check_file(doc, report)
    assert [d["line"] for d in report.defects] == [5]


def test_retired_referent_waiver_suppresses(tmp_path, monkeypatch):
    """Text that *discusses* a dead referent is not text that instructs an agent to use it.

    Without this, the phase record and this very procedure's doc would flag themselves,
    and a checker that cries wolf on its own documentation gets switched off.
    """
    mod = _mod()
    doc = _write(
        tmp_path,
        "SKILL.md",
        "An Agent's `run_in_background` key is dead. "
        "<!-- skill-audit-ok: run_in_background -->\n",
    )
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    report = mod.Report()
    mod.check_file(doc, report)
    assert report.defects == []


def test_waiver_is_token_scoped_not_a_blanket(tmp_path, monkeypatch):
    """A waiver for one token must not silence a different one on the same line."""
    mod = _mod()
    monkeypatch.setattr(
        mod,
        "RETIRED_VOCABULARY",
        (("dead_one", r".", "gone"), ("other_one", r".", "also gone")),
    )
    doc = _write(
        tmp_path, "SKILL.md", "dead_one and other_one <!-- skill-audit-ok: dead_one -->\n"
    )
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    report = mod.Report()
    mod.check_file(doc, report)
    assert len(report.defects) == 1
    assert "other_one" in report.defects[0]["message"]


def test_every_retired_entry_carries_its_evidence():
    """The list grows only on verified findings, so an entry without a reason is a bug."""
    mod = _mod()
    for token, context, reason in mod.RETIRED_VOCABULARY:
        assert token and len(reason) > 40, f"{token} lacks the evidence that retired it"
        assert context, f"{token} has no tool context — it would fire wherever it appears"
        re.compile(context)


def test_run_in_background_is_seeded_and_still_live_in_the_tree():
    """The seed reproduces the § High filing's count independently.

    If this drops to zero the sites were fixed and the entry should close; if it moves,
    the guard has caught either a fix or a regression. Either way it is not silent.
    """
    mod = _mod()
    assert any(entry[0] == "run_in_background" for entry in mod.RETIRED_VOCABULARY)
    report = mod.Report()
    for path in mod.corpus(loop_only=False):
        mod.check_file(path, report)
    hits = [d for d in report.defects if d["check"] == "retired-referent"]
    by_file: dict[str, int] = {}
    for hit in hits:
        by_file[hit["file"]] = by_file.get(hit["file"], 0) + 1
    # Derived from the baseline, NOT hardcoded. The first draft pinned {4, 4, 3}, so
    # running the ratchet exactly as the tool's own STALE output instructs turned the
    # suite red — the documented workflow breaking the gate it is documented for, and a
    # direct contradiction of this phase's "a fix must not break the build" rule. The
    # baseline is the deliberate-acceptance record; a silent drift still fails, because
    # `test_the_checker_is_green_against_its_baseline` compares tree against baseline.
    baseline = mod.load_baseline(REPO_ROOT / "tools" / "skill_audit_baseline.txt")
    expected = {
        key.split("|", 2)[1]: count
        for key, count in baseline.items()
        if key.startswith("retired-referent|")
    }
    assert by_file == expected, (
        "the tree and the baseline disagree — run --update-baseline to accept, or fix"
    )


# --------------------------------------------------------------------------------------
# Check 1 — path:line, and the zero-false-positive property that makes it usable.
# --------------------------------------------------------------------------------------


def test_line_beyond_eof_is_a_certain_defect(tmp_path, monkeypatch):
    mod = _mod()
    _write(tmp_path, "target.py", "one\ntwo\n")
    doc = _write(tmp_path, "SKILL.md", "See `target.py:99` for the detail.\n")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    report = mod.Report()
    mod.check_file(doc, report)
    assert [d["check"] for d in report.defects] == ["path-line-beyond-eof"]
    assert report.worklist == []


def test_resolvable_line_is_worklist_never_defect(tmp_path, monkeypatch):
    """The distinction upstream #239 lost: unroutable and clean must not look alike.

    A line number that exists but points at the wrong content is not mechanically
    decidable, so it is directed attention — never a pass, never a failure.
    """
    mod = _mod()
    _write(tmp_path, "target.py", "one\ntwo\nthree\n")
    doc = _write(tmp_path, "SKILL.md", "See `target.py:2` for the detail.\n")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    report = mod.Report()
    mod.check_file(doc, report)
    assert report.defects == []
    assert [w["check"] for w in report.worklist] == ["path-line-verify"]


def test_unlocatable_path_is_silent(tmp_path, monkeypatch):
    """Consumer-side and illustrative paths must produce nothing at all.

    This is the property the whole check rests on. ``.claude/checks.yml:12`` and
    ``src/db/writer.py:102`` are not ours; guessing at them would bury the real
    findings, which is how a noisy gate becomes an ignored one.
    """
    mod = _mod()
    doc = _write(
        tmp_path,
        "SKILL.md",
        "See `src/db/writer.py:102` and `.claude/checks.yml:12` and `foo.py:123`.\n",
    )
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    report = mod.Report()
    mod.check_file(doc, report)
    assert report.defects == []
    assert report.worklist == []


def test_ambiguous_basename_is_silent(tmp_path, monkeypatch):
    """Two files share the name — we cannot know which was meant, so we say nothing."""
    mod = _mod()
    _write(tmp_path, "a/dup.py", "one\n")
    _write(tmp_path, "b/dup.py", "one\n")
    doc = _write(tmp_path, "SKILL.md", "See `dup.py:99`.\n")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    report = mod.Report()
    mod.check_file(doc, report)
    assert report.defects == [] and report.worklist == []


def test_placeholders_and_globs_never_match():
    """The repo's placeholder vocabulary must not be mistaken for a real referent."""
    mod = _mod()
    for text in ("`docs/<branch>.md:12`", "`tools/*.py:4`", "`<api module>.py:9`"):
        assert not mod.PATH_LINE_RE.search(text.replace("`", "")), text


# --------------------------------------------------------------------------------------
# Check 2 — `_shared/` includes.
# --------------------------------------------------------------------------------------


def test_missing_shared_partial_is_a_defect(tmp_path, monkeypatch):
    mod = _mod()
    shared = tmp_path / "shared"
    shared.mkdir()
    doc = _write(tmp_path, "SKILL.md", "Read `_shared/does-not-exist.md` first.\n")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "SHARED_DIR", shared)
    report = mod.Report()
    mod.check_file(doc, report)
    assert [d["check"] for d in report.defects] == ["shared-partial-missing"]


def test_every_shared_reference_in_the_real_tree_resolves():
    """The live guard: no shipped skill may cite a partial that does not exist."""
    mod = _mod()
    report = mod.Report()
    for path in mod.corpus(loop_only=False):
        mod.check_file(path, report)
    dangling = [d for d in report.defects if d["check"] == "shared-partial-missing"]
    assert dangling == [], f"dangling _shared/ includes: {dangling}"


# --------------------------------------------------------------------------------------
# Exit-code semantics.
# --------------------------------------------------------------------------------------


def test_worklist_alone_does_not_fail_the_run(tmp_path, monkeypatch, capsys):
    mod = _mod()
    _write(tmp_path, "target.py", "one\ntwo\n")
    skills = tmp_path / "core" / "skills" / "demo"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("See `target.py:1`.\n", encoding="utf-8")
    shared = tmp_path / "core" / "skills" / "_shared"
    shared.mkdir(parents=True)
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "SKILLS_DIR", tmp_path / "core" / "skills")
    monkeypatch.setattr(mod, "SHARED_DIR", shared)
    assert mod.main([]) == 0
    assert "WORKLIST" in capsys.readouterr().out


def test_defect_fails_the_run(tmp_path, monkeypatch, capsys):
    mod = _mod()
    _write(tmp_path, "target.py", "one\n")
    skills = tmp_path / "core" / "skills" / "demo"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("See `target.py:99`.\n", encoding="utf-8")
    shared = tmp_path / "core" / "skills" / "_shared"
    shared.mkdir(parents=True)
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "SKILLS_DIR", tmp_path / "core" / "skills")
    monkeypatch.setattr(mod, "SHARED_DIR", shared)
    assert mod.main([]) == 1
    # Phase 163 renamed the block: with a baseline in play, "certain" was the wrong
    # axis — what fails the run is a defect being NEW, not a defect being certain.
    assert "NEW DEFECTS (1)" in capsys.readouterr().out


def test_locate_ignores_vendored_trees(tmp_path, monkeypatch):
    """A vendored copy must not make our own file ambiguous.

    Found by running the checker in this repo: `cli.py` resolved to two files, one
    inside `.venv`, so `_locate` returned None and skipped the site — silently, and
    only on machines that happen to have a venv. Environment-dependent under-reporting
    is worse than either a miss or a false positive, because the result is not
    reproducible between two runs of the same command.
    """
    mod = _mod()
    _write(tmp_path, "src/thing.py", "one\ntwo\n")
    _write(tmp_path, ".venv/lib/thing.py", "vendored\n")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "_EXCLUDED_DIRS", mod._EXCLUDED_DIRS)
    doc = _write(tmp_path, "SKILL.md", "See `thing.py:99`.\n")
    report = mod.Report()
    mod.check_file(doc, report)
    assert [d["check"] for d in report.defects] == ["path-line-beyond-eof"], (
        "the vendored copy made the basename ambiguous and the site was skipped"
    )


# --- Live-tree guards (added by Phase 162's round) -------------------------------
#
# The round's independent mutation set found Check 1 was the only check with no
# live-tree guard — planting `install.sh:999999` into a shipped skill made the
# checker exit 1 while the whole suite stayed green. Check 2 and Check 3 already had
# one each; the check the phase's own flagship example is ABOUT had none.


def test_no_shipped_file_cites_a_line_past_end_of_file():
    """The live-tree guard for Check 1 — a planted beyond-EOF referent must fail here."""
    mod = _mod()
    report = mod.Report()
    for path in mod.corpus(loop_only=False):
        mod.check_file(path, report)
    beyond = [d for d in report.defects if d["check"] == "path-line-beyond-eof"]
    assert beyond == [], f"referents citing past end-of-file: {beyond}"


def test_last_line_citation_is_not_a_defect(tmp_path, monkeypatch):
    """Boundary: `>` not `>=`.

    The round mutated the comparison to `>=` and no test noticed — which would make
    every citation to a file's final line a false CERTAIN DEFECT, the verdict most
    likely to be acted on without reading the site.
    """
    mod = _mod()
    _write(tmp_path, "target.py", "one\ntwo\nthree\n")
    doc = _write(tmp_path, "SKILL.md", "See `target.py:3` — the last line.\n")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    report = mod.Report()
    mod.check_file(doc, report)
    assert report.defects == [], "a citation to the final line is valid, not a defect"
    assert [w["check"] for w in report.worklist] == ["path-line-verify"]


def test_path_line_extensions_stay_pinned():
    """Narrowing the extension set silently drops real worklist entries.

    The round narrowed it to `.py` alone: all tests passed while 2 of 3 real worklist
    rows vanished — including the `claim_task.sh` referent this phase spent its record
    correcting. A regex whose breadth nothing pins is a regex that can be quietly
    narrowed.
    """
    mod = _mod()
    for ext in ("md", "py", "sh", "yml", "yaml", "json", "txt"):
        assert mod.PATH_LINE_RE.search(f"file.{ext}:12"), f".{ext} is no longer matched"


def test_main_actually_honors_loop_only(monkeypatch, capsys):
    """`main()` must pass the flag through to `corpus()`.

    The round replaced `corpus(args.loop_only)` with `corpus(False)` and every test
    still passed — all `--loop-only` coverage called `corpus()` directly and nothing
    drove the CLI. The flag is the whole difference between auditing the loop bundle
    and auditing the tree.
    """
    mod = _mod()
    expected = len(mod.corpus(loop_only=True))
    mod.main(["--loop-only"])
    out = capsys.readouterr().out
    assert f"{expected} files scanned" in out, (
        f"--loop-only did not scan the loop corpus ({expected} files); got: {out.splitlines()[:1]}"
    )
    assert expected < len(mod.corpus(loop_only=False))


# --- Baseline + wiring (Phase 163) -----------------------------------------------
#
# The checker was built in Phase 162 and enforced by nobody: nothing invoked it, and it
# exited 1 on the real tree because the eleven filed `run_in_background` sites were
# never fixed. A checker whose own docstring says "a check enforced only by a reader
# remembering to look is not a check" cannot be left in that state. The baseline accepts
# those eleven as debt so the *gate* can run, and the test at the bottom of this section
# is the wiring — it runs every phase, and the mirror skip is already handled.


def test_baseline_key_excludes_line_numbers():
    """The whole reason this baseline is not shaped like `.claude/checks_baseline.txt`.

    Skill markdown is edited constantly, so a line-keyed entry rots on the first
    unrelated edit above it — the objection `run_checks/baseline.py` already records
    for its own baseline key, and the one upstream #235 raises generally. (This used
    to attribute that objection to a claim about how coverage numbering shifts. Phase 213
    retracted that as false — those numbers are absolute source lines — and **this file ships to
    the public repo**, so it was the live instance of exactly the harm `Q-247` was
    filed to prevent.)
    """
    mod = _mod()
    key = mod.baseline_key("retired-referent", "core/skills/x/SKILL.md", "run_in_background")
    assert ":" not in key.split("|")[-1]
    assert not any(part.isdigit() for part in key.split("|"))


def test_baseline_round_trips(tmp_path):
    mod = _mod()
    defects = [
        {"check": "retired-referent", "file": "a/SKILL.md", "detail": "tok", "line": 1},
        {"check": "retired-referent", "file": "a/SKILL.md", "detail": "tok", "line": 9},
        {"check": "shared-partial-missing", "file": "b/SKILL.md", "detail": "x.md", "line": 3},
    ]
    path = tmp_path / "baseline.txt"
    mod.write_baseline(path, defects)
    loaded = mod.load_baseline(path)
    assert loaded[mod.baseline_key("retired-referent", "a/SKILL.md", "tok")] == 2
    assert loaded[mod.baseline_key("shared-partial-missing", "b/SKILL.md", "x.md")] == 1


def test_damaged_baseline_line_does_not_widen_suppression(tmp_path):
    """A corrupt entry must fail closed — its findings resurface as new.

    The opposite (treating an unparseable line as a blanket allow) is how a damaged
    suppression file turns a gate silently green, which upstream #238 names as strictly
    worse than having no gate.
    """
    mod = _mod()
    path = tmp_path / "baseline.txt"
    path.write_text(
        "retired-referent|a/SKILL.md|tok|notanumber\n"
        "garbage-with-no-pipes\n"
        "shared-partial-missing|b/SKILL.md|x.md|1\n",
        encoding="utf-8",
    )
    loaded = mod.load_baseline(path)
    assert loaded == {mod.baseline_key("shared-partial-missing", "b/SKILL.md", "x.md"): 1}


def test_missing_baseline_means_everything_is_new(tmp_path):
    mod = _mod()
    assert mod.load_baseline(tmp_path / "nope.txt") == {}


def test_update_baseline_always_snapshots_the_full_corpus(tmp_path, monkeypatch, capsys):
    """`--update-baseline --loop-only` must not narrow the snapshot.

    A loop-scoped snapshot would drop every lifecycle-skill entry, and the next full run
    would then see them as new — or, worse, a later `--update` from the loop corpus would
    quietly widen the baseline to "clean" for files it never looked at.

    **Re-pointed at a SYNTHETIC corpus (Phase 233).** This asserted that the snapshot
    contained an `auto-build` entry, which held only while `auto-build` carried
    `run_in_background` debt. `Q-031` paid that off and the shipped baseline is now
    empty, so the assertion could no longer be satisfied by a CORRECT script -- the
    guard was measuring the tree's debt, not the flag's behaviour.
    """
    mod = _mod()
    skills = tmp_path / "core" / "skills"
    # `demo` is deliberately NOT in LOOP_SKILLS, so the loop corpus excludes it.
    (skills / "demo").mkdir(parents=True)
    (skills / "_shared").mkdir(parents=True)
    doc = skills / "demo" / "SKILL.md"
    doc.write_text("Spawn an Agent with `run_in_background: true`.\n", encoding="utf-8")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "SKILLS_DIR", skills)
    monkeypatch.setattr(mod, "SHARED_DIR", skills / "_shared")

    # The PRECONDITION, asserted rather than assumed: if the loop corpus already
    # contained `demo`, this fixture could not tell a narrowed snapshot from a
    # full one and would pass against the bug.
    assert doc not in mod.corpus(loop_only=True), "fixture is wrong: demo is loop-scoped"
    assert doc in mod.corpus(loop_only=False), "fixture is wrong: demo is not in the corpus"

    path = tmp_path / "baseline.txt"
    assert mod.main(["--update-baseline", "--loop-only", "--baseline", str(path)]) == 0
    capsys.readouterr()
    loaded = mod.load_baseline(path)
    assert any("demo" in key for key in loaded), (
        "the snapshot came from the loop corpus and lost the lifecycle-skill entries"
    )


def test_new_occurrence_beyond_the_baselined_count_fails(tmp_path, monkeypatch, capsys):
    """The count is what keeps a line-free key honest."""
    mod = _mod()
    skills = tmp_path / "core" / "skills" / "demo"
    skills.mkdir(parents=True)
    (tmp_path / "core" / "skills" / "_shared").mkdir(parents=True)
    doc = skills / "SKILL.md"
    doc.write_text("Spawn an Agent with `run_in_background: true`.\n", encoding="utf-8")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "SKILLS_DIR", tmp_path / "core" / "skills")
    monkeypatch.setattr(mod, "SHARED_DIR", tmp_path / "core" / "skills" / "_shared")
    base = tmp_path / "baseline.txt"
    assert mod.main(["--update-baseline", "--baseline", str(base)]) == 0
    assert mod.main(["--baseline", str(base)]) == 0
    doc.write_text(
        "Spawn an Agent with `run_in_background: true`.\n"
        "And another Agent with `run_in_background: true`.\n",
        encoding="utf-8",
    )
    assert mod.main(["--baseline", str(base)]) == 1, "a second occurrence was not new"
    assert "NEW DEFECTS (1)" in capsys.readouterr().out


def test_a_fixed_baselined_defect_is_stale_not_a_failure(tmp_path, monkeypatch, capsys):
    """Fixing a defect must never break the build — surface, don't reap."""
    mod = _mod()
    skills = tmp_path / "core" / "skills" / "demo"
    skills.mkdir(parents=True)
    (tmp_path / "core" / "skills" / "_shared").mkdir(parents=True)
    doc = skills / "SKILL.md"
    doc.write_text("Spawn an Agent with `run_in_background: true`.\n", encoding="utf-8")
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "SKILLS_DIR", tmp_path / "core" / "skills")
    monkeypatch.setattr(mod, "SHARED_DIR", tmp_path / "core" / "skills" / "_shared")
    base = tmp_path / "baseline.txt"
    mod.main(["--update-baseline", "--baseline", str(base)])
    doc.write_text("Spawn an Agent, backgrounded by default.\n", encoding="utf-8")
    capsys.readouterr()
    assert mod.main(["--baseline", str(base)]) == 0, "a fix must not fail the run"
    assert "STALE BASELINE (1)" in capsys.readouterr().out


def test_baselined_defects_are_named_not_just_counted(tmp_path, monkeypatch, capsys):
    """Accepted debt that prints only a number becomes invisible debt.

    **Re-pointed at a SYNTHETIC corpus (Phase 233).** This drove the real tree and
    asserted on `run_in_background` debt that `Q-031` has now paid off, leaving the
    shipped baseline empty. Written that way, the guard died the moment the defect it
    described was fixed — and the only ways to revive it in place are to re-add debt or
    to weaken the assertion, both worse than the bug. It now seeds its own defect, so it
    tests the MECHANISM rather than the incidental state of the tree.
    """
    mod = _mod()
    skills = tmp_path / "core" / "skills" / "demo"
    skills.mkdir(parents=True)
    (tmp_path / "core" / "skills" / "_shared").mkdir(parents=True)
    doc = skills / "SKILL.md"
    doc.write_text(
        "Spawn an Agent with `run_in_background: true`.\n"
        "And another Agent with `run_in_background: true`.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "SKILLS_DIR", tmp_path / "core" / "skills")
    monkeypatch.setattr(mod, "SHARED_DIR", tmp_path / "core" / "skills" / "_shared")
    base = tmp_path / "baseline.txt"
    assert mod.main(["--update-baseline", "--baseline", str(base)]) == 0
    capsys.readouterr()
    assert mod.main(["--baseline", str(base)]) == 0
    out = capsys.readouterr().out

    baseline = mod.load_baseline(base)
    assert sum(baseline.values()) == 2, baseline
    assert f"BASELINED ({sum(baseline.values())})" in out
    named = out.split("BASELINED")[1]
    for key in baseline:
        check, file, detail = key.split("|", 2)
        assert file in named and detail in named, f"{key} is counted but not named"


# --- THE WIRING ------------------------------------------------------------------


def test_the_checker_is_green_against_its_baseline():
    """The gate. This is what "wired" means for a maintainer-side script.

    Not CI and not `self_check.sh` — the script lives in mirror-excluded `tools/`, so a
    shipped runner could not call it on a consumer install. pytest already runs every
    phase and already carries the mirror skip, so the enforcement costs no new surface.

    If this fails, a NEW dangling referent entered the skills tree. Either fix it, or
    accept it deliberately with `--update-baseline` — and the diff to
    `tools/skill_audit_baseline.txt` makes that acceptance reviewable rather than silent.
    """
    mod = _mod()
    assert mod.main([]) == 0, (
        "skill_audit_refs found a NEW dangling referent — see the NEW DEFECTS block above"
    )


def test_the_checker_script_exists_in_the_source_repo():
    """Closes the leg Phase 163's first draft *claimed* to close and did not.

    Every other test here routes through ``_mod()``, which skips when the script is
    absent — correct on the sterilized mirror, but it means deleting the script from the
    SOURCE repo makes the whole gate evaporate with a green suite. This assertion is
    deliberately outside that guard, and keyed on a marker the mirror removes, so it
    fires only where the script is supposed to exist.
    """
    if not (REPO_ROOT / "CLAUDE.md").is_file():
        pytest.skip("not the source repo (CLAUDE.md is mirror-excluded)")
    assert SCRIPT.is_file(), (
        "tools/skill_audit_refs.py is missing from the source repo — the skill-audit "
        "gate is silently disabled, since every other guard here skips without it"
    )


def test_no_baseline_flag_counts_everything_as_new(tmp_path, monkeypatch, capsys):
    """``--no-baseline`` shipped untested and undocumented in the first draft.

    **Re-pointed at a SYNTHETIC corpus (Phase 233).** This drove the real tree and
    asserted on `run_in_background` debt that `Q-031` has now paid off, leaving the
    shipped baseline empty. Written that way, the guard died the moment the defect it
    described was fixed — and the only ways to revive it in place are to re-add debt or
    to weaken the assertion, both worse than the bug. It now seeds its own defect, so it
    tests the MECHANISM rather than the incidental state of the tree.
    """
    mod = _mod()
    skills = tmp_path / "core" / "skills" / "demo"
    skills.mkdir(parents=True)
    (tmp_path / "core" / "skills" / "_shared").mkdir(parents=True)
    doc = skills / "SKILL.md"
    doc.write_text(
        "Spawn an Agent with `run_in_background: true`.\n"
        "And another Agent with `run_in_background: true`.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "SKILLS_DIR", tmp_path / "core" / "skills")
    monkeypatch.setattr(mod, "SHARED_DIR", tmp_path / "core" / "skills" / "_shared")
    base = tmp_path / "baseline.txt"
    assert mod.main(["--update-baseline", "--baseline", str(base)]) == 0
    capsys.readouterr()
    assert mod.main(["--no-baseline", "--baseline", str(base)]) == 1, (
        "--no-baseline must ignore the baseline and report the seeded defects as new"
    )
    out = capsys.readouterr().out
    assert "NEW DEFECTS (2)" in out, out
    assert "BASELINED" not in out


# --- Guards added by Phase 163's round (65 mutations, 25 survivors) ---------------


def test_the_committed_baseline_is_tight():
    """A widened baseline must not pass. The mechanism claim depends on this number.

    The round edited the counts to 400/400/300 and the suite stayed green, which made
    "a twelfth occurrence fails" true only while nobody touched the file. A baseline
    allowing more than the tree contains prints STALE, so asserting its absence pins
    tightness directly rather than by side effect.
    """
    mod = _mod()
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        mod.main([])
    assert "STALE BASELINE" not in buf.getvalue(), (
        "the committed baseline allows more than the tree contains — it has been widened, "
        "or a defect was fixed without ratcheting: run --update-baseline"
    )


def test_baseline_regenerates_byte_identically(tmp_path):
    """Pins format, sort order, header and overwrite-not-append in one assertion.

    Append-mode was a live mutation survivor, and it is the nastiest of the set: a second
    --update-baseline could then never ratchet a count *down*, silently defeating the
    remedy the tool prints.
    """
    mod = _mod()
    regenerated = tmp_path / "baseline.txt"
    assert mod.main(["--update-baseline", "--baseline", str(regenerated)]) == 0
    committed = REPO_ROOT / "tools" / "skill_audit_baseline.txt"
    assert regenerated.read_text(encoding="utf-8") == committed.read_text(encoding="utf-8"), (
        "the committed baseline is not what --update-baseline produces"
    )


def test_write_baseline_overwrites_rather_than_appends(tmp_path):
    mod = _mod()
    path = tmp_path / "b.txt"
    mod.write_baseline(path, [{"check": "c", "file": "f", "detail": "d", "line": 1}])
    first = path.read_text(encoding="utf-8")
    mod.write_baseline(path, [{"check": "c", "file": "f", "detail": "d", "line": 1}])
    assert path.read_text(encoding="utf-8") == first, "the baseline grew — it appends"


def test_detail_never_carries_a_line_number_at_the_call_sites(tmp_path, monkeypatch):
    """The rot risk lives at `report.defect(..., detail)`, not in `baseline_key`.

    The round's point: a test over `baseline_key()` cannot catch this, because that
    function takes no line. Two of the three call sites were unguarded — check 1 could
    have keyed on `path:line` and check 2 on a constant, and both mutations survived.
    """
    mod = _mod()
    _write(tmp_path, "target.py", "one\n")
    shared = tmp_path / "core" / "skills" / "_shared"
    shared.mkdir(parents=True)
    doc = _write(
        tmp_path,
        "SKILL.md",
        "See `target.py:99`.\n"
        "Read `_shared/does-not-exist.md`.\n"
        "Spawn an Agent with `run_in_background: true`.\n",
    )
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "SHARED_DIR", shared)
    report = mod.Report()
    mod.check_file(doc, report)
    assert {d["check"] for d in report.defects} == {
        "path-line-beyond-eof", "shared-partial-missing", "retired-referent"
    }, "the fixture stopped exercising all three checks"
    for d in report.defects:
        assert d["detail"], f"{d['check']} has an empty detail — the key collapses"
        assert not re.search(r":\d+$", d["detail"]), (
            f"{d['check']} keys on a line number ({d['detail']!r}) — the baseline will rot"
        )
    # And distinct checks must not collide on one key.
    keys = {mod.baseline_key(d["check"], d["file"], d["detail"]) for d in report.defects}
    assert len(keys) == 3

    # `detail` must also DISCRIMINATE within a check, not merely be non-empty. A constant
    # detail survived the first version of this guard: two different missing partials in
    # one file would then share a key, so baselining one would suppress the other and the
    # count would merge two unrelated defects into one allowance.
    doc2 = _write(
        tmp_path,
        "OTHER.md",
        "Read `_shared/missing-one.md` and `_shared/missing-two.md`.\n",
    )
    r2 = mod.Report()
    mod.check_file(doc2, r2)
    details = {d["detail"] for d in r2.defects if d["check"] == "shared-partial-missing"}
    assert details == {"missing-one.md", "missing-two.md"}, (
        f"check 2's detail does not discriminate between distinct partials: {details}"
    )


def test_new_defect_block_lists_the_sites(tmp_path, monkeypatch, capsys):
    """The gate's failure message says "see the NEW DEFECTS block" — it must have a body.

    Emptying the listing loop survived: both failure tests asserted only the header.
    """
    mod = _mod()
    _write(tmp_path, "target.py", "one\n")
    skills = tmp_path / "core" / "skills" / "demo"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("See `target.py:99`.\n", encoding="utf-8")
    (tmp_path / "core" / "skills" / "_shared").mkdir(parents=True)
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "SKILLS_DIR", tmp_path / "core" / "skills")
    monkeypatch.setattr(mod, "SHARED_DIR", tmp_path / "core" / "skills" / "_shared")
    assert mod.main([]) == 1
    out = capsys.readouterr().out
    assert "core/skills/demo/SKILL.md:1" in out, "NEW DEFECTS has no body"
    assert "path-line-beyond-eof" in out


def test_baselined_block_names_the_debt_not_just_the_file(tmp_path, monkeypatch, capsys):
    """Dropping `detail × count` from the per-key line survived the round's mutations.

    **Re-pointed at a SYNTHETIC corpus (Phase 233).** This drove the real tree and
    asserted on `run_in_background` debt that `Q-031` has now paid off, leaving the
    shipped baseline empty. Written that way, the guard died the moment the defect it
    described was fixed — and the only ways to revive it in place are to re-add debt or
    to weaken the assertion, both worse than the bug. It now seeds its own defect, so it
    tests the MECHANISM rather than the incidental state of the tree.
    """
    mod = _mod()
    skills = tmp_path / "core" / "skills" / "demo"
    skills.mkdir(parents=True)
    (tmp_path / "core" / "skills" / "_shared").mkdir(parents=True)
    doc = skills / "SKILL.md"
    doc.write_text(
        "Spawn an Agent with `run_in_background: true`.\n"
        "And another Agent with `run_in_background: true`.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "SKILLS_DIR", tmp_path / "core" / "skills")
    monkeypatch.setattr(mod, "SHARED_DIR", tmp_path / "core" / "skills" / "_shared")
    base = tmp_path / "baseline.txt"
    assert mod.main(["--update-baseline", "--baseline", str(base)]) == 0
    capsys.readouterr()
    assert mod.main(["--baseline", str(base)]) == 0
    named = capsys.readouterr().out.split("BASELINED")[1]
    assert "run_in_background" in named, "the block names files but not what the debt IS"
    assert "×" in named, "the block does not state multiplicity"


def test_json_contract(tmp_path, monkeypatch, capsys):
    """The `--json` payload this phase reshaped had no assertion at all.

    Three mutations survived here: exit always 0, `defects` emitting baselined entries,
    and the two new keys dropped entirely.
    """
    mod = _mod()
    import json as _json
    _write(tmp_path, "target.py", "one\n")
    skills = tmp_path / "core" / "skills" / "demo"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("See `target.py:99`.\n", encoding="utf-8")
    (tmp_path / "core" / "skills" / "_shared").mkdir(parents=True)
    monkeypatch.setattr(mod, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(mod, "SKILLS_DIR", tmp_path / "core" / "skills")
    monkeypatch.setattr(mod, "SHARED_DIR", tmp_path / "core" / "skills" / "_shared")
    base = tmp_path / "b.txt"
    assert mod.main(["--json", "--baseline", str(base)]) == 1, "--json must honor exit codes"
    payload = _json.loads(capsys.readouterr().out)
    assert {"scanned", "defects", "baselined", "stale_baseline", "worklist"} <= payload.keys()
    assert len(payload["defects"]) == 1 and payload["baselined"] == []
    # Now baseline it: `defects` must narrow to new-only, not report everything.
    mod.main(["--update-baseline", "--baseline", str(base)])
    capsys.readouterr()
    assert mod.main(["--json", "--baseline", str(base)]) == 0
    payload = _json.loads(capsys.readouterr().out)
    assert payload["defects"] == [] and len(payload["baselined"]) == 1


def test_baseline_parser_skips_comments_and_blanks(tmp_path):
    """Comment/blank/whitespace handling was unpinned in four separate mutations."""
    mod = _mod()
    path = tmp_path / "b.txt"
    path.write_text(
        "# a comment|with|pipes|9\n"
        "\n"
        "   \n"
        "  check|file|detail|2  \n",
        encoding="utf-8",
    )
    assert mod.load_baseline(path) == {mod.baseline_key("check", "file", "detail"): 2}
