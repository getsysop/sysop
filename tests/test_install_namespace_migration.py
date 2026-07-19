"""Tests for the Phase 128 sysop/ vendor-namespace migration (install.sh --update).

The migration moves Sysop's consumer-install footprint out of shared namespaces
into a labelled ``sysop/`` dir: ``scripts/`` → ``sysop/scripts/``,
``WORKFLOW*.md`` → ``sysop/docs/``, ``SYSOP_ISSUES.md`` → ``sysop/``. Spec:
``tools/SYSOP_NAMESPACE_SPEC.md`` (§5 algorithm + traps T1–T7).

Most tests build a SYNTHETIC old-layout install (flat ``scripts/`` + a
version-1 lock with old-layout ``managed_paths`` and an unreachable
``sysop_commit``) and exercise the degraded/clean-tree migration path — no
dependency on old git revs. The one preservation test (T1) needs the
reconstructed shadow, so it locates a real pre-namespace ``install.sh`` commit
in history (skipped if none exists) and drives the true two-step upgrade.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
SRC_SCRIPTS = REPO_ROOT / "core/companion/scripts"
SETTINGS_TEMPLATE = REPO_ROOT / "core/companion/.claude/settings.json"

# A syntactically valid but unreachable commit anchor: reconstruct_old_install
# fails on it → the clean-tree fallback (Phase 99) drives the migration, and the
# settings pass takes its tertiary (inverse-mapped template) source.
UNREACHABLE = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


# ── helpers ─────────────────────────────────────────────────────────────────

def _git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args],
                          capture_output=True, text=True)


def _run_update(target, *args, env=None):
    return subprocess.run(
        ["bash", str(INSTALL_SH), str(target), "--update", "--yes", *args],
        capture_output=True, text=True, env=env)


def _lock(root):
    return json.loads((root / ".claude" / "sysop.lock").read_text())


def _old_settings_json():
    """The OLD shipped settings: the current template inverse-mapped to flat
    scripts/ spellings (what a pre-namespace installer would have written),
    plus one consumer-authored rule that migration must preserve."""
    tmpl = json.loads(SETTINGS_TEMPLATE.read_text())
    allow = [r.replace("sysop/scripts/", "scripts/")
             for r in tmpl["permissions"]["allow"]]
    allow.append("Bash(bash scripts/my_deploy.sh)")  # consumer-authored — must survive
    hooks = {
        "PermissionDenied": [{"matcher": "Bash", "hooks": [
            {"type": "command",
             "command": "python3 $CLAUDE_PROJECT_DIR/scripts/permission_denied_hook.py"}]}],
        "SubagentStop": [{"hooks": [
            {"type": "command",
             "command": "python3 $CLAUDE_PROJECT_DIR/scripts/parse_subagent_envelope.py"}]}],
    }
    return {"permissions": {"allow": allow}, "hooks": hooks}


def _build_old_consumer(root, mode="full", diverge=None, extra_managed=()):
    """Construct a committed, clean OLD-layout Sysop install under ``root``.

    ``extra_managed`` seeds lock entries whose files are also written at the old
    spelling — used to exercise the upstream-dropped sweep.
    """
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")

    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "hooks").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "ci").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "run_checks").mkdir(parents=True, exist_ok=True)

    managed = []
    # Copy the real companion scripts to the old flat path.
    for p in sorted(SRC_SCRIPTS.iterdir()):
        if p.name == "__pycache__":
            continue
        if p.is_dir():
            for sub in sorted(p.iterdir()):
                if sub.is_file():
                    shutil.copy(sub, root / "scripts" / p.name / sub.name)
                    managed.append(f"scripts/{p.name}/{sub.name}")
        else:
            shutil.copy(p, root / "scripts" / p.name)
            managed.append(f"scripts/{p.name}")
    # A hook template + a ci template so the hooks/ci prefixes move too.
    (root / "scripts" / "hooks" / "pre-commit").write_text("#!/bin/sh\nexit 0\n")
    managed.append("scripts/hooks/pre-commit")
    (root / "scripts" / "ci" / "sysop-checks.yml.example").write_text("name: x\n")
    managed.append("scripts/ci/sysop-checks.yml.example")

    # Docs (full mode only).
    if mode == "full":
        (root / "WORKFLOW.md").write_text("# workflow\n")
        (root / "WORKFLOW_GUIDE.md").write_text("# guide\n")
        managed += ["WORKFLOW.md", "WORKFLOW_GUIDE.md"]

    # A minimal .claude/ with the OLD-layout settings + a couple managed files.
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude" / "settings.json").write_text(json.dumps(_old_settings_json(), indent=2) + "\n")
    (root / ".claude" / "convention_map.md").write_text("# conv\n")
    managed.append(".claude/convention_map.md")

    # tasks/ + review_tasks so the anchor-resolving scripts have real roots.
    # tasks/index.yml is deliberately NOT added to managed_paths — real installs
    # seed it (skip-if-exists) but never manage it; it's the consumer's backlog.
    (root / "tasks").mkdir(exist_ok=True)
    (root / "tasks" / "index.yml").write_text(
        "schema_version: 1\nphases:\n  - number: 1\n    title: t\n"
        "    status: in_progress\n    current_focus: true\ntasks: []\n")
    (root / "review_tasks.md").write_text("# Review tasks\n")

    for e in extra_managed:
        managed.append(e)

    if diverge:
        with open(root / diverge, "a") as f:
            f.write("\n# CONSUMER LOCAL EDIT\n")

    # The lock is JSON (see write_lock_file / lock_field): old-spelled
    # managed_paths, unreachable anchor, version 1, mode.
    lock = {
        "version": 1,
        "sysop_commit": UNREACHABLE,
        "packs": ["python"],
        "mode": mode,
        "installed_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "managed_paths": managed,
    }
    (root / ".claude" / "sysop.lock").write_text(json.dumps(lock, indent=2) + "\n")

    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "old-layout install")
    return root, managed


def _pre_namespace_commit():
    """The newest commit whose install.sh predates the sysop/ namespace."""
    r = _git(REPO_ROOT, "rev-list", "HEAD", "--max-count=40")
    for c in r.stdout.split():
        show = _git(REPO_ROOT, "show", f"{c}:install.sh")
        if show.returncode == 0 and "sysop/scripts" not in show.stdout:
            return c
    return None


# ── synthetic-fixture migration tests (degraded/clean-tree path) ─────────────

class TestFullMigration:
    def test_layout_and_lock_rewritten(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        r = _run_update(root)
        assert r.returncode == 0, r.stdout + r.stderr
        # Vendor scripts relocated; old flat dir pruned.
        assert (root / "sysop" / "scripts" / "claim_task.sh").is_file()
        assert (root / "sysop" / "scripts" / "run_checks" / "cli.py").is_file()
        assert not (root / "scripts").exists(), "empty old scripts/ not pruned"
        # Docs + issues namespace.
        assert (root / "sysop" / "docs" / "WORKFLOW.md").is_file()
        # Lock now carries new-spelled managed paths (JSON).
        mp = _lock(root)["managed_paths"]
        assert "sysop/scripts/claim_task.sh" in mp
        assert "scripts/claim_task.sh" not in mp
        assert _lock(root)["mode"] == "full"

    def test_migrating_announced_and_summary(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        r = _run_update(root)
        assert "MIGRATING to the sysop/ vendor dir" in r.stdout
        assert "moved:" in r.stdout and "swept:" in r.stdout


class TestSettingsMigration:
    def test_both_settings_files_migrated(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        # settings.local.json (untracked) also carries an old flat shipped rule
        # (bash scripts/run_checks.sh IS in the template → inverse-map removes it).
        (root / ".claude" / "settings.local.json").write_text(json.dumps(
            {"permissions": {"allow": ["Bash(bash scripts/run_checks.sh)"]}}, indent=2) + "\n")
        r = _run_update(root)
        assert r.returncode == 0, r.stdout + r.stderr
        main = json.loads((root / ".claude" / "settings.json").read_text())
        allow = main["permissions"]["allow"]
        # Old flat shipped rule gone, new sysop rule present, consumer rule intact.
        assert "Bash(bash scripts/claim_task.sh:*)" not in allow
        assert "Bash(bash sysop/scripts/claim_task.sh:*)" in allow
        assert "Bash(bash scripts/my_deploy.sh)" in allow
        # Hook command re-pathed.
        cmd = main["hooks"]["PermissionDenied"][0]["hooks"][0]["command"]
        assert "sysop/scripts/permission_denied_hook.py" in cmd
        # settings.local.json's old shipped rule removed too.
        local = json.loads((root / ".claude" / "settings.local.json").read_text())
        assert "Bash(bash scripts/run_checks.sh)" not in local["permissions"]["allow"]


def _rewrite_lock_new_spelled(root, reachable_commit=None):
    """Rewrite a fixture's lock to the NEW-spelled shape cmd_adopt writes (the
    adopt-bridge case): managed_paths mapped to sysop/ spellings, optionally with
    a reachable anchor. This is the lock spelling the original fixtures did NOT
    cover — the one that exposed the adversarial-review data-loss findings."""
    lock = _lock(root)
    def to_new(m):
        if m.startswith("scripts/"):
            return "sysop/" + m
        if m in ("WORKFLOW.md", "WORKFLOW_GUIDE.md"):
            return "sysop/docs/" + m
        return m
    lock["managed_paths"] = [to_new(m) for m in lock["managed_paths"]]
    if reachable_commit:
        lock["sysop_commit"] = reachable_commit
    (root / ".claude" / "sysop.lock").write_text(json.dumps(lock, indent=2) + "\n")


class TestAdoptBridgeLockSpelling:
    """Adversarial-review regression tests. cmd_adopt (the lockless-install
    bridge, e.g. GDP) records the CURRENT pipeline's NEW-spelled managed_paths
    against an OLD-layout tree. The snapshot / clean-tree / settings-removal /
    divergence paths must handle that spelling, or an uncommitted managed-script
    edit is silently, unrecoverably overwritten (Finding 1)."""

    def test_new_spelled_lock_unreachable_anchor_dirty_edit_not_lost(self, tmp_path):
        # Finding 1 (HIGH): the original data-loss window.
        root, _ = _build_old_consumer(tmp_path / "c")
        _rewrite_lock_new_spelled(root)  # anchor stays UNREACHABLE
        with open(root / "scripts" / "claim_task.sh", "a") as f:
            f.write("\n# PRECIOUS UNCOMMITTED EDIT\n")  # dirty, uncommitted
        r = _run_update(root)
        # Must NOT silently overwrite: either snapshotted or fail-closed.
        surfaces = []
        for p in (root / "sysop" / "scripts" / "claim_task.sh",
                  root / "scripts" / "claim_task.sh"):
            if p.is_file() and "PRECIOUS UNCOMMITTED EDIT" in p.read_text():
                surfaces.append("worktree")
        log = subprocess.run(["git", "-C", str(root), "log", "--all", "-p"],
                             capture_output=True, text=True).stdout
        if "PRECIOUS UNCOMMITTED EDIT" in log:
            surfaces.append("git-history")
        assert surfaces, f"uncommitted edit was lost (exit {r.returncode}):\n{r.stdout}"

    def test_new_spelled_lock_reachable_anchor_removes_old_settings_rules(self, tmp_path):
        # Finding 2 (MEDIUM): dead flat allow-rules must not linger.
        root, _ = _build_old_consumer(tmp_path / "c")
        head = _git(REPO_ROOT, "rev-parse", "HEAD").stdout.strip()
        _rewrite_lock_new_spelled(root, reachable_commit=head)
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "new-spelled lock")
        r = _run_update(root)
        assert r.returncode == 0, r.stdout + r.stderr
        allow = json.loads((root / ".claude" / "settings.json").read_text())["permissions"]["allow"]
        assert "Bash(bash scripts/claim_task.sh:*)" not in allow  # dead flat rule gone
        assert "Bash(bash sysop/scripts/claim_task.sh:*)" in allow  # new rule present
        assert "Bash(bash scripts/my_deploy.sh)" in allow  # consumer rule survives


class TestScriptAnchorsWork:
    """§3.1: the migrated scripts must resolve the repo root from sysop/scripts/."""
    def test_validate_tasks_finds_root_tasks(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        _run_update(root)
        r = subprocess.run(
            [sys.executable, str(root / "sysop/scripts/validate_tasks.py")],
            cwd=root, capture_output=True, text=True)
        # Resolves <root>/tasks (not <root>/sysop/tasks): a clean parse, not a
        # "tasks dir not found" crash.
        assert "index.yml" not in r.stderr or "not found" not in r.stderr.lower()
        assert (root / "sysop" / "scripts" / "validate_tasks.py").is_file()

    def test_install_hooks_finds_templates(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        _run_update(root)
        r = subprocess.run(["bash", str(root / "sysop/scripts/install_hooks.sh")],
                           cwd=root, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        assert (root / ".git" / "hooks" / "pre-commit").exists()


class TestDryRun:
    def test_plan_only_tree_untouched(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        r = _run_update(root, "--dry-run")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "MIGRATING to the sysop/ vendor dir" in r.stdout
        assert not (root / "sysop").exists(), "dry-run created sysop/"
        assert (root / "scripts" / "claim_task.sh").is_file(), "dry-run moved files"


class TestIdempotency:
    def test_reupdate_after_migration_is_normal_update(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        _run_update(root)
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "migrated")
        r = _run_update(root)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "MIGRATING to the sysop/ vendor dir" not in r.stdout


class TestObsoleteSweep:
    def test_upstream_dropped_file_swept_no_orphan(self, tmp_path):
        # A managed script that the current pipeline no longer ships.
        root, _ = _build_old_consumer(tmp_path / "c",
                                      extra_managed=("scripts/legacy_dropped.py",))
        (root / "scripts" / "legacy_dropped.py").write_text("# gone upstream\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "add dropped")
        r = _run_update(root)
        assert r.returncode == 0, r.stdout + r.stderr
        # Removed at its old spelling; never orphaned under sysop/.
        assert not (root / "scripts" / "legacy_dropped.py").exists()
        assert not (root / "sysop" / "scripts" / "legacy_dropped.py").exists()


class TestSysopIssuesMove:
    def test_issues_log_moved_with_content(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        (root / "SYSOP_ISSUES.md").write_text("# Issues\n- a real entry\n")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "issues")
        _run_update(root)
        assert not (root / "SYSOP_ISSUES.md").exists()
        moved = (root / "sysop" / "SYSOP_ISSUES.md")
        assert moved.is_file() and "a real entry" in moved.read_text()

    def test_absent_issues_log_is_noop(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        r = _run_update(root)
        assert r.returncode == 0
        assert not (root / "sysop" / "SYSOP_ISSUES.md").exists()  # never reseeded


class TestLoopModeSubset:
    def test_loop_install_migrates_its_subset(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c", mode="loop")
        r = _run_update(root)
        assert r.returncode == 0, r.stdout + r.stderr
        assert (root / "sysop" / "scripts" / "run_checks.sh").is_file()
        assert _lock(root)["mode"] == "loop"


class TestT7Preflight:
    def test_extra_worktree_refused(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        wt = tmp_path / "wt"
        _git(root, "worktree", "add", "-q", "--detach", str(wt))
        r = _run_update(root)
        assert r.returncode != 0
        assert "single worktree" in r.stderr or "worktree" in r.stderr.lower()

    def test_active_lock_refused(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        (root / ".locks").mkdir(exist_ok=True)
        (root / ".locks" / "FEAT-1.lock").write_text("owner: x\n")
        r = _run_update(root)
        assert r.returncode != 0
        assert "lock" in r.stderr.lower()

    def test_fresh_install_over_foreign_sysop_refused(self, tmp_path):
        # A consumer's OWN sysop/ dir (no lock) blocks a fresh install.
        root = tmp_path / "f"
        root.mkdir()
        _git(root, "init", "-q"); _git(root, "config", "user.email", "t@t"); _git(root, "config", "user.name", "t")
        (root / "sysop").mkdir()
        (root / "sysop" / "mine.txt").write_text("my own dir\n")
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "own sysop")
        r = subprocess.run(["bash", str(INSTALL_SH), str(root), "--packs", "", "--yes"],
                           capture_output=True, text=True)
        assert r.returncode != 0
        assert "sysop" in r.stderr and "isn't a Sysop install" in r.stderr


class TestT4StaleRefReport:
    """Adversarial-review regression (spec §8's T4 test, never written). The
    report must surface consumer-owned files that still name old scripts/ paths —
    armed hooks, CI workflows, tracked docs — WITH NO settings.local.json present
    (the common case that aborted the scan under set -e), and must NOT flood with
    the correctly-migrated sysop/scripts rules it just wrote."""

    def test_reports_hooks_ci_docs_and_not_migrated_settings(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        # Consumer-owned stale refs (git-tracked).
        (root / "CLAUDE.md").write_text("Run `bash scripts/run_checks.sh` before commit.\n")
        wf = root / ".github" / "workflows"; wf.mkdir(parents=True)
        (wf / "ci.yml").write_text("jobs:\n  x:\n    steps:\n      - run: bash scripts/run_checks.sh\n")
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "consumer files")
        # Armed hook with a staged-path trigger regex (untracked). NO settings.local.json.
        hooks = root / ".git" / "hooks"; hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "pre-commit").write_text(
            "#!/bin/sh\ngit diff --cached --name-only | grep -E '^scripts/.*\\.py$'\n")
        assert not (root / ".claude" / "settings.local.json").exists()  # the abort-trigger case
        r = _run_update(root)
        assert r.returncode == 0, r.stdout + r.stderr
        out = r.stdout
        # The HIGH (ls set-e abort) + MED-HIGH (\b dead git-grep) fixes: all three
        # consumer surfaces must be listed.
        assert "CLAUDE.md" in out, "tracked doc with scripts/ ref not reported (git-grep \\b dead?)"
        assert ".github/workflows/ci.yml" in out, "CI workflow not scanned (set -e abort?)"
        assert ".git/hooks/pre-commit" in out, "armed hook not scanned (set -e abort?)"
        # The MEDIUM (\b false-positive) fix: the migrated settings.json's ~40
        # sysop/scripts rules must NOT flood the report — at most the consumer's
        # own `bash scripts/my_deploy.sh` line.
        assert out.count(".claude/settings.json:") <= 2, \
            "migrated sysop/scripts rules flooded the stale-ref report"


class TestT6ShimGuard:
    def test_shim_refuses_pre_namespace_source(self, tmp_path):
        # A source clone (git tree) whose install.sh predates the namespace must
        # be refused. It must be a git repo so the shim's git-tree guard passes
        # and control reaches the Phase-128 T6 source-freshness check.
        old_src = tmp_path / "oldsrc"
        old_src.mkdir()
        _git(old_src, "init", "-q")
        (old_src / "install.sh").write_text("#!/usr/bin/env bash\n# flat scripts/ only\n")
        _git(old_src, "add", "-A")
        _git(old_src, "commit", "-q", "-m", "old installer")
        consumer = tmp_path / "c"
        consumer.mkdir()
        _git(consumer, "init", "-q"); _git(consumer, "config", "user.email", "t@t"); _git(consumer, "config", "user.name", "t")
        shim = REPO_ROOT / "core/companion/scripts/sysop-update.sh"
        env = dict(os.environ, SYSOP_SRC=str(old_src))
        r = subprocess.run(["bash", str(shim)], cwd=consumer, capture_output=True, text=True, env=env)
        assert r.returncode != 0
        assert "predates the sysop/ vendor namespace" in r.stderr


# ── static drift guard ───────────────────────────────────────────────────────

class TestMigrationCoverage:
    def test_map_covers_the_three_managed_prefixes(self):
        """The old→new map in install.sh must handle exactly the moved prefixes;
        a new managed prefix added without a map arm would silently not migrate."""
        src = INSTALL_SH.read_text()
        for arm in ("scripts/*)", "WORKFLOW.md)", "WORKFLOW_GUIDE.md)", "SYSOP_ISSUES.md)"):
            assert arm in src, f"_ns_old_to_new missing arm for {arm}"


# ── shadow-based preservation test (real pre-namespace commit) ────────────────

class TestT1Preservation:
    def test_diverged_script_preserved_at_new_path(self, tmp_path):
        commit = _pre_namespace_commit()
        if not commit:
            pytest.skip("no pre-namespace install.sh commit in history")
        # Materialize the OLD installer and run it to build a real old install.
        wt = tmp_path / "oldwt"
        rc = _git(REPO_ROOT, "worktree", "add", "-q", "--detach", str(wt), commit)
        if rc.returncode != 0:
            pytest.skip("could not materialize pre-namespace worktree")
        try:
            consumer = tmp_path / "c"
            consumer.mkdir()
            _git(consumer, "init", "-q"); _git(consumer, "config", "user.email", "t@t"); _git(consumer, "config", "user.name", "t")
            _git(consumer, "commit", "-q", "--allow-empty", "-m", "init")
            subprocess.run(["bash", str(wt / "install.sh"), str(consumer),
                            "--packs", "python", "--yes", "--no-arm-hooks"],
                           capture_output=True, text=True)
            _git(consumer, "add", "-A"); _git(consumer, "commit", "-q", "-m", "old install")
            # Diverge an in-scope managed script and commit it.
            with open(consumer / "scripts" / "claim_task.sh", "a") as f:
                f.write("\n# CONSUMER LOCAL EDIT\n")
            _git(consumer, "add", "-A"); _git(consumer, "commit", "-q", "-m", "diverge")
            r = _run_update(consumer)
            assert r.returncode == 0, r.stdout + r.stderr
            assert "preserved" in r.stdout.lower()
            preserved = consumer / "sysop" / "scripts" / "claim_task.sh"
            assert preserved.is_file()
            assert "CONSUMER LOCAL EDIT" in preserved.read_text()
        finally:
            _git(REPO_ROOT, "worktree", "remove", "--force", str(wt))


# ── review-round regression tests (detection / guard cluster) ────────────────

class TestCrashResumeDetection:
    """Finding 1 (HIGH — crash-resume data-loss). A migration can relocate the
    vendor tree to sysop/ and then die before rewriting the lock (concat failure,
    Ctrl-C): tree NEW-layout, lock still OLD-spelled. The flat-file tree-probe can't
    see that (no flat files remain), so MIGRATION_MODE stayed 0, the reconstructed
    shadow never moved, and copy_file's Phase-24b ancestor check
    (DIVERGENCE_SHADOW/sysop/scripts/X) was always false → diverged in-scope scripts
    silently overwritten. The old-spelled-lock probe must re-detect the migration
    and finish it. Needs a reachable ancestor for shadow-based preservation, so it
    drives the real pre-namespace installer (like TestT1Preservation)."""

    def test_moved_tree_old_lock_resumes_and_preserves(self, tmp_path):
        commit = _pre_namespace_commit()
        if not commit:
            pytest.skip("no pre-namespace install.sh commit in history")
        wt = tmp_path / "oldwt"
        rc = _git(REPO_ROOT, "worktree", "add", "-q", "--detach", str(wt), commit)
        if rc.returncode != 0:
            pytest.skip("could not materialize pre-namespace worktree")
        try:
            consumer = tmp_path / "c"
            consumer.mkdir()
            _git(consumer, "init", "-q"); _git(consumer, "config", "user.email", "t@t"); _git(consumer, "config", "user.name", "t")
            _git(consumer, "commit", "-q", "--allow-empty", "-m", "init")
            subprocess.run(["bash", str(wt / "install.sh"), str(consumer),
                            "--packs", "python", "--yes", "--no-arm-hooks"],
                           capture_output=True, text=True)
            _git(consumer, "add", "-A"); _git(consumer, "commit", "-q", "-m", "old install")
            # Simulate the crash: relocate the vendor tree to sysop/ by hand, leaving
            # the lock untouched (still old-spelled).
            (consumer / "sysop").mkdir(exist_ok=True)
            _git(consumer, "mv", "scripts", "sysop/scripts")
            (consumer / "sysop" / "docs").mkdir(parents=True, exist_ok=True)
            for d in ("WORKFLOW.md", "WORKFLOW_GUIDE.md"):
                if (consumer / d).exists():
                    _git(consumer, "mv", d, f"sysop/docs/{d}")
            _git(consumer, "add", "-A"); _git(consumer, "commit", "-q", "-m", "half-migrated (crash)")
            # Precondition: the lock still names flat scripts/ paths.
            assert any(m.startswith("scripts/") for m in _lock(consumer)["managed_paths"])
            # Diverge an in-scope managed script at its NEW path and commit it.
            with open(consumer / "sysop" / "scripts" / "claim_task.sh", "a") as f:
                f.write("\n# CONSUMER LOCAL EDIT\n")
            _git(consumer, "add", "-A"); _git(consumer, "commit", "-q", "-m", "diverge migrated script")
            r = _run_update(consumer)
            assert r.returncode == 0, r.stdout + r.stderr
            # Detection must fire even though the tree already moved.
            assert "MIGRATING to the sysop/ vendor dir" in r.stdout, \
                "crash-resume not detected (old-spelled-lock probe missing?)"
            # The committed edit must be preserved, not silently overwritten.
            assert "preserved" in r.stdout.lower()
            preserved = consumer / "sysop" / "scripts" / "claim_task.sh"
            assert "CONSUMER LOCAL EDIT" in preserved.read_text()
            # Lock healed to new-spelled.
            mp = _lock(consumer)["managed_paths"]
            assert "sysop/scripts/claim_task.sh" in mp
            assert "scripts/claim_task.sh" not in mp
        finally:
            _git(REPO_ROOT, "worktree", "remove", "--force", str(wt))


class TestPackScriptProbe:
    """Finding 2 (MEDIUM). The tree-probe enumerated only core companion scripts, so
    a partial migration whose sole leftover is a PACK script (packs/python/…/
    shared_cli.py) didn't re-trigger — the fresh copy landed at sysop/ with no
    preservation and the flat original was stranded/swept. The probe must cover
    installed-pack scripts too."""

    def test_leftover_pack_script_retriggers_migration(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        # python ships shared_cli.py; add it at the flat path and track it.
        (root / "scripts" / "shared_cli.py").write_text("# consumer pack script\n")
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "add pack script")
        # Migrate everything EXCEPT the pack script, and rewrite the lock to the NEW
        # (sysop/) spelling so Finding-1's old-spelled-lock probe stays silent — only
        # the pack-aware tree-probe can catch the leftover.
        (root / "sysop").mkdir(exist_ok=True)
        _git(root, "mv", "scripts", "sysop/scripts")
        (root / "sysop" / "docs").mkdir(parents=True, exist_ok=True)
        for d in ("WORKFLOW.md", "WORKFLOW_GUIDE.md"):
            if (root / d).exists():
                _git(root, "mv", d, f"sysop/docs/{d}")
        (root / "scripts").mkdir(exist_ok=True)
        _git(root, "mv", "sysop/scripts/shared_cli.py", "scripts/shared_cli.py")
        _rewrite_lock_new_spelled(root)
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "crash: only pack script left flat")
        assert (root / "scripts" / "shared_cli.py").is_file()
        r = _run_update(root)
        assert r.returncode == 0, r.stdout + r.stderr
        # The pack-aware tree-probe must re-trigger the migration.
        assert "MIGRATING to the sysop/ vendor dir" in r.stdout, \
            "leftover pack script did not re-trigger (probe still core-only?)"
        # It is migrated into sysop/, not left orphaned at flat scripts/.
        assert not (root / "scripts" / "shared_cli.py").exists()
        assert (root / "sysop" / "scripts" / "shared_cli.py").is_file()


class TestPreflightGatedOnRealMoves:
    """Finding 3 (MEDIUM). The T7 preflight (hard-refuse on extra worktrees / active
    locks / foreign sysop) ran BEFORE the derive, so a pending-but-empty migration
    (leftover flat duplicate, or a consumer file at a shipped basename) blocked every
    routine --update whenever a lock or worktree existed — both normal states. It
    must run only when the derive confirms real working-tree moves."""

    def test_active_lock_does_not_block_when_no_real_moves(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        assert _run_update(root).returncode == 0            # perform the real migration
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "migrated")
        # Re-introduce a leftover flat duplicate (the dst-present-skip artifact):
        # the tree-probe fires, but the derive finds nothing to move.
        (root / "scripts").mkdir(exist_ok=True)
        (root / "scripts" / "claim_task.sh").write_text("# leftover flat duplicate\n")
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "leftover flat dup")
        # An active task lock — the routine workflow state the preflight over-blocked.
        (root / ".locks").mkdir(exist_ok=True)
        (root / ".locks" / "FEAT-1.lock").write_text("owner: x\n")
        r = _run_update(root)
        assert r.returncode == 0, \
            f"routine --update blocked despite no real moves:\n{r.stdout}\n{r.stderr}"


class TestFreshInstallOverOldLayout:
    """Finding 4 (MEDIUM). A lockless fresh install over a committed OLD-layout tree
    (a Sysop install whose lock was lost) passed the T7 guard (which only probed for
    a foreign sysop/ dir): it wrote sysop/ and left the whole flat vendor tree as a
    stale duplicate, with no sweep/report and re-armed hooks over customizations. The
    fresh path must also probe for old flat vendor files and refuse with guidance."""

    def test_lockless_fresh_over_old_flat_tree_refused(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        (root / ".claude" / "sysop.lock").unlink()
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "lost the lock")
        r = subprocess.run(
            ["bash", str(INSTALL_SH), str(root), "--packs", "python", "--yes"],
            capture_output=True, text=True)
        assert r.returncode != 0, "fresh install over old flat tree was not refused"
        assert "no lock" in r.stderr.lower()
        assert "scripts/" in r.stderr
        assert not (root / "sysop" / "scripts").exists()  # nothing written


class TestRefPreNamespaceRefused:
    """Finding 5 (MEDIUM). `--ref <pre-128 rev>` re-points SOURCE content only while
    the destination wiring stays new-layout, so a tag cut before the sysop/ namespace
    installs OLD script bodies into sysop/scripts/ paths — silently broken, exit 0.
    The clone-HEAD T6 shim can't catch it. install.sh must detect the ref's era and
    hard-refuse a pre-namespace ref."""

    def test_ref_before_namespace_refused(self, tmp_path):
        commit = _pre_namespace_commit()
        if not commit:
            pytest.skip("no pre-namespace install.sh commit in history")
        consumer = tmp_path / "c"
        consumer.mkdir()
        _git(consumer, "init", "-q"); _git(consumer, "config", "user.email", "t@t"); _git(consumer, "config", "user.name", "t")
        _git(consumer, "commit", "-q", "--allow-empty", "-m", "init")
        r = subprocess.run(
            ["bash", str(INSTALL_SH), str(consumer), "--ref", commit, "--packs", "python", "--yes"],
            capture_output=True, text=True)
        assert r.returncode != 0, "pre-namespace --ref was not refused"
        assert "predates the sysop/ vendor namespace" in r.stderr
        assert not (consumer / "sysop" / "scripts").exists()  # refused before any write


# ── batch-2 verified-fix regression tests ────────────────────────────────────

class TestSettingsRemovalSetScoping:
    """Batch-2 Finding 1 (HIGH — permission loss). _ns_migrate_settings built its
    removal set with a blanket ``r.replace("sysop/scripts/", "scripts/")`` over the
    whole template — a NO-OP for the ~20 non-path rules (Bash(gh pr merge:*), …), so
    those CURRENT-VALID rules entered the removal set verbatim and were stripped from
    the consumer/harness-owned settings.local.json (never re-added) and from loop-mode
    settings.json (only the 14-rule LOOP_ALLOW subset is re-added). Only genuinely-dead
    old flat vendor-path spellings may ever be removed."""

    def test_non_path_rule_survives_in_settings_local(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        # A harness-approved full-template NON-PATH rule lives in settings.local.json,
        # alongside a genuinely-dead old flat vendor rule that MUST be stripped.
        (root / ".claude" / "settings.local.json").write_text(json.dumps(
            {"permissions": {"allow": [
                "Bash(gh pr merge:*)",               # non-path shipped rule — must survive
                "Bash(bash scripts/run_checks.sh)",  # dead flat vendor rule — must be stripped
            ]}}, indent=2) + "\n")
        r = _run_update(root)
        assert r.returncode == 0, r.stdout + r.stderr
        local = json.loads((root / ".claude" / "settings.local.json").read_text())["permissions"]["allow"]
        assert "Bash(gh pr merge:*)" in local, \
            "valid non-path rule stripped from consumer-owned settings.local.json (Finding 1)"
        assert "Bash(bash scripts/run_checks.sh)" not in local, \
            "dead flat vendor rule not stripped from settings.local.json"

    def test_loop_mode_settings_json_keeps_non_subset_rule(self, tmp_path):
        # In loop mode install_permissions only re-adds the 14-rule LOOP_ALLOW subset,
        # so a full-template rule wrongly stripped from settings.json is lost for good.
        root, _ = _build_old_consumer(tmp_path / "c", mode="loop")
        sj = json.loads((root / ".claude" / "settings.json").read_text())["permissions"]["allow"]
        assert "Bash(gh pr merge:*)" in sj  # fixture ships the full inverse-mapped template
        r = _run_update(root)
        assert r.returncode == 0, r.stdout + r.stderr
        allow = json.loads((root / ".claude" / "settings.json").read_text())["permissions"]["allow"]
        assert "Bash(gh pr merge:*)" in allow, \
            "non-subset rule dropped from settings.json in loop-mode migration (Finding 1)"


class TestAcceptUpstreamOldSpelling:
    """Batch-2 Finding 2 (MEDIUM — silent no-op). --accept-upstream with the OLD
    (flat scripts/) spelling — the path that exists in the consumer's tree at
    invocation and that any pre-migration message named — must still match after the
    tree moves to sysop/. On the unfixed code the key stays old-spelled while copy_file
    keys its lookup on the new spelling, so the requested overwrite silently no-ops
    (file preserved) and a spurious stale-accept warning fires. Needs a reachable
    ancestor for shadow-based preservation, so it drives the real pre-namespace
    installer (like TestT1Preservation)."""

    def test_old_spelled_accept_upstream_overwrites_after_move(self, tmp_path):
        commit = _pre_namespace_commit()
        if not commit:
            pytest.skip("no pre-namespace install.sh commit in history")
        wt = tmp_path / "oldwt"
        rc = _git(REPO_ROOT, "worktree", "add", "-q", "--detach", str(wt), commit)
        if rc.returncode != 0:
            pytest.skip("could not materialize pre-namespace worktree")
        try:
            consumer = tmp_path / "c"
            consumer.mkdir()
            _git(consumer, "init", "-q"); _git(consumer, "config", "user.email", "t@t"); _git(consumer, "config", "user.name", "t")
            _git(consumer, "commit", "-q", "--allow-empty", "-m", "init")
            subprocess.run(["bash", str(wt / "install.sh"), str(consumer),
                            "--packs", "python", "--yes", "--no-arm-hooks"],
                           capture_output=True, text=True)
            _git(consumer, "add", "-A"); _git(consumer, "commit", "-q", "-m", "old install")
            # Diverge an in-scope managed script and commit it.
            with open(consumer / "scripts" / "claim_task.sh", "a") as f:
                f.write("\n# CONSUMER LOCAL EDIT\n")
            _git(consumer, "add", "-A"); _git(consumer, "commit", "-q", "-m", "diverge")
            # Consumer opts to take upstream, naming the OLD path that exists NOW.
            r = _run_update(consumer, "--accept-upstream", "scripts/claim_task.sh")
            assert r.returncode == 0, r.stdout + r.stderr
            migrated = consumer / "sysop" / "scripts" / "claim_task.sh"
            assert migrated.is_file()
            # The explicit accept-upstream must have overwritten the diverged file.
            assert "CONSUMER LOCAL EDIT" not in migrated.read_text(), \
                "old-spelled --accept-upstream silently no-op'd (key not normalized old→new)"
            # And it must not be reported as a stale (unmatched) accept-upstream entry.
            assert "not in preserved set; ignored" not in r.stdout, \
                "old-spelled --accept-upstream reported stale despite naming a real path"
        finally:
            _git(REPO_ROOT, "worktree", "remove", "--force", str(wt))


class TestDryRunStaleRefFidelity:
    """Batch-2 Finding 3 (MEDIUM — dry-run fidelity). The dry-run stale-ref report ran
    against the UNMOVED tree (the report call precedes the dry-run early-return, while
    the tree move + settings/lock rewrite are DRY_RUN=0-gated), so the ``:!sysop/``
    exclusion excluded nothing and the report flooded with Sysop's OWN files (flat
    vendor scripts, old skill bodies, ~20 pre-migration allow-rules, the lock). The
    dry-run scan must simulate the post-move reality — excluding the files Sysop
    owns/rewrites — while STILL surfacing genuine consumer-owned stale refs."""

    def test_dry_run_report_excludes_sysop_owned_lists_consumer(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        # A genuine consumer-owned stale ref that the real run WOULD report.
        (root / "CLAUDE.md").write_text("Run `bash scripts/run_checks.sh` before commit.\n")
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "consumer stale ref")
        r = _run_update(root, "--dry-run")
        assert r.returncode == 0, r.stdout + r.stderr
        assert not (root / "sysop").exists(), "dry-run moved files"
        out = r.stdout
        # The stale-ref entries render as `  • <file>:<line>` under the report header;
        # isolate that section so unrelated output lines don't confuse the assertions.
        marker = "stale references to old scripts/ paths"
        section = out.split(marker, 1)[1] if marker in out else ""
        # The consumer's own file must be surfaced (the scan still runs).
        assert "CLAUDE.md" in section, \
            "dry-run stale-ref scan dropped a genuine consumer ref"
        # Sysop-owned files must NOT flood the report.
        assert ".claude/sysop.lock:" not in section, "lock flooded the dry-run report"
        assert ".claude/settings.json:" not in section, "settings.json flooded the dry-run report"
        assert ".claude/skills/" not in section, "old skill body flooded the dry-run report"
        # A flat vendor script the migration moves must not be listed as a stale ref.
        assert "scripts/claim_task.sh:" not in section, "flat vendor script flooded the dry-run report"


class TestDryRunAdoptBridgePreservationPreview:
    """Batch-2 Finding 4 (MEDIUM — wrong dry-run preview). copy_file's dry-run migration
    remap re-pointed BOTH _work and _anc to the OLD spelling from a single `_work
    missing` gate. On an adopt-bridge dry run the shadow is reconstructed NEW-layout, so
    a VALID new-spelled ancestor was clobbered with a nonexistent old-spelled path → the
    `[[ -f $_anc ]]` gate failed → a file the REAL run preserves was previewed as an
    overwrite. The remap must resolve _work and _anc independently to whichever spelling
    exists."""

    def test_adopt_bridge_dry_run_previews_preserved_not_overwrite(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        head = _git(REPO_ROOT, "rev-parse", "HEAD").stdout.strip()
        # Adopt-bridge shape: NEW-spelled lock + reachable anchor → the reconstructed
        # shadow is NEW-layout while the working tree is still OLD-layout.
        _rewrite_lock_new_spelled(root, reachable_commit=head)
        # Diverge an in-scope script at its OLD path (tree is old-layout) and commit it.
        with open(root / "scripts" / "claim_task.sh", "a") as f:
            f.write("\n# CONSUMER LOCAL EDIT\n")
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "new-spelled lock + diverge")
        r = _run_update(root, "--dry-run")
        assert r.returncode == 0, r.stdout + r.stderr
        assert not (root / "sysop").exists(), "dry-run moved files"
        # The real run preserves this diverged in-scope script; the dry-run PREVIEW
        # must say so, not preview an overwrite.
        assert "preserved: sysop/scripts/claim_task.sh" in r.stdout, \
            "adopt-bridge dry-run mispreviewed a preserved script as an overwrite (Finding 4)"


# ── orchestrator-review revisions ────────────────────────────────────────────

class TestNoLatchOnCollidingBasename:
    """Revision 1. Detection fires whenever the tree-probe matches, and the probe
    matches a SINGLE flat file — so a fully-migrated consumer who keeps their OWN file
    at a shipped basename under flat scripts/ (run_checks.sh; scripts/ was the
    consumer's dir pre-128) trips it on every --update. MIGRATION_MODE must NOT latch
    when there's no real migration work (pending=0, new-spelled lock): otherwise
    report_post_overwrite_deltas is permanently suppressed and the migration report
    prints forever. It must run as a plain update."""

    def test_colliding_own_file_does_not_relatch_migration(self, tmp_path):
        root, _ = _build_old_consumer(tmp_path / "c")
        assert _run_update(root).returncode == 0            # real migration → new-spelled lock
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "migrated")
        # Consumer's OWN file at a shipped basename, at the flat (consumer) dir.
        (root / "scripts").mkdir(exist_ok=True)
        (root / "scripts" / "run_checks.sh").write_text("#!/bin/sh\n# my own runner\n")
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "consumer's own run_checks.sh")
        r = _run_update(root)
        assert r.returncode == 0, r.stdout + r.stderr
        # No re-latch: neither the plan's MIGRATING line nor the migration report fire.
        assert "MIGRATING to the sysop/ vendor dir" not in r.stdout, \
            "migration mode re-latched on a consumer-owned colliding basename"
        assert "namespace migration summary" not in r.stdout, \
            "migration report printed on a normal update (MIGRATION_MODE latched)"
        # Layout record intact — a plain update didn't corrupt the new-spelled lock.
        mp = _lock(root)["managed_paths"]
        assert "sysop/scripts/claim_task.sh" in mp
        assert "scripts/claim_task.sh" not in mp


class TestFreshInstallSingleCollisionProceeds:
    """Revision 2. The lockless-fresh guard refused on a single vendor-basename match,
    so a genuinely-new consumer (never used Sysop) whose repo owns one file at a
    shipped basename (scripts/run_checks.sh) was refused as a lost-lock install. The
    guard now requires corroboration (2+ vendor basenames, or one plus a Sysop
    artifact); a single collision proceeds to a normal fresh install."""

    def test_single_colliding_basename_not_refused(self, tmp_path):
        root = tmp_path / "n"
        root.mkdir()
        _git(root, "init", "-q"); _git(root, "config", "user.email", "t@t"); _git(root, "config", "user.name", "t")
        (root / "scripts").mkdir()
        (root / "scripts" / "run_checks.sh").write_text("#!/bin/sh\n# my own runner\n")
        _git(root, "add", "-A"); _git(root, "commit", "-q", "-m", "my repo, one colliding name")
        # No other Sysop artifacts (no root WORKFLOW*.md, no .claude/convention_map.md).
        r = subprocess.run(
            ["bash", str(INSTALL_SH), str(root), "--packs", "", "--yes"],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
        # It installed (fresh), not refused.
        assert (root / "sysop" / "scripts").exists()
        assert (root / ".claude" / "sysop.lock").exists()
        # The consumer's own flat file is left untouched by the fresh install.
        assert (root / "scripts" / "run_checks.sh").read_text() == "#!/bin/sh\n# my own runner\n"
