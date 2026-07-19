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
WANT = ("sysop/runtime/",)
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


def _install_sh_want_list():
    """Parse ensure_runtime_gitignore()'s `want=(...)` array from install.sh."""
    text = INSTALL_SH.read_text()
    m = re.search(r"local -a want=\(([^)]*)\)", text)
    assert m, "could not find ensure_runtime_gitignore's want=(...) in install.sh"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def test_want_list_is_the_consolidated_runtime_home():
    """Locks the Phase-133 consolidation: one entry, sysop/runtime/. Fails if
    install.sh regresses to per-dir entries (or drops the entry entirely)."""
    assert _install_sh_want_list() == set(WANT)


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
    want = _install_sh_want_list()
    missing = {
        c for c in claimed
        if not any(c == w or c.startswith(w) for w in want)
    }
    assert not missing, (
        f"skills assert these dirs are gitignored but ensure_runtime_gitignore() "
        f"misses them (add to install.sh's want=() AND to WANT here): {sorted(missing)}"
    )
