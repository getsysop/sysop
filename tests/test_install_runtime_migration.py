"""Integration tests for install.sh's runtime-dir consolidation (Phase 133).

The four gitignored runtime dirs move under one vendor-namespaced home on
--update (SYSOP_NAMESPACE_SPEC § 10, the deliberately-cut Phase 128 leg):
    .subagent-envelopes/ → sysop/runtime/subagent-envelopes/
    .auto-build/         → sysop/runtime/auto-build/
    .pending-docs/       → sysop/runtime/pending-docs/
    .locks/              → sysop/runtime/locks/

Hard requirements exercised here (spec § 10 v2):
  1. move-if-exists — .auto-build/parked/ archive content survives (Phase 65a);
  2. resumable — a crash-resume where both sides exist merges without clobber;
  3. the worktree preflight — extra worktrees refuse the consolidation
     (mixed-version lock split-brain), and the leg must not ship without it.

These drive the real installer against scratch git consumers (the
test_install_*.py pattern).
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _run_install(target, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )


def _consumer_with_old_runtime_dirs(root):
    """Fresh Sysop install, committed, then the four PRE-133 dot-dirs planted
    with distinguishable content (simulating a pre-consolidation consumer)."""
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("hi\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    r = _run_install(root, "--packs", "")
    assert r.returncode == 0, r.stdout + r.stderr
    # A real pre-133 consumer's installer appended the four dot-dir gitignore
    # entries — replicate that so the planted dirs are ignored (the plain
    # re-install path's dirty-tree refusal keys on untracked+unignored files,
    # and a genuine pre-133 tree is clean here).
    with open(root / ".gitignore", "a") as gi:
        gi.write(".subagent-envelopes/\n.auto-build/\n.pending-docs/\n.locks/\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "sysop install")
    # Plant the old runtime dirs (gitignored content — no commit needed).
    (root / ".locks").mkdir()
    (root / ".locks" / "FEAT-DONE.lock~stale").write_text("not-a-lock\n")
    (root / ".auto-build" / "parked").mkdir(parents=True)
    (root / ".auto-build" / "parked" / "TECH-X__20260701.md").write_text(
        "# park verdict — must survive (Phase 65a)\n"
    )
    (root / ".pending-docs").mkdir()
    (root / ".pending-docs" / "feat-branch.md").write_text("---\nroadmap_ids: []\n---\n")
    (root / ".subagent-envelopes").mkdir()
    (root / ".subagent-envelopes" / "_unparseable_1.json").write_text("{}\n")
    return root


def test_update_moves_all_four_dirs_and_content_survives(tmp_path):
    root = _consumer_with_old_runtime_dirs(tmp_path / "c")
    r = _run_install(root, "--update")
    assert r.returncode == 0, r.stdout + r.stderr
    rt = root / "sysop" / "runtime"
    # Phase 65a durability: the parked archive arrived intact.
    parked = rt / "auto-build" / "parked" / "TECH-X__20260701.md"
    assert parked.is_file() and "must survive" in parked.read_text()
    assert (rt / "pending-docs" / "feat-branch.md").is_file()
    assert (rt / "subagent-envelopes" / "_unparseable_1.json").is_file()
    assert (rt / "locks" / "FEAT-DONE.lock~stale").is_file()
    # Old spellings are gone.
    for old in (".locks", ".auto-build", ".pending-docs", ".subagent-envelopes"):
        assert not (root / old).exists(), f"{old} left behind"


def test_second_update_is_a_no_op_resume(tmp_path):
    root = _consumer_with_old_runtime_dirs(tmp_path / "c")
    assert _run_install(root, "--update").returncode == 0
    _git(root, "add", "-A"); _git(root, "commit", "-qm", "post-migration")
    r2 = _run_install(root, "--update")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "runtime-dir consolidation" not in r2.stdout, (
        "second --update re-announced a migration that already completed"
    )
    assert (root / "sysop" / "runtime" / "auto-build" / "parked"
            / "TECH-X__20260701.md").is_file()


def test_crash_resume_merges_without_clobber(tmp_path):
    """Both sides exist (a crash between dirs): the merge moves absent entries,
    recurses into dir/dir collisions (parked/), and never clobbers an existing
    destination file."""
    root = _consumer_with_old_runtime_dirs(tmp_path / "c")
    rt = root / "sysop" / "runtime"
    # Pre-create a partially-migrated destination: auto-build/parked already
    # holds one archive; the old side holds another + a colliding name with
    # DIFFERENT content that must not be overwritten.
    (rt / "auto-build" / "parked").mkdir(parents=True)
    (rt / "auto-build" / "parked" / "TECH-Y__20260702.md").write_text("already migrated\n")
    (root / ".auto-build" / "parked" / "TECH-Y__20260702.md").write_text("OLD COPY — must not clobber\n")
    r = _run_install(root, "--update")
    assert r.returncode == 0, r.stdout + r.stderr
    parked = rt / "auto-build" / "parked"
    # The non-colliding archive merged in; the colliding one kept the
    # destination copy and left the old copy in place for hand reconciliation.
    assert (parked / "TECH-X__20260701.md").is_file()
    assert (parked / "TECH-Y__20260702.md").read_text() == "already migrated\n"
    assert (root / ".auto-build" / "parked" / "TECH-Y__20260702.md").is_file(), (
        "colliding old entry silently discarded instead of left for reconciliation"
    )
    assert "NOT removed" in r.stdout


def test_extra_worktree_refuses_consolidation(tmp_path):
    """Spec § 10 v2: pre-migration worktree script copies write .locks/ at the
    main checkout while a migrated main writes sysop/runtime/locks/ — the
    preflight must refuse rather than half-migrate into a split-brain."""
    root = _consumer_with_old_runtime_dirs(tmp_path / "c")
    wt = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", "--detach", str(wt))
    r = _run_install(root, "--update")
    assert r.returncode != 0
    assert "split-brain" in r.stderr or "worktree" in r.stderr.lower()
    # Nothing moved.
    assert (root / ".auto-build" / "parked" / "TECH-X__20260701.md").is_file()
    assert not (root / "sysop" / "runtime").exists()


def test_active_lock_refuses_consolidation(tmp_path):
    root = _consumer_with_old_runtime_dirs(tmp_path / "c")
    (root / ".locks" / "FEAT-LIVE.lock").write_text("owner: someone\n")
    r = _run_install(root, "--update")
    assert r.returncode != 0
    assert "quiet queue" in r.stderr or "lock" in r.stderr.lower()
    assert not (root / "sysop" / "runtime").exists()


def test_dry_run_prints_plan_and_moves_nothing(tmp_path):
    root = _consumer_with_old_runtime_dirs(tmp_path / "c")
    r = _run_install(root, "--update", "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "would move" in r.stdout
    assert "sysop/runtime/" in r.stdout
    assert (root / ".auto-build" / "parked" / "TECH-X__20260701.md").is_file()
    assert not (root / "sysop" / "runtime").exists()


def test_fresh_install_never_announces_consolidation(tmp_path):
    root = tmp_path / "f"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("hi\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    r = _run_install(root, "--packs", "")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "runtime-dir consolidation" not in r.stdout


def test_plain_reinstall_over_locked_install_also_migrates(tmp_path):
    """Adversarial-review fix (2026-07-19): a plain re-install (no --update)
    over a lock-carrying install is a sanctioned path that installs post-133
    writers — it must run the consolidation (and its preflight) too, or live
    locks/parked archives strand at the old paths while every new resolver
    reads sysop/runtime/."""
    root = _consumer_with_old_runtime_dirs(tmp_path / "c")
    r = _run_install(root, "--packs", "")           # NOT --update
    assert r.returncode == 0, r.stdout + r.stderr
    assert (root / "sysop" / "runtime" / "auto-build" / "parked"
            / "TECH-X__20260701.md").is_file()
    assert not (root / ".auto-build").exists()


def test_plain_reinstall_with_live_lock_refuses(tmp_path):
    root = _consumer_with_old_runtime_dirs(tmp_path / "c")
    (root / ".locks" / "FEAT-LIVE.lock").write_text("owner: someone\n")
    r = _run_install(root, "--packs", "")           # NOT --update
    assert r.returncode != 0
    assert "quiet queue" in r.stderr or "lock" in r.stderr.lower()
    assert not (root / "sysop" / "runtime").exists()


def test_fresh_install_never_moves_foreign_runtime_dirs(tmp_path):
    """A lock-less target's .locks/ or .pending-docs/ belongs to some OTHER
    tool — a genuinely fresh install must leave it alone."""
    root = tmp_path / "f"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("hi\n")
    (root / ".locks").mkdir()
    (root / ".locks" / "other-tool.lock").write_text("not ours\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    r = _run_install(root, "--packs", "")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (root / ".locks" / "other-tool.lock").is_file()
    assert not (root / "sysop" / "runtime" / "locks").exists()
