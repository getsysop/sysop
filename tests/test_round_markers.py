"""Phase 143 — review-round refusal/abandonment loudness.

A review round that dies mid-flight (a model refusing the task class after
starting, a crash, quota exhaustion, context death) produces no
`review_tasks.md` entries, no error, and no trace — indistinguishable from a
clean round that found nothing. Provenance: a cross-harness comparison in which
one frontier non-Claude model refused `/security-audit` 2/2, once before doing
any work and once after ~1 minute of genuine effort.

The design has two layers with different reach, and this file tests both:

- **In-skill marker** (§1) — a nonce-keyed file under
  `sysop/runtime/pending-rounds/`, written at round-open and cleared when
  findings land. Catches mid-run death. The heredoc bodies are extracted from
  the shipped SKILL.md prose and executed here, so the thing under test is the
  thing that ships (the test_review_close_close_heredoc.py pattern).
- **Outer absence checks** (§2) — `run_checks`' pre-scan summary note and
  `/sitrep`'s discrepancy scan. These run independently of the round, which is
  the only way to see a round that never started.

The honest limit, which no test here can close: a refusal that *precedes*
compliance leaves nothing for layer 1 to find. `self_check.sh`'s asymmetric
round-history alarm (tests/test_self_check_sh.py) is what covers that world.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = {
    "codebase-review": REPO_ROOT / "core/skills/codebase-review/SKILL.md",
    "security-audit": REPO_ROOT / "core/skills/security-audit/SKILL.md",
}
MARKER_REL = "sysop/runtime/pending-rounds"


# ── heredoc extraction ──────────────────────────────────────────────────────


def _extract(skill: str, opener: str) -> str:
    """Pull a `python3 - <<'PY'` body out of a skill's markdown.

    Both blocks sit at column 0 inside fenced code blocks, so the terminator is
    a bare `PY` line. Anchoring on the full opener (which carries the skill name
    or the ROUND_MARKER placeholder) keeps this robust if more heredocs are
    added later.
    """
    text = SKILLS[skill].read_text(encoding="utf-8")
    at = text.find(opener)
    assert at != -1, f"{skill}: could not find heredoc opener {opener!r}"
    start = at + len(opener)
    end = text.find("\nPY\n", start)
    assert end != -1, f"{skill}: could not find heredoc terminator"
    return textwrap.dedent(text[start:end])


def write_src(skill: str) -> str:
    return _extract(skill, f"python3 - <<'PY' \"{skill}\" \"$ARGUMENTS\"\n")


def clear_src(skill: str) -> str:
    return _extract(
        skill, "python3 - <<'PY' \"<ROUND_MARKER path from Pre-flight>\"\n"
    )


# ── fixtures ────────────────────────────────────────────────────────────────


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo(root: Path, gitignore: str = "sysop/runtime/\n") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("hi\n")
    if gitignore:
        (root / ".gitignore").write_text(gitignore)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(src: str, cwd: Path, *argv: str) -> subprocess.CompletedProcess:
    """Execute an extracted heredoc body the way the skill would.

    `python3 - <<PY a b` puts a/b at sys.argv[1:]; `-c` has the same shape.
    """
    return subprocess.run(
        [sys.executable, "-c", src, *argv],
        cwd=cwd, capture_output=True, text=True,
    )


def _markers(root: Path) -> list[Path]:
    d = root / MARKER_REL
    return sorted(d.glob("*.pending")) if d.is_dir() else []


def _plant(root: Path, name: str, age_hours: float, nonce: str = "1-1") -> Path:
    d = root / MARKER_REL
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(f"skill: x\nstarted: 2026-07-23T10:00:00\nnonce: {nonce}\n")
    old = time.time() - age_hours * 3600
    os.utime(p, (old, old))
    return p


def _marker_path(stdout: str) -> Path:
    line = [ln for ln in stdout.splitlines() if ln.startswith("ROUND_MARKER=")]
    assert line, f"no ROUND_MARKER= line in output:\n{stdout}"
    return Path(line[0].split("=", 1)[1])


# ── §1 marker write ─────────────────────────────────────────────────────────


def test_write_creates_a_nonce_keyed_marker(tmp_path):
    for skill in SKILLS:
        root = _repo(tmp_path / skill)
        r = _run(write_src(skill), root, skill, "--full")
        assert r.returncode == 0, r.stderr
        found = _markers(root)
        assert len(found) == 1, r.stdout
        assert found[0].name.startswith(f"{skill}.")
        body = found[0].read_text()
        assert f"skill: {skill}" in body
        assert "started: " in body
        assert "nonce: " in body
        assert "flags: --full" in body
        assert _marker_path(r.stdout) == found[0]


def test_write_never_reports_its_own_marker(tmp_path):
    """The listing runs BEFORE the write, so a round cannot detect itself.

    Ordering them the other way would make every round report a live marker on
    its own first run — a false 'concurrent session' on a single-session repo.
    """
    root = _repo(tmp_path / "self")
    r = _run(write_src("security-audit"), root, "security-audit", "")
    assert r.returncode == 0, r.stderr
    assert "no prior markers" in r.stdout
    assert "live " not in r.stdout


def test_write_reports_prior_markers_by_age(tmp_path):
    root = _repo(tmp_path / "prior")
    _plant(root, "security-audit.old.pending", age_hours=9)
    _plant(root, "codebase-review.new.pending", age_hours=0.2)
    r = _run(write_src("codebase-review"), root, "codebase-review", "")
    assert r.returncode == 0, r.stderr
    assert "STALE security-audit.old.pending" in r.stdout
    assert "never completed" in r.stdout
    assert "live  codebase-review.new.pending" in r.stdout
    assert "concurrent session" in r.stdout
    # Reporting is read-only: prior markers survive, including the stale one.
    assert len(_markers(root)) == 3


def test_write_skips_when_runtime_dir_is_not_gitignored(tmp_path):
    """A marker that dirties the tree breaks /review-close's dirty-worktree
    classification, so a stale pre-Phase-133 install gets NO marker rather than
    a corrupted close. Layer 1 disarms loudly instead of doing harm."""
    root = _repo(tmp_path / "unignored", gitignore="")
    r = _run(write_src("security-audit"), root, "security-audit", "")
    assert r.returncode == 0, r.stderr
    assert "not gitignored" in r.stdout
    assert "layer 1 disarmed" in r.stdout
    assert _markers(root) == []
    assert "ROUND_MARKER=" not in r.stdout


def test_write_outside_a_git_repo_degrades_quietly(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(tmp_path))
    r = subprocess.run(
        [sys.executable, "-c", write_src("codebase-review"), "codebase-review", ""],
        cwd=plain, capture_output=True, text=True, env=env,
    )
    assert r.returncode == 0, r.stderr
    assert "not a git repository" in r.stdout
    assert _markers(plain) == []


def test_write_from_a_worktree_lands_in_the_main_checkout(tmp_path):
    """Phase 32 lock precedent, reaffirmed by Phase 65a: a marker written inside
    a worktree is invisible to every reader and is destroyed by
    `git worktree remove` — exactly the evidence loss this phase exists to stop.
    """
    main = _repo(tmp_path / "main")
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", "feat/x", str(wt))
    r = _run(write_src("security-audit"), wt, "security-audit", "")
    assert r.returncode == 0, r.stderr
    assert len(_markers(main)) == 1, r.stdout
    assert _markers(wt) == []
    assert _marker_path(r.stdout).is_relative_to(main.resolve())


# ── §1 marker removal ───────────────────────────────────────────────────────


def test_round_trip_write_then_clear(tmp_path):
    for skill in SKILLS:
        root = _repo(tmp_path / f"rt-{skill}")
        w = _run(write_src(skill), root, skill, "")
        marker = _marker_path(w.stdout)
        c = _run(clear_src(skill), root, str(marker))
        assert c.returncode == 0, c.stderr
        assert "cleared" in c.stdout
        assert _markers(root) == []


def test_clear_refuses_on_nonce_mismatch(tmp_path):
    """Concurrent rounds each own exactly one nonce-keyed file. Deleting another
    session's marker would erase the evidence this mechanism exists to preserve,
    so a path/content nonce disagreement is a refusal, not a best guess."""
    root = _repo(tmp_path / "mismatch")
    victim = _plant(root, "security-audit.111-1.pending", age_hours=0.1,
                    nonce="999-9")
    r = _run(clear_src("security-audit"), root, str(victim))
    assert r.returncode == 0, r.stderr
    assert "REFUSING to remove" in r.stdout
    assert victim.exists(), "refused removal must leave the marker in place"


def test_clear_is_a_noop_when_the_marker_is_already_gone(tmp_path):
    root = _repo(tmp_path / "gone")
    r = _run(clear_src("codebase-review"), root,
             str(root / MARKER_REL / "codebase-review.1-1.pending"))
    assert r.returncode == 0, r.stderr
    assert "nothing to clear" in r.stdout


def test_clear_removes_only_the_named_marker(tmp_path):
    root = _repo(tmp_path / "siblings")
    w = _run(write_src("security-audit"), root, "security-audit", "")
    mine = _marker_path(w.stdout)
    other = _plant(root, "codebase-review.222-2.pending", age_hours=0.1,
                   nonce="222-2")
    _run(clear_src("security-audit"), root, str(mine))
    assert not mine.exists()
    assert other.exists(), "a concurrent session's marker must survive"


# ── §2 outer absence: the pre-scan summary note ─────────────────────────────


def _note(root: Path, **kw):
    from run_checks.cli import _pending_rounds_note
    return _pending_rounds_note(str(root), **kw)


def test_prescan_note_silent_without_markers(tmp_path):
    assert _note(_repo(tmp_path / "clean")) is None


def test_prescan_note_silent_on_a_fresh_marker(tmp_path):
    root = _repo(tmp_path / "fresh")
    _plant(root, "security-audit.1-1.pending", age_hours=0.2)
    assert _note(root) is None


def test_prescan_note_names_stale_rounds(tmp_path):
    root = _repo(tmp_path / "stale")
    _plant(root, "security-audit.1-1.pending", age_hours=9)
    note = _note(root)
    assert note is not None
    assert "1 review round(s) started and never completed" in note
    assert "security-audit.1-1.pending" in note


def test_prescan_note_truncates_long_lists(tmp_path):
    root = _repo(tmp_path / "many")
    for i in range(5):
        _plant(root, f"security-audit.{i}-1.pending", age_hours=9)
    note = _note(root)
    assert note is not None
    assert "5 review round(s)" in note
    assert "(+2 more)" in note


def test_prescan_note_sees_markers_from_inside_a_worktree(tmp_path):
    """The pre-scan may run in a worktree; markers live in the main checkout."""
    main = _repo(tmp_path / "main")
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", "feat/y", str(wt))
    _plant(main, "security-audit.1-1.pending", age_hours=9)
    note = _note(wt)
    assert note is not None
    assert "never completed" in note


def test_prescan_note_never_raises_outside_a_repo(tmp_path):
    """A probe that breaks the pre-scan would be a worse defect than the silence
    it reports on."""
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _note(plain) is None


# ── §2 outer absence: /sitrep ───────────────────────────────────────────────


def _discrepancies(root: Path):
    import sitrep_survey
    return sitrep_survey._find_discrepancies([], [], {}, root)


def test_sitrep_flags_a_stale_round(tmp_path):
    root = _repo(tmp_path / "sitrep")
    _plant(root, "security-audit.1-1.pending", age_hours=9)
    kinds = [d.kind for d in _discrepancies(root)]
    assert "abandoned review round" in kinds


def test_sitrep_ignores_a_live_round(tmp_path):
    root = _repo(tmp_path / "sitrep-live")
    _plant(root, "security-audit.1-1.pending", age_hours=0.2)
    kinds = [d.kind for d in _discrepancies(root)]
    assert "abandoned review round" not in kinds


# ── drift guards on the shipped prose ───────────────────────────────────────


def test_both_skills_ship_the_marker_lifecycle():
    """The write and the pinned removal must stay paired in BOTH skills. A skill
    that writes without clearing turns every completed round into a false
    abandonment report — the chronic-false-alarm failure the pinned removal
    point was chosen to avoid."""
    for skill, path in SKILLS.items():
        text = path.read_text(encoding="utf-8")
        assert "## Pre-flight: Round Marker" in text, skill
        assert f"python3 - <<'PY' \"{skill}\" \"$ARGUMENTS\"" in text, skill
        assert "### 5f. Clear the round marker" in text, skill
        assert MARKER_REL in text, skill
        # Removal is pinned BEFORE the report summary, not at the true end.
        assert text.index("### 5f.") < text.index("## Step 6: Report Summary"), skill


def test_a_clean_round_still_clears_its_marker():
    """Zero findings is a result, not a reason to skip Step 5. Without this
    stated, a model finding nothing could reasonably jump to the summary and
    strand a marker — reporting every healthy round as abandoned, which is the
    cry-wolf failure that makes the whole signal worthless."""
    for skill, path in SKILLS.items():
        text = path.read_text(encoding="utf-8")
        assert "found nothing still clears its marker" in text, skill


def test_zero_finding_guard_is_at_the_step5_heading_not_only_in_5f():
    """Adversarial review 2026-07-23: a model that finds nothing reads the
    Step 5 heading, concludes 'nothing to write', and can skip to Step 6 —
    never reaching the clear-your-marker instruction if it lives only inside
    5f. The guard must sit at the Step 5 entrypoint, ahead of 5a, where a
    step-skipping model actually reads it."""
    for skill, path in SKILLS.items():
        text = path.read_text(encoding="utf-8")
        step5 = text.index("## Step 5: Write to")
        step5a = text.index("### 5a.", step5)
        heading_block = text[step5:step5a]
        assert "even with zero findings" in heading_block, (
            f"{skill}: the zero-findings guard is not at the Step 5 heading — a "
            "model skipping Step 5 on a clean round won't read it"
        )


def test_both_skills_state_the_honest_limit():
    """A refusal preceding compliance is undetectable from inside the round.
    Overstating the marker's reach is the failure mode this phase is correcting,
    so the limit ships in the prose, not just the spec."""
    for skill, path in SKILLS.items():
        text = path.read_text(encoding="utf-8")
        assert "cannot detect a refusal that *precedes* compliance" in text, skill
        assert "workaround" in text, skill


def test_marker_step_is_best_effort_not_a_hard_permission_gate():
    """`Bash(python3 -:*)` ships in both the master template and the loop
    subset, but a consumer on an older settings.json must lose the MARKER, not
    the ability to run a review. Guards against a future author 'tidying' the
    dependency into the hard-stop guard list."""
    for skill, path in SKILLS.items():
        text = path.read_text(encoding="utf-8")
        assert "best-effort and must never block the round" in text, skill
        guard = text.split("## Pre-flight: Round Marker")[0]
        assert "Bash(python3 -:*)" not in guard, (
            f"{skill}: the marker's allow-rule leaked into the hard-stop "
            "permission guard — a missing rule would now block the whole round"
        )


def test_loop_allow_subset_still_carries_the_heredoc_rule():
    """The marker rides the existing `Bash(python3 -:*)` rule — zero new
    permission surface. If loop mode ever drops it, layer 1 silently disarms in
    exactly the install mode the public docs route newcomers to."""
    text = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    subset = text.split("LOOP_ALLOW = {", 1)[1].split("}", 1)[0]
    assert '"Bash(python3 -:*)"' in subset
