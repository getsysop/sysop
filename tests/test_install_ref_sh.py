"""Integration tests for install.sh's ``--ref <tag>`` release-pinning (Phase 111).

``--ref`` lets a cautious consumer install/update from a reviewed *release* tag
instead of the source clone's live HEAD — the bash-path half of the supply-chain
hardening (the plugin path can't offer a consumer-side pin; see SECURITY.md).

There is no ref-establishment step in install.sh's copy path — every ``install_*``
reads ``$REPO_ROOT`` directly — so ``--ref`` materialises the rev into a temp
worktree (the ``reconstruct_old_install`` pattern) and re-points ``$REPO_ROOT`` at
it for the whole pipeline; ``get_sysop_commit`` then records the rev's commit.

These drive the *real* install.sh against a self-contained scratch **source
clone** built from the current working tree (so it captures the edits under test),
tagged at an earlier commit than its HEAD. That gap is load-bearing: a ``--ref``
install must record the *tag's* commit and ship the *tag's* content, where a plain
install records HEAD and ships HEAD — the two are asserted against each other so
the tests can't pass by accident.
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

# Isolate every git call (source-clone build AND install.sh's own worktree ops)
# from a contributor's global/system git config — mirrors the other install
# integration suites.
_GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

_SENTINEL = "PHASE111-HEAD-ONLY-SENTINEL"
TAG = "v0.1.0-test"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                   env={**os.environ, **_GIT_ISOLATION})


def _git_out(cwd, *args):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                          text=True, env={**os.environ, **_GIT_ISOLATION}).stdout.strip()


@pytest.fixture(scope="module")
def pinned_source(tmp_path_factory):
    """A scratch Sysop *source clone* with a tag one commit behind its HEAD.

    Returns (src_dir, tag_sha, head_sha). The post-tag HEAD commit appends
    ``_SENTINEL`` to a shipped doc, so a ``--ref TAG`` install (pre-sentinel) is
    distinguishable from a HEAD install (with sentinel) by content, not just sha.
    """
    src = tmp_path_factory.mktemp("sysop_src")
    # Copy the install-relevant tree from the live working tree (captures the
    # uncommitted --ref edits under test).
    shutil.copy2(REPO_ROOT / "install.sh", src / "install.sh")
    for d in ("core", "packs"):
        shutil.copytree(REPO_ROOT / d, src / d,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"))
    _git(src, "init", "-q")
    _git(src, "config", "user.email", "test@test")
    _git(src, "config", "user.name", "test")
    _git(src, "config", "commit.gpgsign", "false")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "release cut")
    _git(src, "tag", TAG)
    tag_sha = _git_out(src, "rev-parse", "HEAD")
    # A later commit that modifies shipped content — HEAD is now ahead of the tag.
    workflow = src / "core" / "companion" / "docs" / "WORKFLOW.md"
    workflow.write_text(workflow.read_text() + f"\n<!-- {_SENTINEL} -->\n")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "post-release edit")
    head_sha = _git_out(src, "rev-parse", "HEAD")
    assert tag_sha != head_sha
    return src, tag_sha, head_sha


def _seed_target(root):
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
    """Run the scratch-source install.sh; return the CompletedProcess (no assert)."""
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    env.update(_GIT_ISOLATION)
    return subprocess.run(
        ["bash", str(src / "install.sh"), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env, cwd=str(target),
    )


def _lock_commit(target):
    return json.loads((target / ".claude" / "sysop.lock").read_text())["sysop_commit"]


def _tree_has_sentinel(target):
    for p in target.rglob("*"):
        if p.is_file():
            try:
                if _SENTINEL in p.read_text():
                    return True
            except (UnicodeDecodeError, OSError):
                continue
    return False


class TestRefPinsToTag:
    def test_fresh_ref_records_tag_commit_not_head(self, pinned_source, tmp_path):
        src, tag_sha, head_sha = pinned_source
        target = _seed_target(tmp_path / "pinned")
        r = _run(src, target, "--packs", "python", "--ref", TAG)
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert "pinned to " + TAG in r.stdout
        assert _lock_commit(target) == tag_sha       # the tag's commit …
        assert _lock_commit(target) != head_sha      # … not the source HEAD
        # The fresh-install footer must point SYSOP_SRC at the real clone, not
        # the ephemeral --ref worktree (which is deleted on exit) — otherwise the
        # documented first `sysop-update.sh` fails the shim's SYSOP_SRC check.
        # (If the footer regressed to $REPO_ROOT it would print the temp worktree
        # path, not `src`, so this assertion pins the SYSOP_SRC_CLONE fallback.)
        assert f'export SYSOP_SRC="{src}"' in r.stdout

    def test_fresh_without_ref_records_head(self, pinned_source, tmp_path):
        # Control: the SAME install without --ref records HEAD. The delta between
        # this and the test above is exactly what --ref changes.
        src, tag_sha, head_sha = pinned_source
        target = _seed_target(tmp_path / "unpinned")
        r = _run(src, target, "--packs", "python")
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert _lock_commit(target) == head_sha
        assert _lock_commit(target) != tag_sha

    def test_ref_ships_content_from_the_tag_not_head(self, pinned_source, tmp_path):
        # The sentinel exists only in the post-tag HEAD commit. Pinning to the tag
        # must ship pre-sentinel content; a plain install must ship it. Proves the
        # FILES come from the ref, not merely the recorded sha.
        src, _, _ = pinned_source
        pinned = _seed_target(tmp_path / "c_pinned")
        unpinned = _seed_target(tmp_path / "c_unpinned")
        assert _run(src, pinned, "--packs", "python", "--ref", TAG).returncode == 0
        assert _run(src, unpinned, "--packs", "python").returncode == 0
        assert not _tree_has_sentinel(pinned), "pinned install leaked post-tag content"
        assert _tree_has_sentinel(unpinned), "control install missing HEAD content"

    def test_ref_accepts_a_bare_commit_sha_not_only_a_tag(self, pinned_source, tmp_path):
        # SECURITY.md and docs/install-and-update.md now lead with a commit SHA as the
        # pin to use, because the one published tag predates the sysop/ namespace and is
        # refused. Nothing exercised that path — every other case in this module passes
        # TAG — so the primary documented remedy was the untested one. Found by this
        # change's own review round, which is exactly the gap it should find.
        src, tag_sha, head_sha = pinned_source
        target = _seed_target(tmp_path / "sha_pinned")
        r = _run(src, target, "--packs", "python", "--ref", tag_sha)
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert _lock_commit(target) == tag_sha
        assert _lock_commit(target) != head_sha
        assert not _tree_has_sentinel(target), "SHA pin shipped post-ref content"

    def test_ref_accepts_an_abbreviated_commit_sha(self, pinned_source, tmp_path):
        # "a commit SHA" in the docs is what a reader copies out of `git log --oneline`,
        # which is abbreviated. The lock must still record the FULL commit.
        src, tag_sha, _ = pinned_source
        target = _seed_target(tmp_path / "short_sha_pinned")
        r = _run(src, target, "--packs", "python", "--ref", tag_sha[:8])
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert _lock_commit(target) == tag_sha


class TestRefGuards:
    def test_nonexistent_ref_fails_cleanly(self, pinned_source, tmp_path):
        src, _, _ = pinned_source
        target = _seed_target(tmp_path / "bad")
        r = _run(src, target, "--packs", "python", "--ref", "no-such-tag-xyz")
        assert r.returncode == 1
        assert "cannot resolve" in r.stderr
        assert "fetch --tags" in r.stderr
        # A failed pin writes nothing — no partial install.
        assert not (target / ".claude").exists()

    def test_ref_rejected_with_adopt(self, pinned_source, tmp_path):
        src, _, _ = pinned_source
        target = _seed_target(tmp_path / "adopt")
        r = _run(src, target, "--adopt", "--packs", "python", "--ref", TAG)
        assert r.returncode == 2
        assert "only valid for a fresh install or --update" in r.stderr

    def test_ref_requires_a_value(self, pinned_source, tmp_path):
        # A trailing `--ref` with no tag exits 2 with a clear message (not a
        # silent shift-2 failure); mirrors --accept-upstream's value guard.
        src, _, _ = pinned_source
        target = _seed_target(tmp_path / "noval")
        r = _run(src, target, "--packs", "python", "--ref")
        assert r.returncode == 2
        assert "--ref requires a tag/rev" in r.stderr
        assert not (target / ".claude").exists()

    def test_ref_rejected_with_check(self, pinned_source, tmp_path):
        src, _, _ = pinned_source
        target = _seed_target(tmp_path / "check")
        # --check would also need --source; the --ref rejection fires first
        # (arg-validation, before mode dispatch), so it exits 2 regardless.
        r = _run(src, target, "--check", "--source", str(src), "--ref", TAG)
        assert r.returncode == 2
        assert "only valid for a fresh install or --update" in r.stderr


class TestUpdateRef:
    def test_update_ref_repins_and_leaves_no_worktree(self, pinned_source, tmp_path):
        src, tag_sha, head_sha = pinned_source
        target = _seed_target(tmp_path / "upd")
        # Install tracking HEAD, then update pinned to the tag.
        assert _run(src, target, "--packs", "python").returncode == 0
        assert _lock_commit(target) == head_sha
        wt_before = _git_out(src, "worktree", "list").count("\n")

        r = _run(src, target, "--update", "--ref", TAG)
        assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
        assert "pinned to " + TAG in r.stdout
        # The update re-pinned the recorded commit back to the tag …
        assert _lock_commit(target) == tag_sha
        # … and the ref worktree + divergence shadow were cleaned (no leak).
        assert _git_out(src, "worktree", "list").count("\n") == wt_before


# --------------------------------------------------------------------------------------
# Drift guard — no advertised `--ref` value may name a concrete rev
# --------------------------------------------------------------------------------------
#
# Filed 2026-08-11 (§ High, release-state audit). Every surface that taught `--ref` pinned
# the example to `v0.1.0`, and install.sh's own Phase-128 namespace guard *hard-refuses*
# that tag: it greps the ref'd tree's own `install.sh` for `sysop/scripts`, which the
# v0.1.0 installer predates. So the one command SECURITY.md gave a security-conscious
# reader exited 1 — on the public repo — and two of the sites ship into consumer trees:
# `core/companion/scripts/sysop-update.sh` in BOTH install modes, and
# `core/companion/docs/WORKFLOW.md` as `sysop/docs/WORKFLOW.md` in full mode only
# (`install.sh:3248` skips `install_workflow_docs` under `--mode loop`).
#
# **Cutting a newer tag does not close this.** The refusal is a property of the *ref'd
# tree*, not of which tags exist, so `--ref v0.1.0` stays refused after `v0.2.0` ships.
# The durable rule is the one guarded here: a `--ref` value a reader can copy is a
# placeholder, and the published release list is the source of truth for what resolves.
#
# **The population is derived from `git ls-files`, not from a list kept here.** The first
# draft of this guard named five files by hand. Its own author-side battery then walked
# three mutations straight through it: dropping the one entry that SHIPS
# (`core/companion/docs/WORKFLOW.md`) left the guard green, because the non-vacuity check
# was derived from that same list and so could never fail. Deriving from the tree also
# widened the scanned set from 5 files to 9 — `CLAUDE.md`, `PHASE_29_HANDOFF.md`,
# `README.md` and `core/skills/release/SKILL.md` were simply missing from it.
# (`PHASE_29_HANDOFF.md` was deleted as spent by Phase 194, so the derived set is 8
# now; the count is derived from `git ls-files`, which is the point — it narrowed
# without this comment or any assertion having to be edited.) None of the
# four held a `--ref` *value*, so nothing about the fix changed; what changed is that a
# concrete pin written into any of them from now on is caught. That is this repo's
# most-repeated defect
# (`_shared/adversarial-review.md` rule 1, *where it looks*) reproduced inside a guard
# written to close an instance of it.
#
# **What it does and does not reach**, stated because a green zero-invariant proves its
# population is empty and not that the class is. It takes the whitespace-delimited token
# after `--ref` (or `--ref=`) and flags it when that token *contains* a concrete rev:
# version-shaped (`v0.1.0`, `0.1.0`, `v1`), or a hex run of 6-40 chars carrying at least
# one digit. Reading the whole token rather than anchoring at its start is deliberate —
# this change's own review round walked six bypasses through the anchored first draft:
# `--ref "v0.1.0"`, `--ref  v0.1.0` (two spaces), `--ref tags/v0.1.0`,
# `--ref sysop-v0.1.0`, `--ref=d5a288` (6-char abbrev), and `--ref ${PIN:-v0.1.0}`. That
# last one is the per-line-filter blindness this whole entry indicts the reporter for,
# reproduced inside the guard written to close it.
#
# It deliberately does NOT flag `--ref main` or `--ref stable` — those resolve, so they
# are not this class. The hex arm requires a digit so ordinary words (`defaced`,
# `decafbad`) do not false-positive.

# Maintainer-side records and this suite's own fixtures quote the historical defect on
# purpose. Nothing here reaches a consumer or a public reader as instruction.
_REF_SCAN_SKIP_PREFIXES = ("tools/", "tests/")
_REF_SCAN_SKIP_FILES = frozenset({
    "REVIEW_CHECKLIST.md", "REVIEW_ARCHIVE.md", "PHASE_LOG.md",
})

# An INDEPENDENT anchor, deliberately not derived from the scan above: if an exclusion is
# widened or the scan silently stops reading a surface, this is what goes red. Of the two
# `core/companion/` entries, only `sysop-update.sh` reaches EVERY consumer; the workflow
# docs are full-mode only (`install.sh:3248`).
_REF_MUST_BE_COVERED = frozenset({
    "install.sh",
    "SECURITY.md",
    "docs/install-and-update.md",
    "core/companion/docs/WORKFLOW.md",
    "core/companion/scripts/sysop-update.sh",
})

# The value token after `--ref` / `--ref=` — whitespace, tabs and repeats all allowed.
_REF_VALUE_RE = re.compile(r"--ref[=\s]+(\S+)")

# A concrete rev appearing ANYWHERE inside that token: `v0.1.0`, `0.1.0`, `v1`,
# `tags/v0.1.0`, `sysop-v0.1.0`, `"v0.1.0"`, `${PIN:-v0.1.0}`, `d5a288`.
_CONCRETE_REV_RE = re.compile(
    r"(?<![\w.])v?\d+\.\d+[\w.\-]*"                     # v0.1.0 / 0.1.0 / v1.2-rc1
    r"|(?<![\w.])v\d+(?![\w.])"                           # v1
    r"|(?<![\w])(?=[0-9a-f]*\d)[0-9a-f]{6,40}(?![\w])"    # abbreviated/full sha
)


def _concrete_ref_in(line):
    """The offending `--ref <concrete rev>` substring on this line, or None."""
    for m in _REF_VALUE_RE.finditer(line):
        hit = _CONCRETE_REV_RE.search(m.group(1))
        if hit:
            return f"--ref {m.group(1)}"
    return None


def _ref_teaching_lines():
    """(rel, lineno, line) for every `--ref` line on a shipped or public-doc surface."""
    # Tracked AND untracked-but-not-ignored: `git ls-files` reads the index, so a file
    # authored and not yet `git add`ed was invisible on exactly the run meant to catch it
    # (found by this change's review round).
    listed = []
    for args in (["git", "ls-files"], ["git", "ls-files", "--others", "--exclude-standard"]):
        listed += subprocess.run(
            args, cwd=str(REPO_ROOT), capture_output=True, text=True, check=True,
        ).stdout.split()
    out = []
    for rel in sorted(set(listed)):
        if rel.startswith(_REF_SCAN_SKIP_PREFIXES) or rel in _REF_SCAN_SKIP_FILES:
            continue
        try:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            # OSError covers IsADirectoryError, which is load-bearing rather than
            # incidental: `--others` reports a nested git worktree (an adversarial-review
            # round creates several) as a single DIRECTORY entry, not as its files. Named
            # here so a later narrowing to UnicodeDecodeError does not make the guard fail
            # spuriously during exactly the round that is checking it.
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if "--ref" in line:
                out.append((rel, n, line))
    return out


def test_no_advertised_ref_value_names_a_concrete_rev():
    offenders = [
        f"{rel}:{n}: {_concrete_ref_in(line)}"
        for rel, n, line in _ref_teaching_lines()
        if _concrete_ref_in(line)
    ]
    assert not offenders, (
        "A `--ref` example names a concrete rev. Use a placeholder (`<tag-or-commit>`) and "
        "point at the release list — a pinned example rots the moment the tree moves past "
        "it, and install.sh refuses a ref predating the sysop/ namespace outright:\n  "
        + "\n  ".join(offenders)
    )


def test_the_ref_scan_still_reaches_every_surface_that_must_be_covered():
    """The zero-invariant above is worthless if the scan stopped reading. Pin it."""
    seen = {rel for rel, _, _ in _ref_teaching_lines()}
    missing = _REF_MUST_BE_COVERED - seen
    assert not missing, (
        "the `--ref` scan no longer reaches these surfaces — an exclusion was widened, a "
        f"file moved, or the scan broke: {sorted(missing)}"
    )


def test_the_concrete_rev_pattern_actually_matches_the_defect_it_was_written_for():
    """Positive control — the exact strings this guard was filed against."""
    for bad in (
        # the filed defect, in the forms it actually appeared in
        "  bash install.sh ~/Projects/myapp --packs python --ref v0.1.0",
        'echo "❌ --ref requires a tag/rev (e.g. --ref=v0.1.0)" >&2',
        "bash sysop/scripts/sysop-update.sh --ref 0.1.0",
        "bash install.sh <target> --ref 1f03f9ea9b2c",
        # every bypass this change's review round walked through the first draft
        'bash install.sh <target> --ref "v0.1.0"',
        "bash install.sh <target> --ref  v0.1.0",
        "bash install.sh <target> --ref tags/v0.1.0",
        "bash install.sh <target> --ref sysop-v0.1.0",
        "bash install.sh <target> --ref=d5a288",
        "bash install.sh <target> --ref ${PIN:-v0.1.0}",
        "bash install.sh <target> --ref\tv0.1.0",
        "bash install.sh <target> --ref v1",
    ):
        assert _concrete_ref_in(bad), f"guard is blind to its own defect: {bad}"
    for ok in (
        "  bash install.sh ~/Projects/myapp --update --ref <tag-or-commit>",
        "  --ref REV             (Fresh install or --update) Pin the install to a git",
        "`--ref <tag>` (Phase 111) — pin a fresh install or `--update` to a git tag/rev",
        "`--ref <tag-or-commit>` (Phase 111) — pin a fresh install or `--update` to a rev",
        "    --ref)             # arg parsing",
        'REF_OVERRIDE="${1#--ref=}"',
        "    --ref=*)       REF_OVERRIDE=...",
        "the bash installer's `--ref` flag pins an install to any rev",
        # a moving ref is not this class: it resolves
        "bash install.sh <target> --ref main",
        "bash install.sh <target> --ref stable",
        # ordinary words that are incidentally hex-shaped carry no digit
        "bash install.sh <target> --ref defaced",
        "bash install.sh <target> --ref decafbad",
    ):
        assert not _concrete_ref_in(ok), f"guard false-positives on: {ok}"


def test_the_scan_population_includes_untracked_files(tmp_path, monkeypatch):
    """A file authored but not yet `git add`ed is exactly when the guard should fire.

    `git ls-files` reads the index, so the first draft's population went blind on the one
    run that could have stopped the pin from being committed. Found by this change's own
    review round, which authored `docs/pinning.md` with a concrete pin and watched the
    guard stay green until the file was staged.
    """
    repo = _seed_target(tmp_path / "scanrepo")
    (repo / "tracked.md").write_text("bash install.sh --ref <tag-or-commit>\n")
    _git(repo, "add", "tracked.md")
    _git(repo, "commit", "-qm", "add tracked")
    (repo / "untracked.md").write_text("bash install.sh --ref v0.1.0\n")

    # A nested git worktree — an adversarial-review round makes several — is reported by
    # `--others` as one directory entry. The scan must step over it, not die on it.
    _git(repo, "worktree", "add", "-q", "nested/wt", "-b", "probe")

    monkeypatch.setattr(sys.modules[__name__], "REPO_ROOT", repo)
    seen = {rel for rel, _, _ in _ref_teaching_lines()}
    assert "tracked.md" in seen, "the tracked half of the population broke"
    assert "untracked.md" in seen, (
        "an untracked file is invisible to the scan — a concrete pin would be missed on "
        "the very run that should catch it, before it is ever committed"
    )
