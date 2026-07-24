"""Codex-native skill links (Phase 142, tools/CODEX_INTEGRATION_SPEC.md).

The installer emits two RELATIVE symlinks under <target>/.agents/skills/ pointing
at the shipped review-skill dirs, so a Codex CLI session discovers and selects
them natively with no converted or duplicated files:

    .agents/skills/codebase-review -> ../../.claude/skills/codebase-review
    .agents/skills/security-audit  -> ../../.claude/skills/security-audit

These drive the real installer against scratch git consumers (the
test_install_*.py pattern). The load-bearing invariants, each of which was a
finding in the spec's two-reviewer adversarial pass:

  * identity is the RAW readlink value, never resolved content — a different
    link is consumer data even when it resolves to the same bytes;
  * the collision hard-error fires BEFORE any target mutation (asserted where
    it actually bites: no pre-update snapshot commit exists afterward);
  * a failed capability probe disables link CREATION only — links that already
    exist and are still ours stay recorded and managed, so a transient
    mid-update probe failure can never feed them to the obsolete sweep;
  * the opt-out is persisted in the lock, so the documented one-line
    sysop-update.sh honors it with no retyped flag;
  * a path Sysop does not own never enters managed_paths (the sweep's blast
    radius), which is what makes --adopt of a real Codex user safe.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"

SKILLS = ("codebase-review", "security-audit")
LINK_PATHS = tuple(f".agents/skills/{n}" for n in SKILLS)


def _want(name):
    """The exact raw target the installer must write."""
    return f"../../.claude/skills/{name}"


def _git(cwd, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=check, capture_output=True, text=True
    )


def _consumer(root, files=None):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "README.md").write_text("hi\n")
    for rel, content in (files or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _install(target, *extra, path_prefix=None):
    env = dict(os.environ)
    prefix = os.path.dirname(sys.executable)
    if path_prefix:
        prefix = f"{path_prefix}{os.pathsep}{prefix}"
    env["PATH"] = prefix + os.pathsep + env["PATH"]
    return subprocess.run(
        ["bash", str(INSTALL_SH), str(target), "--packs", "", "--yes", *extra],
        capture_output=True, text=True, env=env,
    )


def _install_ok(target, *extra, **kw):
    r = _install(target, *extra, **kw)
    assert r.returncode == 0, r.stdout + r.stderr
    return r


def _commit_all(target, msg="install"):
    _git(target, "add", "-A")
    _git(target, "commit", "-qm", msg, check=False)


def _lock(target):
    return json.loads((Path(target) / ".claude" / "sysop.lock").read_text())


def _agents_in_lock(target):
    return sorted(p for p in _lock(target)["managed_paths"] if p.startswith(".agents"))


def _commit_count(target):
    return int(_git(target, "rev-list", "--count", "HEAD").stdout.strip())


def _tree_digest(root):
    """Content+link-target digest of a whole tree — proves byte-identity."""
    root = Path(root)
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if ".git" in p.parts:
            continue
        rel = p.relative_to(root).as_posix()
        if p.is_symlink():
            h.update(f"L:{rel}:{os.readlink(p)}\n".encode())
        elif p.is_file():
            h.update(f"F:{rel}:".encode() + hashlib.sha256(p.read_bytes()).digest())
        else:
            h.update(f"D:{rel}\n".encode())
    return h.hexdigest()


def _assert_links_correct(target):
    """Both links exist as symlinks, raw targets exact, SKILL.md readable through."""
    target = Path(target)
    for name in SKILLS:
        link = target / ".agents" / "skills" / name
        os.lstat(link)  # raises if absent
        assert link.is_symlink(), f"{name}: not a symlink"
        assert os.readlink(link) == _want(name), (
            f"{name}: raw target {os.readlink(link)!r} != {_want(name)!r}"
        )
        body = (link / "SKILL.md").read_text()
        assert f"name: {name}" in body, f"{name}: SKILL.md not readable through the link"


def _no_probe_artifacts(target):
    strays = [p.name for p in Path(target).iterdir() if "sysop-codex-probe" in p.name]
    assert not strays, f"probe left artifacts behind: {strays}"


@pytest.fixture
def failing_ln(tmp_path):
    """A PATH-prepended `ln` that always fails.

    Implementation requirement this enforces: the probe must invoke external
    `ln` (resolved through PATH), never a hardcoded /bin/ln — otherwise a
    filesystem without symlink support could not be simulated at all.
    """
    bindir = tmp_path / "fakebin"
    bindir.mkdir()
    fake = bindir / "ln"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    return str(bindir)


class TestFreshInstall:
    """Spec § 6 cases 1 + 2 — both install modes emit the same two links."""

    @pytest.mark.parametrize("mode", ["loop", "full"])
    def test_fresh_install_emits_both_links(self, tmp_path, mode):
        target = _consumer(tmp_path / f"fresh-{mode}")
        r = _install_ok(target, "--mode", mode)

        _assert_links_correct(target)
        assert _agents_in_lock(target) == sorted(LINK_PATHS)
        assert _lock(target)["codex_links"] is True
        assert "Codex: 2 native skill links" in r.stdout
        _no_probe_artifacts(target)

    def test_links_are_relative_not_absolute(self, tmp_path):
        """Absolute targets would break the moment the consumer moves the repo."""
        target = _consumer(tmp_path / "rel")
        _install_ok(target)
        for name in SKILLS:
            raw = os.readlink(target / ".agents" / "skills" / name)
            assert not os.path.isabs(raw), f"{name}: link target is absolute ({raw})"
            assert str(tmp_path) not in raw


class TestOptOut:
    """Spec § 6 case 3 — --no-codex-links writes nothing and records the choice."""

    def test_no_codex_links_creates_nothing(self, tmp_path):
        target = _consumer(tmp_path / "optout")
        _install_ok(target, "--no-codex-links")

        assert not (target / ".agents").exists()
        assert _agents_in_lock(target) == []
        assert _lock(target)["codex_links"] is False
        _no_probe_artifacts(target)


class TestReinstall:
    """Spec § 6 case 4 — a re-apply over correct links is a genuine no-op."""

    def test_force_reapply_keeps_the_same_inode(self, tmp_path):
        target = _consumer(tmp_path / "reapply")
        _install_ok(target)
        before = {n: os.lstat(target / ".agents" / "skills" / n).st_ino for n in SKILLS}

        r = _install_ok(target, "--force")

        after = {n: os.lstat(target / ".agents" / "skills" / n).st_ino for n in SKILLS}
        # Inode, not mtime: mtime can false-pass a fast delete/recreate.
        assert before == after, "link was recreated, not left alone"
        assert "(unchanged)" in r.stdout
        assert _agents_in_lock(target) == sorted(LINK_PATHS)

    def test_no_duplicate_lock_entries(self, tmp_path):
        target = _consumer(tmp_path / "dupes")
        _install_ok(target)
        _install_ok(target, "--force")
        paths = [p for p in _lock(target)["managed_paths"] if p.startswith(".agents")]
        assert len(paths) == len(set(paths)) == 2


class TestCollisions:
    """Spec § 6 case 5 — one case per collision class, all hard errors.

    Hard-fail rather than skip-with-a-warning is the point: a consumer-owned
    entry would route ordinary Codex requests to THEIR workflow while the
    install claimed success.
    """

    def _colliding_consumer(self, root, kind):
        if kind == "file":
            files = {".agents/skills/codebase-review": "my own routing\n"}
            target = _consumer(root, files)
        elif kind == "directory":
            target = _consumer(root, {".agents/skills/codebase-review/SKILL.md": "mine\n"})
        elif kind == "foreign-symlink":
            target = _consumer(root, {"my-skill/SKILL.md": "mine\n"})
            link = target / ".agents" / "skills"
            link.mkdir(parents=True)
            os.symlink("../../my-skill", link / "codebase-review")
            _commit_all(target, "foreign link")
        else:  # pragma: no cover - guard
            raise AssertionError(kind)
        return target

    @pytest.mark.parametrize("kind", ["file", "directory", "foreign-symlink"])
    def test_collision_hard_errors_and_leaves_tree_identical(self, tmp_path, kind):
        target = self._colliding_consumer(tmp_path / f"collide-{kind}", kind)
        before = _tree_digest(target)

        r = _install(target)

        assert r.returncode != 0, "collision must not install"
        assert ".agents/skills/codebase-review" in r.stderr
        assert "--no-codex-links" in r.stderr, "error must name the escape hatch"
        # Nothing was written — not even the parts of the pipeline that run first.
        assert _tree_digest(target) == before, "target tree mutated despite the error"
        assert not (target / "sysop").exists()
        assert not (target / ".claude" / "sysop.lock").exists()

    @pytest.mark.parametrize("kind", ["file", "directory", "foreign-symlink"])
    def test_same_tree_installs_cleanly_under_opt_out(self, tmp_path, kind):
        """The escape hatch must actually work on the exact tree that failed."""
        target = self._colliding_consumer(tmp_path / f"escape-{kind}", kind)
        _install_ok(target, "--no-codex-links")

        assert (target / "sysop").exists(), "install did not proceed"
        assert _lock(target)["codex_links"] is False
        assert _agents_in_lock(target) == []
        # The consumer's entry is untouched.
        entry = target / ".agents" / "skills" / "codebase-review"
        if kind == "file":
            assert entry.read_text() == "my own routing\n"
        elif kind == "directory":
            assert (entry / "SKILL.md").read_text() == "mine\n"
        else:
            assert os.readlink(entry) == "../../my-skill"


class TestParentComponentCollisions:
    """Adversarial-review finding: the leaf collision checks can't see a
    consumer FILE at `.agents`, or a parent we can't write into. Both would
    otherwise surface as a bare mkdir/ln failure that `set -e` turns into a
    mid-pipeline abort — a half-applied target with a stale lock."""

    def test_regular_file_at_agents_is_refused_before_any_write(self, tmp_path):
        target = _consumer(tmp_path / "agents-file", {".agents": "not a dir\n"})
        before = _tree_digest(target)

        r = _install(target)

        assert r.returncode != 0
        assert ".agents" in r.stderr
        assert "--no-codex-links" in r.stderr
        # The whole point: the pipeline must not have half-run.
        assert _tree_digest(target) == before, "target mutated before the refusal"
        assert not (target / "sysop").exists(), "install_skills ran before the abort"
        assert not (target / ".claude" / "sysop.lock").exists()

    def test_unwritable_skills_parent_is_refused_before_any_write(self, tmp_path):
        target = _consumer(tmp_path / "agents-ro")
        skills = target / ".agents" / "skills"
        skills.mkdir(parents=True)
        _commit_all(target, "consumer .agents")
        skills.chmod(0o555)
        try:
            before = _tree_digest(target)
            r = _install(target)

            assert r.returncode != 0, "unwritable parent must be refused, not hit at ln"
            assert "--no-codex-links" in r.stderr
            assert _tree_digest(target) == before
            assert not (target / "sysop").exists()
        finally:
            skills.chmod(0o755)

    def test_update_with_a_file_at_agents_makes_no_snapshot_commit(self, tmp_path):
        """The --update variant is the damaging one: without the parent check
        the abort lands after the pre-update snapshot commit and after the
        skills are overwritten, leaving a split-version install."""
        target = _consumer(tmp_path / "agents-file-update")
        _install_ok(target)
        _commit_all(target)
        import shutil
        shutil.rmtree(target / ".agents")
        (target / ".agents").write_text("not a dir\n")
        (target / "sysop" / "scripts" / "run_checks.sh").write_text("# edited\n")
        _commit_all(target, "consumer takeover")
        (target / "sysop" / "scripts" / "run_checks.sh").write_text("# dirty\n")
        commits_before = _commit_count(target)

        r = _install(target, "--update")

        assert r.returncode != 0
        assert _commit_count(target) == commits_before, "snapshot commit was made"
        assert (target / ".agents").read_text() == "not a dir\n"


class TestSweepBlastRadius:
    """Adversarial-review finding: the sweep resolves candidates with `-e`
    (which follows symlinks) and removes with `rm -f`, so a lock entry naming a
    path THROUGH one of our links would delete the real skill body out of
    `.claude/skills/`. Only a corrupt/hand-edited lock produces one — which is
    exactly what the sweep's sibling consumer-path guard exists for."""

    def _lock_with_extra_path(self, target, extra):
        lock_path = target / ".claude" / "sysop.lock"
        data = json.loads(lock_path.read_text())
        data["managed_paths"] = sorted(data["managed_paths"] + [extra])
        lock_path.write_text(json.dumps(data, indent=2) + "\n")

    def test_lock_path_through_a_link_never_deletes_the_real_skill(self, tmp_path):
        target = _consumer(tmp_path / "through-link")
        _install_ok(target)
        real = target / ".claude" / "skills" / "codebase-review" / "SKILL.md"
        body = real.read_text()
        self._lock_with_extra_path(target, ".agents/skills/codebase-review/SKILL.md")
        _commit_all(target, "corrupt lock")

        _install_ok(target, "--update")

        assert real.exists(), "the sweep deleted through the symlink"
        assert real.read_text() == body
        assert "remove: .agents/skills/codebase-review/SKILL.md" not in _install(
            target, "--update"
        ).stdout

    def test_lock_path_naming_the_skills_dir_is_not_swept(self, tmp_path):
        """A directory entry would make both `git rm -f` and `rm -f` fail, and
        under `set -e` that aborts main() after the pipeline but before the lock
        is rewritten."""
        target = _consumer(tmp_path / "dir-entry")
        _install_ok(target)
        self._lock_with_extra_path(target, ".agents/skills")
        _commit_all(target, "corrupt lock")

        r = _install_ok(target, "--update")

        assert (target / ".agents" / "skills").is_dir()
        _assert_links_correct(target)
        # The lock was still rewritten — i.e. main() ran to completion.
        assert _lock(target)["codex_links"] is True
        assert "remove: .agents/skills\n" not in r.stdout


class TestConsumerCoexistence:
    """Spec § 6 case 6 — Sysop owns two entries; everything else survives."""

    def test_agents_md_and_sibling_skill_survive_byte_for_byte(self, tmp_path):
        target = _consumer(tmp_path / "coexist", {
            "AGENTS.md": "# My project instructions\n\nDo the thing.\n",
            ".agents/skills/consumer-helper/SKILL.md": "---\nname: consumer-helper\n---\nmine\n",
        })
        agents_before = hashlib.sha256((target / "AGENTS.md").read_bytes()).hexdigest()
        helper = target / ".agents" / "skills" / "consumer-helper" / "SKILL.md"
        helper_before = hashlib.sha256(helper.read_bytes()).hexdigest()

        _install_ok(target)

        assert hashlib.sha256((target / "AGENTS.md").read_bytes()).hexdigest() == agents_before
        assert hashlib.sha256(helper.read_bytes()).hexdigest() == helper_before
        _assert_links_correct(target)
        # The consumer's sibling never enters Sysop's blast radius.
        assert ".agents/skills/consumer-helper" not in _lock(target)["managed_paths"]

    def test_installer_emits_no_agents_md(self, tmp_path):
        """The AGENTS.md shim is deliberately not built — links register, prose
        only routes. A stray emission would compete for the 32 KiB budget."""
        target = _consumer(tmp_path / "no-agents-md")
        _install_ok(target)
        assert not (target / "AGENTS.md").exists()


class TestCapabilityProbe:
    """Spec § 6 cases 7 + 10 — degrade gracefully, and never sweep on a probe fail."""

    def test_probe_failure_warns_and_install_proceeds(self, tmp_path, failing_ln):
        target = _consumer(tmp_path / "noprobe")
        r = _install_ok(target, path_prefix=failing_ln)

        assert (target / "sysop").exists(), "a default-on garnish must not brick the install"
        assert not (target / ".agents").exists()
        assert _agents_in_lock(target) == []
        assert "Codex skill links skipped" in r.stdout, "probe failure must be loud"
        assert "Codex: skipped (no symlink support" in r.stdout
        _no_probe_artifacts(target)

    def test_probe_failure_during_update_leaves_existing_links_alone(
        self, tmp_path, failing_ln
    ):
        """The blocker case from the spec's reviewers: a transient probe failure
        must not drop a still-good link from managed_paths and hand it to the
        obsolete sweep.

        Setup detail that makes this test mean anything: the probe only runs
        when something actually needs creating, so one link is deleted first to
        force it. Without that, `need == 0`, the probe is skipped entirely, the
        failing `ln` is never invoked, and the test passes no matter what the
        code does. (It did, in the first draft.) The SURVIVING link is the
        subject — still exactly ours, and it must come through fully managed.
        """
        target = _consumer(tmp_path / "update-noprobe")
        _install_ok(target)
        _commit_all(target)
        survivor = target / ".agents" / "skills" / "security-audit"
        ino = os.lstat(survivor).st_ino
        (target / ".agents" / "skills" / "codebase-review").unlink()
        _commit_all(target, "one link missing → the probe must fire")

        r = _install_ok(target, "--update", path_prefix=failing_ln)

        assert "Codex skill links skipped" in r.stdout, (
            "precondition failed: the probe did not run, so this test proves nothing"
        )
        # The survivor is byte-for-byte untouched and still managed.
        assert os.lstat(survivor).st_ino == ino, "surviving link was recreated"
        assert os.readlink(survivor) == _want("security-audit")
        assert ".agents/skills/security-audit" in _agents_in_lock(target), (
            "a probe failure dropped a working link from managed_paths — the "
            "next sweep would delete it"
        )
        assert "remove: .agents/skills/security-audit" not in r.stdout
        # Creation stayed disabled, so the deleted one is not resurrected.
        assert not (target / ".agents" / "skills" / "codebase-review").exists()


class TestUpdate:
    """Spec § 6 case 8 — migration onto a pre-Codex install, and the
    preflight-before-mutation guarantee asserted where it bites."""

    def _strip_codex(self, target):
        """Rewind a fresh install to look like a pre-Codex one."""
        import shutil
        shutil.rmtree(target / ".agents")
        lock_path = target / ".claude" / "sysop.lock"
        data = json.loads(lock_path.read_text())
        data.pop("codex_links", None)
        data["managed_paths"] = [
            p for p in data["managed_paths"] if not p.startswith(".agents")
        ]
        lock_path.write_text(json.dumps(data, indent=2) + "\n")
        _commit_all(target, "pre-codex")

    def test_update_from_pre_codex_lock_adds_links(self, tmp_path):
        target = _consumer(tmp_path / "pre-codex")
        _install_ok(target)
        _commit_all(target)
        self._strip_codex(target)
        assert "codex_links" not in _lock(target)

        _install_ok(target, "--update")

        _assert_links_correct(target)
        assert _agents_in_lock(target) == sorted(LINK_PATHS)
        assert _lock(target)["codex_links"] is True

    def test_skill_body_upgrade_flows_through_an_untouched_link(self, tmp_path):
        """The link is an entry, not a copy: refreshing the skill body must be
        visible through it without the link itself being rewritten."""
        target = _consumer(tmp_path / "body-upgrade")
        _install_ok(target)
        _commit_all(target)
        link = target / ".agents" / "skills" / "security-audit"
        ino_before = os.lstat(link).st_ino
        # Simulate a stale consumer-side body; --update restores upstream's.
        real = target / ".claude" / "skills" / "security-audit" / "SKILL.md"
        real.write_text("stale\n")

        _install_ok(target, "--update")

        assert os.lstat(link).st_ino == ino_before, "link was recreated"
        assert (link / "SKILL.md").read_text() != "stale\n", "body not refreshed"
        assert "name: security-audit" in (link / "SKILL.md").read_text()

    def test_update_collision_errors_before_any_snapshot_commit(self, tmp_path):
        """The preflight-before-mutation guarantee, asserted where it bites:
        --update's pre-update snapshot commit must not exist afterward."""
        target = _consumer(tmp_path / "update-collide")
        _install_ok(target)
        _commit_all(target)
        # Consumer replaces one link with their own directory, and dirties a
        # managed path so a snapshot commit WOULD be created if we got that far.
        link = target / ".agents" / "skills" / "codebase-review"
        link.unlink()
        link.mkdir()
        (link / "SKILL.md").write_text("mine\n")
        (target / "sysop" / "scripts" / "run_checks.sh").write_text("# edited\n")
        _commit_all(target, "consumer takeover")
        (target / "sysop" / "scripts" / "run_checks.sh").write_text("# dirty edit\n")
        commits_before = _commit_count(target)

        r = _install(target, "--update")

        assert r.returncode != 0
        assert ".agents/skills/codebase-review" in r.stderr
        assert _commit_count(target) == commits_before, (
            "a pre-update snapshot commit was created before the collision error"
        )
        assert (link / "SKILL.md").read_text() == "mine\n"


class TestStickyOptOut:
    """Spec § 6 case 9 — the whole lifecycle, including the plain-update leg
    that the draft's per-run flag broke forever for collision consumers."""

    def test_opt_out_persists_across_a_plain_update(self, tmp_path):
        target = _consumer(tmp_path / "sticky")
        _install_ok(target)
        _commit_all(target)

        # 1. Opt out on an install that has links → they are swept.
        r = _install_ok(target, "--update", "--no-codex-links")
        for link in LINK_PATHS:
            assert f"remove: {link}" in r.stdout
        assert not (target / ".agents" / "skills" / "codebase-review").exists()
        assert _lock(target)["codex_links"] is False
        _commit_all(target, "opt out")

        # 2. Plain update — no retyped flag — must honor the lock.
        _install_ok(target, "--update")
        assert not (target / ".agents").exists() or not list(
            (target / ".agents" / "skills").iterdir()
        )
        assert _lock(target)["codex_links"] is False
        assert _agents_in_lock(target) == []

        _commit_all(target, "plain update")
        # 2b. A PLAIN re-install (not --update) honors the lock too — the
        # re-read is deliberately not --update-scoped, or a re-install would
        # silently resurrect the links, or hard-error on a collision the
        # consumer already acknowledged.
        _install_ok(target)
        assert _lock(target)["codex_links"] is False
        assert _agents_in_lock(target) == []
        assert not (target / ".agents" / "skills" / "codebase-review").is_symlink()

        # 3. Explicit re-enable brings them back.
        _install_ok(target, "--update", "--codex-links")
        _assert_links_correct(target)
        assert _lock(target)["codex_links"] is True
        assert _agents_in_lock(target) == sorted(LINK_PATHS)

    def test_opt_out_on_a_plain_reinstall_also_removes_them(self, tmp_path):
        """A plain re-install never reaches the obsolete sweep (it is
        --update-gated), so opting out there would otherwise drop the links from
        managed_paths while leaving them on disk: still registering with Codex,
        now unmanaged, and invisible to every future sweep."""
        target = _consumer(tmp_path / "optout-reinstall")
        _install_ok(target)
        _commit_all(target)

        r = _install_ok(target, "--no-codex-links")  # NOT --update

        assert _lock(target)["codex_links"] is False
        assert _agents_in_lock(target) == []
        for name in SKILLS:
            link = target / ".agents" / "skills" / name
            assert not link.is_symlink(), f"{name} left on disk but unmanaged"
        assert "codex links disabled" in r.stdout

    def test_plain_reinstall_opt_out_spares_a_consumer_replaced_entry(self, tmp_path):
        """Same guard as the sweep's: decided by raw link value, not by path."""
        target = _consumer(tmp_path / "optout-reinstall-guard")
        _install_ok(target)
        replaced = target / ".agents" / "skills" / "security-audit"
        replaced.unlink()
        os.symlink("../../my-own-thing", replaced)
        _commit_all(target, "repoint")

        _install_ok(target, "--no-codex-links")

        assert os.readlink(replaced) == "../../my-own-thing", "consumer link deleted"
        assert not (target / ".agents" / "skills" / "codebase-review").is_symlink()

    def test_opt_out_sweep_spares_a_consumer_replaced_entry(self, tmp_path):
        """Guarded removal: ours goes, theirs stays — decided by raw link value."""
        target = _consumer(tmp_path / "sticky-guard")
        _install_ok(target)
        replaced = target / ".agents" / "skills" / "security-audit"
        replaced.unlink()
        os.symlink("../../my-own-thing", replaced)
        _commit_all(target, "repoint")

        r = _install_ok(target, "--update", "--no-codex-links")

        assert os.readlink(replaced) == "../../my-own-thing", "consumer link deleted"
        assert "keep: .agents/skills/security-audit" in r.stdout
        assert "remove: .agents/skills/codebase-review" in r.stdout
        assert not (target / ".agents" / "skills" / "codebase-review").exists()


class TestObsoleteSweepSymlinkAwareness:
    """Spec § 6 case 11 — `-e` alone is false for a broken symlink."""

    def test_broken_managed_link_is_still_swept(self, tmp_path):
        """A link whose target vanished fails -e; without the -L half it would
        be stranded in the tree forever.

        Constructed as the case that actually reaches this branch: upstream
        drops a skill from CODEX_SKILLS. The lock still lists the path, the
        pipeline no longer records it, and on disk it is a BROKEN link carrying
        our exact raw target — so it is ours to remove. (Breaking the two live
        links instead proves nothing: --update reinstalls .claude/skills/ before
        the sweep runs, healing them.)
        """
        target = _consumer(tmp_path / "broken")
        _install_ok(target)
        retired = target / ".agents" / "skills" / "retired-skill"
        os.symlink("../../.claude/skills/retired-skill", retired)
        assert retired.is_symlink() and not retired.exists(), "precondition: broken link"
        lock_path = target / ".claude" / "sysop.lock"
        data = json.loads(lock_path.read_text())
        data["managed_paths"] = sorted(
            data["managed_paths"] + [".agents/skills/retired-skill"]
        )
        lock_path.write_text(json.dumps(data, indent=2) + "\n")
        _commit_all(target, "retired skill still in the lock")

        r = _install_ok(target, "--update")

        assert "remove: .agents/skills/retired-skill" in r.stdout, "broken link stranded"
        assert not retired.is_symlink(), "broken link survived the sweep"
        # The two live links are untouched by the retirement.
        _assert_links_correct(target)

    def test_broken_link_that_is_not_ours_is_spared(self, tmp_path):
        """The -L half must not become a licence to delete: a broken link the
        consumer repointed is still their data."""
        target = _consumer(tmp_path / "broken-foreign")
        _install_ok(target)
        foreign = target / ".agents" / "skills" / "retired-skill"
        os.symlink("../../somewhere-of-mine", foreign)
        lock_path = target / ".claude" / "sysop.lock"
        data = json.loads(lock_path.read_text())
        data["managed_paths"] = sorted(
            data["managed_paths"] + [".agents/skills/retired-skill"]
        )
        lock_path.write_text(json.dumps(data, indent=2) + "\n")
        _commit_all(target, "foreign broken link")

        r = _install_ok(target, "--update")

        assert os.readlink(foreign) == "../../somewhere-of-mine", "consumer link deleted"
        assert "keep: .agents/skills/retired-skill" in r.stdout

    def test_sweep_removes_the_entry_not_the_target(self, tmp_path):
        target = _consumer(tmp_path / "entry-only")
        _install_ok(target)
        _commit_all(target)

        _install_ok(target, "--update", "--no-codex-links")

        for name in SKILLS:
            assert not (target / ".agents" / "skills" / name).is_symlink()
            assert (target / ".claude" / "skills" / name / "SKILL.md").exists(), (
                "the sweep followed the link and deleted the real skill"
            )


class TestDryRun:
    """Spec § 6 case 12 — dry-run plans the links and writes nothing."""

    def test_dry_run_lists_links_and_leaves_tree_clean(self, tmp_path):
        target = _consumer(tmp_path / "dry")
        before = _tree_digest(target)

        r = _install_ok(target, "--dry-run")

        for name in SKILLS:
            assert f"link: .agents/skills/{name} → {_want(name)}" in r.stdout
        assert "capability probed at apply time" in r.stdout, (
            "dry-run must not claim the probe ran"
        )
        assert not (target / ".agents").exists()
        assert _tree_digest(target) == before
        assert _git(target, "status", "--porcelain").stdout.strip() == ""
        _no_probe_artifacts(target)

    def test_probe_does_not_run_before_the_confirm_gate(self, tmp_path, failing_ln):
        """The probe writes into the target, so it must run only after the
        Proceed? gate — a run that never gets past that gate must not have
        touched the consumer's repo.

        Observable proof, same trick as the dry-run case: under a failing `ln`,
        a run that stops at the gate must NOT report the probe verdict, because
        that verdict is only knowable by having written. (Omitting --yes stops
        the run at the gate: with no controlling terminal, `confirm` refuses
        rather than prompting.)
        """
        target = _consumer(tmp_path / "gated")
        before = _tree_digest(target)
        env = dict(os.environ)
        env["PATH"] = failing_ln + os.pathsep + os.path.dirname(sys.executable) \
            + os.pathsep + env["PATH"]
        r = subprocess.run(
            ["bash", str(INSTALL_SH), str(target), "--packs", ""],  # no --yes
            capture_output=True, text=True, env=env,
        )

        assert r.returncode != 0, "precondition: the run must stop at the gate"
        assert "Codex skill links skipped" not in r.stdout, (
            "the probe ran before the user confirmed"
        )
        assert _tree_digest(target) == before
        _no_probe_artifacts(target)

    def test_dry_run_does_not_run_the_capability_probe(self, tmp_path, failing_ln):
        """`--dry-run` promises nothing will be written, and the probe writes a
        dir inside the target. Observable proof it stayed out: under a failing
        `ln`, a dry run must still plan both links and must NOT report the
        probe-failure skip — that verdict is only knowable by probing."""
        target = _consumer(tmp_path / "dry-noprobe")

        r = _install_ok(target, "--dry-run", path_prefix=failing_ln)

        assert "capability probed at apply time" in r.stdout
        assert "Codex skill links skipped" not in r.stdout, "the probe ran in dry-run"
        assert "no symlink support" not in r.stdout
        assert not (target / ".agents").exists()
        _no_probe_artifacts(target)

    def test_dry_run_reports_a_collision_without_writing(self, tmp_path):
        target = _consumer(tmp_path / "dry-collide",
                           {".agents/skills/security-audit": "mine\n"})
        before = _tree_digest(target)

        r = _install(target, "--dry-run")

        assert r.returncode != 0
        assert ".agents/skills/security-audit" in r.stderr
        assert _tree_digest(target) == before


class TestAdopt:
    """Spec § 6 case 13 — adopt records reality; it never writes, and never
    records a path Sysop does not own."""

    def _pre_lock_tree(self, root, extra=None):
        target = _consumer(root)
        _install_ok(target)
        import shutil
        shutil.rmtree(target / ".agents")
        (target / ".claude" / "sysop.lock").unlink()
        for rel, content in (extra or {}).items():
            p = target / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        _commit_all(target, "pre-lock")
        return target

    def test_adopt_records_link_paths_without_creating_them(self, tmp_path):
        target = self._pre_lock_tree(tmp_path / "adopt")

        _install_ok(target, "--adopt")

        assert not (target / ".agents").exists(), "adopt wrote to the tree"
        assert _agents_in_lock(target) == sorted(LINK_PATHS)
        assert _lock(target)["codex_links"] is True

    def test_adopt_with_a_colliding_entry_succeeds_and_excludes_it(self, tmp_path):
        """A path Sysop doesn't own must never enter managed_paths, where a
        later sweep would put consumer data in the deletion blast radius."""
        target = self._pre_lock_tree(
            tmp_path / "adopt-collide",
            {".agents/skills/codebase-review/SKILL.md": "mine\n"},
        )

        r = _install_ok(target, "--adopt")

        assert ".agents/skills/codebase-review" not in _lock(target)["managed_paths"]
        assert _agents_in_lock(target) == [".agents/skills/security-audit"]
        assert (target / ".agents" / "skills" / "codebase-review" / "SKILL.md"
                ).read_text() == "mine\n"
        assert "leaving it unmanaged" in r.stdout


class TestDocumentedCommitLine:
    """The install payload gained a top-level dir, so every documented
    `git add` line had to gain `.agents/`. Phase 131 fixed this exact class of
    drift after two cold readers hit `fatal: pathspec ...` on the quickstart;
    this guard keeps a future payload change from silently reopening it."""

    DOC_SITES = [
        "README.md",
        "docs/loop-mode.md",
        "docs/getting-started.md",
        "docs/install-and-update.md",
        "docs/index.html",
    ]

    def test_every_documented_install_commit_line_stages_agents(self):
        import re
        # Every documented `git add` of the Sysop payload, including the
        # loop→full upgrade lines: a PRE-Codex loop install gains .agents/ for
        # the first time on that upgrade, so those lines need it too (and for a
        # post-Codex install, re-adding an already-tracked path is a no-op).
        pattern = re.compile(r"git add [^\n&|`]*(?:CLAUDE\.md|\.gitignore)")
        offenders = []
        for rel in self.DOC_SITES:
            text = (REPO_ROOT / rel).read_text()
            for m in pattern.finditer(text):
                if ".agents/" not in m.group(0):
                    offenders.append(f"{rel}: {m.group(0)}")
        assert not offenders, (
            "install commit line(s) missing .agents/ — a Codex-links install "
            "leaves them untracked:\n  " + "\n  ".join(offenders)
        )

    def test_documented_line_actually_works_on_a_fresh_loop_install(self, tmp_path):
        """Run the README's loop-mode line verbatim against a real install."""
        target = _consumer(tmp_path / "quickstart")
        _install_ok(target, "--mode", "loop")

        add = subprocess.run(
            ["git", "add", ".claude/", ".agents/", "sysop/", "CLAUDE.md", ".gitignore"],
            cwd=target, capture_output=True, text=True,
        )
        assert add.returncode == 0, f"documented line failed: {add.stderr}"
        _git(target, "commit", "-qm", "chore: install Sysop (loop mode)")
        # The links are tracked, and tracked AS links (mode 120000), not as
        # copies of the skill bodies.
        ls = _git(target, "ls-files", "-s", ".agents/").stdout
        assert ls.count("120000") == 2, f"links not tracked as symlinks:\n{ls}"
        assert _git(target, "status", "--porcelain").stdout.strip() == ""


class TestFlagSurface:
    def test_help_documents_both_flags_and_the_lock_persistence(self):
        r = subprocess.run(
            ["bash", str(INSTALL_SH), "--help"], capture_output=True, text=True
        )
        assert r.returncode == 0
        assert "--no-codex-links" in r.stdout
        assert "--codex-links" in r.stdout
        assert "RECORDED IN THE LOCK" in r.stdout

    def test_reconstruct_old_install_never_forwards_the_flag(self):
        """A pre-Codex old installer would die on the unknown option, taking
        Phase-24b preservation down with it."""
        body = INSTALL_SH.read_text()
        start = body.index("reconstruct_old_install() {")
        end = body.index("\ndetect_committed_divergence()", start)
        assert "--no-codex-links" not in body[start:end]
        assert "--codex-links" not in body[start:end]
