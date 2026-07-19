"""Round-4 cold-read first-touch fixes (Phase 131).

Both round-4 readers install-tested the public repo and hit the same wall:
the README quickstart's first post-install command —
  git add .claude/ sysop/ tasks/ CLAUDE.md .gitignore
— died with `fatal: pathspec 'CLAUDE.md'` (exit 128, nothing staged) on any
repo without a pre-existing CLAUDE.md, because seed_claude_md_stub() was
loop-gated. Both also flagged discovering the allow-list's `git push` grants
only by reading the shipped JSON.

These drive the real installer against scratch git consumers (the
test_install_*.py pattern): the stub now seeds in BOTH modes (append-if-absent
on existing files), the quickstart line succeeds verbatim on a bare repo, and
the permission blast-radius disclosure prints at install time in both modes.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"

SECTION_HEADERS = (
    "## Scope mapping",
    "## Map coverage exclusions",
    "## Security-critical always-include files",
)


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def _consumer(root, files=None):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("hi\n")
    for rel, content in (files or {}).items():
        (root / rel).write_text(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _install(target, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return subprocess.run(
        ["bash", str(INSTALL_SH), str(target), "--packs", "", "--yes", *extra],
        capture_output=True, text=True, env=env,
    )


class TestFullModeClaudeMdStub:
    def test_bare_repo_gets_stub_and_quickstart_line_succeeds_verbatim(self, tmp_path):
        """The round-4 repro, inverted: fresh full-mode install on a repo with
        no CLAUDE.md must leave the documented quickstart command runnable
        as-is — this is the exact command from README/install-and-update."""
        target = _consumer(tmp_path / "bare")
        r = _install(target)
        assert r.returncode == 0, r.stdout + r.stderr

        text = (target / "CLAUDE.md").read_text()
        for hdr in SECTION_HEADERS:
            assert hdr in text, f"stub missing section {hdr!r}"

        add = subprocess.run(
            ["git", "add", ".claude/", "sysop/", "tasks/", "CLAUDE.md", ".gitignore"],
            cwd=target, capture_output=True, text=True,
        )
        assert add.returncode == 0, f"quickstart git add failed: {add.stderr}"
        _git(target, "commit", "-qm", "chore: install Sysop")

    def test_existing_claude_md_is_appended_not_rewritten(self, tmp_path):
        authored = "# CLAUDE.md\n\nMy project notes.\n\n## Scope mapping\n\nmine.\n"
        target = _consumer(tmp_path / "auth", files={"CLAUDE.md": authored})
        r = _install(target)
        assert r.returncode == 0, r.stdout + r.stderr
        text = (target / "CLAUDE.md").read_text()
        assert text.startswith(authored), "consumer-authored content rewritten"
        # The authored section is not duplicated; the two absent ones append.
        assert text.count("## Scope mapping") == 1
        assert "## Map coverage exclusions" in text
        assert "## Security-critical always-include files" in text


class TestPermissionDisclosure:
    def test_full_mode_discloses_push_grants(self, tmp_path):
        target = _consumer(tmp_path / "full")
        r = _install(target)
        assert r.returncode == 0, r.stdout + r.stderr
        # Each note line carries a bullet prefix, so assert phrases that sit
        # within a single disclosure line.
        flat = " ".join(r.stdout.split())
        assert "git push origin" in flat, "full-mode blast-radius line missing"
        assert "--force-with-lease" in flat
        assert "delete any rule" in flat

    def test_loop_mode_discloses_no_push_subset(self, tmp_path):
        target = _consumer(tmp_path / "loop")
        r = _install(target, "--mode", "loop")
        assert r.returncode == 0, r.stdout + r.stderr
        assert "no push, merge, or rebase grants" in r.stdout, (
            "loop-mode subset disclosure missing"
        )
        # And the loop settings really carry no push grant (the disclosure is
        # honest, not aspirational).
        settings = (target / ".claude" / "settings.json").read_text()
        assert "git push" not in settings
