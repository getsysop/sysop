"""Integration tests for install.sh's ensure_runtime_gitignore() (Phase 99, tester round;
consolidated Phase 133).

Sysop's runtime-artifact dirs hold transient orchestration state that a stray
`git add -A` would otherwise commit into project history. As of Phase 133 all
four live under one vendor-namespaced home, covered by a single ignore entry:
  sysop/runtime/subagent-envelopes/  in-flight SubagentStop envelope JSON (Phase 37)
  sysop/runtime/auto-build/          parked-task plan + adversarial-verdict archive (Phase 65a)
  sysop/runtime/pending-docs/        deferred documentation drafts (/document-work Step 3)
  sysop/runtime/locks/               in-progress task locks (claim_task.sh; Phase 32)

The helper stays an idempotent, update-safe append-if-missing (a consumer-owned
.gitignore is never rewritten — only missing entries appended).

These drive the real installer against scratch git consumers (the
test_install_*.py pattern).
"""
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
WANT = ("sysop/runtime/", ".claude/review_index.json",
        ".claude/review_index.json.*.tmp", "sysop/**/__pycache__/")
# The pre-133 per-dir entries — the installer must no longer append these.
OLD_DOT_DIRS = (".subagent-envelopes/", ".auto-build/", ".pending-docs/", ".locks/")


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _consumer(root, gitignore=None):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")  # ignore a global signing config
    (root / "README.md").write_text("hi\n")
    if gitignore is not None:
        (root / ".gitignore").write_text(gitignore)
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


def _lines(target):
    return (target / ".gitignore").read_text().splitlines()


def test_appends_to_preexisting_committed_gitignore(tmp_path):
    """Dia's scenario: a project .gitignore committed BEFORE the install still
    gets the runtime entry, and existing project entries are left untouched."""
    target = _consumer(tmp_path / "c", gitignore=".env\n.venv/\ndata/\n")
    r = _install(target, "--packs", "")
    assert r.returncode == 0, r.stdout + r.stderr
    lines = _lines(target)
    for want in WANT:
        assert lines.count(want) == 1, f"{want} not appended exactly once: {lines}"
    for keep in (".env", ".venv/", "data/"):
        assert keep in lines, f"clobbered existing entry {keep}: {lines}"


def test_creates_entries_when_no_gitignore(tmp_path):
    target = _consumer(tmp_path / "c")  # no .gitignore at all
    r = _install(target, "--packs", "")
    assert r.returncode == 0, r.stdout + r.stderr
    lines = _lines(target)
    for want in WANT:
        assert lines.count(want) == 1, f"{want} missing: {lines}"


def test_no_legacy_dot_dir_entries_appended(tmp_path):
    """Phase 133 regression guard: a fresh install appends ONLY the consolidated
    sysop/runtime/ entry — none of the four pre-133 dot-dir entries."""
    target = _consumer(tmp_path / "c")
    r = _install(target, "--packs", "")
    assert r.returncode == 0, r.stdout + r.stderr
    lines = _lines(target)
    for old in OLD_DOT_DIRS:
        assert old not in lines, f"legacy entry {old} appended on fresh install: {lines}"


def test_append_is_idempotent_on_update(tmp_path):
    """Non-tautological guard: --update must NOT duplicate the entry or the
    section header (the whole point of append-if-missing)."""
    target = _consumer(tmp_path / "c", gitignore=".env\n")
    assert _install(target, "--packs", "").returncode == 0
    _git(target, "add", "-A")
    _git(target, "commit", "-qm", "sysop install")
    r2 = _install(target, "--update")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    lines = _lines(target)
    for want in WANT:
        assert lines.count(want) == 1, f"{want} duplicated on --update: {lines}"
    assert sum(1 for line in lines if "# Sysop runtime artifacts" in line) == 1


def test_preexisting_legacy_entries_left_in_place_on_update(tmp_path):
    """A pre-133 consumer's four dot-dir entries are consumer-file lines: the
    append-only contract means --update leaves them untouched and still adds
    the consolidated entry exactly once."""
    legacy = "".join(f"{d}\n" for d in OLD_DOT_DIRS)
    target = _consumer(
        tmp_path / "c",
        gitignore=f"# Sysop runtime artifacts (transient orchestration state)\n{legacy}",
    )
    r = _install(target, "--packs", "")
    assert r.returncode == 0, r.stdout + r.stderr
    lines = _lines(target)
    for old in OLD_DOT_DIRS:
        assert lines.count(old) == 1, f"legacy entry {old} rewritten/duplicated: {lines}"
    for want in WANT:
        assert lines.count(want) == 1, f"{want} not appended exactly once: {lines}"


def _appended_sysop_entries(tmp_path):
    """The entries install.sh ACTUALLY appends, by running it.

    This replaced a regex that read `local -a want=(...)` out of install.sh and
    pulled double-quoted strings from it. Phase 212's review round scored that
    parser and it was wrong in both directions:

      * BLIND — a single-quoted (`'node_modules/'`) or unquoted (`secrets.env`)
        element is appended by bash and invisible to `re.findall(r'"([^"]+)"')`,
        so the installer could start writing arbitrary rules into a consumer's
        .gitignore with this guard green. A decoy `local -a want=(...)` earlier
        in the file bound the regex's first match too — Phase 170's
        first-occurrence trap — letting the real array be gutted undetected.
      * OVER-STRICT — `[^)]*` stops at the first `)`, so one-entry-per-line with
        a trailing comment containing parentheses (`# state (Phase 133)`) and
        holding the glob in a `local` variable both FALSE-FAILED. A guard that
        reds on a legal rewrite gets weakened or deleted.

    Reading behaviour instead of source is invariant under every legal bash
    rewrite, and it is the only form that can see what bash sees.
    """
    target = _consumer(tmp_path / "want-probe")  # no .gitignore at all
    r = _install(target, "--packs", "")
    assert r.returncode == 0, r.stdout + r.stderr
    return {
        ln for ln in _lines(target)
        if ln.strip() and not ln.lstrip().startswith("#")
    }


def test_want_list_is_the_consolidated_runtime_home(tmp_path):
    """Locks the Phase-133 consolidation AND the Phase-212 bytecode entry: the
    set install.sh appends is exactly WANT — no more, no fewer."""
    assert _appended_sysop_entries(tmp_path) == set(WANT)


def test_gitignore_append_covers_every_skill_asserted_runtime_dir():
    """Drift guard (tester issue #10): /review-close Step 2a reads `dirty` from
    `git status --porcelain`, so any runtime dir a shipped skill/script asserts
    is gitignored MUST be covered by the append — else a clean branch reads
    dirty and the close silently SKIPs. Grep every runtime-dir token on a
    gitignore-mentioning line and assert the append covers it (prefix
    coverage: `sysop/runtime/` covers `sysop/runtime/<anything>/`), so the
    consolidated entry can't silently drift out from under the skills."""
    # Dirs that legitimately appear near "gitignore" text but are NOT Sysop
    # runtime artifacts (project/tooling dirs the consumer owns).
    denylist = {".github/", ".git/", ".claude/", ".venv/", ".pytest_cache/"}
    claimed = set()
    for base in ("core/skills", "core/companion/scripts"):
        for f in (REPO_ROOT / base).rglob("*"):
            if f.suffix not in (".md", ".py"):
                continue
            for line in f.read_text().splitlines():
                if "gitignore" in line.lower():
                    claimed.update(
                        re.findall(r"(?:sysop/runtime/|\.)[a-z][a-z0-9-]*/", line)
                    )
    claimed -= denylist
    assert claimed, "expected to find at least one gitignored runtime dir in the skills"
    want = set(WANT)
    missing = {
        c for c in claimed
        if not any(c == w or c.startswith(w) for w in want)
    }
    assert not missing, (
        f"skills assert these dirs are gitignored but ensure_runtime_gitignore() "
        f"misses them (add to install.sh's want=() AND to WANT here): {sorted(missing)}"
    )


# ── Phase 212: untrack_vendor_bytecode ───────────────────────────────────────
#
# A gitignore rule does NOTHING for an already-tracked file, so for every
# consumer who ran a pre-212 install the new `sysop/**/__pycache__/` entry
# arrives and changes nothing: `--update` still rewrites the `.pyc` and still
# dirties a clean tree. That population — the one that already has the defect —
# is exactly the one the ignore rule cannot help, which is why the installer
# also untracks. This shipped with no coverage until the review round asked
# where its guards were.


def _tracked_pyc(target):
    out = subprocess.run(["git", "ls-files"], cwd=target,
                         capture_output=True, text=True, check=True).stdout
    return sorted(l for l in out.splitlines() if "__pycache__" in l)


def _seed_tracked_bytecode(target):
    """Reproduce a pre-212 consumer: bytecode under sysop/, committed.

    Includes a DEPTH-0 file (`sysop/__pycache__/`). git's default pathspec
    syntax gives `**` no special meaning, so a bare `sysop/**/__pycache__/*`
    silently misses that one while the gitignore rule — gitignore syntax, where
    `**` spans zero directories — covers it. The two halves of the fix
    disagreed about their own population; this fixture is what makes the
    disagreement fail loudly.
    """
    for rel in ("sysop/__pycache__/top.pyc",
                "sysop/scripts/__pycache__/a.pyc",
                "sysop/scripts/run_checks/__pycache__/c.pyc"):
        p = target / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"stale-bytecode\n")
    # `-f` because the install under test has ALREADY appended the ignore rule,
    # so a plain `git add -A` would refuse to stage these and the fixture would
    # silently not take. The state being reproduced is a consumer who tracked
    # this bytecode BEFORE any ignore rule existed — which is the whole reason
    # the untrack is needed, since a gitignore does nothing for a tracked file.
    _git(target, "add", "-f", *[
        "sysop/__pycache__/top.pyc",
        "sysop/scripts/__pycache__/a.pyc",
        "sysop/scripts/run_checks/__pycache__/c.pyc",
    ])
    _git(target, "commit", "-qm", "pre-212 state")


def test_untrack_removes_tracked_bytecode_at_every_depth(tmp_path):
    target = _consumer(tmp_path / "c")
    assert _install(target, "--packs", "").returncode == 0
    _seed_tracked_bytecode(target)
    assert len(_tracked_pyc(target)) == 3, "fixture did not take"

    r = _install(target, "--update")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _tracked_pyc(target) == [], (
        "tracked bytecode survived --update; a depth-0 miss is the likely cause"
    )


def test_untrack_never_deletes_the_files_from_disk(tmp_path):
    """`--cached` is the whole safety argument for passing `-f`. If this ever
    fails, the installer is destroying files in a consumer's tree."""
    target = _consumer(tmp_path / "c")
    assert _install(target, "--packs", "").returncode == 0
    _seed_tracked_bytecode(target)

    assert _install(target, "--update").returncode == 0
    for rel in ("sysop/__pycache__/top.pyc",
                "sysop/scripts/__pycache__/a.pyc",
                "sysop/scripts/run_checks/__pycache__/c.pyc"):
        p = target / rel
        assert p.is_file(), f"installer DELETED {rel} from the working tree"
        assert p.read_bytes() == b"stale-bytecode\n", f"installer rewrote {rel}"


def test_untrack_survives_a_staged_then_remodified_pyc(tmp_path):
    """The case that made the first cut print a remedy identical to the command
    that had just failed. `git add -A` then any run that imports the module
    leaves staged content differing from both the file and HEAD, and git refuses
    the whole all-or-nothing removal without `-f`."""
    target = _consumer(tmp_path / "c")
    assert _install(target, "--packs", "").returncode == 0
    _seed_tracked_bytecode(target)
    p = target / "sysop/scripts/__pycache__/a.pyc"
    p.write_bytes(b"staged-version\n")
    _git(target, "add", "-f", "sysop/scripts/__pycache__/a.pyc")  # -f: now ignored
    p.write_bytes(b"worktree-version\n")

    r = _install(target, "--update")
    assert r.returncode == 0, r.stdout + r.stderr
    assert _tracked_pyc(target) == [], r.stdout
    assert p.read_bytes() == b"worktree-version\n", "working-tree content lost"


def test_untrack_is_silent_and_idempotent_when_nothing_is_tracked(tmp_path):
    """Non-vacuity control for the three above: on a clean consumer the section
    must not announce itself. Without this, a function that fired unconditionally
    would satisfy every other test here."""
    target = _consumer(tmp_path / "c")
    assert _install(target, "--packs", "").returncode == 0
    r = _install(target, "--update")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "vendored bytecode untrack" not in r.stdout, r.stdout


def test_untrack_dry_run_mutates_nothing(tmp_path):
    target = _consumer(tmp_path / "c")
    assert _install(target, "--packs", "").returncode == 0
    _seed_tracked_bytecode(target)
    before = _tracked_pyc(target)

    r = _install(target, "--update", "--dry-run")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "would untrack 3" in r.stdout, r.stdout
    assert _tracked_pyc(target) == before, "--dry-run changed the index"


def test_install_writes_no_bytecode_into_the_vendor_dir(tmp_path):
    """`install.sh` sets PYTHONDONTWRITEBYTECODE=1 on its model-roles call.

    That call is the one install-time python invocation that runs a FILE from
    the vendor dir (the others are `"$_py" - <<'PY'` stdin heredocs, which cache
    nothing), so without the setting CPython leaves
    `sysop/scripts/__pycache__/{_model_roles,migrate_skill_model}.cpython-*.pyc`
    in the consumer's tree — the `Q-041` defect, verbatim.

    Asserted on the FILESYSTEM, deliberately, and not via `git status`: this
    phase also added `sysop/**/__pycache__/` to the consumer's .gitignore, so a
    porcelain check would report clean while the files were being written. The
    review round made exactly that point — the obvious assertion is masked by
    the phase's own other fix.

    Requires a PyYAML-bearing interpreter on PATH (`_install` puts the venv
    there); on a PyYAML-less one nothing is cached and this would pass
    vacuously, which the sibling control below rules out.
    """
    target = _consumer(tmp_path / "c")
    r = _install(target, "--packs", "python")
    assert r.returncode == 0, r.stdout + r.stderr
    caches = sorted(str(p.relative_to(target)) for p in target.rglob("__pycache__"))
    assert caches == [], f"install.sh left vendored bytecode: {caches}"

    r2 = _install(target, "--update")
    assert r2.returncode == 0, r2.stdout + r2.stderr
    caches = sorted(str(p.relative_to(target)) for p in target.rglob("__pycache__"))
    assert caches == [], f"--update left vendored bytecode: {caches}"


def test_the_model_roles_step_actually_ran(tmp_path):
    """Non-vacuity control for the test above.

    If `pick_python_with_yaml` finds no PyYAML the model-roles step no-ops, no
    module is ever imported from the vendor dir, and the assertion above is
    trivially true no matter what the installer sets. This asserts the step
    really ran, so a green sibling means the suppression worked rather than that
    nothing was attempted.
    """
    target = _consumer(tmp_path / "c")
    r = _install(target, "--packs", "python")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "skipping: no python3 with PyYAML" not in r.stdout, (
        "the model-roles step no-opped, so the bytecode assertion is vacuous:\n"
        + r.stdout
    )


def test_untrack_stays_inside_the_vendor_dir(tmp_path):
    """`Q-126` asks for a DECISION — assert a general `__pycache__/` ignore on
    the consumer's whole repo, or scope it to Sysop's own vendor dir. The phase
    answered vendor-scoped, consistent with Phase 128's namespace boundary.

    Nothing held that answer: the review round widened the pathspec from
    `sysop/**/__pycache__/*` to `**/__pycache__/*` and the suite stayed green,
    which would have Sysop's installer silently untracking a consumer's OWN
    bytecode — files it does not own and was never asked about.
    """
    target = _consumer(tmp_path / "c")
    assert _install(target, "--packs", "").returncode == 0
    _seed_tracked_bytecode(target)

    # The consumer's own bytecode, outside the vendor dir. Sysop must not touch it.
    theirs = target / "app" / "__pycache__" / "theirs.pyc"
    theirs.parent.mkdir(parents=True)
    theirs.write_bytes(b"not-ours\n")
    _git(target, "add", "-f", "app/__pycache__/theirs.pyc")
    _git(target, "commit", "-qm", "consumer's own bytecode")

    r = _install(target, "--update")
    assert r.returncode == 0, r.stdout + r.stderr
    tracked = _tracked_pyc(target)
    assert tracked == ["app/__pycache__/theirs.pyc"], (
        "the untrack crossed the vendor boundary and touched files Sysop does "
        f"not own: {tracked}"
    )
    assert theirs.is_file(), "consumer's own bytecode deleted from disk"
