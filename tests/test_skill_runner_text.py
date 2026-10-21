"""Phase 384 (`Q-409` P1, first half): the guards that enumerated `SKILL.md` see step files.

`tools/RUNNER_CORE_SPLIT_SPEC.md` § 3.2 class D: a guard that builds its population from
`glob("*/SKILL.md")` goes blind, green over a defect, the moment a skill's text moves into
`<skill>/steps/`. Phase 382 measured it for the harmlessness screen; this phase re-derived
the population (28 sites found in 16 files, not the spec's 13 in 8; ten of them by its two rounds) and
widened every one through
`tests/skill_runner_text.py`. No step file exists today, so each widening is inert on the
live tree; what shows it works is a **plant**: the defect each guard exists to catch,
written into a step file of a copied tree, must turn that guard red.

Layers:

1. the helper's own behaviour (splice, append, skips, ordering);
2. its population against the installer's: what `runner_files` scans is what
   `install.sh` ships into each skill directory (Phase 383's recursion);
3. one plant per widened site, run through the site's own test function, each beside a
   harmless plant through the same path that must stay green;
4. a static guard: no other test or tool enumerates `SKILL.md` directly, except the
   allowlisted readers that want the core alone or only the skill's name.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path

import pytest

import skill_runner_text as RT

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / "core" / "skills"


# ── 1. the helper ──────────────────────────────────────────────────────────

def _skill(tmp_path, files):
    d = tmp_path / "demo"
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return d


def test_a_marker_is_replaced_by_its_step_in_document_order(tmp_path):
    d = _skill(tmp_path, {
        "SKILL.md": "# demo\n\n## Step 1\n<!-- sysop:arm=one -->\n\n## Step 2\n<!-- sysop:arm=two -->\n",
        "steps/one.md": "ONE BODY\n",
        "steps/two.md": "TWO BODY\n",
    })
    text = RT.skill_text(d)
    assert "sysop:arm" not in text
    assert text.index("## Step 1") < text.index("ONE BODY") < text.index("## Step 2") < text.index("TWO BODY")


def test_a_marker_naming_a_missing_step_raises(tmp_path):
    d = _skill(tmp_path, {"SKILL.md": "<!-- sysop:arm=gone -->\n"})
    with pytest.raises(FileNotFoundError, match="gone"):
        RT.skill_text(d)


def test_an_unreferenced_step_file_is_still_scanned(tmp_path):
    d = _skill(tmp_path, {"SKILL.md": "core\n", "steps/orphan.md": "ORPHAN\n",
                          "steps/deeper/x.md": "DEEP\n"})
    text = RT.skill_text(d)
    assert "ORPHAN" in text and "DEEP" in text


def test_a_marker_is_matched_only_as_a_whole_line(tmp_path):
    d = _skill(tmp_path, {"SKILL.md": "see `<!-- sysop:arm=one -->` in prose\n",
                          "steps/one.md": "ONE BODY\n"})
    text = RT.skill_text(d)
    assert "see `<!-- sysop:arm=one -->` in prose" in text
    assert text.count("ONE BODY") == 1          # appended once, as unreferenced


def test_editor_text_and_the_installers_skips_are_not_runner_text(tmp_path):
    d = _skill(tmp_path, {
        "SKILL.md": "core\n",
        "REFERENCE.md": "EDITOR TEXT\n",
        "notes.md": "TOP-LEVEL SIBLING\n",
        "steps/.hidden.md": "DOTFILE\n",
        "steps/__pycache__/x.md": "PYCACHE\n",
        ".dot/a.md": "DOT DIR\n",
        "steps/real.md": "REAL\n",
        "steps/data.json": "{}\n",
    })
    (d / "linked").symlink_to("steps")
    text = RT.skill_text(d)
    for absent in ("EDITOR TEXT", "TOP-LEVEL SIBLING", "DOTFILE", "PYCACHE", "DOT DIR"):
        assert absent not in text, absent
    assert text.count("REAL") == 1               # not again through the linked directory
    assert [p.relative_to(d).as_posix() for p in RT.step_files(d)] == ["steps/real.md"]


def test_a_symlinked_directory_below_steps_is_not_followed(tmp_path):
    """The walk's own link check, not `step_files`' top-level one (author battery H04)."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "o.md").write_text("OUTSIDE\n")
    d = _skill(tmp_path, {"SKILL.md": "core\n", "steps/real.md": "REAL\n"})
    (d / "steps" / "out").symlink_to(outside)
    assert "OUTSIDE" not in RT.skill_text(d)
    assert [p.name for p in RT.step_files(d)] == ["real.md"]


def test_a_fenced_marker_is_an_example_not_an_arm(tmp_path):
    d = _skill(tmp_path, {"SKILL.md": "```\n<!-- sysop:arm=doc-example -->\n```\n"})
    assert RT.skill_text(d) == "```\n<!-- sysop:arm=doc-example -->\n```\n"


@pytest.mark.parametrize("name", ["x/../../SKILL", "../REFERENCE", "x/../one", ".hidden"])
def test_an_arm_name_cannot_leave_steps(tmp_path, name):
    d = _skill(tmp_path, {"SKILL.md": f"<!-- sysop:arm={name} -->\n", "steps/x/a.md": "a\n",
                          "steps/one.md": "one\n"})
    with pytest.raises(ValueError, match="not a path below steps"):
        RT.skill_text(d)


def test_a_spliced_step_is_not_appended_again(tmp_path):
    d = _skill(tmp_path, {"SKILL.md": "a\n<!-- sysop:arm=one -->\nb\n", "steps/one.md": "ONE\n"})
    assert RT.skill_text(d) == "a\nONE\nb\n"


def test_an_appended_step_starts_its_own_paragraph(tmp_path):
    d = _skill(tmp_path, {"SKILL.md": "core line\n", "steps/z.md": "STEP\n"})
    assert RT.skill_text(d) == "core line\n\nSTEP\n"


def test_a_step_without_a_trailing_newline_loses_nothing(tmp_path):
    d = _skill(tmp_path, {"SKILL.md": "a\n<!-- sysop:arm=one -->\nb\n", "steps/one.md": "ONE"})
    assert RT.skill_text(d) == "a\nONE\nb\n"


def test_only_a_column_0_marker_splices_until_transform_5_says_otherwise(tmp_path):
    """Pinned as built (round 2, lens B K10/K11). An indented marker is text, and its step is
    appended; trailing spaces do not stop a column-0 marker. Transform 5 (Phase 388) kept it:
    a marker is a whole line at column 0, outside any fence."""
    d = _skill(tmp_path, {"SKILL.md": "a\n  <!-- sysop:arm=one -->\nb\n<!-- sysop:arm=two -->   \nc\n",
                          "steps/one.md": "ONE\n", "steps/two.md": "TWO\n"})
    assert RT.skill_text(d) == "a\n  <!-- sysop:arm=one -->\nb\nTWO\nc\n\nONE\n"


def test_skill_of_at_depth(tmp_path):
    p = tmp_path / "a" / "steps" / "b" / "c" / "d.md"
    assert RT.skill_of(p, tmp_path) == "a"


@pytest.mark.parametrize("blank_moves", [False, True], ids=["blank-stays", "blank-moves"])
@pytest.mark.parametrize("heading", ["### 2b. Prevention Convention Check", "## Step 8: Report"])
def test_a_real_section_round_trips_byte_for_byte(tmp_path, blank_moves, heading):
    """Phase 385's slices rest on this (lens A, M3): moving a real section into a step file
    behind its marker and splicing it back gives the original file, wherever the blank line
    before the next heading went."""
    src = SKILLS / "review-close"
    d = tmp_path / "review-close"
    d.mkdir()
    # On the flattened runner text, not a copy of the tree (Phase 385): once a step has
    # moved, the section may already be a bare marker in the core, and moving that marker
    # into a step file would lose the text it names. The property is the splice's, so it
    # is measured on the real text as one file, whatever the tree's split state.
    original = RT.skill_text(src)
    lines = original.split("\n")
    h = lines.index(heading)
    nxt = next((i for i in range(h + 1, len(lines))
                if lines[i].startswith("#") and lines[i].split(" ")[0] in ("##", "###")),
               len(lines))
    end = nxt if blank_moves else nxt - 1
    assert blank_moves or lines[nxt - 1] == ""
    body = lines[h + 1:end]
    (d / "steps").mkdir()
    (d / "steps" / "moved.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    core = lines[:h + 1] + ["<!-- sysop:arm=moved -->"] + lines[end:]
    (d / "SKILL.md").write_text("\n".join(core), encoding="utf-8")
    assert RT.skill_text(d) == original


def test_runner_files_lists_each_core_then_its_steps(tmp_path):
    for name in ("a", "b"):
        (tmp_path / name / "steps").mkdir(parents=True)
        (tmp_path / name / "SKILL.md").write_text("x\n")
        (tmp_path / name / "steps" / "s.md").write_text("y\n")
    (tmp_path / "_shared").mkdir()
    (tmp_path / "_shared" / "p.md").write_text("z\n")
    got = [p.relative_to(tmp_path).as_posix() for p in RT.runner_files(tmp_path)]
    assert got == ["a/SKILL.md", "a/steps/s.md", "b/SKILL.md", "b/steps/s.md"]
    assert set(RT.runner_texts(tmp_path)) == {"a", "b"}
    assert RT.skill_of(tmp_path / "b" / "steps" / "s.md", tmp_path) == "b"


def test_today_every_skill_is_its_core_but_review_closes_arms():
    """Phase 388 (`Q-409` P2) moved the first step, review-close's `steps/4d-direct.md`, and
    Phase 390 (P4) moved `4a-append` and `4a-fix`, and Phase 393 (P4b) `4d-pr` and the two
    flag sections, and Phase 397 (P5) Step 3b's two exit arms, so the widened guards read every
    skill's core plus those eight files. When another step moves, this is the line that
    changes."""
    cores = sorted(SKILLS.glob("*/SKILL.md"))
    at = cores.index(SKILLS / "review-close" / "SKILL.md") + 1
    steps = [SKILLS / "review-close" / "steps" / f"{a}.md"
             for a in ("3b-collect-exit", "3b-rollback", "4a-append", "4a-fix", "4d-direct",
                       "4d-pr", "prepare-resume", "request-review-land")]
    assert RT.runner_files(SKILLS) == cores[:at] + steps + cores[at:]


# ── 2. the population is what the installer ships ──────────────────────────

def test_runner_files_scans_what_the_installer_ships(tmp_path):
    """Two rules written to agree are not one measurement: plant a nested tree (Phase 383's
    fixture, with its dotfile, `__pycache__/` and linked directory), install it, and compare
    each skill's installed `.md` files with what `runner_files` scans in the source."""
    import test_install_skill_subdirs as I
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy2(REPO_ROOT / "install.sh", src / "install.sh")
    for d in ("core", "packs"):
        shutil.copytree(REPO_ROOT / d, src / d,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"))
    I._git(src, "init", "-q", "-b", "main")
    I._identity(src)
    I._git(src, "add", "-A")
    I._git(src, "commit", "-qm", "source")
    I._planted(src)
    t = I._target(tmp_path)
    res = I._install(src, t, "--packs", "python")
    assert res.returncode == 0, res.stdout + res.stderr
    src_skills = src / "core" / "skills"
    want = {p.relative_to(src_skills).as_posix() for p in RT.runner_files(src_skills)}
    installed = t / ".claude" / "skills"
    got = set()
    for skill_md in installed.glob("*/SKILL.md"):
        d = skill_md.parent
        got.add(skill_md.relative_to(installed).as_posix())
        for p in d.rglob("*.md"):
            if p.parent != d:
                got.add(p.relative_to(installed).as_posix())
    assert want == got, (sorted(want - got), sorted(got - want))
    assert any("/steps/" in p for p in want), "the planted step files were not seen"


# ── 3. a plant per widened site ────────────────────────────────────────────

@pytest.fixture(scope="module")
def pristine_core(tmp_path_factory):
    root = tmp_path_factory.mktemp("rt_core")
    shutil.copytree(REPO_ROOT / "core", root / "core",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return root


@pytest.fixture
def planted(pristine_core, tmp_path, monkeypatch):
    """Return `plant(module, skill, text)`: a fresh copy of `core/`, the text written to
    `<skill>/steps/plant.md` (unreferenced, so the append path carries it), and every
    module-level path constant that has a twin in the copy re-pointed at it."""
    root = tmp_path / "root"
    shutil.copytree(pristine_core / "core", root / "core", symlinks=True)

    def plant(module, skill, text, core=None, after=None):
        """`core` is appended to the copy's SKILL.md. With `after`, a marker line naming the
        plant is inserted below the first line equal to `after`, so the text arrives through
        the splice instead of the append."""
        step = root / "core" / "skills" / skill / "steps" / "plant.md"
        step.parent.mkdir(parents=True, exist_ok=True)
        step.write_text(text, encoding="utf-8")
        skill_md = root / "core" / "skills" / skill / "SKILL.md"
        if core is not None or after is not None:
            body = skill_md.read_text(encoding="utf-8")
            if after is not None:
                lines = body.split("\n")
                k = lines.index(after)
                lines[k + 1:k + 1] = ["", "<!-- sysop:arm=plant -->", ""]
                body = "\n".join(lines)
            if core is not None:
                body = body.rstrip("\n") + "\n\n" + core
            skill_md.write_text(body, encoding="utf-8")
        def repoint(val):
            if isinstance(val, Path):
                try:
                    twin = root / val.relative_to(REPO_ROOT)
                except ValueError:
                    return val
                return twin if twin.exists() else val
            if isinstance(val, (list, tuple, set, frozenset)):
                return type(val)(repoint(v) for v in val)
            if isinstance(val, dict):
                return {repoint(k): repoint(v) for k, v in val.items()}
            return val

        # Paths inside module-level containers too: `DISPOSITION_PINS` keys its pins by
        # absolute path, and a copied tree's consumers matched none of them, so every
        # site there read red for the wrong reason until its control caught it.
        for name, val in list(vars(module).items()):
            if isinstance(val, (Path, list, tuple, set, frozenset, dict)) \
                    and not name.startswith("__"):
                new = repoint(val)
                if new != val:
                    monkeypatch.setattr(module, name, new)
        return root

    return plant


def _no_preflight_skill(perm):
    """A skill with no pre-flight of its own and no declared rules, so a planted pre-flight
    is the one the reader finds."""
    for name, text in RT.runner_texts(SKILLS).items():
        if name not in perm.SKILLS_WITH_DECLARED_RULES and perm._preflight_body(text) is None:
            return name
    pytest.fail("every skill has a pre-flight; pick another plant site")


PLANTS = [
    # (id, module, test function, kwargs, skill, defect, harmless)
    ("screens-gh", "test_review_close_screens",
     "test_no_hook_paragraph_promises_coverage_for_a_gh_command", {}, "review-close",
     "The Phase 36 `PermissionDenied` hook fires here, and it surfaces the "
     "`! gh pr merge 12 --squash` escape for you.\n",
     "Nothing about hooks here.\n"),
    ("screens-census", "test_review_close_screens", "test_the_hook_mention_census_is_unchanged",
     {}, "review-close",
     "The `PermissionDenied` hook matches three git shapes only.\n",
     "Nothing about hooks here.\n"),
    ("screens-harmless", "test_review_close_screens",
     "test_no_shipped_prose_claims_a_doc_only_diff_is_harmless", {}, "review-close",
     "A docs-only diff cannot regress code-level lint or typecheck, after all.\n",
     "A doc-only cycle never bypasses this gate.\n"),
    ("screens-step-number", "test_review_close_screens",
     "test_no_shipped_prose_scopes_hook_coverage_by_step_number", {}, "review-close",
     "The `PermissionDenied` hook covers the git patterns in Steps 4c/4d/6.\n",
     "Nothing about hooks here.\n"),
    ("screens-open-ended", "test_review_close_screens",
     "test_no_shipped_prose_claims_open_ended_hook_coverage", {}, "review-close",
     "When any close-critical command is denied mid-cycle, though, the Phase 36 "
     "`PermissionDenied` hook surfaces the `!`-escape form to relay.\n",
     "Nothing about hooks here.\n"),
    ("batch-twins", "test_batch_status_vocabulary",
     "test_no_skill_knows_one_twin_without_the_other", {}, "add-task",
     "A batch reads Review Ready here.\n",
     "A batch reads Review Ready here, and Ready for Review once closed.\n"),
    ("batch-selector", "test_batch_selector",
     "test_the_population_is_the_two_skills_that_lacked_a_selector", {}, "add-task",
     "Parse the argument → the concurrency cap.\n",
     "Parse the argument.\n"),
    ("friction-readers", "test_friction_log_entry_boundaries",
     "test_the_population_of_readers_is_derived_and_complete", {}, "add-task",
     "Classify each entry in SYSOP_ISSUES.md by kind.\n",
     "Read SYSOP_ISSUES.md.\n"),
    ("give-back-edit-claim", "test_give_back_body_file",
     "test_no_skill_says_a_file_edit_needs_no_rule", {"skill": "review-close"}, "review-close",
     "This edit needs no allow-rule.\n",
     "This edit needs an allow-rule.\n"),
    ("isolation-carve-out", "test_adversarial_review_gate",
     "test_the_procedure_does_not_contradict_the_skills_that_consume_it", {}, "add-task",
     'Do NOT set `isolation: "worktree"` on this spawn.\n',
     "Spawn it as usual.\n"),
    ("blocker-consumer", "test_blocker_halt_contract",
     "test_every_rubric_consumer_has_a_pinned_disposition", {}, "add-task",
     "Run it under `_shared/adversarial-review.md`; a blocker halts the run.\n",
     "Run it under `_shared/adversarial-review.md`.\n"),
    ("loop-worktree-rule", "test_loop_worktree_placement",
     "test_every_loop_runner_worktree_command_has_a_loop_rule", {}, "codebase-review",
     "```bash\ngit worktree frobnicate \"$X\"\n```\n",
     "```bash\necho placed\n```\n"),
    ("claim-commit-rule", "test_permission_surface_drift",
     "test_the_unbound_claim_commit_rule_stays_deleted", {}, "add-task",
     "Then run git commit -m claim for it.\n",
     "Then commit it.\n"),
    ("unquoted-summary", "test_pending_doc_integrity",
     "test_no_shipped_file_emits_an_unquoted_summary", {}, "review-close",
     "```yaml\nsummary: Batch 3 complete: done\n```\n",
     "```yaml\nsummary: \"Batch 3 complete: done\"\n```\n"),
    ("pending-writer", "test_pending_doc_integrity",
     "test_every_pending_doc_writer_emits_branch_tip", {}, "add-task",
     "```yaml\nbranch: x\nsummary: \"y\"\nbranch_tip: z\n```\n",
     "```yaml\nnot_a_doc: x\n```\n"),
    ("runtime-write", "test_runtime_probe_skill_paths",
     "test_the_derivation_finds_exactly_the_census_per_writer", {}, "add-task",
     "mkdir -p \"<worktree>/plant-scratch\"\n",
     "mkdir -p nothing-anchored\n"),
    ("runtime-write-shared", "test_runtime_probe_skill_paths",
     "test_the_derivation_finds_exactly_the_census_per_writer", {}, "_shared",
     "mkdir -p \"<worktree>/plant-scratch\"\n",
     "mkdir -p nothing-anchored\n"),
    # Phase 384's round: four more sites, found by the lenses, not by the phase's grep.
    ("mid-turn-invocation", "test_reasoning_role_split",
     "test_no_skill_invokes_a_cheaper_pinned_skill_mid_turn", {}, "auto-build",
     "Invoke `/next-task` via the Skill tool.\n",
     "Read `/next-task`'s output.\n"),
    ("release-flag", "test_batch_selector",
     "test_neither_sibling_prescribes_a_release_flag_that_does_not_exist", {}, "auto-fix",
     "Then run close_batch.sh --release 3.\n",
     "Then run batch_work.sh --release 3.\n"),
    ("unmeasured-conflation", "test_review_close_merge_write_path",
     "test_all_three_surfaces_name_the_unmeasured_state_the_same_way", {}, "auto-fix",
     "On a timeout, treat as failure and report it.\n",
     "On a timeout, report VERIFY: TIMEOUT.\n"),
    # Phase 384's round 2: six more, each a negative scan over a hardcoded skill.
    ("merged-gate-skip", "test_review_close_screens",
     "test_nothing_says_the_merged_tree_gate_inherits_the_skip", {}, "review-close",
     "The merged-tree pass inherits this skip as well — a docs cycle that skipped here skips there too.\n",
     "`4a-post` therefore does not inherit this skip.\n"),
    ("item-4-scope", "test_review_close_screens",
     "test_every_reference_to_item_4s_skip_says_which_pass_owns_it", {}, "review-close",
     "**Each pass scopes itself to its own tree, with one command.** Item 3's surface "
     "gate and item 4's doc-only skip both read the list this prints:\n",
     "Nothing about item four here.\n"),
    ("2devnull-claim", "test_git_add_staging_discipline",
     "test_the_false_2devnull_tolerance_claim_is_gone", {}, "codebase-review",
     "`2>/dev/null` tolerates their absence in the source repo.\n",
     "`git add` is all-or-nothing across its pathspecs.\n"),
    ("give-back-tmp", "test_give_back_body_file",
     "test_no_give_back_skill_stages_outside_the_project", {"skill": "report-issues"}, "report-issues",
     "Stage the body at /tmp/sysop-issue.md first.\n",
     "Stage the body under the project first.\n"),
    ("give-back-reader", "test_give_back_body_file",
     "test_every_staged_file_reader_takes_the_printed_path", {"skill": "report-issues"}, "report-issues",
     "```bash\ngh issue create --body-file \"$TMPDIR/sysop-issue.md\"\n```\n",
     "```bash\necho nothing staged here\n```\n"),
    ("give-back-stray-expr", "test_give_back_body_file",
     "test_every_staging_site_is_resolved_once_and_carries_both_arms", {"skill": "report-issues"},
     "report-issues",
     "Then `Write` it to `$(git rev-parse --show-toplevel)/$(git rev-parse --show-prefix)"
     "sysop/runtime/giveback/sysop-issue-<n>.md`.\n",
     "Then `Write` it where the echo said.\n"),
    ("root-location", "test_phase128_path_drift",
     "test_the_pre_128_fallback_prose_is_not_flagged", {}, "review-close",
     "Hit any Sysop friction while planning (a confusing step, a rough edge)? Note it\n"
     "in SYSOP_ISSUES.md at the repo root — /report-issues sends the keepers upstream.\n",
     "Nothing about the friction log here.\n"),
]


def _run(planted, mod_name, fn, kwargs, skill, text):
    module = importlib.import_module(mod_name)
    planted(module, skill, text)
    getattr(module, fn)(**kwargs)


@pytest.mark.parametrize("pid,mod_name,fn,kwargs,skill,defect,harmless", PLANTS,
                         ids=[p[0] for p in PLANTS])
def test_a_defect_in_a_step_file_turns_the_guard_red(planted, pid, mod_name, fn, kwargs,
                                                     skill, defect, harmless):
    with pytest.raises(AssertionError):
        _run(planted, mod_name, fn, kwargs, skill, defect)


@pytest.mark.parametrize("pid,mod_name,fn,kwargs,skill,defect,harmless", PLANTS,
                         ids=[p[0] for p in PLANTS])
def test_a_harmless_step_file_keeps_the_guard_green(planted, pid, mod_name, fn, kwargs,
                                                    skill, defect, harmless):
    _run(planted, mod_name, fn, kwargs, skill, harmless)


def test_a_step_files_runtime_write_counts_for_its_skill(planted):
    """A counted writer's step file adds to that writer's census, under the skill's name, not
    `steps` (author battery D15: every other plant used an uncounted skill)."""
    rp = importlib.import_module("test_runtime_probe_skill_paths")
    planted(rp, "auto-build", 'mkdir -p "<worktree>/plant-scratch"\n')
    sites = [s for s in rp.derive_sites() if s[2] == "plant-scratch"]
    assert [s[0] for s in sites] == ["auto-build"], sites


@pytest.mark.parametrize("pid,mod_name,fn,kwargs,skill,defect,harmless", PLANTS,
                         ids=[p[0] for p in PLANTS])
def test_a_defect_in_editor_text_counts_for_nothing(planted, pid, mod_name, fn, kwargs,
                                                     skill, defect, harmless):
    """`REFERENCE.md` is not runner text: each defect written there leaves its guard green,
    so a site widened to every `*.md` would show here. (`_shared/` has no editor text: a
    top-level file there is a partial the runner reads.)"""
    if skill == "_shared":
        pytest.skip("every top-level _shared/ file is a partial, i.e. runner text")
    module = importlib.import_module(mod_name)
    root = planted(module, skill, harmless)
    ref = root / "core" / "skills" / skill / "REFERENCE.md"
    ref.write_text((ref.read_text(encoding="utf-8") if ref.exists() else "") + "\n" + defect,
                   encoding="utf-8")
    getattr(module, fn)(**kwargs)


@pytest.mark.parametrize("where", ["## Step 8: Report"])
def test_a_defect_spliced_into_a_late_section_turns_the_screens_red(planted, where):
    """Phase 384's round, lens A: `_prose_only` paired fences with a lazy regex, so prose from
    ~line 1405 to the end of review-close was blanked and a claim spliced into Step 8 went
    unseen; every other plant passed because the append put it after the last fence. This
    one arrives through a real marker."""
    screens = importlib.import_module("test_review_close_screens")
    planted(screens, "review-close", "Nothing about hooks here.\n", after=where)
    screens.test_no_hook_paragraph_promises_coverage_for_a_gh_command()
    planted(screens, "review-close",
            "The Phase 36 `PermissionDenied` hook fires here, and it surfaces the "
            "`! gh pr merge 12 --squash` escape for you.\n", after=where)
    with pytest.raises(AssertionError):
        screens.test_no_hook_paragraph_promises_coverage_for_a_gh_command()


def test_the_splice_plant_arrives_through_the_marker(planted):
    """The late-section test's premise (round 2, lens B): the plant must land below its
    heading and before the rest of the file, or it proves nothing the append did not."""
    screens = importlib.import_module("test_review_close_screens")
    root = planted(screens, "review-close", "PLANTED-THROUGH-MARKER\n", after="## Step 8: Report")
    d = root / "core" / "skills" / "review-close"
    assert "<!-- sysop:arm=plant -->" in (d / "SKILL.md").read_text(encoding="utf-8")
    text = RT.skill_text(d)
    i = text.index("PLANTED-THROUGH-MARKER")
    assert text.count("PLANTED-THROUGH-MARKER") == 1
    assert text.index("## Step 8: Report") < i
    assert text[i:].strip() != "PLANTED-THROUGH-MARKER", "arrived by append, at the end"


def test_a_fenced_comment_spliced_late_is_screened(planted):
    """`_fence_comment_lines` had the lazy regex's desync too (round 2, both lenses): a
    fenced instruction comment past ~line 1548 was read as prose and missed."""
    screens = importlib.import_module("test_review_close_screens")
    planted(screens, "review-close", "```bash\n# a harmless note\necho ok\n```\n",
            after="## Step 8: Report")
    screens.test_nothing_says_the_merged_tree_gate_inherits_the_skip()
    planted(screens, "review-close",
            "```bash\n# On a doc-only assembled diff, 4a-post inherits item 4's skip: echo SKIP and go to 4b\n"
            "echo ok\n```\n", after="## Step 8: Report")
    with pytest.raises(AssertionError):
        screens.test_nothing_says_the_merged_tree_gate_inherits_the_skip()


def test_prose_only_blanks_fenced_lines():
    screens = importlib.import_module("test_review_close_screens")
    out = screens._prose_only("before\n```bash\nFENCED\n```\nafter\n")
    assert "FENCED" not in out and "before" in out and "after" in out


def test_twins_split_across_core_and_step_are_one_skill_knowing_both(planted):
    """The reason the twin check reads per skill (lens B survivor S01): a core naming one
    twin and a step naming the other is a skill that knows both."""
    bv = importlib.import_module("test_batch_status_vocabulary")
    planted(bv, "add-task", "Once closed it reads Ready for Review.\n",
            core="A batch reads Review Ready here.\n")
    bv.test_no_skill_knows_one_twin_without_the_other()
    planted(bv, "add-task", "Nothing here.\n")
    with pytest.raises(AssertionError):
        bv.test_no_skill_knows_one_twin_without_the_other()


@pytest.mark.parametrize("fn,defect", [
    ("test_parsers_find_the_surface", "## Pre-flight\n\n- `Bash(frobnicate:*)`\n\n## After\n"),
    ("test_hard_stopping_skills_point_at_the_mode_check",
     "## Pre-flight\n\nIf it is missing, Do not proceed.\n\n## After\n"),
], ids=["declared-rules", "hard-stop-escape"])
def test_a_preflight_in_a_step_file_is_read(planted, fn, defect):
    perm = importlib.import_module("test_permission_surface_drift")
    skill = _no_preflight_skill(perm)
    planted(perm, skill, "## After\n")
    getattr(perm, fn)()                         # control: green with no pre-flight planted
    planted(perm, skill, defect)
    with pytest.raises(AssertionError):
        getattr(perm, fn)()


def _audit():
    script = REPO_ROOT / "tools" / "skill_audit_refs.py"
    if not script.is_file():
        pytest.skip("tools/ is maintainer-side and excluded from the public mirror")
    spec = importlib.util.spec_from_file_location("skill_audit_refs_rt", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("where", ["review-close/steps/plant.md", "_shared/partial-dir/plant.md"])
def test_the_skill_audit_corpus_reads_step_files_and_shared_subdirectories(pristine_core,
                                                                           tmp_path, where):
    mod = _audit()
    root = tmp_path / "root"
    shutil.copytree(pristine_core / "core", root / "core", symlinks=True)
    skills = root / "core" / "skills"
    plant = skills / where
    plant.parent.mkdir(parents=True, exist_ok=True)
    plant.write_text("See `core/companion/scripts/self_check.sh:999999`.\n", encoding="utf-8")
    mod.REPO_ROOT, mod.SKILLS_DIR, mod.SHARED_DIR = root, skills, skills / "_shared"
    assert plant in mod.corpus(loop_only=False)
    report = mod.Report()
    for path in mod.corpus(loop_only=False):
        mod.check_file(path, report)
    hits = [d for d in report.defects if d["check"] == "path-line-beyond-eof"]
    assert hits and all(where.split("/")[-1] in json.dumps(d) for d in hits), hits


def test_the_skill_audit_loop_corpus_filters_a_shared_directory_by_name(pristine_core, tmp_path):
    mod = _audit()
    root = tmp_path / "root"
    shutil.copytree(pristine_core / "core", root / "core", symlinks=True)
    skills = root / "core" / "skills"
    excluded = sorted(mod.LOOP_EXCLUDE_SHARED)[0][:-len(".md")]
    for d in (excluded, "kept-partials"):
        (skills / "_shared" / d).mkdir()
        (skills / "_shared" / d / "x.md").write_text("x\n")
    (skills / "codebase-review" / "steps").mkdir()
    (skills / "codebase-review" / "steps" / "s.md").write_text("s\n")
    mod.REPO_ROOT, mod.SKILLS_DIR, mod.SHARED_DIR = root, skills, skills / "_shared"
    got = {p.relative_to(skills).as_posix() for p in mod.corpus(loop_only=True)}
    assert "_shared/kept-partials/x.md" in got
    assert f"_shared/{excluded}/x.md" not in got
    assert "codebase-review/steps/s.md" in got


def test_the_skill_audit_corpus_keeps_the_installers_skips_at_depth(pristine_core, tmp_path):
    """Lens B survivors S05/S06: `_below`'s link and dot/`__pycache__` filters, below the
    first level as well as at it."""
    mod = _audit()
    root = tmp_path / "root"
    shutil.copytree(pristine_core / "core", root / "core", symlinks=True)
    skills = root / "core" / "skills"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "o.md").write_text("o\n")
    rc = skills / "review-close"
    for rel in ("steps/real.md", "steps/deep/__pycache__/p.md", "steps/deep/.dot/d.md",
                "steps/.hidden.md", "__pycache__/top.md"):
        (rc / rel).parent.mkdir(parents=True, exist_ok=True)
        (rc / rel).write_text("x\n")
    (rc / "steps" / "deep" / "linked").symlink_to(outside)
    (rc / "linked-top").symlink_to(outside)
    mod.REPO_ROOT, mod.SKILLS_DIR, mod.SHARED_DIR = root, skills, skills / "_shared"
    got = sorted(p.relative_to(rc).as_posix() for p in mod.corpus(loop_only=False)
                 if p.is_relative_to(rc))
    # Whatever step files review-close already has, plus the one planted here (Phase 385:
    # the first move would otherwise have had to edit this line).
    have = [p.relative_to(SKILLS / "review-close").as_posix()
            for p in RT.step_files(SKILLS / "review-close")]
    assert got == ["SKILL.md", *sorted(have + ["steps/real.md"])], got


def test_the_role_census_counts_a_step_file_for_its_skill():
    """Lens A, M2: `tools/phase223_role_census.py` named `review-close/steps/2b.md` skill
    `2b`, which put its pins past LOOP_EXCLUDE_SKILLS in the loop-mode count."""
    script = REPO_ROOT / "tools" / "phase223_role_census.py"
    if not script.is_file():
        pytest.skip("tools/ is maintainer-side and excluded from the public mirror")
    spec = importlib.util.spec_from_file_location("phase223_role_census_rt", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    assert mod._skill_name("core/skills/review-close/steps/2b.md") == "review-close"
    assert mod._skill_name("core/skills/review-close/steps/deep/x.md") == "review-close"
    assert mod._skill_name("core/skills/review-close/SKILL.md") == "review-close"
    assert mod._skill_name("core/skills/_shared/adversarial-review.md") == "adversarial-review"


# ── 4. nothing else enumerates SKILL.md ────────────────────────────────────

# A `glob`/`rglob`/`glob.glob` call whose string pattern ends in `SKILL.md`, with any path
# prefix and any string prefix (`f`, `r`). Phase 384's round widened it from `*/SKILL.md`
# alone. It still cannot see an `iterdir()` or `os.walk` loop, a pattern built by
# concatenation or held in a constant, or a `/ "SKILL.md"` read. Phase 385 repointed
# review-close's `/ "SKILL.md"` readers and guards that read spelling for review-close in
# `test_review_close_runner_reads.py`; another skill's readers stay unflagged until it splits.
ENUMERATION = re.compile(
    r"""\b(?:r?glob|glob\.glob)\(\s*[frFR]{0,2}(['"])[^'"\n]*SKILL\.md\1"""
    r"""|\bglob\.glob\([^\n]*SKILL\.md""")

# Each reader that may enumerate `SKILL.md` directly, and why.
ALLOWED = {
    "tests/skill_runner_text.py": "the helper itself: one skill directory per SKILL.md",
    "tests/test_skill_runner_text.py": "this module: the static guard and the live-tree identity check",
    "tests/test_reader_census.py": "class E: the census measures the core by design",
    "tests/test_skill_frontmatter_parses.py": "class E: frontmatter lives in SKILL.md only",
    "tests/test_close_arms.py": "skill directories, for the marker map: a marker lives in the core, its step under steps/",
    "tests/test_skill_audit_refs.py": "the skill NAMES on disk, compared with LOOP_SKILLS",
    "tests/test_give_back_body_file.py": "the skill NAMES to parametrize over; the text is skill_text",
    "tests/test_self_check_sh.py": "a consumer's installed tree, not the source skills",
    "tests/test_phantom_shell_vars.py": "a docstring quoting a past narrowing, not a call",
    "tools/skill_audit_refs.py": "one SKILL.md per skill, then its step files (_below)",
    "tools/reader_census.py": "the skill NAMES in a usage message",
}

# Author batteries quote the shapes they mutate; they are not readers.
_BATTERY = re.compile(r"(_mutations\d*\.py|mutation_battery\.py)$")


def _readers():
    files = sorted(REPO_ROOT.glob("tests/*.py")) + sorted(
        p for p in REPO_ROOT.glob("tools/*.py") if not _BATTERY.search(p.name))
    return {p.relative_to(REPO_ROOT).as_posix(): p.read_text(encoding="utf-8") for p in files}


def _offenders(readers, allowed):
    return {rel: [ln for ln in text.splitlines() if ENUMERATION.search(ln)]
            for rel, text in readers.items()
            if rel not in allowed and ENUMERATION.search(text)}


def _stale(readers, allowed):
    return [rel for rel in allowed if rel not in readers or not ENUMERATION.search(readers[rel])]


def test_no_other_reader_enumerates_skill_md_directly():
    offenders = _offenders(_readers(), ALLOWED)
    assert not offenders, (
        "these enumerate `SKILL.md` alone, which goes blind when a skill's text moves "
        f"into steps/ — use tests/skill_runner_text.py, or allowlist with a reason: {offenders}")


def _without_stripped(allowed):
    """The public mirror strips tools/, so its allowlisted readers are absent there by design."""
    if (REPO_ROOT / "tools").is_dir():
        return allowed
    return {k: v for k, v in allowed.items() if not k.startswith("tools/")}


def _skip_without_tools():
    if not (REPO_ROOT / "tools").is_dir():
        pytest.skip("tools/ is mirror-excluded; this runs in the source repo")


def test_the_mirror_skips_stay_off_in_the_source_repo():
    """The skips above exist for the public mirror. In the source repo they must not fire, or
    this module's guards would skip in CI with nothing red."""
    if not (REPO_ROOT / "tests" / "test_mirror_leak_gate.py").is_file():
        pytest.skip("the public mirror, where these skips are meant to fire")
    assert _without_stripped(ALLOWED) == ALLOWED
    try:
        _skip_without_tools()
    except pytest.skip.Exception as e:
        pytest.fail(f"a mirror skip fired in the source repo: {e}")


def test_every_allowlisted_reader_exists_and_still_enumerates():
    stale = _stale(_readers(), _without_stripped(ALLOWED))
    assert not stale, f"allowlist entries that are gone or no longer enumerate SKILL.md: {stale}"


def test_the_guard_reads_tools_as_well_as_tests():
    _skip_without_tools()
    readers = _readers()
    assert any(r.startswith("tools/") for r in readers)
    assert "tools/phase223_role_census.py" in readers, "a non-battery tool was excluded"
    assert not any(_BATTERY.search(r) for r in readers if r.startswith("tools/"))


def test_the_guard_functions_judge_synthetic_readers():
    bad = {"tests/x.py": 'for p in d.glob("*/SKILL.md"): pass\n'}
    assert _offenders(bad, {}) == {"tests/x.py": ['for p in d.glob("*/SKILL.md"): pass']}
    assert _offenders(bad, {"tests/x.py": "why"}) == {}
    assert _stale({"tests/x.py": "nothing\n"}, {"tests/x.py": "why"}) == ["tests/x.py"]
    assert _stale({}, {"tests/gone.py": "why"}) == ["tests/gone.py"]


@pytest.mark.parametrize("line", [
    'for p in sorted(SKILLS.glob("*/SKILL.md")):',
    "x = list(root.rglob('SKILL.md'))",
    'files = d.glob("**/SKILL.md")',
    'files = d.glob( "*/SKILL.md" )',
    'files = REPO.glob("core/skills/*/SKILL.md")',
    'files = d.glob(f"{prefix}/SKILL.md")',
    "files = d.glob(r'./*/SKILL.md')",
    'files = glob.glob(str(SKILLS / "*" / "SKILL.md"))',
    'files = d.glob("[!_]*/SKILL.md")',
])
def test_the_enumeration_pattern_sees_each_spelling(line):
    assert ENUMERATION.search(line), line


@pytest.mark.parametrize("line", [
    'text = (SKILLS / "review-close" / "SKILL.md").read_text()',
    'files = d.glob("*.md")',
])
def test_the_enumeration_pattern_leaves_a_single_read_alone(line):
    assert not ENUMERATION.search(line), line
