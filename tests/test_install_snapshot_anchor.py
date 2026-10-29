"""Integration tests for the pre-update snapshot's rollback anchor (Phase 306, `Q-542`).

`snapshot_managed_paths` stamps its commit `sysop: pre-update snapshot (was at
<hash>)`. That hash used to come from `lock_field sysop_commit`, which reads
`"$TARGET/$LOCK_REL"` — the **working-tree** lock. The snapshot exists for one
purpose: to be the state an operator returns to when an update goes wrong. So it
has to name the last **committed** state, and the working-tree lock is not that
whenever an earlier `--update` advanced it and was never committed.

**That is the ordinary case, not a crash.** `--update` deliberately leaves its
result uncommitted ("The update is uncommitted — review and commit
intentionally"), so running it twice before committing is enough. The filing
described it as an interrupted run and said "the tree it is snapshotting is
still the old one"; reproduction showed otherwise — the earlier run wrote the
*content* too, so the snapshot holds a **mix**: already-overwritten files under
the older lock. The fix therefore names the committed anchor *and* says the
on-disk lock had already moved, rather than silently swapping one hash for
another and implying a clean pre-update state.

Live instance that prompted it: BeanRider `6b972f5` reads "was at 6de1581c"
while the lock inside that commit and inside its parent both read 9f03becf.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

SUFFIX = "lock on disk already advanced to"
WARN = "an earlier --update advanced the lock on disk and was never committed"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                   env={**os.environ, **_GIT_ISOLATION})


def _git_out(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                          text=True, env={**os.environ, **_GIT_ISOLATION}).stdout.strip()


@pytest.fixture(scope="module")
def pristine_source(tmp_path_factory):
    src = tmp_path_factory.mktemp("anchor_src")
    shutil.copy2(REPO_ROOT / "install.sh", src / "install.sh")
    for d in ("core", "packs"):
        shutil.copytree(REPO_ROOT / d, src / d,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"))
    _git(src, "init", "-q")
    _git(src, "config", "user.email", "test@test")
    _git(src, "config", "user.name", "test")
    _git(src, "config", "commit.gpgsign", "false")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "A")
    return src


@pytest.fixture
def source(pristine_source, tmp_path):
    dst = tmp_path / "src"
    subprocess.run(["git", "clone", "-q", str(pristine_source), str(dst)],
                   check=True, capture_output=True,
                   env={**os.environ, **_GIT_ISOLATION})
    _git(dst, "config", "user.email", "test@test")
    _git(dst, "config", "user.name", "test")
    _git(dst, "config", "commit.gpgsign", "false")
    return dst


def _bump(src, marker):
    """Advance the source by one commit that changes a shipped managed path."""
    p = src / "core" / "companion" / "scripts" / "self_check.sh"
    p.write_text(p.read_text() + f"\n# {marker}\n")
    _git(src, "commit", "-qam", marker)
    return _git_out(src, "rev-parse", "HEAD")


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


def _snapshot_subject(target):
    """The subject of the newest `pre-update snapshot` commit, or None."""
    log = _git_out(target, "log", "--format=%s", "-20")
    for line in log.splitlines():
        if line.startswith("sysop: pre-update snapshot"):
            return line
    return None


def _installed_and_committed(source, tmp_path):
    """Target with a committed Sysop install; returns (target, committed_sha)."""
    tgt = _target(tmp_path)
    assert _run(source, tgt, "--packs", "python", "--no-arm-hooks").returncode == 0
    sha = json.loads((tgt / ".claude" / "sysop.lock").read_text())["sysop_commit"]
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "install")
    return tgt, sha


# ── the defect ───────────────────────────────────────────────────────────────

def test_second_update_anchors_to_the_committed_lock(source, tmp_path):
    """Run `--update` twice without committing in between — the documented flow
    leaves the first one uncommitted — and the snapshot must name the state the
    operator can actually return to, not the one the interrupted run was
    installing."""
    tgt, sha_a = _installed_and_committed(source, tmp_path)

    sha_b = _bump(source, "commit-B")
    assert _run(source, tgt, "--update", "--no-arm-hooks").returncode == 0
    assert _git_out(tgt, "status", "--porcelain") != "", "update should leave work uncommitted"
    on_disk = json.loads((tgt / ".claude" / "sysop.lock").read_text())["sysop_commit"]
    assert on_disk == sha_b, "precondition: the on-disk lock advanced"

    _bump(source, "commit-C")
    res = _run(source, tgt, "--update", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr

    subject = _snapshot_subject(tgt)
    assert subject is not None, "no snapshot commit was written"
    assert sha_a[:12] in subject, (
        f"snapshot must anchor to the committed lock {sha_a[:12]}; got: {subject}")
    assert subject.index(sha_a[:12]) < subject.index(sha_b[:12]), (
        "the committed anchor must be the one after 'was at'")
    assert SUFFIX in subject, (
        "the snapshot is a MIX, not a clean pre-update state — the message must "
        f"say the on-disk lock had already moved; got: {subject}")
    assert sha_b[:12] in subject, "the superseded on-disk hash must still be named"
    assert WARN in res.stdout + res.stderr, "the divergence must be reported at run time"


def test_the_anchor_names_the_state_the_snapshots_PARENT_was_installed_from(source, tmp_path):
    """The anchor must be the Sysop commit the pre-update state came from.

    **This test replaces one that measured nothing, and the replacement is the
    finding.** Its predecessor read `.claude/sysop.lock` out of the *snapshot
    commit's own tree* and asserted it equalled the anchor — with a docstring
    claiming that "asserting the message alone would pass on a fix that printed
    any plausible sha". Exactly inverted: `write_lock_file` never calls
    `record_managed_path`, so the lock is not in `managed_paths`, never in
    `snap_candidates`, and the snapshot commit therefore *inherits* HEAD's copy by
    construction. The assertion held for every possible value of the anchor — it
    passed against the pre-fix installer, against the anchor reverted to the
    on-disk lock, and against a literal `000000000000deadbeef`. Phase 306's round
    (guard lens) ran all three.

    The real question is about the snapshot's **parent**: the commit an operator
    returns to. That is the state the anchor claims to name, and its lock is a
    value the fix genuinely selects between.
    """
    tgt, sha_a = _installed_and_committed(source, tmp_path)
    sha_b = _bump(source, "commit-B")
    assert _run(source, tgt, "--update", "--no-arm-hooks").returncode == 0
    _bump(source, "commit-C")
    assert _run(source, tgt, "--update", "--no-arm-hooks").returncode == 0

    snap = next(l.split()[0] for l in _git_out(tgt, "log", "--format=%H %s", "-20").splitlines()
                if "pre-update snapshot" in l)
    parent = _git_out(tgt, "rev-parse", f"{snap}^")
    parent_lock = json.loads(_git_out(tgt, "show", f"{parent}:.claude/sysop.lock"))
    assert parent_lock["sysop_commit"] == sha_a, (
        "the snapshot's parent is the state being preserved; its lock is what the "
        "anchor must name")

    subject = _snapshot_subject(tgt)
    assert subject.split("was at ")[1][:12] == sha_a[:12], subject
    assert sha_a[:12] != sha_b[:12], "fixture degenerate: the two anchors must differ"


# ── controls ─────────────────────────────────────────────────────────────────

def test_ordinary_single_update_message_is_unchanged(source, tmp_path):
    """The common path must be byte-identical to pre-Phase-306 output: no warning,
    no suffix, anchored to the lock (which here is both on-disk and committed)."""
    tgt, sha_a = _installed_and_committed(source, tmp_path)
    p = tgt / "sysop" / "scripts" / "self_check.sh"
    p.write_text(p.read_text() + "\n# consumer edit\n")
    _bump(source, "commit-B")

    res = _run(source, tgt, "--update", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    subject = _snapshot_subject(tgt)
    assert subject == f"sysop: pre-update snapshot (was at {sha_a[:12]})", subject
    assert WARN not in res.stdout + res.stderr


def test_untracked_lock_falls_back_instead_of_failing(source, tmp_path):
    """`committed_lock_field` must return empty — never abort — where there is no
    committed answer. An install that was never committed is the reachable case:
    `git show HEAD:<lock>` exits non-zero and the anchor falls back to the
    on-disk value, which is the best available."""
    tgt = _target(tmp_path)
    assert _run(source, tgt, "--packs", "python", "--no-arm-hooks").returncode == 0
    on_disk = json.loads((tgt / ".claude" / "sysop.lock").read_text())["sysop_commit"]
    # Deliberately NOT committed: the lock is untracked in HEAD. `git status
    # --porcelain` collapses this to `?? .claude/`, so ask git directly.
    untracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".claude/sysop.lock"],
        cwd=str(tgt), capture_output=True,
        env={**os.environ, **_GIT_ISOLATION}).returncode
    assert untracked != 0, "precondition: the lock must not be tracked in HEAD"

    _bump(source, "commit-B")
    res = _run(source, tgt, "--update", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    assert WARN not in res.stdout + res.stderr
    subject = _snapshot_subject(tgt)
    if subject is not None:
        assert SUFFIX not in subject, subject
        assert on_disk[:12] in subject, subject


def test_divergence_does_not_leak_into_the_update_banner(source, tmp_path):
    """Scoping guard. Only the rollback anchor changes.

    Everywhere else — `reconstruct_old_install`'s 3-way divergence, the `mode:
    update (was at …)` banner, the closing `was:` line — the question is what
    content is on disk *now*, and the earlier run advanced the on-disk lock along
    with the files. A fix that redirected `old_commit` globally would break
    divergence detection silently, so this pins the banner to the on-disk value.
    """
    tgt, _sha_a = _installed_and_committed(source, tmp_path)
    sha_b = _bump(source, "commit-B")
    assert _run(source, tgt, "--update", "--no-arm-hooks").returncode == 0
    _bump(source, "commit-C")
    res = _run(source, tgt, "--update", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    assert f"mode:    update (was at {sha_b[:12]})" in res.stdout, res.stdout


# ── round findings (Phase 306's own round) ───────────────────────────────────

def test_a_subdirectory_target_reads_its_own_lock_not_the_repo_roots(source, tmp_path):
    """`git show HEAD:<path>` resolves from the REPOSITORY ROOT, not from `-C`'s
    directory — so a target that is a subdirectory of its repo read the ROOT's
    `.claude/sysop.lock`. That shape is supported (`validate_target` accepts it via
    `rev-parse --show-toplevel`), and the failure is worse than returning nothing:
    the installer announced a divergence that had not happened and anchored a
    rollback to a commit from a different tree. Found by this phase's round; it
    contradicted `committed_lock_field`'s own "empty, never wrong" contract.
    """
    mono = tmp_path / "mono"
    mono.mkdir()
    _git(mono, "init", "-q")
    _git(mono, "config", "user.email", "test@test")
    _git(mono, "config", "user.name", "test")
    _git(mono, "config", "commit.gpgsign", "false")
    (mono / ".claude").mkdir()
    # A foreign lock at the repo root, naming a commit that exists nowhere.
    (mono / ".claude" / "sysop.lock").write_text(
        json.dumps({"version": 1, "sysop_commit": "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
                    "packs": [], "mode": "full", "managed_paths": []}) + "\n")
    sub = mono / "sub"
    sub.mkdir()
    (sub / "README.md").write_text("# sub\n")
    _git(mono, "add", "-A")
    _git(mono, "commit", "-qm", "root lock + sub")

    assert _run(source, sub, "--packs", "python", "--no-arm-hooks").returncode == 0
    _git(mono, "add", "-A")
    _git(mono, "commit", "-qm", "install into sub")
    _bump(source, "commit-B")
    res = _run(source, sub, "--update", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "deadbeefdead" not in res.stdout + res.stderr, (
        "the root's lock leaked into the subdirectory target's anchor")
    assert WARN not in res.stdout + res.stderr, (
        "a divergence was announced that did not happen")


def test_the_unknown_sentinel_is_not_used_as_a_rollback_anchor(source, tmp_path):
    """`unknown` is `get_sysop_commit`'s sentinel for a non-git source, guarded at
    seven other sites in the file. Without it here, a tarball install that was
    committed and then updated from a git clone anchors its snapshot to the
    literal string `unknown` — a permanent commit message naming nothing, with the
    only real SHA demoted to a parenthetical. That is strictly worse than the
    pre-phase behaviour for that population, which named a real commit.
    """
    tgt = _target(tmp_path)
    assert _run(source, tgt, "--packs", "python", "--no-arm-hooks").returncode == 0
    lock = tgt / ".claude" / "sysop.lock"
    data = json.loads(lock.read_text())
    real = data["sysop_commit"]
    data["sysop_commit"] = "unknown"
    lock.write_text(json.dumps(data, indent=2) + "\n")
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "tarball-era install")
    # On-disk lock carries a real anchor; the committed one is the sentinel.
    data["sysop_commit"] = real
    lock.write_text(json.dumps(data, indent=2) + "\n")

    # A snapshot only fires when a MANAGED path is dirty, and after install+commit
    # the tree is clean — so without this edit the message assertions below never
    # run at all. Both of this module's sentinel-shaped tests were vacuous in
    # exactly that way until the round's replay measured it.
    cons = tgt / "sysop" / "scripts" / "self_check.sh"
    cons.write_text(cons.read_text() + "\n# consumer edit\n")
    _bump(source, "commit-B")
    res = _run(source, tgt, "--update", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    subject = _snapshot_subject(tgt)
    assert subject is not None, "no snapshot commit — the assertions below would be vacuous"
    assert "was at unknown" not in subject, subject
    assert real[:12] in subject, subject
    assert WARN not in res.stdout + res.stderr


def test_the_anchor_reads_HEAD_not_the_index(source, tmp_path):
    """`git show ":<path>"` reads the INDEX; `"HEAD:<path>"` reads the commit.

    Phase 306's round (guard lens) swapped one for the other and the suite stayed
    green. The two diverge on an ordinary habit: an operator who `git add`s the
    refreshed lock to look at it before committing would then have the *staged*
    value returned as "the last committed state" — which is precisely the
    distinction `Q-542` is about.
    """
    tgt, sha_a = _installed_and_committed(source, tmp_path)
    sha_b = _bump(source, "commit-B")
    assert _run(source, tgt, "--update", "--no-arm-hooks").returncode == 0
    # Stage the advanced lock without committing it: index = B, HEAD = A.
    _git(tgt, "add", ".claude/sysop.lock")
    staged = json.loads(_git_out(tgt, "show", ":.claude/sysop.lock"))["sysop_commit"]
    committed = json.loads(_git_out(tgt, "show", "HEAD:.claude/sysop.lock"))["sysop_commit"]
    assert staged == sha_b and committed == sha_a, (staged, committed)

    _bump(source, "commit-C")
    assert _run(source, tgt, "--update", "--no-arm-hooks").returncode == 0
    subject = _snapshot_subject(tgt)
    assert subject is not None, "no snapshot commit was written"
    assert subject.split("was at ")[1][:12] == sha_a[:12], (
        f"the anchor must come from HEAD ({sha_a[:12]}), not the index "
        f"({sha_b[:12]}): {subject}")


def test_a_structured_sysop_commit_is_refused_not_stringified(source, tmp_path):
    """`committed_lock_field` drops a `list`/`dict` value on purpose.

    Without that arm a lock whose `sysop_commit` is a list prints a Python repr
    straight into a permanent commit message. The round dropped it and nothing
    noticed.
    """
    tgt = _target(tmp_path)
    assert _run(source, tgt, "--packs", "python", "--no-arm-hooks").returncode == 0
    lock = tgt / ".claude" / "sysop.lock"
    data = json.loads(lock.read_text())
    real = data["sysop_commit"]
    data["sysop_commit"] = ["not", "a", "sha"]
    lock.write_text(json.dumps(data, indent=2) + "\n")
    _git(tgt, "add", "-A")
    _git(tgt, "commit", "-qm", "structured anchor")
    data["sysop_commit"] = real
    lock.write_text(json.dumps(data, indent=2) + "\n")

    cons = tgt / "sysop" / "scripts" / "self_check.sh"
    cons.write_text(cons.read_text() + "\n# consumer edit\n")
    _bump(source, "commit-B")
    res = _run(source, tgt, "--update", "--no-arm-hooks")
    assert res.returncode == 0, res.stdout + res.stderr
    subject = _snapshot_subject(tgt)
    assert subject is not None, "no snapshot commit — the assertions below would be vacuous"
    anchor = subject.split("was at ")[1]
    assert "[" not in anchor and "'" not in anchor and "not" not in anchor[:20], subject
    assert real[:12] in subject, subject
