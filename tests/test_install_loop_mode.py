"""Integration tests for install.sh's loop mode (`--mode loop`, Phase 123).

Loop mode ships only the convention loop — the audit/review skills, maps,
compiled checks, and the review_tasks.md ledger — into a repo whose owner keeps
their own branching/merge workflow. No tasks/ queue, no worktrees, no merge-gate
skill, no root workflow docs. The loop/full split runs entirely through core:
install.sh filters the skill/script/permission lists and skips two pipeline
steps (see LOOP_ONLY_SPEC.md).

These tests are the **drift guard** the install.sh exclude-list comments point
at. Two layers:

  1. Static classification — every skill / _shared partial / companion script in
     the source tree must be bucketed as loop-side or lifecycle-side here, and
     the buckets must agree with install.sh's LOOP_EXCLUDE_* lists. A NEW
     upstream skill/script that nobody classified fails the suite loudly, rather
     than silently leaking into (or dropping out of) the "smallest install".

  2. End-to-end — a real `--mode loop` install must ship *exactly* the loop
     bundle and nothing lifecycle, write the 14-rule hookless settings.json,
     leave a clean root footprint, record `mode: loop`, and satisfy the full
     mode/update state machine (preserve on --update, additive loop→full
     upgrade, rejected full→loop downgrade).

Design intent under test: the loop bundle is a *carving*, so the exact set is the
contract — an over-ship (a lifecycle file leaking in) undercuts the footprint
pitch, an under-ship (a loop file dropped) breaks the loop.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"

# ── The loop bundle contract (leg-1 audit, LOOP_ONLY_SPEC § The bundle) ──
LOOP_SKILLS = {
    "codebase-review", "security-audit", "test-audit",
    "report-issues", "contribute-convention", "_shared",
}
EXCLUDED_SKILLS = {
    "intake", "add-task", "claim-task", "auto-build", "auto-fix", "auto-judge",
    "next-task", "roadmap", "sitrep", "triage", "plan-review", "document-work",
    "review-close", "onboard", "daily-summary", "release", "share-wins",
    "pr-dependabot",
}
# _shared partials, by stem (install.sh's list is stem-only; files carry .md).
LOOP_SHARED_STEMS = {
    "adversarial-review", "permission-guard",
    "promotion-write-target", "test-assessment-rubric",
}
EXCLUDED_SHARED_STEMS = {
    "decomposition-rubric", "guided-mode", "main-push-guard", "ui-verify",
}
# Companion scripts (files). run_checks/ is a directory, kept in both modes.
LOOP_SCRIPTS = {
    "_log.py", "_model_roles.py", "archive_review_tasks.py",
    "check_skill_models.py", "install_hooks.sh", "migrate_skill_model.py",
    "resolve_skill_models.py", "review_index.py", "run_checks_impl.py",
    "run_checks.sh", "sysop-update.sh",
}
EXCLUDED_SCRIPTS = {
    "backfill_completed_dates.py", "batch_work.sh", "claim_task.sh",
    "cleanup_worktrees.sh", "close_batch.sh", "next_task.py",
    "parse_subagent_envelope.py", "permission_denied_hook.py",
    "pr_dependabot.py", "scope_overlap.py", "sitrep_survey.py",
    "validate_tasks.py",
}
LOOP_ALLOW_COUNT = 14
# The exact loop-mode allow-list (LOOP_ONLY_SPEC § "Leg 1 findings"). Asserting
# the *set*, not just the count, is what stops a wrong-but-14 permission set
# (e.g. a dropped `gh release create` swapped in for a loop rule) shipping green.
EXPECTED_LOOP_ALLOW = {
    "Bash(git add review_tasks.md)",
    "Bash(git commit -m docs:*)",
    "Bash(bash sysop/scripts/run_checks.sh)",
    "Bash(bash sysop/scripts/run_checks.sh:*)",
    "Bash(bash sysop/scripts/install_hooks.sh)",
    "Bash(bash sysop/scripts/sysop-update.sh)",
    "Bash(bash sysop/scripts/sysop-update.sh:*)",
    "Bash(python sysop/scripts/archive_review_tasks.py:*)",
    "Bash(python3 sysop/scripts/archive_review_tasks.py:*)",
    "Bash(.venv/bin/python3 sysop/scripts/archive_review_tasks.py:*)",
    "Bash(python3 -c:*)",
    "Bash(python3 -:*)",
    "Bash(gh issue list:*)",
    "Bash(gh issue create:*)",
}
# Loop mode's enforcement payload — checks are the merge gate here, so these must
# ship (a refactor that gated any behind loop mode would leave a loop with
# nothing to enforce; only lifecycle-absence was tested before).
LOOP_ENFORCEMENT_FILES = (
    ".claude/checks.yml", ".claude/convention_map.md",
    ".claude/security_map.md", ".claude/served_models.yml",
)
ROOT_LIFECYCLE_FILES = ("WORKFLOW.md", "WORKFLOW_GUIDE.md", "SYSOP_ISSUES.md")


# ── subprocess helpers (mirror test_install_detect.py) ──
def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_consumer(root, files=None):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    for rel, content in (files or {"README.md": "# scratch\n"}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(target, *extra, expect_rc=0):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    result = subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == expect_rc, (
        f"expected rc={expect_rc}, got {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    return result


def _commit_all(root, msg="apply"):
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", msg)


def _install_sh_list(varname):
    text = INSTALL_SH.read_text()
    m = re.search(rf'^{re.escape(varname)}="([^"]*)"', text, re.MULTILINE)
    assert m, f"{varname}= not found in install.sh"
    return set(m.group(1).split())


def _install_sh_loop_allow():
    """The Bash(...) keep-set from install.sh's LOOP_ALLOW python heredoc — the
    source of truth the filtered settings.json is built from. Extracted so the
    test and install.sh can't silently drift (the exclude lists already have this
    cross-check; the permission keep-set lacked one)."""
    text = INSTALL_SH.read_text()
    m = re.search(r"LOOP_ALLOW = \{(.*?)\}", text, re.S)
    assert m, "LOOP_ALLOW block not found in install.sh"
    return set(re.findall(r'"(Bash\([^"]*\))"', m.group(1)))


def _lock(target):
    return json.loads((Path(target) / ".claude" / "sysop.lock").read_text())


def _fresh_loop(tmp_path, name="c", files=None):
    root = _make_consumer(tmp_path / name, files)
    _run(root, "--packs", "", "--mode", "loop")
    return root


# ── Layer 1: static classification drift guard ──
class TestClassificationComplete:
    def test_every_source_skill_is_bucketed(self):
        src = {d.name for d in (REPO_ROOT / "core/skills").iterdir() if d.is_dir()}
        unclassified = src - LOOP_SKILLS - EXCLUDED_SKILLS
        assert not unclassified, (
            f"unclassified skill(s): {sorted(unclassified)} — classify each as "
            "loop (LOOP_SKILLS) or lifecycle (LOOP_EXCLUDE_SKILLS in install.sh "
            "+ EXCLUDED_SKILLS here)."
        )

    def test_every_source_shared_partial_is_bucketed(self):
        src = {p.stem for p in (REPO_ROOT / "core/skills/_shared").glob("*.md")}
        unclassified = src - LOOP_SHARED_STEMS - EXCLUDED_SHARED_STEMS
        assert not unclassified, (
            f"unclassified _shared partial(s): {sorted(unclassified)} — a new "
            "partial must join the loop closure or the exclude list."
        )

    def test_every_source_script_is_bucketed(self):
        scripts_dir = REPO_ROOT / "core/companion/scripts"
        src = {
            p.name for p in scripts_dir.iterdir()
            if p.is_file() and p.name != "__pycache__"
        }
        unclassified = src - LOOP_SCRIPTS - EXCLUDED_SCRIPTS
        assert not unclassified, (
            f"unclassified companion script(s): {sorted(unclassified)} — classify "
            "each as loop (LOOP_SCRIPTS) or lifecycle (LOOP_EXCLUDE_SCRIPTS in "
            "install.sh + EXCLUDED_SCRIPTS here)."
        )

    def test_install_sh_exclude_lists_match_this_suite(self):
        assert _install_sh_list("LOOP_EXCLUDE_SKILLS") == EXCLUDED_SKILLS
        assert _install_sh_list("LOOP_EXCLUDE_SHARED") == EXCLUDED_SHARED_STEMS
        assert _install_sh_list("LOOP_EXCLUDE_SCRIPTS") == EXCLUDED_SCRIPTS


# ── Layer 2: end-to-end loop install ──
class TestLoopBundleExact:
    def test_skills_shipped_are_exactly_the_loop_set(self, tmp_path):
        root = _fresh_loop(tmp_path)
        shipped = {d.name for d in (root / ".claude/skills").iterdir() if d.is_dir()}
        assert shipped == LOOP_SKILLS

    def test_shared_partials_are_exactly_the_closure(self, tmp_path):
        root = _fresh_loop(tmp_path)
        shipped = {p.stem for p in (root / ".claude/skills/_shared").glob("*.md")}
        assert shipped == LOOP_SHARED_STEMS

    def test_scripts_shipped_are_exactly_the_loop_set(self, tmp_path):
        root = _fresh_loop(tmp_path)
        shipped = {
            p.name for p in (root / "sysop" / "scripts").iterdir()
            if p.is_file()
        }
        assert shipped == LOOP_SCRIPTS
        # run_checks/ package still ships as a directory.
        assert (root / "sysop/scripts/run_checks").is_dir()

    def test_no_lifecycle_script_leaks(self, tmp_path):
        root = _fresh_loop(tmp_path)
        for name in EXCLUDED_SCRIPTS:
            assert not (root / "sysop" / "scripts" / name).exists(), f"leaked: {name}"

    def test_shipped_skills_do_not_invoke_dropped_scripts(self, tmp_path):
        """No shipped skill *invokes* a dropped script or *includes* a dropped
        _shared partial. Functional refs only — a prose mention of a lifecycle
        script (e.g. adversarial-review.md describing the SubagentStop hook, a
        partial it shares with full mode) is inert in loop mode, not a break."""
        root = _fresh_loop(tmp_path)
        blob = "\n".join(
            p.read_text() for p in (root / ".claude/skills").rglob("*.md")
        )
        for name in EXCLUDED_SCRIPTS:
            # An invocation looks like `bash sysop/scripts/x`, `python3 sysop/scripts/x`,
            # `.venv/bin/python3 sysop/scripts/x` — a verb immediately before the path.
            pat = re.compile(
                rf"(?:bash|python3?|\.venv/bin/python3)\s+sysop/scripts/{re.escape(name)}"
            )
            assert not pat.search(blob), f"loop skill invokes dropped script {name}"
        for stem in EXCLUDED_SHARED_STEMS:
            # An include/read directive (skills say "read _shared/x.md" / "per
            # _shared/x.md"). Bare backtick mentions are prose.
            pat = re.compile(
                rf"(?:read|see|per|follow|load)\s+`?_shared/{re.escape(stem)}\.md"
            )
            assert not pat.search(blob), f"loop skill includes dropped partial {stem}.md"


class TestLoopSettings:
    def test_allow_is_exactly_the_loop_set_and_no_hooks(self, tmp_path):
        root = _fresh_loop(tmp_path)
        data = json.loads((root / ".claude/settings.json").read_text())
        allow = data["permissions"]["allow"]
        # Exact set — count-only would let a dropped lifecycle rule (gh release
        # create, git push, ...) swap in for a loop rule and still read 14.
        assert set(allow) == EXPECTED_LOOP_ALLOW
        assert len(allow) == LOOP_ALLOW_COUNT  # no duplicates
        assert "hooks" not in data

    def test_install_sh_loop_allow_matches_this_suite(self):
        # install.sh's LOOP_ALLOW keep-set (the settings source of truth) and
        # this suite cannot drift silently — mirrors the exclude-list cross-check.
        assert _install_sh_loop_allow() == EXPECTED_LOOP_ALLOW


class TestLoopEnforcementPayload:
    def test_enforcement_files_ship(self, tmp_path):
        # In loop mode the checks ARE the merge gate, so the payload must ship.
        root = _fresh_loop(tmp_path)
        for rel in LOOP_ENFORCEMENT_FILES:
            assert (root / rel).is_file(), f"loop mode must ship {rel}"
        assert (root / ".claude/semgrep").is_dir()


class TestLoopFootprint:
    def test_no_lifecycle_root_files(self, tmp_path):
        root = _fresh_loop(tmp_path)
        for name in ROOT_LIFECYCLE_FILES:
            assert not (root / name).exists(), f"loop mode should not seed {name}"
        assert not (root / "tasks").exists(), "loop mode should not scaffold tasks/"

    def test_lock_records_loop_mode(self, tmp_path):
        root = _fresh_loop(tmp_path)
        assert _lock(root)["mode"] == "loop"

    def test_gitignore_covers_pending_docs_and_nothing_lifecycle(self, tmp_path):
        # The audit skills' Step 8 promotion-deferral writes
        # .pending-docs/convention-candidates.md even in loop mode (leg-5 dogfood
        # finding), so that one dir must be ignored — while the three
        # lifecycle-only dirs must NOT appear as dead entries (the enumerated
        # footprint claim depends on this).
        root = _fresh_loop(tmp_path)
        lines = (root / ".gitignore").read_text().splitlines()
        assert lines.count(".pending-docs/") == 1, lines
        for dead in (".subagent-envelopes/", ".auto-build/", ".locks/"):
            assert dead not in lines, f"lifecycle-dead entry {dead} in loop gitignore"

    def test_composes_with_packs(self, tmp_path):
        root = _make_consumer(
            tmp_path / "lpk", files={"pyproject.toml": "", "README.md": "#\n"}
        )
        _run(root, "--packs", "python", "--mode", "loop")
        assert _lock(root)["mode"] == "loop"
        assert "python" in _lock(root)["packs"]


class TestLoopDryRun:
    def test_dry_run_writes_nothing(self, tmp_path):
        root = _make_consumer(tmp_path / "drl", files={"README.md": "# r\n"})
        r = _run(root, "--packs", "", "--mode", "loop", "--dry-run")
        assert not (root / ".claude").exists()
        assert not (root / "CLAUDE.md").exists()
        assert not (root / "sysop" / "scripts").exists()
        assert "loop allow-subset" in r.stdout  # plan still reported


class TestFullModeUnchanged:
    def test_full_install_is_default_and_ships_lifecycle(self, tmp_path):
        root = _make_consumer(tmp_path / "full")
        _run(root, "--packs", "")
        assert _lock(root)["mode"] == "full"
        assert (root / "sysop" / "docs" / "WORKFLOW.md").exists()
        assert (root / "tasks").exists()
        assert (root / "sysop/scripts/claim_task.sh").exists()
        assert (root / ".claude/skills/review-close").is_dir()


class TestModeStateMachine:
    def test_invalid_mode_rejected(self, tmp_path):
        root = _make_consumer(tmp_path / "bad")
        r = _run(root, "--mode", "bogus", "--packs", "", expect_rc=2)
        assert "must be 'loop' or 'full'" in r.stderr

    def test_mode_rejected_with_check(self, tmp_path):
        root = _make_consumer(tmp_path / "chk")
        r = _run(root, "--mode", "loop", "--check",
                 "--source", str(REPO_ROOT), expect_rc=2)
        assert "only valid for a fresh install or --update" in r.stderr

    def test_mode_rejected_with_adopt(self, tmp_path):
        # The --mode applicability check fires in post-parse validation, before
        # main() dispatches to cmd_adopt — so a plain consumer suffices.
        root = _make_consumer(tmp_path / "adopt")
        r = _run(root, "--mode", "full", "--adopt", "--packs", "", expect_rc=2)
        assert "only valid for a fresh install or --update" in r.stderr

    def test_update_preserves_loop_mode(self, tmp_path):
        root = _fresh_loop(tmp_path, "upd")
        _commit_all(root, "loop install")
        _run(root, "--update")
        assert _lock(root)["mode"] == "loop"
        assert not (root / "tasks").exists()
        shipped = {d.name for d in (root / ".claude/skills").iterdir() if d.is_dir()}
        assert shipped == LOOP_SKILLS

    def test_loop_to_full_upgrade_is_additive(self, tmp_path):
        root = _fresh_loop(tmp_path, "upg")
        _commit_all(root, "loop install")
        r = _run(root, "--update", "--mode", "full")
        assert "upgrading loop → full" in r.stdout
        assert _lock(root)["mode"] == "full"
        assert (root / "tasks").exists()
        assert (root / "sysop" / "docs" / "WORKFLOW.md").exists()
        assert (root / ".claude/skills/review-close").is_dir()
        assert (root / "sysop/scripts/claim_task.sh").exists()

    def test_full_to_loop_downgrade_rejected(self, tmp_path):
        root = _make_consumer(tmp_path / "down")
        _run(root, "--packs", "")
        _commit_all(root, "full install")
        r = _run(root, "--update", "--mode", "loop", expect_rc=2)
        assert "Downgrade full → loop is out of scope" in r.stderr

    def test_preinstall_modeless_lock_treated_as_full(self, tmp_path):
        # A pre-123 lock has no `mode` field. --update must resolve it to full
        # (not crash, not silently switch shape). Simulate by stripping `mode`.
        root = _make_consumer(tmp_path / "premodeless")
        _run(root, "--packs", "")
        lock_path = root / ".claude/sysop.lock"
        d = json.loads(lock_path.read_text())
        d.pop("mode", None)
        lock_path.write_text(json.dumps(d, indent=2) + "\n")
        _commit_all(root, "modeless (pre-123) lock")
        _run(root, "--update")
        assert _lock(root)["mode"] == "full"
        assert (root / "tasks").exists()  # stayed full

    def test_mode_missing_value_rejected(self, tmp_path):
        # `--mode` with a flag-shaped next token must be rejected, not consume it.
        root = _make_consumer(tmp_path / "mv")
        r = _run(root, "--mode", "--packs", "", expect_rc=2)
        assert "requires a value" in r.stderr


class TestClaudeMdStub:
    SECTIONS = (
        "## Scope mapping",
        "## Map coverage exclusions",
        "## Security-critical always-include files",
    )

    def test_fresh_repo_gets_all_three_sections(self, tmp_path):
        # A repo whose only file is a non-CLAUDE.md file → stub is created.
        root = _fresh_loop(tmp_path, "cmfresh", files={"README.md": "# r\n"})
        text = (root / "CLAUDE.md").read_text()
        for h in self.SECTIONS:
            assert re.search(rf"^{re.escape(h)}\s*$", text, re.MULTILINE), h

    def test_authored_claude_md_gets_only_absent_sections_appended(self, tmp_path):
        authored = (
            "# My Project\n\nHand-authored.\n\n"
            "## Scope mapping\n\n- app → `app/**/*.py`\n\n## Build\n\nmake.\n"
        )
        root = _fresh_loop(tmp_path, "cmauth", files={"CLAUDE.md": authored})
        text = (root / "CLAUDE.md").read_text()
        # Existing content preserved.
        assert "Hand-authored." in text
        assert "- app → `app/**/*.py`" in text
        assert "## Build" in text
        # Each header appears exactly once (no duplicate Scope mapping).
        for h in self.SECTIONS:
            n = len(re.findall(rf"^{re.escape(h)}\s*$", text, re.MULTILINE))
            assert n == 1, f"{h} appears {n} times"

    def test_stub_is_idempotent(self, tmp_path):
        root = _fresh_loop(tmp_path, "cmidem")
        _commit_all(root, "loop install")
        before = (root / "CLAUDE.md").read_text()
        _run(root, "--packs", "", "--mode", "loop", "--force")
        after = (root / "CLAUDE.md").read_text()
        assert before == after
