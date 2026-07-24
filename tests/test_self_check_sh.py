"""Tests for sysop/scripts/self_check.sh (Phase 133 — the round-4 cold-read
one-command post-install prereq check: bash + PyYAML + hooks in one report
instead of discovery-by-failure).

Real-subprocess tests against scratch consumers (the test_install_*.py
pattern): the script's contract is exit 0 iff the hard prereqs (git repo,
install lock, a PyYAML-capable python3) all pass; hooks + optional scanners
are reported but advisory.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
SELF_CHECK_SRC = REPO_ROOT / "core/companion/scripts/self_check.sh"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _consumer(root):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("hi\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _install(target, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )


def _self_check(root, cwd=None):
    env = dict(os.environ)
    # The test venv's python has PyYAML — put it first on PATH so probe 3
    # passes deterministically regardless of the host system python.
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    # The script binary lives in the install target (main checkout); `cwd`
    # lets a worktree case run it from inside the worktree while still pointing
    # at main's copy (sysop/scripts/ is an uncommitted install artifact absent
    # from a fresh worktree checkout).
    return subprocess.run(
        ["bash", str(root / "sysop/scripts/self_check.sh")],
        cwd=str(cwd or root), capture_output=True, text=True, env=env,
    )


def test_passes_on_fresh_full_install(tmp_path):
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "install lock present (mode: full)" in r.stdout
    assert "python3 with PyYAML" in r.stdout
    # Fresh installs arm hooks by default — the report should show them armed.
    assert "hook armed:" in r.stdout
    assert "0 failed" in r.stdout


def test_passes_on_loop_install_and_reports_mode(tmp_path):
    root = _consumer(tmp_path / "l")
    assert _install(root, "--packs", "", "--mode", "loop").returncode == 0
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "install lock present (mode: loop)" in r.stdout


def test_fails_without_lock(tmp_path):
    root = _consumer(tmp_path / "n")
    assert _install(root, "--packs", "").returncode == 0
    (root / ".claude" / "sysop.lock").unlink()
    r = _self_check(root)
    assert r.returncode == 1
    assert "no .claude/sysop.lock" in r.stdout


def test_fails_outside_git_repo(tmp_path):
    root = _consumer(tmp_path / "g")
    assert _install(root, "--packs", "").returncode == 0
    script = root / "sysop/scripts/self_check.sh"
    bare = tmp_path / "bare"
    bare.mkdir()
    env = dict(os.environ)
    env["GIT_CEILING_DIRECTORIES"] = str(tmp_path)
    r = subprocess.run(["bash", str(script)], cwd=bare,
                       capture_output=True, text=True, env=env)
    assert r.returncode == 1
    assert "not inside a git repository" in r.stdout


def test_unarmed_hooks_reported_advisory_not_failing(tmp_path):
    root = _consumer(tmp_path / "u")
    assert _install(root, "--packs", "", "--no-arm-hooks").returncode == 0
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "hook not armed:" in r.stdout
    assert "install_hooks.sh" in r.stdout


def test_source_and_installed_copies_match():
    """self_check.sh ships via install_companion_scripts — drift guard that the
    source copy is executable bash (a syntax error would break every consumer's
    first command)."""
    r = subprocess.run(["bash", "-n", str(SELF_CHECK_SRC)],
                      capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ── Probe 6: review-round evidence (Phase 143) ──────────────────────────────
# The outer half of the refusal/abandonment check. A round that dies mid-flight
# leaves a marker; a model that refuses one task class outright leaves an
# asymmetric round history. Both must be loud; neither may fire on the
# innocent cases (fresh install, live concurrent session).

MARKER_DIR = "sysop/runtime/pending-rounds"


def _marker(root, name, age_hours=0.0, nonce="1-1"):
    d = root / MARKER_DIR
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(f"skill: x\nstarted: 2026-07-23T10:00:00\nnonce: {nonce}\n")
    if age_hours:
        old = time.time() - age_hours * 3600
        os.utime(p, (old, old))
    return p


def _rounds(root, text, archive=False):
    name = "review_tasks_archive.md" if archive else "review_tasks.md"
    (root / name).write_text(text)


def test_no_markers_reports_clean(tmp_path):
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no review round left pending" in r.stdout


def test_fresh_marker_is_neutral_not_a_failure(tmp_path):
    """A concurrent session mid-round is normal. Alarming on it would train
    consumers to ignore the signal — the failure mode the pinned-removal
    design exists to avoid."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _marker(root, "security-audit.1-1.pending", age_hours=0.1)
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "in flight" in r.stdout
    assert "never completed" not in r.stdout


def test_stale_marker_fails_and_names_the_round(tmp_path):
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _marker(root, "security-audit.1-1.pending", age_hours=9)
    r = _self_check(root)
    assert r.returncode == 1
    assert "started and never completed" in r.stdout
    assert "security-audit.1-1.pending" in r.stdout
    # The marker file's own `started:` value is echoed, so the reader knows
    # WHEN without the script doing BSD/GNU date arithmetic.
    assert "2026-07-23T10:00:00" in r.stdout


def test_symmetric_absence_is_neutral(tmp_path):
    """Fresh install: neither skill has run. That is a not-yet-started loop,
    not a refusal, and must not redden the check."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _rounds(root, "# Code Review Tasks\n\nno rounds yet\n")
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "nothing has run, which is not a fault" in r.stdout


def test_asymmetric_history_is_reported_but_does_not_fail(tmp_path):
    """Quality rounds recorded, no security audit ever. That is the shape a
    refused task class leaves — but it is ALSO the shape of a consumer who
    simply hasn't run the audit yet, and round history cannot tell them apart.
    Failing here would redden every adopter mid-adoption, so the check names
    both readings and stays advisory."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _rounds(root, "## Round 1 (2026-07-01) — Code Quality Review\n")
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "asymmetric round history" in r.stdout
    assert "no security audit has completed" in r.stdout
    # Both readings offered — no unearned refusal claim.
    assert "has not been run here yet" in r.stdout
    assert "refused/abandoned" in r.stdout


def test_asymmetry_is_reported_in_the_other_direction_too(tmp_path):
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _rounds(root, "## Round 1 (2026-07-01) — OWASP Security Audit\n")
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "no code-quality round has completed" in r.stdout


def test_only_the_stale_marker_fails_the_check(tmp_path):
    """The two probe-6 signals are deliberately split by how ambiguous they
    are: a marker that outlived its round proves a round started and never
    finished, so it fails; an asymmetric history proves nothing on its own."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _rounds(root, "## Round 1 (2026-07-01) — Code Quality Review\n")
    assert _self_check(root).returncode == 0
    _marker(root, "security-audit.1-1.pending", age_hours=9)
    assert _self_check(root).returncode == 1


def test_combined_same_day_header_counts_for_both_skills(tmp_path):
    """Step 5b merges same-day rounds into one combined header. A suffix-keyed
    parse would read this as 'no code-quality round ever ran' and fire a false
    refusal alarm — the substring match is what prevents that."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _rounds(root, "## Round 4 (2026-07-02) — Code Quality Review + OWASP Security Audit\n")
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "last code-quality round: 2026-07-02" in r.stdout
    assert "last security audit: 2026-07-02" in r.stdout


def test_archived_rounds_count(tmp_path):
    """A diligent consumer's active file legitimately holds no security round —
    the archiver relocated it. Reading only review_tasks.md would report a
    completed audit as missing."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _rounds(root, "## Round 9 (2026-07-20) — Code Quality Review\n")
    _rounds(root, "## Round 2 (2026-07-01) — OWASP Security Audit\n", archive=True)
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "last security audit: 2026-07-01" in r.stdout


def test_latest_round_date_wins_across_both_files(tmp_path):
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _rounds(root, "## Round 9 (2026-07-20) — Code Quality Review + OWASP Security Audit\n")
    _rounds(root, "## Round 2 (2026-07-01) — OWASP Security Audit\n", archive=True)
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "last security audit: 2026-07-20" in r.stdout


def test_stale_marker_in_main_is_seen_from_a_worktree(tmp_path):
    """Regression guard (adversarial review 2026-07-23): probe 6 must anchor to
    the MAIN checkout via --git-common-dir, not --show-toplevel. Markers live in
    main; a self-check run from inside a worktree that read the worktree copy
    would find an empty dir and falsely report all-clear on an abandoned round —
    the silent under-report this phase exists to close. Mirrors the pre-scan's
    test_prescan_note_sees_markers_from_inside_a_worktree."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _marker(root, "security-audit.1-1.pending", age_hours=9)
    wt = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", "-b", "feat/x", str(wt))
    r = _self_check(root, cwd=wt)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "started and never completed" in r.stdout
    assert "security-audit.1-1.pending" in r.stdout


def test_round_history_read_from_main_when_run_from_a_worktree(tmp_path):
    """The canonical round history lives on the main checkout. A worktree on a
    fresh feature branch (no review_tasks.md of its own) must still see main's
    completed rounds rather than reporting 'the loop has not run here'."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _rounds(root, "## Round 3 (2026-07-05) — Code Quality Review + OWASP Security Audit\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed rounds")
    wt = tmp_path / "wt"
    _git(root, "worktree", "add", "-q", "-b", "feat/y", str(wt))
    r = _self_check(root, cwd=wt)
    assert "last security audit: 2026-07-05" in r.stdout, r.stdout + r.stderr
