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
     bundle and nothing lifecycle, write the 27-rule hookless settings.json,
     leave a clean root footprint, record `mode: loop`, and satisfy the full
     mode/update state machine (preserve on --update, additive loop→full
     upgrade, and the full→loop downgrade `Q-671` added, whose oracle is a
     fresh loop install's own tree).

Design intent under test: the loop bundle is a *carving*, so the exact set is the
contract — an over-ship (a lifecycle file leaking in) undercuts the footprint
pitch, an under-ship (a loop file dropped) breaks the loop.
"""
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

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
    "fanout-evidence", "upstream-repo",
}
EXCLUDED_SHARED_STEMS = {
    "decomposition-rubric", "guided-mode", "main-push-guard",
    "plan-review-preference", "ui-verify",
}
# Companion scripts (files). run_checks/ is a directory, kept in both modes.
LOOP_SCRIPTS = {
    "_log.py", "_model_roles.py", "archive_review_tasks.py",
    "check_skill_models.py", "ingest_security_report.py", "install_hooks.sh",
    "migrate_skill_model.py", "resolve_skill_models.py", "review_index.py",
    "run_checks_impl.py", "run_checks.sh", "security_partition.py",
    "self_check.sh", "sysop-update.sh",
    # Phase 368 (`Q-376`): the shipped `pre-merge-commit` hook, armed in both
    # modes, sources `_git_lib.sh` to resolve the protected branch, and its
    # fallback warning tells the operator to run `default_branch.sh`.
    "_git_lib.sh", "default_branch.sh",
    # Phase 386 (`Q-409` P3): the two loop review skills' Step 5f, which was a heredoc.
    "round_receipt.py",
}
EXCLUDED_SCRIPTS = {
    # Phase 386 (`Q-409` P3): heredocs of `/review-close` (1-pre, 3c, 3b, 4c) and
    # `/claim-task` (7f) that became scripts. Loop mode installs neither skill.
    "clone_sync.py", "smoke_detect.py", "pending_doc_collect.py", "close_index.py",
    "claim_record.py",
    # Phase 387: review-close's remaining always-run heredocs (2a, 2b, 2e, 3b, 3c, 4a, 4c).
    "feature_branch.py", "convention_size.py", "claim_artifacts.py", "workspace_locate.py",
    "smoke_record.py", "pr_head_check.py", "close_check.py",
    # Phase 394 (`Q-667`): Step 2b's verdict reuse. Phase 395 (`Q-666`): its security copy.
    "gate_verdict.py", "security_map_filter.py",
    # Phase 388 (`Q-409` P2): the arm receipt behind review-close's step files.
    "close_arms.py",
    # Phase 421 (`Q-665`, `Q-710`): Rule A's check (main-push-guard.md, which loop mode
    # does not install), and review-close's read-only git, Step 2b pins and Step 1 reads.
    "git_check.py", "git_ro.py", "review_pins.py", "close_state.py",
    # Phase 425 (`Q-629`): Step 4a's shared-append resolver, a `tasks/index.yml` writer.
    "resolve_append_conflict.py",
    "backfill_completed_dates.py", "batch_work.sh", "claim_task.sh",
    # Phase 237: a `tasks/index.yml` writer, so it is lifecycle. Loop mode
    # installs no task queue at all, which is what makes this a classification
    # rather than a judgement call.
    "clear_user_action.py",
    "cleanup_worktrees.sh", "close_batch.sh", "next_task.py",
    "parse_subagent_envelope.py",
    # Phase 353 (`Q-625`): Step 4c 1c's hold test, a pending-doc writer. Loop
    # mode installs no `/review-close` and no pending docs.
    "pending_doc_hold.py",
    # Phase 354 (`Q-633`): the executors' and `/review-close`'s ignored-file
    # check. Loop mode installs none of the three.
    "ignored_refs.py",
    # Phase 363 (`Q-603`): `/review-close --prepare`/`--resume`'s run directory.
    # Loop mode installs no `/review-close`.
    "close_run.py",
    # Phase 374 (`Q-411`): the unattended land's signed gate, which runs `close_run.py`.
    "close_gate.py",
    "permission_denied_hook.py",
    "pr_dependabot.py", "scope_overlap.py", "sitrep_survey.py",
    "validate_tasks.py",
}
LOOP_ALLOW_COUNT = 33  # Phase 386: + round_receipt.py; Phase 420: + three Edit rules
# The exact loop-mode allow-list (LOOP_ONLY_SPEC § "Leg 1 findings"). Asserting
# the *set*, not just the count, is what stops a wrong-but-same-size permission set
# (e.g. a dropped `gh release create` swapped in for a loop rule) shipping green.
EXPECTED_LOOP_ALLOW = {
    # Phase 152: both loop-mode review skills run a plain
    # `git add review_tasks_archive.md` at Step 7, which no literal rule covers.
    # See install.sh's LOOP_ALLOW comment for why Step 9 is NOT the reason.
    "Bash(git add:*)",
    "Bash(git add review_tasks.md)",
    "Bash(git commit -m \"docs: *)",
    # Q-588 (Phase 333): both loop review skills place each isolated agent with
    # `git worktree add <dir> --detach <sha>` off the default branch, and remove it after.
    "Bash(git worktree add:*)",
    "Bash(git worktree remove:*)",
    "Bash(bash sysop/scripts/run_checks.sh)",
    "Bash(bash sysop/scripts/run_checks.sh:*)",
    "Bash(bash sysop/scripts/install_hooks.sh)",
    # Phase 368: the armed hook's fallback warning names it, and loop mode now ships it.
    "Bash(bash sysop/scripts/default_branch.sh)",
    # Phase 184: self_check.sh ships in BOTH modes and the installer's own
    # post-install footer prescribes it, so a loop-mode consumer met a
    # permission prompt on the first thing the install told them to run.
    "Bash(bash sysop/scripts/self_check.sh)",
    "Bash(bash sysop/scripts/self_check.sh:*)",
    "Bash(bash sysop/scripts/sysop-update.sh)",
    "Bash(bash sysop/scripts/sysop-update.sh:*)",
    "Bash(python sysop/scripts/archive_review_tasks.py:*)",
    "Bash(python3 sysop/scripts/archive_review_tasks.py:*)",
    # Phase 220: `--check-headers`, prescribed by WORKFLOW.md, by
    # close_batch.sh's fallback warning and by the archiver's refusal.
    "Bash(python3 sysop/scripts/review_index.py:*)",
    "Bash(.venv/bin/python3 sysop/scripts/archive_review_tasks.py:*)",
    # Phase 144: the claude-security ingest CLI — /security-audit ships in loop
    # mode and calls this at its new Step 3c, so its allow-rule must ship too
    # (without it the call is auto-denied with no prompt under `dontAsk`).
    "Bash(python3 sysop/scripts/ingest_security_report.py:*)",
    "Bash(.venv/bin/python3 sysop/scripts/ingest_security_report.py:*)",
    "Bash(python3 sysop/scripts/security_partition.py:*)",
    "Bash(.venv/bin/python3 sysop/scripts/security_partition.py:*)",
    # Phase 386: Step 5f's receipt writer, a heredoc until then.
    "Bash(python3 sysop/scripts/round_receipt.py:*)",
    # Q-663 (Phase 377): /report-issues ships in loop mode; under `dontAsk` its staged body
    # and its friction-log record are denied without these.
    "Edit(/sysop/SYSOP_ISSUES.md)",
    "Edit(/sysop/runtime/giveback/**)",
    # Q-665 (Phase 420): the review skills' ledger and `/security-audit`'s file list, both
    # written with the `Write` tool.
    "Edit(/review_tasks.md)",
    "Edit(/sysop/runtime/audit-scope.txt)",
    "Edit(/sysop/runtime/pending-docs/**)",  # Step 8 candidates (Phase 420's round, lens A)
    "Bash(python3 -c:*)",
    "Bash(python3 -:*)",
    # Phase 152: the give-back skills' auth gate. `gh` is not in Claude Code's
    # built-in read-only set, so even `gh auth status` needs an explicit rule.
    "Bash(gh auth status)",
    "Bash(gh issue list:*)",
    "Bash(gh issue create:*)",
    # The give-back skills' read-only target-visibility probe
    # (_shared/upstream-repo.md § B). /report-issues + /contribute-convention
    # both ship in loop mode, and without the rule the probe degrades to the
    # offline heuristic on every loop-mode run.
    "Bash(gh repo view:*)",
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
    m = re.search(r"^LOOP_ALLOW = (\{.*?^\})", text, re.S | re.M)
    assert m, "LOOP_ALLOW block not found in install.sh"
    # A Python literal, evaluated -- a quoted-string scan reads a commented-out rule as live
    # (Phase 333's round, W1b), which the installer's own Python does not.
    try:
        return set(ast.literal_eval(m.group(1)))
    except ValueError as exc:
        raise AssertionError(
            f"install.sh's LOOP_ALLOW is no longer a literal set of strings ({exc})"
        ) from None


def _lock(target):
    return json.loads((Path(target) / ".claude" / "sysop.lock").read_text())


def _fresh_loop(tmp_path, name="c", files=None):
    root = _make_consumer(tmp_path / name, files)
    _run(root, "--packs", "", "--mode", "loop")
    return root


def _shared_entries(shared):
    """What loop mode filters in `_shared/`: each `.md` file's stem and, since
    Phase 383 (install_skills ships subdirectories), each directory's name, with
    the installer's own skips. A directory left out of this set would reach every
    loop install unclassified."""
    entries = {p.stem for p in shared.glob("*.md")}
    entries |= {
        p.name for p in shared.iterdir()
        if p.is_dir() and not p.is_symlink()
        and p.name != "__pycache__" and not p.name.startswith(".")
    }
    return entries


def test_shared_entries_sees_a_directory_and_skips_what_the_installer_skips(tmp_path):
    for name in ("kept.md", "newdir/a.md", "__pycache__/x.pyc", ".dot/a.md"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("x\n")
    (tmp_path / "linked").symlink_to("newdir")
    assert _shared_entries(tmp_path) == {"kept", "newdir"}


def test_the_drift_guard_names_an_unbucketed_shared_directory(tmp_path, monkeypatch):
    """The helper working is not the guard using it: today `_shared/` has no
    directory, so a guard reverted to file stems would stay green. Point it at a
    tree that has one (Phase 383's round)."""
    shared = tmp_path / "core/skills/_shared"
    shared.mkdir(parents=True)
    for stem in LOOP_SHARED_STEMS:
        (shared / f"{stem}.md").write_text("x\n")
    (shared / "brand-new-partials").mkdir()
    monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)
    with pytest.raises(AssertionError, match="brand-new-partials"):
        TestClassificationComplete().test_every_source_shared_partial_is_bucketed()


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
        src = _shared_entries(REPO_ROOT / "core/skills/_shared")
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
        # A loop-shipped script reaches another through `subprocess`, so no shell verb sits
        # before the path: any `sysop/scripts/<dropped>` in one is a call that cannot resolve.
        # Phase 386 made `round_receipt.py` the first loop script that was a skill heredoc.
        scripts = {p.name: p.read_text() for p in (root / "sysop/scripts").rglob("*.py")}
        for name in EXCLUDED_SCRIPTS:
            for script, text in scripts.items():
                assert f"sysop/scripts/{name}" not in text, f"loop script {script} names dropped {name}"
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
        # create, git push, ...) swap in for a loop rule and still read the same count.
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
        # sysop/runtime/pending-docs/convention-candidates.md even in loop mode
        # (leg-5 dogfood finding), so the consolidated sysop/runtime/ entry must
        # be present (Phase 133: one entry covers all runtime dirs in both
        # modes) — while the pre-133 per-dir dot entries must NOT appear (the
        # enumerated footprint claim depends on the single-line append).
        root = _fresh_loop(tmp_path)
        lines = (root / ".gitignore").read_text().splitlines()
        assert lines.count("sysop/runtime/") == 1, lines
        for dead in (".subagent-envelopes/", ".auto-build/", ".locks/",
                     ".pending-docs/"):
            assert dead not in lines, f"legacy per-dir entry {dead} in loop gitignore"

    def test_composes_with_packs(self, tmp_path):
        root = _make_consumer(
            tmp_path / "lpk", files={"pyproject.toml": "", "README.md": "#\n"}
        )
        _run(root, "--packs", "python", "--mode", "loop")
        assert _lock(root)["mode"] == "loop"
        assert "python" in _lock(root)["packs"]


def _undisclosed_edit_grants(rules, flat):
    """Q-665 (Phase 420): every `Edit(...)` rule seeded is a file-edit grant, and Phase 131's
    rule is that none is applied silently. The full disclosure names a rule under
    `sysop/runtime/` with the phrase "paths under sysop/runtime/" (the list runs to ten paths);
    any other rule, and every rule in a disclosure without that phrase, by its own path. A bare
    `sysop/runtime/` is not enough: the loop disclosure carries it inside `giveback/` (Phase
    420's battery, I05)."""
    missing = []
    for rule in rules:
        m = re.fullmatch(r"Edit\(/(.+?)(\*\*)?\)", rule)
        if not m:
            continue
        path = m.group(1)
        if path.startswith("sysop/runtime/") and "sysop/runtime/giveback/" != path:
            needle = "paths under sysop/runtime/" if "paths under sysop/runtime/" in flat else path
        else:
            needle = path
        if needle not in flat:
            missing.append(rule)
    return missing


class TestLoopDryRun:
    def test_dry_run_writes_nothing(self, tmp_path):
        root = _make_consumer(tmp_path / "drl", files={"README.md": "# r\n"})
        r = _run(root, "--packs", "", "--mode", "loop", "--dry-run")
        assert not (root / ".claude").exists()
        assert not (root / "CLAUDE.md").exists()
        assert not (root / "sysop" / "scripts").exists()
        # Guard the user-visible count too — the dry-run "plan" must not claim a
        # different number than the apply actually writes (LOOP_ALLOW_COUNT).
        assert f"loop allow-subset: {LOOP_ALLOW_COUNT} rules" in r.stdout
        # Q-588 (Phase 333): the subset gained two worktree write verbs, so the
        # install-time disclosure must name them (Phase 131: no grant applied silently).
        # Strip each `note` line's `  • ` bullet before joining, or a legal re-wrap of the
        # disclosure across two note lines reads `'git • worktree` (Phase 333's round, I2).
        flat = " ".join(
            " ".join(re.sub(r"^\s*•\s*", "", line).split()) for line in r.stdout.splitlines()
        )
        assert "'git worktree add/remove'" in flat, (
            "the loop disclosure no longer names its git worktree add/remove grants"
        )
        assert "and file edits to sysop/SYSOP_ISSUES.md and sysop/runtime/giveback/" in flat, (
            "the loop disclosure no longer names its two file-edit grants (Q-663)"
        )
        missing = _undisclosed_edit_grants(EXPECTED_LOOP_ALLOW, flat)
        assert not missing, f"the loop disclosure does not name these Edit grants: {missing}"


class TestFullModeUnchanged:
    def test_full_install_is_default_and_ships_lifecycle(self, tmp_path):
        root = _make_consumer(tmp_path / "full")
        _run(root, "--packs", "")
        assert _lock(root)["mode"] == "full"
        assert (root / "sysop" / "docs" / "WORKFLOW.md").exists()
        assert (root / "tasks").exists()
        assert (root / "sysop/scripts/claim_task.sh").exists()
        assert (root / ".claude/skills/review-close").is_dir()


    def test_full_disclosure_names_the_edit_grants(self, tmp_path):
        """Q-663 (Phase 377): Phase 131's rule, no grant applied silently, for the two
        file-edit rules the full template seeds."""
        root = _make_consumer(tmp_path / "fdr", files={"README.md": "# r\n"})
        r = _run(root, "--packs", "", "--dry-run")
        flat = " ".join(
            " ".join(re.sub(r"^\s*•\s*", "", line).split()) for line in r.stdout.splitlines()
        )
        assert "pre-authorizes the agent" in flat, "not the full-mode disclosure"
        template = json.loads((REPO_ROOT / "core/companion/.claude/settings.json").read_text())
        missing = _undisclosed_edit_grants(template["permissions"]["allow"], flat)
        assert not missing, f"the full disclosure does not name these Edit grants: {missing}"
        assert "(never locks/)" in flat, "the full disclosure no longer says locks are not granted"

    @pytest.mark.parametrize("mode", ["full", "loop"])
    def test_the_edit_rules_reach_an_existing_settings_file(self, tmp_path, mode):
        """Q-663 (Phase 377's round, lens 2): every installed consumer takes the merge path on
        `--update`, not the fresh copy, and nothing checked the two rules arrive through it."""
        root = _make_consumer(tmp_path / f"merge-{mode}", files={
            "README.md": "# r\n",
            ".claude/settings.json": json.dumps(
                {"permissions": {"allow": ["Bash(make test)"]}}, indent=2) + "\n",
        })
        _run(root, "--packs", "", "--mode", mode)
        allow = json.loads((root / ".claude" / "settings.json").read_text())["permissions"]["allow"]
        assert "Bash(make test)" in allow, "the merge dropped the consumer's own rule"
        assert {"Edit(/sysop/SYSOP_ISSUES.md)", "Edit(/sysop/runtime/giveback/**)"} <= set(allow)
        assert len(allow) == len(set(allow)), "the merge duplicated a rule"


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


# ── Q-671: the full→loop downgrade ──
# What the fixture's consumer owns, on top of an install: a hand-written allow rule,
# a stale reset grant of the installer's own shape, a hook of their own on an event
# Sysop also hooks, an edit to a script loop mode keeps and to one it drops, a task
# body, and a lifecycle-only CLAUDE.md section.
_CONSUMER_RULE = "Bash(make test)"
_STALE_RESET = "Bash(git reset --hard origin/old-trunk)"
_CONSUMER_HOOK = "bash scripts/my_subagent_hook.sh"
_CONSUMER_SUB_HOOK = "bash scripts/my_denied_hook.sh"
# Names a Sysop hook script as a substring, and is not Sysop's.
_LOOKALIKE_HOOK = "python3 tools/my_permission_denied_hook.py"
_MALFORMED_ENTRY = {"hooks": None}


def _full_with_consumer_state(root):
    _make_consumer(root)
    _run(root, "--packs", "")
    _commit_all(root, "full install")
    sp = root / ".claude" / "settings.json"
    data = json.loads(sp.read_text())
    data["permissions"]["allow"] += [_CONSUMER_RULE, _STALE_RESET]
    data["hooks"]["SubagentStop"].append(
        {"hooks": [{"type": "command", "command": _CONSUMER_HOOK}]})
    # A sub-hook of their own inside Sysop's entry: the entry goes, theirs stays.
    data["hooks"]["PermissionDenied"][0]["hooks"].append(
        {"type": "command", "command": _CONSUMER_SUB_HOOK})
    data["hooks"]["PostToolUse"] = [{"hooks": [{"type": "command", "command": _LOOKALIKE_HOOK}]}]
    data["hooks"]["Stop"] = [_MALFORMED_ENTRY]
    sp.write_text(json.dumps(data, indent=2) + "\n")
    # An armed close-gate workflow under a name of the consumer's choosing.
    wf = root / ".github" / "workflows" / "gate.yml"
    wf.parent.mkdir(parents=True, exist_ok=True)
    wf.write_text((REPO_ROOT / "core/companion/ci/sysop-close-gate.yml.example").read_text())
    # A lock that lists consumer files (hand-edited or corrupt): the sweep's guard
    # must still refuse them, the five scaffold paths aside.
    lp = root / ".claude" / "sysop.lock"
    lock = json.loads(lp.read_text())
    lock["managed_paths"] += ["tasks/index.yml", "tasks/open/T-1.md"]
    lp.write_text(json.dumps(lock, indent=2) + "\n")
    for name in ("run_checks.sh", "claim_task.sh"):
        with (root / "sysop" / "scripts" / name).open("a") as f:
            f.write("# consumer edit\n")
    (root / "tasks" / "open").mkdir(parents=True, exist_ok=True)
    (root / "tasks" / "open" / "T-1.md").write_text("a task body\n")
    with (root / "CLAUDE.md").open("a") as f:
        f.write("\n## Merge policy\n\npr\n\n## Task Workflow (pointer)\n\nFollow it.\n")
    _commit_all(root, "consumer state")
    # Gitignored lifecycle state, which the leftover report names.
    for d in ("preserved/feat-x", "parked"):
        (root / "sysop" / "runtime" / d).mkdir(parents=True, exist_ok=True)
    (root / "sysop/runtime/preserved/feat-x/.env.local").write_text("ONLY_COPY=1\n")
    return root


@pytest.fixture(scope="module")
def downgraded(tmp_path_factory):
    base = tmp_path_factory.mktemp("downgrade")
    root = _full_with_consumer_state(base / "c")
    claude_md = (root / "CLAUDE.md").read_bytes()
    r = _run(root, "--update", "--mode", "loop")
    fresh = _fresh_loop(base, "fresh")
    return root, r, claude_md, fresh


def _on_disk(root):
    return {
        str(p.relative_to(root)) for p in root.rglob("*")
        if (p.is_file() or p.is_symlink()) and ".git" not in p.relative_to(root).parts[:1]
        and "runtime" not in p.relative_to(root).parts[:2]
    }


class TestDowngrade:
    # What the consumer owns and a fresh loop install does not have. Everything else
    # on disk must match the fresh loop install exactly: that is the whole contract.
    CONSUMER_ONLY = {"tasks/index.yml", "tasks/open/T-1.md", "sysop/SYSOP_ISSUES.md",
                     ".github/workflows/gate.yml"}

    def test_the_tree_is_a_fresh_loop_install_plus_what_the_consumer_owns(self, downgraded):
        root, _, _, fresh = downgraded
        assert _on_disk(root) - self.CONSUMER_ONLY == _on_disk(fresh)
        assert sorted(_lock(root)["managed_paths"]) == sorted(_lock(fresh)["managed_paths"])
        assert _lock(root)["mode"] == "loop"

    def test_consumer_files_survive(self, downgraded):
        root, _, claude_md, _ = downgraded
        assert (root / "tasks/open/T-1.md").read_text() == "a task body\n"
        assert (root / "tasks/index.yml").is_file()
        assert (root / "CLAUDE.md").read_bytes() == claude_md, "the downgrade edited CLAUDE.md"
        # Phase 24b: an edit to a path loop mode still manages is preserved.
        assert (root / "sysop/scripts/run_checks.sh").read_text().endswith("# consumer edit\n")
        assert not (root / "sysop/scripts/claim_task.sh").exists()
        assert not (root / "tasks/schema.md").exists()

    def test_settings_keep_only_the_loop_set_and_the_consumers_own(self, downgraded):
        root, _, _, _ = downgraded
        data = json.loads((root / ".claude/settings.json").read_text())
        allow = data["permissions"]["allow"]
        assert set(allow) == EXPECTED_LOOP_ALLOW | {_CONSUMER_RULE}
        assert len(allow) == len(set(allow))
        assert _STALE_RESET not in allow
        # Sysop's two hooks went; the consumer's own entry on the same event stayed.
        assert data["hooks"] == {
            "SubagentStop": [{"hooks": [{"type": "command", "command": _CONSUMER_HOOK}]}],
            "PermissionDenied": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": _CONSUMER_SUB_HOOK}]}],
            "PostToolUse": [{"hooks": [{"type": "command", "command": _LOOKALIKE_HOOK}]}],
            "Stop": [_MALFORMED_ENTRY],
        }

    def test_every_removal_is_named_and_the_leftovers_listed(self, downgraded):
        root, r, _, _ = downgraded
        out = r.stdout
        assert "downgrading full → loop" in out
        assert "removed: Bash(bash sysop/scripts/claim_task.sh:*)" in out
        assert "removed: SubagentStop: python3 $CLAUDE_PROJECT_DIR/sysop/scripts/parse_subagent_envelope.py" in out
        assert "remove: sysop/scripts/claim_task.sh" in out
        assert "CLAUDE.md § Merge policy — read only by lifecycle skills" in out
        assert "CLAUDE.md § Task Workflow — read only by lifecycle skills" in out
        assert ".github/workflows/gate.yml — runs close_gate.py" in out
        # The count is the template's, so a strip that ignored the loop set would show.
        tmpl = json.loads((REPO_ROOT / "core/companion/.claude/settings.json").read_text())
        n = len(set(tmpl["permissions"]["allow"]) - EXPECTED_LOOP_ALLOW) + 1  # + _STALE_RESET
        assert f"removed {n} full-mode allow rule(s) and 2 hook(s)" in out
        assert "sysop/runtime/parked/ — lifecycle state (gitignored)" in out
        assert ("sysop/runtime/preserved/ — files a close kept as their only copy; "
                "move what you need before deleting it") in out
        assert (root / "sysop/runtime/preserved/feat-x/.env.local").is_file()
        assert _CONSUMER_RULE not in out, "a kept rule was reported as removed"

    def test_a_second_update_is_a_no_op(self, downgraded, tmp_path):
        root, _, _, _ = downgraded
        _commit_all(root, "downgrade")
        r = _run(root, "--update")
        assert "downgrading" not in r.stdout
        st = subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                            capture_output=True, text=True, check=True).stdout
        assert st == "", st

    def test_a_live_claim_lock_refuses_and_changes_nothing(self, tmp_path):
        root = _make_consumer(tmp_path / "lk")
        _run(root, "--packs", "")
        _commit_all(root, "full install")
        locks = root / "sysop/runtime/locks"
        locks.mkdir(parents=True, exist_ok=True)
        (locks / "T-9.lock").write_text("task: T-9\n")
        (locks / "BATCH-3.lock").write_text("batch: 3\n")
        before = _on_disk(root)
        r = _run(root, "--update", "--mode", "loop", expect_rc=2)
        assert "Downgrade refused: 2 claim(s) are live" in r.stderr
        assert "BATCH-3.lock" in r.stderr
        assert "batch_work.sh --release" in r.stderr
        assert _on_disk(root) == before
        assert _lock(root)["mode"] == "full"

    def test_dry_run_lists_and_writes_nothing(self, tmp_path):
        root = _full_with_consumer_state(tmp_path / "dry")
        settings = (root / ".claude/settings.json").read_bytes()
        lock = root / "sysop/runtime/locks/T-9.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("task: T-9\n")
        r = _run(root, "--update", "--mode", "loop", "--dry-run")
        assert "the apply will refuse: 1 claim(s) are live" in r.stdout
        assert "CLAUDE.md § Merge policy — read only by lifecycle skills" in r.stdout
        assert "would remove: Bash(bash sysop/scripts/claim_task.sh:*)" in r.stdout
        assert "remove: sysop/scripts/claim_task.sh" in r.stdout
        assert (root / ".claude/settings.json").read_bytes() == settings
        assert (root / "sysop/scripts/claim_task.sh").exists()
        assert _lock(root)["mode"] == "full"

    def test_a_stale_reset_grant_goes_when_the_default_branch_is_unresolved(self, tmp_path):
        """With both `main` and `master` and no remote HEAD, the default branch does not
        resolve and `_prune_stale_branch_grants` prunes nothing, so the strip's own shape
        match is the only thing that removes a reset grant an earlier install seeded."""
        root = _make_consumer(tmp_path / "unres")
        _run(root, "--packs", "")
        # Whichever of the two `git init` did not make (CI's default is `master`).
        current = subprocess.run(["git", "-C", str(root), "branch", "--show-current"],
                                 capture_output=True, text=True, check=True).stdout.strip()
        _git(root, "branch", "master" if current == "main" else "main")
        sp = root / ".claude/settings.json"
        data = json.loads(sp.read_text())
        data["permissions"]["allow"].append(_STALE_RESET)
        sp.write_text(json.dumps(data, indent=2) + "\n")
        _commit_all(root, "full install")
        _run(root, "--update", "--mode", "loop")
        allow = json.loads(sp.read_text())["permissions"]["allow"]
        assert set(allow) == EXPECTED_LOOP_ALLOW, set(allow) ^ EXPECTED_LOOP_ALLOW

    def test_settings_of_an_unexpected_shape_are_left_alone(self, tmp_path):
        """The harness defines `hooks.<event>` as a list. An event of another shape is the
        consumer's to fix, and the strip must not delete it while it removes Sysop's hooks
        beside it. (A non-list `allow` is rebuilt by the installer's own merge afterwards,
        as on every install; that is not the strip's to change.)"""
        root = _make_consumer(tmp_path / "shape")
        _run(root, "--packs", "")
        sp = root / ".claude/settings.json"
        data = json.loads(sp.read_text())
        data["hooks"]["Notification"] = {"not": "a list"}
        data["permissions"]["allow"] = {"not": "a list"}
        sp.write_text(json.dumps(data, indent=2) + "\n")
        _commit_all(root, "full install")
        _run(root, "--update", "--mode", "loop")
        after = json.loads(sp.read_text())
        assert after["hooks"]["Notification"] == {"not": "a list"}
        assert "SubagentStop" not in after["hooks"] and "PermissionDenied" not in after["hooks"]

    def test_a_claim_lock_in_the_main_checkout_refuses_a_run_from_a_worktree(self, tmp_path):
        """claim_task.sh writes locks under the main checkout (git-common-dir), so a
        downgrade run from a linked worktree must look there, not only in its own tree."""
        root = _make_consumer(tmp_path / "main")
        _run(root, "--packs", "")
        _commit_all(root, "full install")
        wt = tmp_path / "wt"
        _git(root, "worktree", "add", "-q", "-b", "feat/x", str(wt))
        locks = root / "sysop/runtime/locks"
        locks.mkdir(parents=True, exist_ok=True)
        (locks / "FEAT-X.lock").write_text("task: FEAT-X\n")
        r = _run(wt, "--update", "--mode", "loop", expect_rc=2)
        assert "Downgrade refused: 1 claim(s) are live" in r.stderr
        assert (wt / "sysop/scripts/claim_task.sh").exists()

    def test_an_in_progress_task_with_no_lock_refuses(self, tmp_path):
        """`claim_task.sh` writes no lock without `--lock` (its documented default), so a
        task at `in_progress` is the only trace of such a claim."""
        root = _make_consumer(tmp_path / "ip")
        _run(root, "--packs", "")
        idx = root / "tasks/index.yml"
        idx.write_text(idx.read_text().replace(
            "tasks: []", "tasks:\n  - id: FEAT-7\n    title: x\n    status: in_progress\n"))
        _commit_all(root, "full install")
        r = _run(root, "--update", "--mode", "loop", expect_rc=2)
        assert "tasks/index.yml: FEAT-7 (in_progress)" in r.stderr
        assert (root / "sysop/scripts/claim_task.sh").exists()

    def test_an_unreadable_task_index_refuses_rather_than_reading_as_no_claims(self, tmp_path):
        root = _make_consumer(tmp_path / "ur")
        _run(root, "--packs", "")
        (root / "tasks/index.yml").write_text("tasks: [unclosed\n")
        _commit_all(root, "full install")
        r = _run(root, "--update", "--mode", "loop", expect_rc=2)
        assert "tasks/index.yml: UNREADABLE" in r.stderr

    def test_a_symlinked_skill_directory_outside_the_target_is_not_swept(self, tmp_path):
        """`git rm` refuses a path beyond a symlink and the `rm -f` fallback followed it,
        deleting another tree's files (Phase 417's round, execution lens)."""
        root = _make_consumer(tmp_path / "ln")
        _run(root, "--packs", "")
        _commit_all(root, "full install")
        shared = tmp_path / "shared" / "auto-build"
        shared.parent.mkdir()
        skill = root / ".claude/skills/auto-build"
        _git(root, "rm", "-rq", "--cached", ".claude/skills/auto-build")
        skill.rename(shared)
        skill.symlink_to(shared)
        _commit_all(root, "auto-build shared via a symlink")
        before = sorted(p.name for p in shared.iterdir())
        r = _run(root, "--update", "--mode", "loop")
        assert sorted(p.name for p in shared.iterdir()) == before, "the sweep reached outside the target"
        assert "resolves outside the target through a symlink" in r.stdout

    def test_a_loop_update_keeps_the_scaffold_guard(self, tmp_path):
        """The five `tasks/` paths pass the sweep's guard only in a downgrade: a loop
        install never manages them, so a lock listing one is the corruption the guard
        is for (Phase 417's round, guards lens)."""
        root = _fresh_loop(tmp_path, "lp", files={"README.md": "# r\n", "tasks/README.md": "mine\n"})
        lp = root / ".claude/sysop.lock"
        lock = json.loads(lp.read_text())
        lock["managed_paths"].append("tasks/README.md")
        lp.write_text(json.dumps(lock, indent=2) + "\n")
        _commit_all(root, "loop install, corrupt lock")
        _run(root, "--update")
        assert (root / "tasks/README.md").read_text() == "mine\n"

    def test_a_loop_update_does_not_strip_settings(self, tmp_path):
        """The strip is a downgrade's: a loop→loop update keeps a full-template rule the
        consumer added by hand."""
        root = _fresh_loop(tmp_path, "ll")
        sp = root / ".claude/settings.json"
        data = json.loads(sp.read_text())
        data["permissions"]["allow"].append("Bash(bash sysop/scripts/claim_task.sh:*)")
        sp.write_text(json.dumps(data, indent=2) + "\n")
        _commit_all(root, "loop install")
        _run(root, "--update")
        assert "Bash(bash sysop/scripts/claim_task.sh:*)" in json.loads(sp.read_text())["permissions"]["allow"]

    def test_a_strip_failure_names_its_reason(self, tmp_path):
        root = _make_consumer(tmp_path / "bad")
        _run(root, "--packs", "")
        (root / ".claude/settings.json").write_text("{ // a comment\n}\n")
        _commit_all(root, "full install")
        r = subprocess.run(["bash", str(INSTALL_SH), str(root), "--update", "--mode", "loop", "--yes"],
                           capture_output=True, text=True,
                           env=dict(os.environ, PATH=os.path.dirname(sys.executable) + os.pathsep + os.environ["PATH"]))
        assert re.search(r"settings\.json was not changed: \S", r.stderr), r.stderr[-2000:]

    def test_growing_back_to_full_restores_the_lifecycle(self, tmp_path):
        root = _full_with_consumer_state(tmp_path / "back")
        _run(root, "--update", "--mode", "loop")
        _commit_all(root, "downgrade")
        _run(root, "--update", "--mode", "full")
        assert (root / ".claude/skills/review-close").is_dir()
        assert (root / "tasks/schema.md").is_file()
        assert (root / "tasks/open/T-1.md").read_text() == "a task body\n"
        data = json.loads((root / ".claude/settings.json").read_text())
        assert "Bash(bash sysop/scripts/claim_task.sh:*)" in data["permissions"]["allow"]
        assert any("parse_subagent_envelope.py" in h["command"]
                   for e in data["hooks"]["SubagentStop"] for h in e["hooks"])


def _install_sh_unused_sections():
    text = INSTALL_SH.read_text()
    m = re.search(r"^LOOP_UNUSED_CLAUDE_SECTIONS=\((.*?)^\)", text, re.S | re.M)
    assert m, "LOOP_UNUSED_CLAUDE_SECTIONS not found in install.sh"
    return re.findall(r'"([^"]+)"', m.group(1))


# A loop file that names a lifecycle section without reading it: upstream-repo.md
# cites the two as precedent for its own section's shape.
_SECTION_ANALOGIES = {("_shared/upstream-repo.md", "Merge policy"),
                      ("_shared/upstream-repo.md", "Pre-merge verification")}


def test_the_lifecycle_only_sections_are_template_sections_no_loop_skill_reads():
    """`Q-671`: the downgrade tells a consumer a section is unused. That claim is true
    only while no loop skill reads it, and only means something if WORKFLOW.md § 6.1
    defines it."""
    sections = _install_sh_unused_sections()
    assert len(sections) >= 9
    wf = (REPO_ROOT / "core/companion/docs/WORKFLOW.md").read_text()
    for sec in sections:
        assert re.search(rf"^\| `## {re.escape(sec)}[` (]", wf, re.M), f"{sec}: not in WORKFLOW.md § 6.1"
    skills = REPO_ROOT / "core/skills"
    loop_files = [p for d in LOOP_SKILLS - {"_shared"} for p in (skills / d).rglob("*.md")]
    loop_files += [skills / "_shared" / f"{stem}.md" for stem in LOOP_SHARED_STEMS]
    for f in loop_files:
        text = f.read_text()
        rel_f = str(f.relative_to(skills))
        for sec in sections:
            if sec in text and (rel_f, sec) not in _SECTION_ANALOGIES:
                raise AssertionError(f"{rel_f} reads § {sec}, which a downgrade calls unused")
