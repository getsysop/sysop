"""Integration tests for install.sh's park-namespace rename (Phase 159b).

    sysop/runtime/auto-build/parked/ → sysop/runtime/parked/

/claim-task parks tasks too once it becomes an orchestrator, so an
/auto-build-shaped path is a lie about who writes there. The dir is
gitignored, so the move is a plain mv — same class as Phase 133, whose
_rt_merge_dir this reuses for the crash-resume case.

The load-bearing test here is test_park_migration_is_not_gated_by_the_runtime_
preflight: the rename deliberately does NOT copy _rt_migration_preflight, and
that omission is a decision rather than an oversight. A parked task is by
construction lock-plus-worktree, so the preflight's worktree arm would refuse
on exactly the consumers that have content to migrate — while the skill files
repoint on the same run. See the rationale block above migrate_parked_dir().

These drive the real installer against scratch git consumers (the
test_install_*.py pattern).
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"

PARK_OLD = ("sysop", "runtime", "auto-build", "parked")
PARK_NEW = ("sysop", "runtime", "parked")


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _run_install(target, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )


def _post133_consumer_with_park(root, *, marker="TECH-X__20260701.md",
                                body="# park verdict — must survive\n"):
    """A consumer already on the Phase-133 layout (a fresh install is one by
    construction), with a parked archive planted at the pre-159b path."""
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
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "sysop install")
    # sysop/runtime/ is gitignored, so planting here leaves the tree clean.
    old = root.joinpath(*PARK_OLD)
    old.mkdir(parents=True)
    (old / marker).write_text(body)
    return root


def test_park_moves_to_the_unnested_home(tmp_path):
    root = _post133_consumer_with_park(tmp_path / "c")
    r = _run_install(root, "--update")
    assert r.returncode == 0, r.stdout + r.stderr
    moved = root.joinpath(*PARK_NEW, "TECH-X__20260701.md")
    assert moved.is_file() and "must survive" in moved.read_text()
    assert not root.joinpath(*PARK_OLD).exists(), "old park dir left behind"


def test_auto_build_scratch_dir_survives_the_rename(tmp_path):
    """Only parked/ comes out. sysop/runtime/auto-build/ stays as /auto-build's
    per-worktree plan.md/review.md scratch home — moving or deleting it would
    break a different, still-current path."""
    root = _post133_consumer_with_park(tmp_path / "c")
    scratch = root / "sysop" / "runtime" / "auto-build" / "plan.md"
    scratch.write_text("scratch plan\n")
    r = _run_install(root, "--update")
    assert r.returncode == 0, r.stdout + r.stderr
    assert scratch.is_file(), "auto-build scratch home destroyed by the park rename"
    assert scratch.read_text() == "scratch plan\n"


def test_park_migration_is_not_gated_by_the_runtime_preflight(tmp_path):
    """THE decision test. _rt_migration_preflight refuses when extra worktrees
    exist; the park rename deliberately does not adopt it. A parked task is by
    construction lock-plus-worktree, so adopting it would refuse on precisely
    the consumers with content to migrate, while the skill files repoint on the
    same run — a guaranteed stranding rather than a prevented split-brain.

    If a future change routes the park rename through that preflight, this test
    fails and the tradeoff gets re-argued instead of silently flipping."""
    root = _post133_consumer_with_park(tmp_path / "c")
    wt = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", "--detach", str(wt))
    # And a live lock, the other half of a real parked task's footprint.
    locks = root / "sysop" / "runtime" / "locks"
    locks.mkdir(parents=True, exist_ok=True)
    (locks / "TECH-X.lock").write_text("task_id: TECH-X\nstatus: in_progress\n")

    r = _run_install(root, "--update")
    assert r.returncode == 0, (
        "park rename refused on a worktree+lock consumer — i.e. on exactly the "
        "shape a parked task has:\n" + r.stdout + r.stderr
    )
    assert root.joinpath(*PARK_NEW, "TECH-X__20260701.md").is_file()
    assert (locks / "TECH-X.lock").is_file(), "the live lock was disturbed"


def test_park_crash_resume_merges_without_clobber(tmp_path):
    """Both sides exist (a crash mid-rename): absent entries move, a colliding
    name keeps the DESTINATION copy, and the old copy is left for hand
    reconciliation rather than silently discarded."""
    root = _post133_consumer_with_park(tmp_path / "c")
    new = root.joinpath(*PARK_NEW)
    new.mkdir(parents=True)
    (new / "TECH-Y__20260702.md").write_text("already migrated\n")
    root.joinpath(*PARK_OLD, "TECH-Y__20260702.md").write_text(
        "OLD COPY — must not clobber\n"
    )
    r = _run_install(root, "--update")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (new / "TECH-X__20260701.md").is_file()
    assert (new / "TECH-Y__20260702.md").read_text() == "already migrated\n"
    assert root.joinpath(*PARK_OLD, "TECH-Y__20260702.md").is_file(), (
        "colliding old entry silently discarded instead of left for reconciliation"
    )
    assert "NOT removed" in r.stdout


def test_park_second_run_is_a_no_op(tmp_path):
    root = _post133_consumer_with_park(tmp_path / "c")
    assert _run_install(root, "--update").returncode == 0
    r2 = _run_install(root, "--update")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    assert "park-namespace rename" not in r2.stdout, (
        "second --update re-announced a rename that already completed"
    )
    assert root.joinpath(*PARK_NEW, "TECH-X__20260701.md").is_file()


def test_park_dry_run_previews_and_moves_nothing(tmp_path):
    root = _post133_consumer_with_park(tmp_path / "c")
    r = _run_install(root, "--update", "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "sysop/runtime/parked/" in r.stdout
    assert root.joinpath(*PARK_OLD, "TECH-X__20260701.md").is_file()
    assert not root.joinpath(*PARK_NEW).exists()


def test_no_shipped_content_still_writes_the_old_park_path():
    """Phase-130 class: a prose site missed by the rename keeps writing to a
    dir nothing cleans, and nothing fails. Only install.sh may name the old
    path — it is the migration's source.

    Scoped to the *shipped* tree (core/, packs/, docs/) because that is what a
    consumer installs; tools/ carries spec prose that quotes the old path on
    purpose."""
    offenders = []
    for base in ("core", "packs", "docs"):
        root = REPO_ROOT / base
        if not root.is_dir():
            continue
        for p in root.rglob("*"):
            # .html is in the set because it was NOT, and docs/workflow.html
            # carried a tenth site the sweep therefore could not see.
            if p.is_file() and p.suffix in {".md", ".sh", ".py", ".json",
                                            ".yml", ".yaml", ".html"}:
                try:
                    text = p.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if "runtime/auto-build/parked" in line:
                        offenders.append(f"{p.relative_to(REPO_ROOT)}:{i}")
    assert not offenders, (
        "shipped content still names the pre-159b park path:\n  "
        + "\n  ".join(offenders)
    )


def test_monograph_runtime_figure_lists_the_park_dir():
    """A path-shaped grep cannot see the monograph's ASCII tree — it renders
    the layout as nested basenames, so `runtime/auto-build/parked` never
    appears as a string even when the figure is wrong. The tenth site was
    missed twice over: wrong suffix filter AND wrong search shape.

    Assert the figure's own vocabulary instead: it must name a `parked/` node,
    and its `auto-build/` node must no longer be described as the archive."""
    fig = (REPO_ROOT / "docs" / "workflow.html").read_text(encoding="utf-8")
    assert "runtime/" in fig, "the runtime-dir figure moved — update this guard"
    park_lines = [ln for ln in fig.splitlines()
                  if "├──" in ln or "└──" in ln]
    assert any("parked/" in ln for ln in park_lines), (
        "docs/workflow.html's runtime figure does not list parked/"
    )
    for ln in park_lines:
        if "auto-build/" in ln and "parked" not in ln:
            assert "archive" not in ln.lower(), (
                f"the figure still calls auto-build/ the park archive: {ln.strip()}"
            )


def test_fresh_install_never_announces_the_park_rename(tmp_path):
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
    assert "park-namespace rename" not in r.stdout
