"""Integration tests for install.sh's dirty-source detection (Phase 306, `Q-539`).

``install.sh:48`` sets ``REPO_ROOT="$SCRIPT_DIR"`` — the directory the script
lives in, whatever state it is in — so the installer copies the source clone's
**working tree**. ``get_sysop_commit`` meanwhile records that clone's **HEAD**
into the consumer's lock. Those two describe the same files only when the source
is clean, and before this phase nothing said so at either end: no warning at
install time and no record afterward, so a consumer holding ``sysop_commit:
<sha>`` had no way to learn that ``<sha>``'s tree was never what it received.

Reproduced before the fix: an uncommitted line appended to
``core/companion/scripts/self_check.sh`` landed in the consumer's
``sysop/scripts/self_check.sh`` while the lock recorded a commit whose tree
contains zero occurrences of it.

These drive the *real* install.sh against a scratch **source clone** whose
dirtiness each test sets deliberately. That is the whole point of the fixture:
the other install suites run ``REPO_ROOT`` = the live repo, which is dirty
whenever a maintainer is mid-phase and clean in CI — so a test that inherited
ambient state would exercise a different branch locally than on the runner.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

# The uncommitted line the tests append to a shipped source file. It must be
# something the installer copies verbatim into the consumer, so that "the warning
# fired" and "the uncommitted content actually landed" are asserted together.
SENTINEL = "PHASE306-UNCOMMITTED-SOURCE-SENTINEL"

WARN_LINE = "the Sysop source tree has uncommitted changes"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                   env={**os.environ, **_GIT_ISOLATION})


def _git_out(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                          text=True, env={**os.environ, **_GIT_ISOLATION}).stdout.strip()


@pytest.fixture(scope="module")
def pristine_source(tmp_path_factory):
    """A committed, clean scratch Sysop source clone built from the live tree."""
    src = tmp_path_factory.mktemp("sysop_pristine")
    shutil.copy2(REPO_ROOT / "install.sh", src / "install.sh")
    for d in ("core", "packs"):
        shutil.copytree(REPO_ROOT / d, src / d,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"))
    _git(src, "init", "-q")
    _git(src, "config", "user.email", "test@test")
    _git(src, "config", "user.name", "test")
    _git(src, "config", "commit.gpgsign", "false")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "source")
    assert _git_out(src, "status", "--porcelain") == ""
    return src


@pytest.fixture
def source(pristine_source, tmp_path):
    """A per-test clone of the pristine source, so dirtying it cannot leak."""
    dst = tmp_path / "src"
    subprocess.run(["git", "clone", "-q", str(pristine_source), str(dst)],
                   check=True, capture_output=True,
                   env={**os.environ, **_GIT_ISOLATION})
    _git(dst, "config", "user.email", "test@test")
    _git(dst, "config", "user.name", "test")
    _git(dst, "config", "commit.gpgsign", "false")
    assert _git_out(dst, "status", "--porcelain") == ""
    return dst


def _dirty(src, rel="core/companion/scripts/self_check.sh"):
    p = src / rel
    p.write_text(p.read_text() + f"\n# {SENTINEL}\n")
    assert _git_out(src, "status", "--porcelain") != ""


def _target(tmp_path, name="tgt"):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("# scratch\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(src, target, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    env.update(_GIT_ISOLATION)
    return subprocess.run(
        ["bash", str(src / "install.sh"), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env, cwd=str(target),
    )


def _lock(target):
    return json.loads((target / ".claude" / "sysop.lock").read_text())


# ── the defect, and its control ──────────────────────────────────────────────

def test_clean_source_warns_nothing_and_adds_no_lock_key(source, tmp_path):
    """The control. A clean source must leave both halves untouched.

    `source_dirty` is written only-when-true precisely so this lock is
    byte-identical to a pre-Phase-306 one; an always-present key would rewrite —
    and so dirty — every clean consumer's lock on their next update, which is the
    idempotence Phase 148 restored.
    """
    tgt = _target(tmp_path)
    res = _run(source, tgt, "--packs", "python", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    assert WARN_LINE not in res.stdout + res.stderr
    assert "source_dirty" not in _lock(tgt)


def test_dirty_source_warns_records_and_the_content_really_lands(source, tmp_path):
    """Both halves of `Q-539`, asserted against each other.

    The third assertion is what stops this passing by accident: it is not enough
    that the installer *says* the recorded sha does not denote what landed — the
    uncommitted line must actually be in the consumer's file while being absent
    from the tree of the commit the lock names.
    """
    _dirty(source)
    head = _git_out(source, "rev-parse", "HEAD")
    tgt = _target(tmp_path)
    res = _run(source, tgt, "--packs", "python", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr

    combined = res.stdout + res.stderr
    assert WARN_LINE in combined, combined
    assert _lock(tgt)["source_dirty"] is True
    assert _lock(tgt)["sysop_commit"] == head

    landed = (tgt / "sysop" / "scripts" / "self_check.sh").read_text()
    assert SENTINEL in landed, "the uncommitted source edit did not reach the consumer"
    at_head = subprocess.run(
        ["git", "show", f"{head}:core/companion/scripts/self_check.sh"],
        cwd=str(source), check=True, capture_output=True, text=True,
        env={**os.environ, **_GIT_ISOLATION}).stdout
    assert SENTINEL not in at_head, (
        "the commit the lock records must NOT contain what was installed — "
        "otherwise this test proves nothing")


def test_dirty_under_packs_also_warns(source, tmp_path):
    """SOURCE_SCAN_PATHS has more than one entry, and each must actually be
    scanned. Without this, truncating the array to `core` alone passes the whole
    suite while leaving every pack edit invisible.
    """
    _dirty(source, "packs/python/companion/convention_map.md")
    tgt = _target(tmp_path)
    res = _run(source, tgt, "--packs", "python", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    assert WARN_LINE in res.stdout + res.stderr
    assert _lock(tgt)["source_dirty"] is True


def test_dirty_install_sh_itself_warns(source, tmp_path):
    """install.sh is in the scan set for a different reason than core/ and packs/:
    its uncommitted state changes the installer that runs, so the recorded HEAD
    does not denote the code that produced the install either."""
    p = source / "install.sh"
    p.write_text(p.read_text() + f"\n# {SENTINEL}\n")
    tgt = _target(tmp_path)
    res = _run(source, tgt, "--packs", "python", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    assert WARN_LINE in res.stdout + res.stderr
    assert _lock(tgt)["source_dirty"] is True


def test_dirty_outside_the_scanned_paths_stays_quiet(source, tmp_path):
    """Scoping control. The probe reads only what the installer reads.

    Unscoped, `git status --porcelain` fires on any stray untracked file anywhere
    in the clone — in this repo that is the steady state (scratch scripts, drafts),
    and a warning that fires always is one nobody reads. A file outside
    SOURCE_SCAN_PATHS cannot reach a consumer, so it must not warn.
    """
    (source / "tools").mkdir(exist_ok=True)
    (source / "tools" / "scratch_probe.py").write_text("# not shipped\n")
    assert _git_out(source, "status", "--porcelain") != "", "fixture must be dirty"
    tgt = _target(tmp_path)
    res = _run(source, tgt, "--packs", "python", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    assert WARN_LINE not in res.stdout + res.stderr
    assert "source_dirty" not in _lock(tgt)


def test_ref_install_from_a_dirty_source_is_clean(source, tmp_path):
    """--ref re-points REPO_ROOT at a fresh detached worktree, which is clean by
    construction — so the probe, which runs after that re-point, must report
    nothing even though the operator's clone is dirty. This is also the remedy
    the warning prescribes, so it has to actually work."""
    _dirty(source)
    tgt = _target(tmp_path)
    res = _run(source, tgt, "--packs", "python", "--no-arm-hooks", "--ref", "HEAD")
    assert res.returncode == 0, res.stdout + res.stderr
    assert WARN_LINE not in res.stdout + res.stderr
    assert "source_dirty" not in _lock(tgt)
    assert SENTINEL not in (tgt / "sysop" / "scripts" / "self_check.sh").read_text()


def test_update_warns_and_records_too_not_just_a_fresh_install(source, tmp_path):
    """`--update` is the path a consumer lives on, and it was unguarded.

    Every positive assertion in this module was on a fresh install or `--adopt`;
    the one `--update` test asserts the key is *absent*. Phase 306's round (guard
    lens) switched both halves off for update mode specifically — an early
    `[[ "$UPDATE_MODE" -eq 1 ]] && return 0` in the probe, and an
    `[[ "$UPDATE_MODE" -eq 1 ]] && SOURCE_DIRTY=0` in `write_lock_file` — and the
    suite stayed 16/16 green through both. A consumer installs once and updates
    forever, so that is the arm that matters most.
    """
    tgt = _target(tmp_path)
    assert _run(source, tgt, "--packs", "python", "--no-arm-hooks").returncode == 0
    assert "source_dirty" not in _lock(tgt), "precondition: clean install"
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "install")

    _dirty(source)
    res = _run(source, tgt, "--update", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    assert WARN_LINE in res.stdout + res.stderr, "the update path must warn"
    assert _lock(tgt)["source_dirty"] is True, "the update path must record"
    assert SENTINEL in (tgt / "sysop" / "scripts" / "self_check.sh").read_text(), (
        "and the uncommitted content must really have landed, or this proves nothing")


def test_a_tarball_unpacked_inside_a_git_repo_is_not_reported_as_a_dirty_source(
        pristine_source, tmp_path):
    """`rev-parse --git-dir` WALKS UP, so the non-git early-out did not establish
    what it claimed.

    Unpack a tarball inside any git repo — a project dir, a dotfiles repo, a
    version-controlled `$HOME` — and the probe answers with the HOST repo: it
    reports the host's dirtiness and writes `"source_dirty": true` into the lock
    about a tarball with no git relationship at all. A fresh instance of the class
    `Q-539` exists to close, minted by its own fix, found by this phase's round.
    `test_non_git_source_is_quiet` pinned the opposite claim only in the
    arrangement where it is trivially true — the tarball outside any repo.
    """
    host = tmp_path / "host"
    host.mkdir()
    _git(host, "init", "-q")
    _git(host, "config", "user.email", "test@test")
    _git(host, "config", "user.name", "test")
    _git(host, "config", "commit.gpgsign", "false")
    (host / "README.md").write_text("# host\n")
    _git(host, "add", "-A")
    _git(host, "commit", "-qm", "host")

    src = host / "sysop-src"
    shutil.copytree(pristine_source, src, ignore=shutil.ignore_patterns(".git"))
    assert not (src / ".git").exists()
    # The host repo now has the whole unpacked tarball as untracked content, so it
    # is emphatically dirty — which is the trap.
    assert _git_out(host, "status", "--porcelain") != ""

    tgt = _target(tmp_path)
    res = _run(src, tgt, "--packs", "python", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    assert WARN_LINE not in res.stdout + res.stderr, res.stdout
    assert "source_dirty" not in _lock(tgt), _lock(tgt)


def test_the_key_clears_when_the_source_is_committed(source, tmp_path):
    """An exception marker that never clears is a permanent false alarm."""
    _dirty(source)
    tgt = _target(tmp_path)
    assert _run(source, tgt, "--packs", "python", "--no-arm-hooks").returncode == 0
    assert _lock(tgt)["source_dirty"] is True
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "install")

    _git(source, "add", "-A")
    _git(source, "commit", "-qm", "commit the edit")
    res = _run(source, tgt, "--update", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "source_dirty" not in _lock(tgt)


def test_non_git_source_is_quiet(pristine_source, tmp_path):
    """The "any agent or none" path: an unpacked tarball has no committed state
    for a working tree to differ from. get_sysop_commit already records the honest
    anchor `unknown` there; a warning would be noise on every such install."""
    src = tmp_path / "tarball"
    shutil.copytree(pristine_source, src, ignore=shutil.ignore_patterns(".git"))
    assert not (src / ".git").exists()
    tgt = _target(tmp_path)
    res = _run(src, tgt, "--packs", "python", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    assert WARN_LINE not in res.stdout + res.stderr
    assert "source_dirty" not in _lock(tgt)
    assert _lock(tgt)["sysop_commit"] == "unknown"


def test_adopt_from_a_dirty_source_records_the_key(source, tmp_path):
    """--adopt runs the pipeline and writes a lock, so it ships the same working
    tree and records the same HEAD an install does."""
    tgt = _target(tmp_path)
    # --adopt backfills a lock for an install that predates the lock mechanism, so
    # it needs an existing install to adopt. Lay one down from the CLEAN source,
    # commit it, drop the lock, then dirty the source — so the key under test can
    # only have come from the adopt run.
    assert _run(source, tgt, "--packs", "python", "--no-arm-hooks").returncode == 0
    (tgt / ".claude" / "sysop.lock").unlink()
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "pre-lock install")

    _dirty(source)
    res = _run(source, tgt, "--adopt", "--packs", "python", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    assert WARN_LINE in res.stdout + res.stderr
    assert _lock(tgt)["source_dirty"] is True


def test_check_from_a_dirty_source_warns_read_only(source, tmp_path):
    """--check derives its verdict from CHECK_SOURCE's working tree, so a dirty
    source makes "you are current / you have diverged" an answer about
    uncommitted work. It writes nothing, so it must say that rather than promise
    a lock key it will not write."""
    tgt = _target(tmp_path)
    assert _run(source, tgt, "--packs", "python", "--no-arm-hooks").returncode == 0
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "install")
    _dirty(source)
    res = _run(source, tgt, "--check", "--source", str(source))
    combined = res.stdout + res.stderr
    assert WARN_LINE in combined, combined
    assert "read-only" in combined, combined
    assert "source_dirty" not in _lock(tgt)


# ── the population guard ─────────────────────────────────────────────────────

def test_scan_paths_cover_every_source_root_install_sh_reads():
    """Derive the population from the source of truth, not from a model of it.

    SOURCE_SCAN_PATHS is a hand-written list, and a hand-written list of paths is
    exactly the thing that goes stale when a later phase teaches the installer to
    read a new source directory. A new `$REPO_ROOT/<dir>/...` reference that is
    not covered would make the probe silently blind to edits under it — the
    defect class this phase exists to close, one level up.
    """
    text = (REPO_ROOT / "install.sh").read_text()

    # findall, not search: a SECOND assignment further down wins at runtime, and
    # the first-match form could not see one (round, guard lens).
    ms = re.findall(r"^SOURCE_SCAN_PATHS=\(([^)]*)\)", text, re.M)
    assert ms, "SOURCE_SCAN_PATHS array not found in install.sh"
    assert len(ms) == 1, (
        f"SOURCE_SCAN_PATHS is assigned {len(ms)} times; the last wins at runtime, "
        f"so this guard may be reading a population that never applies: {ms}")
    # Strip quotes: `("core" "packs")` is behaviourally identical bash, and the
    # first cut reddened on it with a message blaming a coverage hole — which sends
    # a maintainer to repair the test instead of the quoting (round, guard lens).
    declared = {w.strip('"').strip("'") for w in ms[0].split()}
    assert declared, "SOURCE_SCAN_PATHS is empty — the probe would scan nothing"

    # Accept every spelling of the reference, not just the bare one. The first cut
    # matched `$REPO_ROOT/…` only; the round's guard lens inserted a new source
    # read in the braced and quoted forms and both survived. Measured at that
    # commit: bare 34, `${SYSOP_SRC_CLONE:-$REPO_ROOT}/` 4, `"$REPO_ROOT"/` 2 —
    # the bare form is the majority here, but "majority" is not "only", and a
    # guard that parses a file has to accept the spellings that file uses.
    # `(?<!\\)` — a BACKSLASH-escaped form is literal text, not a reference. The
    # widening's first run flagged `scripts` on `install.sh:4713`, which is
    # advisory prose shown to a consumer (`say "… shell \\${REPO_ROOT}/scripts …"`)
    # about THEIR old-layout tree, not a path this installer reads. Widening a
    # pattern without this is how a guard starts reporting its own file's prose.
    ref_re = re.compile(
        r'(?<!\\)'
        r'(?:\$REPO_ROOT/'
        r'|\$\{REPO_ROOT\}/'
        r'|\$\{SYSOP_SRC_CLONE:-\$REPO_ROOT\}/'
        r'|"\$REPO_ROOT"/'
        r'|"\$\{SYSOP_SRC_CLONE:-\$REPO_ROOT\}"/'
        r')([A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)')
    raw = {ref.split("/")[0] for ref in ref_re.findall(text)}
    # `$REPO_ROOT/...` appears in prose as an ellipsis; keep only roots that are
    # real entries in the tree. A genuinely new source directory exists, so it is
    # still caught — this drops noise, not coverage.
    roots = {r for r in raw if (REPO_ROOT / r).exists()}
    assert roots, "no $REPO_ROOT/... references resolved — the derivation itself broke"

    uncovered = {r for r in roots if r not in declared}
    assert not uncovered, (
        f"install.sh reads source paths under {sorted(uncovered)}, which "
        f"SOURCE_SCAN_PATHS ({sorted(declared)}) does not cover — the dirty-source "
        f"probe is blind to uncommitted edits there")


# ── round findings (Phase 306's own round) ───────────────────────────────────

def test_the_prescribed_command_carries_the_mode_it_was_printed_in(source, tmp_path):
    """The remedy must be runnable as printed, in the mode it was printed in.

    Both execution lenses found this independently. A mode-less `--ref HEAD` is
    not a no-op on an installed target: `validate_target`'s dirty refusal is
    skipped for `--update`/`--adopt`/`--check`, so the line does not merely fail —
    on a clean target it performs a **fresh install**, skipping the pre-update
    snapshot, the removed-path sweep and the migration handling. And `--ref` is
    rejected outright for `--adopt`, so offering it there prescribes an exit 2.

    This also corrects the phase's first rule-3 write-up, which read the mode-less
    command's refusal as an ordering constraint. It was not; it was the missing flag.
    """
    _dirty(source)
    tgt = _target(tmp_path)
    assert _run(source, tgt, "--packs", "python", "--no-arm-hooks").returncode == 0
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "install")

    upd = _run(source, tgt, "--update", "--no-arm-hooks")
    assert "--update --ref HEAD" in upd.stdout, upd.stdout
    assert " --ref HEAD" in upd.stdout and "--update --ref HEAD" in upd.stdout

    # --adopt on its own target: an install with no lock is what adopt is for.
    tgt2 = _target(tmp_path, "adoptme")
    assert _run(source, tgt2, "--packs", "python", "--no-arm-hooks").returncode == 0
    (tgt2 / ".claude" / "sysop.lock").unlink()
    _git(tgt2, "add", "-A")
    _git(tgt2, "commit", "-qm", "pre-lock install")
    adp = _run(source, tgt2, "--adopt", "--packs", "python", "--no-arm-hooks")
    assert "--ref is not valid with --adopt" in adp.stdout, adp.stdout
    assert "--adopt --ref" not in adp.stdout


def test_the_prescribed_command_is_absolute_and_quotes_the_target(source, tmp_path):
    """`$0` is whatever the caller typed, so a relative form is runnable only from
    that CWD; and an unquoted target with a space parses as an extra positional
    argument. Both make a printed remedy that cannot be copied."""
    _dirty(source)
    tgt = _target(tmp_path, "my target")
    res = _run(source, tgt, "--packs", "python", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    line = next(l for l in res.stdout.splitlines() if "--ref HEAD" in l)
    assert str(source / "install.sh") in line, line
    assert f'"{tgt}"' in line, line


def test_dry_run_does_not_promise_a_lock_key_or_a_prompt(source, tmp_path):
    """A dry run writes no lock and never reaches the `Proceed?` confirm, so the
    two sentences the apply path prints would both be false for it."""
    _dirty(source)
    tgt = _target(tmp_path)
    res = _run(source, tgt, "--packs", "python", "--no-arm-hooks", "--dry-run")
    assert WARN_LINE in res.stdout, res.stdout
    assert "dry run: nothing is written" in res.stdout, res.stdout
    assert "will carry" not in res.stdout
    assert "decline below" not in res.stdout


def test_check_reports_an_install_taken_from_a_dirty_source(source, tmp_path):
    """The key shipped with no reader, and `--check` — whose whole job is "am I
    current?" — answered `Up to date` over an install its own lock records as not
    denoting that commit."""
    _dirty(source)
    tgt = _target(tmp_path)
    assert _run(source, tgt, "--packs", "python", "--no-arm-hooks").returncode == 0
    assert _lock(tgt)["source_dirty"] is True
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "install")
    _git(source, "checkout", "--", "core")   # source clean again

    res = _run(source, tgt, "--check", "--source", str(source))
    combined = res.stdout + res.stderr
    assert "taken from a DIRTY Sysop source tree" in combined, combined
    assert combined.index("taken from a DIRTY") < combined.index("installed commit:"), (
        "the caveat must precede the verdict, not trail it")


def test_check_is_silent_for_an_ordinary_install(source, tmp_path):
    """Control for the reader above: no key, no caveat."""
    tgt = _target(tmp_path)
    assert _run(source, tgt, "--packs", "python", "--no-arm-hooks").returncode == 0
    assert "source_dirty" not in _lock(tgt)
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "install")
    res = _run(source, tgt, "--check", "--source", str(source))
    assert "taken from a DIRTY Sysop source tree" not in res.stdout + res.stderr


def test_no_surface_still_says_the_default_tracks_head():
    """The `Q-539` falsehood is a CLASS, and the phase's first cut fixed 1 of 6.

    `Q-539` named one site — the update shim's *"Omit --ref to track HEAD
    (default)"* — and the phase fixed exactly that one. Its round found the same
    claim live in the installer's own `--help`, in a `--ref` refusal message, in
    `WORKFLOW.md` § 8.2b (the section the phase edited), in `SECURITY.md`'s
    supply-chain bullet, and in `docs/install-and-update.md`. Two of those are
    public pages and one is the security doc, which is where a reader goes
    precisely to learn what a pin does.

    The pattern is deliberately narrow — it wants an assertion that *omitting
    `--ref`, or the default,* tracks HEAD. "How far behind HEAD you are" is true
    and must not trip, and the **plugin** path genuinely does track HEAD by commit
    SHA (a different mechanism), so that line is allowlisted by name.
    """
    # BIDIRECTIONAL on purpose. The first cut required the default-token before
    # the claim, and this module's own vacuity check then showed it missing
    # `SECURITY.md`'s real historical wording — *"tracks the HEAD of your local
    # Sysop clone **by default**"* — where the token trails. A guard that misses
    # the exact string it was written for is the defect it is guarding against.
    _DEFAULT = r"(omit|omitting|by default|the default|instead of|default)"
    _TRACKS = r"track(s|ing)?\s+(the\s+)?HEAD"
    claim = re.compile(
        rf"{_DEFAULT}[^.\n]{{0,90}}{_TRACKS}"
        rf"|{_TRACKS}[^.\n]{{0,90}}{_DEFAULT}"
        r"|the default track is HEAD"
        r"|follows the latest commit",
        re.I)
    plugin = re.compile(r"plugin path.{0,40}tracks HEAD by commit SHA", re.I)

    surfaces = [
        REPO_ROOT / "install.sh",
        REPO_ROOT / "SECURITY.md",
        REPO_ROOT / "docs" / "install-and-update.md",
        REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md",
        REPO_ROOT / "core" / "companion" / "scripts" / "sysop-update.sh",
    ]
    present = [p for p in surfaces if p.exists()]
    assert len(present) == len(surfaces), (
        f"a guarded surface moved or was renamed: {[str(p) for p in surfaces if not p.exists()]}")

    hits = []
    for path in present:
        for n, line in enumerate(path.read_text().splitlines(), 1):
            if claim.search(line) and not plugin.search(line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{n}: {line.strip()[:120]}")
    assert not hits, (
        "a surface asserts that omitting --ref tracks HEAD. The installer copies "
        "the source clone's WORKING TREE; the lock records HEAD. They differ "
        "whenever the clone is dirty — which is `Q-539`.\n  " + "\n  ".join(hits))


def test_the_warnings_body_is_pinned_not_just_its_headline(source, tmp_path):
    """Only `WARN_LINE` was asserted, so the whole body was free.

    Phase 306's round (guard lens) deleted all three detail lines, replaced the
    recorded sha with the literal `unknown`, inverted *"does NOT denote"* to
    *"DOES denote"*, flipped the promised key to `false`, hard-coded the dirty
    count to 1, and deleted the entire remedy block — **every one of those stayed
    green.** A headline assertion measures that a function ran, not that it said
    anything true.

    Each clause below is load-bearing: the count is the operator's only sense of
    scale, the recorded sha is the thing being said not to denote the tree, the
    remedy is the only actionable line, and the polarity is the whole claim.
    """
    # TWO dirty paths, not one. With one, `SOURCE_DIRTY_COUNT=1` hard-coded is
    # indistinguishable from the real count — the round's replay measured that
    # survivor against the first cut of this test.
    _dirty(source)
    _dirty(source, "packs/python/companion/convention_map.md")
    head = _git_out(source, "rev-parse", "HEAD")
    tgt = _target(tmp_path)
    res = _run(source, tgt, "--packs", "python", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    out = res.stdout

    assert "does NOT denote" in out, out
    assert "DOES denote" not in out.replace("does NOT denote", ""), (
        "the claim's polarity must not invert")
    assert f"source:    {source}" in out, out
    assert "dirty:     2 path(s)" in out, out
    assert f"recorded:  {head[:12]}" in out, out
    assert 'will carry "source_dirty": true' in out, out
    assert "--ref HEAD" in out, "the remedy must still be offered"


def test_the_divergent_snapshot_still_discloses_the_MIX(source, tmp_path):
    """The MIX disclosure is the phase's stated reason for not silently swapping
    one hash for another, and it shipped unguarded.

    The round deleted all three divergence notes, and separately inverted the MIX
    line to say the snapshot holds *"a clean pre-update state"* — the exact
    falsehood the design exists to avoid. Both stayed green.
    """
    tgt = _target(tmp_path)
    assert _run(source, tgt, "--packs", "python", "--no-arm-hooks").returncode == 0
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "install")
    p = source / "core" / "companion" / "scripts" / "self_check.sh"
    p.write_text(p.read_text() + "\n# B\n")
    _git(source, "commit", "-qam", "B")
    assert _run(source, tgt, "--update", "--no-arm-hooks").returncode == 0
    p.write_text(p.read_text() + "\n# C\n")
    _git(source, "commit", "-qam", "C")

    out = _run(source, tgt, "--update", "--no-arm-hooks").stdout
    assert "an earlier --update advanced the lock on disk" in out, out
    assert "committed lock:" in out and "on-disk lock:" in out, out
    assert "anchoring the snapshot to" in out, out
    assert "holds a MIX" in out, out
    assert "clean pre-update state" not in out, (
        "the snapshot is a mix; calling it clean is the falsehood the design "
        "exists to avoid")


def test_the_warning_precedes_the_proceed_confirm(source, tmp_path):
    """The shipped comment and the warning itself both assert the ordering.

    `probe_source_tree_state`'s comment says *"This warning precedes the
    'Proceed?' confirm, and a declined run leaves the target untouched — so
    'decline and re-run' is actionable at the moment it is read"*, and the warning
    prints "decline below". Phase 306's round (guard lens) moved the probe to
    *after* the confirm and the suite stayed green, because `_run` appends
    `--yes` to every invocation in this module so nothing ever reaches it.
    Eighteen lines below where that mutation lands, Phase 142's own comment reads
    "Deliberately AFTER the confirm" — so this is an ordinary edit, not an
    exotic one.

    Run WITHOUT `--yes` in a non-interactive environment: the installer refuses at
    the confirm, which makes the confirm's position observable in the output.
    """
    _dirty(source)
    tgt = _target(tmp_path)
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    env.update(_GIT_ISOLATION)
    res = subprocess.run(
        ["bash", str(source / "install.sh"), str(tgt), "--packs", "python",
         "--no-arm-hooks"],
        capture_output=True, text=True, env=env, cwd=str(tgt), stdin=subprocess.DEVNULL,
    )
    out = res.stdout + res.stderr
    assert WARN_LINE in out, out
    marker = "Non-interactive environment"
    assert marker in out, ("expected the confirm to be reached and refused; "
                           "if this message changed, re-anchor the test\n" + out)
    assert out.index(WARN_LINE) < out.index(marker), (
        "the warning must precede the Proceed? confirm — otherwise 'decline "
        "below' names a prompt the reader has already passed\n" + out)
    # And a declined/refused run must leave the target untouched, which is what
    # makes "decline and re-run" actionable rather than merely printable.
    assert not (tgt / ".claude").exists(), "a refused run wrote to the target"


def test_check_probes_the_source_flag_not_the_installers_own_root(pristine_source, tmp_path):
    """`--check` must read `$CHECK_SOURCE`, and the obvious test cannot see that.

    `test_check_from_a_dirty_source_warns_read_only` runs `install.sh` *out of*
    the same clone it passes to `--source`, so `CHECK_SOURCE == REPO_ROOT` and a
    probe of the wrong variable is indistinguishable — the round's guard lens
    switched it to `$REPO_ROOT` and that test stayed green. Comparing a consumer
    against a *different* clone is the whole point of the flag, so drive the two
    apart: a clean installer clone, a dirty comparison source.
    """
    runner = tmp_path / "runner"
    subprocess.run(["git", "clone", "-q", str(pristine_source), str(runner)],
                   check=True, capture_output=True,
                   env={**os.environ, **_GIT_ISOLATION})
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(pristine_source), str(other)],
                   check=True, capture_output=True,
                   env={**os.environ, **_GIT_ISOLATION})
    for d in (runner, other):
        _git(d, "config", "user.email", "test@test")
        _git(d, "config", "user.name", "test")
        _git(d, "config", "commit.gpgsign", "false")

    tgt = _target(tmp_path)
    assert _run(runner, tgt, "--packs", "python", "--no-arm-hooks").returncode == 0
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "install")

    _dirty(other)                                  # only the --source clone is dirty
    assert _git_out(runner, "status", "--porcelain") == "", "runner must stay clean"

    res = _run(runner, tgt, "--check", "--source", str(other))
    combined = res.stdout + res.stderr
    assert WARN_LINE in combined, (
        "--check must probe the tree it is comparing against, not the one it "
        "happens to be running from\n" + combined)
    assert str(other) in combined, combined
