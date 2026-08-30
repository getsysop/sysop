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


def _with_hookspath(tmp_path, name, value="myhooks", make_dir=True):
    root = _consumer(tmp_path / name)
    assert _install(root, "--packs", "", "--no-arm-hooks").returncode == 0
    if make_dir and value:
        (root / value).mkdir(parents=True, exist_ok=True)
    _git(root, "config", "core.hooksPath", value)
    return root


def test_hookspath_remedy_is_one_that_actually_works(tmp_path):
    # Phase 150: self_check is the designated backstop now that no lifecycle
    # script arms hooks, so its remedy has to work. Under a configured
    # core.hooksPath, install_hooks.sh deliberately skips — naming it as the
    # fix would leave the reader unarmed with no next step.
    root = _with_hookspath(tmp_path, "hp1")
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "hook not present:" in r.stdout
    assert "skips by design" in r.stdout, "pointed at a remedy that no-ops"
    assert "hook not armed:" not in r.stdout, "used the .git/hooks wording under core.hooksPath"


def test_hookspath_does_not_claim_credit_for_the_consumers_own_hooks(tmp_path):
    # A hook found in the consumer's own core.hooksPath dir was neither written
    # nor compared by Sysop; reporting it as "armed" is a false attribution the
    # phase's own "your hooks are yours" framing makes worse.
    root = _with_hookspath(tmp_path, "hp2")
    for n in ("pre-commit", "pre-merge-commit"):
        p = root / "myhooks" / n
        p.write_text("#!/bin/sh\nexit 0\n")
        p.chmod(0o755)
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "hook present:" in r.stdout
    assert "not Sysop-managed" in r.stdout
    assert "hook armed:" not in r.stdout, \
        "claimed credit for a hook Sysop neither wrote nor compares"


def test_empty_hookspath_is_surfaced_as_no_hooks_at_all(tmp_path):
    root = _with_hookspath(tmp_path, "hp3", value="", make_dir=False)
    r = _self_check(root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NO hooks at all" in r.stdout


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


# ── Phase 240: agent-isolation residue + core.hooksPath shape ───────────────
# The post-spawn assertion that catches this residue lives in /review-close
# Step 2b, so it runs only during a close. An ad-hoc adversarial round spawns
# the same isolated agents and asserts nothing, so self_check.sh is the
# invoker outside the close. These are behaviour tests, not text greps: each
# builds the state and asserts the report changes.


def _agent_worktree(root, wt_parent, agent_id):
    """Reproduce the shape Claude Code's isolation: worktree creates."""
    path = wt_parent / ".claude" / "worktrees" / f"agent-{agent_id}"
    path.parent.mkdir(parents=True, exist_ok=True)
    _git(root, "worktree", "add", "-q", "-b", f"worktree-agent-{agent_id}", str(path))
    return path


def test_reports_no_residue_on_a_clean_install(tmp_path):
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    r = _self_check(root)
    assert "no agent-isolation residue" in r.stdout, r.stdout + r.stderr


def test_detects_a_leaked_agent_worktree_and_its_branch(tmp_path):
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _agent_worktree(root, root, "deadbeef")
    r = _self_check(root)
    assert "agent-isolation residue: 1 worktree(s), 1 branch(es)" in r.stdout, r.stdout
    assert "no agent-isolation residue" not in r.stdout


def test_detects_the_half_cleaned_state_worktree_gone_branch_left(tmp_path):
    """The common residue shape: the worktree is reclaimed and the branch is
    not. Counting only worktrees would report clean over a real leak."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    path = _agent_worktree(root, root, "cafe1234")
    _git(root, "worktree", "remove", "--force", str(path))
    r = _self_check(root)
    assert "agent-isolation residue: 0 worktree(s), 1 branch(es)" in r.stdout, r.stdout


def test_residue_report_never_prescribes_a_blind_removal(tmp_path):
    """Phase 165 removed the wholesale-wipe rollback. Detection here must not
    reintroduce it: a leaked worktree can hold uncommitted work, and after a
    squash-merge an ancestry test reports non-zero for merged work too."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _agent_worktree(root, root, "beefcafe")
    r = _self_check(root)
    assert "CHECK BEFORE REMOVING" in r.stdout, r.stdout
    # A denylist of exact spellings is not a property. The round showed
    # `git worktree remove -f` -- the same blind removal, one flag shorter --
    # walked straight through the first version of this check.
    import re as _re
    forbidden = [
        _re.compile(r"worktree\s+remove\b[^\n]*(--force|\s-f\b)"),
        _re.compile(r"git\s+branch\s+-[dD]\b"),
        _re.compile(r"\brm\s+-[a-zA-Z]*[rf]"),
        _re.compile(r"worktree\s+prune\b"),
    ]
    for pat in forbidden:
        hit = pat.search(r.stdout)
        assert not hit, (
            f"self_check prescribed a blind removal ({hit.group(0)!r}); Phase 165 "
            "removed exactly this shape and a residue report must not reintroduce it"
        )


def test_relative_hookspath_is_reported_as_the_good_shape(tmp_path):
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _git(root, "config", "--local", "core.hooksPath", ".githooks")
    r = _self_check(root)
    assert "core.hooksPath (--local) is relative ('.githooks')" in r.stdout, r.stdout


def test_absolute_hookspath_is_reported_with_the_restore_command(tmp_path):
    """This is the state an isolated-agent spawn leaves behind. self_check
    cannot know what the owner originally set, so it reports the property and
    its consequence rather than asserting a defect."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _git(root, "config", "--local", "core.hooksPath", str(root / ".githooks"))
    r = _self_check(root)
    assert "core.hooksPath (--local) resolves ABSOLUTE" in r.stdout, r.stdout
    assert "git config --local core.hooksPath" in r.stdout
    assert "is relative" not in r.stdout


def test_unset_hookspath_reports_neither_shape(tmp_path):
    """A repo that sets no core.hooksPath is unaffected by the rewrite; it must
    not be told about a property it does not have."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    r = _self_check(root)
    assert "resolves ABSOLUTE" not in r.stdout
    assert "is relative" not in r.stdout


def test_residue_check_does_not_change_the_exit_code(tmp_path):
    """Residue is advisory. A leaked worktree is not a failed prereq, and
    turning self_check red on it would make the report unusable mid-round."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    clean = _self_check(root)
    _agent_worktree(root, root, "0badcafe")
    dirty = _self_check(root)
    assert clean.returncode == dirty.returncode == 0, (clean.stdout, dirty.stdout)


def test_a_worktree_under_the_dir_counts_even_without_the_agent_prefix(tmp_path):
    """The scope question, decided against this phase's first answer.

    The author's battery row B03 dropped the `agent-` prefix and survived, and
    the first fix read that as "the prefix is load-bearing, it prevents a
    human's checkout being called residue". The round's execution lens showed
    the opposite error is the one that matters: `EnterWorktree`'s `name`
    parameter puts a worktree at `.claude/worktrees/<name>`, so `agent-` is the
    DEFAULT shape and not the only one — and scoping to it reports clean over a
    named agent worktree that `/review-close` Step 2b would flag.

    Step 2b's own first assertion greps `-F '/.claude/worktrees/'`. Two
    detectors for one condition disagreeing is worse than either answer, so
    this one now matches the skill. The cost is stated rather than hidden: a
    human who parks a worktree there is reported too, which is why the report
    is advisory, names what to check, and removes nothing.
    """
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    other = root / ".claude" / "worktrees" / "mine-in-progress"
    other.parent.mkdir(parents=True, exist_ok=True)
    _git(root, "worktree", "add", "-q", "-b", "feat/mine", str(other))
    r = _self_check(root)
    assert "agent-isolation residue: 1 worktree(s), 0 branch(es)" in r.stdout, r.stdout


def test_the_two_counts_are_independent(tmp_path):
    """Worktrees and branches are counted separately: a named worktree has no
    `worktree-agent-*` branch, and a reclaimed lens leaves a branch with no
    worktree. Collapsing them would hide whichever half is zero."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    other = root / ".claude" / "worktrees" / "mine-in-progress"
    other.parent.mkdir(parents=True, exist_ok=True)
    _git(root, "worktree", "add", "-q", "-b", "feat/mine", str(other))
    _agent_worktree(root, root, "facefeed")
    r = _self_check(root)
    assert "agent-isolation residue: 2 worktree(s), 1 branch(es)" in r.stdout, r.stdout


def test_a_tilde_hookspath_is_not_reported_as_relative(tmp_path):
    """`~/gh` is not relative: git expands it, so every worktree is pinned to
    one directory — the exact property this arm warns about. The first version
    tested only `/*` and gave `~/gh` a green tick."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    _git(root, "config", "--local", "core.hooksPath", "~/gh")
    r = _self_check(root)
    assert "resolves ABSOLUTE" in r.stdout, r.stdout
    assert "is relative" not in r.stdout


def test_a_global_absolute_hookspath_is_not_blamed_on_a_spawn(tmp_path):
    """The remedy writes a --local key. If the absolute value came from
    --global and there is no local key, no spawn rewrote anything, and running
    the printed restore would shadow the user's deliberate setting."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    gitconfig = tmp_path / "gc"
    gitconfig.write_text("[core]\n\thooksPath = /somewhere/global-hooks\n")
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    env["GIT_CONFIG_GLOBAL"] = str(gitconfig)
    env["GIT_CONFIG_SYSTEM"] = "/dev/null"
    r = subprocess.run(
        ["bash", str(root / "sysop/scripts/self_check.sh")],
        cwd=str(root), capture_output=True, text=True, env=env,
    )
    assert "agent spawn rewrote it" not in r.stdout, r.stdout
    assert "resolves ABSOLUTE" not in r.stdout
    assert "is relative" not in r.stdout


def test_residue_is_reported_even_when_no_hooks_are_armed(tmp_path):
    """H04: every other fixture installs with hooks armed, so gating the whole
    residue block on $ARMED survived the round's mutation. A hooks-less
    consumer -- loop mode, or CI-only enforcement, which this script's own
    header calls out -- is exactly who would never see the report."""
    root = _consumer(tmp_path / "c")
    assert _install(root, "--packs", "").returncode == 0
    hooks = root / ".git" / "hooks"
    for f in hooks.glob("*"):
        if not f.name.endswith(".sample"):
            f.unlink()
    _agent_worktree(root, root, "beadfeed")
    r = _self_check(root)
    assert "hook armed:" not in r.stdout, "fixture still has hooks armed"
    assert "agent-isolation residue: 1 worktree(s), 1 branch(es)" in r.stdout, r.stdout
