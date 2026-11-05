"""`--update`'s pre-overwrite divergence warning, and the consumer's own layer files.

The warning lists managed paths whose committed content differs from what the
OLD Sysop install wrote, rebuilt in a shadow target. Four consumer-authored files
shape managed outputs without being managed themselves — the role override
`.claude/served_models.local.yml` (skill pins), the overlays
`.claude/{convention_map,security_map}.project.md` and `.claude/checks.project.yml`
(appended or merged onto the concat outputs), and
`.claude/substitutions.project.yml` (tokens in `checks.yml`). A shadow built
without the layers that produced the committed content reports that content as a
local edit "that will be lost", which it is not:

- `Q-622`: an override added after the last install. The shadow was seeded with the
  CURRENT override, the committed skills were resolved before it existed.
- `Q-055`: an overlay, or a substitutions file, already applied by an earlier
  update. The shadow was seeded with neither, so the warning repeated on every
  update.

The fix compares each committed path with the old install built from the current
layer files and, when that differs, with the one built from the layer files as
committed at the commit that last changed the path. These tests pin both halves:
no warning for content the consumer's layers produced, and a warning for every
hand edit, in each layer state.

They drive the real `install.sh` from a scratch source clone, never from this
checkout: `reconstruct_old_install` registers temporary worktrees in the source
repo, and a crashed case would leave one in the live repo's `.git`.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[1]

_GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}

WARN = "carry committed local edits"
CLEAN = "no committed local edits detected"
AUTO_BUILD = ".claude/skills/auto-build/SKILL.md"
CLAIM_TASK = ".claude/skills/claim-task/SKILL.md"
CONV_MAP = ".claude/convention_map.md"
CHECKS = ".claude/checks.yml"
EXEC_PIN = '`model`: `"{m}"`, `effort`: `"high"` <!-- sysop:role=executor -->'


def _env(**extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    env.update(_GIT_ISOLATION)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.update(extra)
    return env


def _git(cwd, *args, env=None):
    return subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True,
                          text=True, env=env or _env()).stdout.strip()


def _identity(repo):
    _git(repo, "config", "user.email", "test@test")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "commit.gpgsign", "false")


def _commit(repo, msg):
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", msg, "--allow-empty")


def _run(src, target, *extra, env=None):
    res = subprocess.run(
        ["bash", str(src / "install.sh"), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env or _env(), cwd=str(target),
        stdin=subprocess.DEVNULL, timeout=900,
    )
    return res, res.stdout + res.stderr


def _update(src, target, *extra, env=None):
    res, out = _run(src, target, "--update", *extra, env=env)
    assert res.returncode == 0, out
    return out


def _listed(out):
    """The paths the warning block lists, in its `<path>  (+A / -R vs old Sysop install)` grammar."""
    return re.findall(r"^\s*\S+\s+(\S+)\s+\(\+\d+ / -\d+ vs old Sysop install\)$", out, re.M)


def _write(target, rel, text):
    p = target / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _sub(target, rel, old, new):
    p = target / rel
    body = p.read_text()
    assert old in body, (rel, old)
    p.write_text(body.replace(old, new, 1))


OVERRIDE = "roles:\n  executor: haiku\n"
OVERLAY = "## Project section\n\n- local rule one\n"
SUBS = 'substitutions:\n  "<api module>": "app"\n'


@pytest.fixture(scope="module")
def pristine(tmp_path_factory):
    """A committed scratch source, and a target installed from it and committed."""
    base = tmp_path_factory.mktemp("divergence")
    src = base / "src"
    src.mkdir()
    shutil.copy2(REPO_ROOT / "install.sh", src / "install.sh")
    for d in ("core", "packs"):
        shutil.copytree(REPO_ROOT / d, src / d,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"))
    _git(src, "init", "-q", "-b", "main")
    _identity(src)
    _commit(src, "source")

    tgt = base / "tgt"
    tgt.mkdir()
    _git(tgt, "init", "-q", "-b", "main")
    _identity(tgt)
    (tgt / "README.md").write_text("# scratch\n")
    _commit(tgt, "seed")
    res, out = _run(src, tgt, "--packs", "python", "--no-arm-hooks")
    assert res.returncode == 0, out
    _commit(tgt, "installed")
    return src, tgt


def _worktrees(repo):
    return [ln for ln in _git(repo, "worktree", "list", "--porcelain").splitlines()
            if ln.startswith("worktree ")]


@pytest.fixture
def setup(pristine, tmp_path):
    """Per-test copies of the source and the installed target. Asserts afterwards that
    no run left a temporary worktree registered in the source."""
    src0, tgt0 = pristine
    src = tmp_path / "src"
    subprocess.run(["git", "clone", "-q", str(src0), str(src)], check=True,
                   capture_output=True, env=_env())
    _identity(src)
    tgt = tmp_path / "tgt"
    shutil.copytree(tgt0, tgt, symlinks=True)
    yield src, tgt
    left = _worktrees(src)[1:]
    for line in left:
        subprocess.run(["git", "-C", str(src), "worktree", "remove", "--force",
                        line[len("worktree "):]], capture_output=True, env=_env())
    assert not left, left


def _steady(src, tgt, rel, text):
    """Add a layer file, apply it with an update, commit — the state after one update.
    (That update's own report is `Q-622`'s case, asserted by its own test, not here.)"""
    _write(tgt, rel, text)
    _commit(tgt, f"add {rel}")
    _update(src, tgt)
    _commit(tgt, "update applying the layer")


# --- no warning for content the consumer's own layers produced (red at the base) -------

def test_an_override_added_after_the_install_is_not_reported(setup):
    """`Q-622` as filed: install, commit, add an override that moves pins, commit, update."""
    src, tgt = setup
    _write(tgt, ".claude/served_models.local.yml", OVERRIDE)
    _commit(tgt, "override")
    out = _update(src, tgt)
    assert WARN not in out and _listed(out) == [], out
    assert CLEAN in out, out
    # The update does apply it — the warning was the only thing wrong.
    assert EXEC_PIN.format(m="haiku") in (tgt / AUTO_BUILD).read_text()


def test_the_same_sequence_under_dry_run_is_not_reported(setup):
    src, tgt = setup
    _write(tgt, ".claude/served_models.local.yml", OVERRIDE)
    _commit(tgt, "override")
    out = _update(src, tgt, "--dry-run")
    assert WARN not in out and _listed(out) == [], out
    assert CLEAN in out, out


def test_an_override_removed_since_the_install_is_not_reported(setup):
    """Committed skills were resolved with an override that is gone now: the current
    layers do not reproduce them, the layers at their last commit do."""
    src, tgt = setup
    _steady(src, tgt, ".claude/served_models.local.yml", OVERRIDE)
    (tgt / ".claude/served_models.local.yml").unlink()
    _commit(tgt, "drop the override")
    out = _update(src, tgt)
    assert WARN not in out and _listed(out) == [], out
    assert EXEC_PIN.format(m="sonnet") in (tgt / AUTO_BUILD).read_text()


def test_an_overlay_already_applied_is_not_reported_again(setup):
    """`Q-055`'s permanent case: the committed base map already carries the overlay."""
    src, tgt = setup
    _steady(src, tgt, ".claude/convention_map.project.md", OVERLAY)
    assert "- local rule one" in (tgt / CONV_MAP).read_text()
    out = _update(src, tgt)
    assert WARN not in out and _listed(out) == [], out
    assert _git(tgt, "status", "--porcelain") == "", out


def test_applied_substitutions_are_not_reported_again(setup):
    """`Q-055`'s second route: a substituted checks.yml against an unsubstituted shadow."""
    src, tgt = setup
    _steady(src, tgt, ".claude/substitutions.project.yml", SUBS)
    assert '"app/"' in (tgt / CHECKS).read_text()
    out = _update(src, tgt)
    assert WARN not in out and _listed(out) == [], out


def test_a_live_override_is_applied_in_the_shadow_when_pyyaml_is_only_in_the_venv(setup, tmp_path):
    """The shadow has no venv, so the old installer looked for PyYAML on PATH only. On a
    host whose `python3` lacks it (the case `pick_python_with_yaml` reads the venv for),
    the shadow kept the default pins and every update reported each overridden skill."""
    src, tgt = setup
    os.symlink(sys.prefix, tgt / ".venv")
    with open(tgt / ".git" / "info" / "exclude", "a") as fh:
        fh.write(".venv\n")
    shim = tmp_path / "noyaml"
    shim.mkdir()
    # `-S`: no site-packages, so no PyYAML; the stdlib the installer needs stays.
    (shim / "python3").write_text(f'#!/bin/sh\nexec "{sys.executable}" -S "$@"\n')
    (shim / "python3").chmod(0o755)
    env = _env()
    env["PATH"] = f"{shim}{os.pathsep}{os.environ['PATH']}"
    assert subprocess.run(["python3", "-c", "import yaml"], env=env,
                          capture_output=True).returncode != 0
    _write(tgt, ".claude/served_models.local.yml", OVERRIDE)
    _commit(tgt, "override")
    out = _update(src, tgt, env=env)
    assert WARN not in out, out
    assert EXEC_PIN.format(m="haiku") in (tgt / AUTO_BUILD).read_text(), out
    _commit(tgt, "apply")
    out = _update(src, tgt, env=env)
    assert WARN not in out and _listed(out) == [], out


def test_a_hand_edit_in_a_subdirectory_target_is_reported(pristine, tmp_path):
    """A bare `HEAD:<path>` resolves from the repository root, so a target that is a
    subdirectory of its repo found none of its managed paths and never warned."""
    src0, _ = pristine
    src = tmp_path / "src"
    subprocess.run(["git", "clone", "-q", str(src0), str(src)], check=True,
                   capture_output=True, env=_env())
    repo = tmp_path / "mono"
    tgt = repo / "svc"
    tgt.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _identity(repo)
    (tgt / "README.md").write_text("# svc\n")
    _commit(repo, "seed")
    res, out = _run(src, tgt, "--packs", "python", "--no-arm-hooks")
    assert res.returncode == 0, out
    _commit(repo, "installed")
    try:
        _sub(tgt, AUTO_BUILD, EXEC_PIN.format(m="sonnet"), EXEC_PIN.format(m="opus"))
        _commit(repo, "hand edit")
        out = _update(src, tgt)
        assert _listed(out) == [AUTO_BUILD], out
        assert "show HEAD:./<path>" in out, out
    finally:
        left = _worktrees(src)[1:]
        for line in left:
            subprocess.run(["git", "-C", str(src), "worktree", "remove", "--force",
                            line[len("worktree "):]], capture_output=True, env=_env())
        assert not left, left


# --- every hand edit is still reported (boundary pins) ---------------------------------

def test_a_consumer_with_no_layers_keeps_todays_report(setup):
    src, tgt = setup
    out = _update(src, tgt)
    assert CLEAN in out and WARN not in out, out
    _sub(tgt, AUTO_BUILD, EXEC_PIN.format(m="sonnet"), EXEC_PIN.format(m="opus"))
    _commit(tgt, "hand edit")
    out = _update(src, tgt)
    assert _listed(out) == [AUTO_BUILD], out
    assert f"{AUTO_BUILD}  (+1 / -1 vs old Sysop install)" in out, out
    assert "1 managed path(s) carry committed local edits" in out, out


def test_an_override_present_at_the_install_and_still_present_is_not_reported(setup):
    src, tgt = setup
    _steady(src, tgt, ".claude/served_models.local.yml", OVERRIDE)
    out = _update(src, tgt)
    assert WARN not in out and _listed(out) == [], out


def test_a_hand_edited_pin_under_a_live_override_is_reported(setup):
    src, tgt = setup
    _steady(src, tgt, ".claude/served_models.local.yml", OVERRIDE)
    _sub(tgt, CLAIM_TASK, EXEC_PIN.format(m="haiku"), EXEC_PIN.format(m="opus"))
    _commit(tgt, "hand edit")
    out = _update(src, tgt)
    assert _listed(out) == [CLAIM_TASK], out
    assert f"{CLAIM_TASK}  (+1 / -1 vs old Sysop install)" in out, out


def test_a_pin_hand_edited_back_to_the_default_under_a_tracked_override_is_reported(setup):
    """The hole a "matches the layerless build" rule would open: the edit reproduces the
    default output, and the update would silently re-resolve it to the override. The
    layers at the edit's own commit include the override, so it is reported."""
    src, tgt = setup
    _steady(src, tgt, ".claude/served_models.local.yml", OVERRIDE)
    _sub(tgt, AUTO_BUILD, EXEC_PIN.format(m="haiku"), EXEC_PIN.format(m="sonnet"))
    _commit(tgt, "hand edit back to the default")
    out = _update(src, tgt)
    assert _listed(out) == [AUTO_BUILD], out


def test_a_hand_edit_after_an_override_was_added_but_not_applied_is_reported(setup):
    """`Q-622`'s window: the override is committed, no update has applied it, and a pin
    is hand-edited to a third model. It matches neither the current layers' build nor
    the layerless one it was written from."""
    src, tgt = setup
    _write(tgt, ".claude/served_models.local.yml", OVERRIDE)
    _commit(tgt, "override")
    _sub(tgt, AUTO_BUILD, EXEC_PIN.format(m="sonnet"), EXEC_PIN.format(m="opus"))
    _commit(tgt, "hand edit")
    out = _update(src, tgt)
    assert _listed(out) == [AUTO_BUILD], out


def test_a_hand_edit_to_the_base_map_beside_an_overlay_is_reported(setup):
    src, tgt = setup
    _steady(src, tgt, ".claude/convention_map.project.md", OVERLAY)
    p = tgt / CONV_MAP
    p.write_text(p.read_text().replace("\n## ", "\n- a hand-added rule\n\n## ", 1))
    _commit(tgt, "hand edit")
    out = _update(src, tgt)
    assert _listed(out) == [CONV_MAP], out
    assert f"{CONV_MAP}  (+2 / -0 vs old Sysop install)" in out, out


def test_a_hand_edit_to_checks_beside_substitutions_is_reported(setup):
    src, tgt = setup
    _steady(src, tgt, ".claude/substitutions.project.yml", SUBS)
    _sub(tgt, CHECKS, '"app/"', '"handwritten/"')
    _commit(tgt, "hand edit")
    out = _update(src, tgt)
    assert _listed(out) == [CHECKS], out


def test_the_first_update_after_a_dual_write_still_reports_the_base_map_once(setup):
    """Out of scope, pinned so the choice is visible: a promotion written to the base map
    in place AND to its overlay differs from both builds (the update relocates it to the
    appended region), so that one update reports it. The next one does not."""
    src, tgt = setup
    _steady(src, tgt, ".claude/convention_map.project.md", OVERLAY)
    section = "## Promoted rule\n\n- promoted in a review\n"
    p = tgt / CONV_MAP
    p.write_text(p.read_text().replace("\n## ", "\n" + section + "\n## ", 1))
    _write(tgt, ".claude/convention_map.project.md", OVERLAY + "\n" + section)
    _commit(tgt, "dual-write")
    out = _update(src, tgt)
    assert _listed(out) == [CONV_MAP], out
    _commit(tgt, "update relocating the promotion")
    out = _update(src, tgt)
    assert WARN not in out and _listed(out) == [], out


def test_copy_file_preservation_is_unchanged_with_layers_present(setup):
    """DIVERGENCE_SHADOW still drives sysop/scripts preservation; the layered shadows
    are read by the warning alone."""
    src, tgt = setup
    rel = "sysop/scripts/self_check.sh"
    p = tgt / rel
    p.write_text(p.read_text() + "\n# consumer tweak\n")
    _commit(tgt, "edit a managed script")
    _write(tgt, ".claude/convention_map.project.md", OVERLAY)
    _write(tgt, ".claude/served_models.local.yml", OVERRIDE)
    _commit(tgt, "layers")
    out = _update(src, tgt)
    assert f"⚠ preserved: {rel}" in out, out
    assert p.read_text().endswith("# consumer tweak\n")
    assert _listed(out) == [rel], out


def _untracked_override(tgt):
    with open(tgt / ".git" / "info" / "exclude", "a") as fh:
        fh.write(".claude/served_models.local.yml\n")
    _write(tgt, ".claude/served_models.local.yml", OVERRIDE)


def test_a_pin_edited_back_to_the_default_under_an_untracked_override_is_reported(setup):
    """An override that was never committed is invisible at every commit, so the anchor
    takes it as in effect throughout. Read as absent, the edit (the skill's only pin put
    back to the default) would match the layerless build and the update would
    re-resolve it to the override without a word."""
    src, tgt = setup
    _untracked_override(tgt)
    _update(src, tgt)
    _commit(tgt, "update applying an untracked override")
    _sub(tgt, AUTO_BUILD, EXEC_PIN.format(m="haiku"), EXEC_PIN.format(m="sonnet"))
    _commit(tgt, "hand edit back to the default")
    out = _update(src, tgt)
    assert _listed(out) == [AUTO_BUILD], out


def test_an_untracked_override_added_after_the_install_is_still_reported_once(setup):
    """The cost of the rule above, pinned so it is visible: with no commit to anchor an
    untracked override, its first update reports the skills it moves, as before this
    fix. Committing the override (the documented path) avoids it."""
    src, tgt = setup
    _untracked_override(tgt)
    out = _update(src, tgt)
    assert sorted(_listed(out)) == sorted([AUTO_BUILD, CLAIM_TASK]), out
    _commit(tgt, "update applying it")
    out = _update(src, tgt)
    assert WARN not in out and _listed(out) == [], out


# --- structure ------------------------------------------------------------------------

def test_the_layer_list_names_every_file_the_installer_layers_onto_a_managed_output():
    body = (REPO_ROOT / "install.sh").read_text()
    block = body[body.index("SYSOP_LAYER_FILES=("):]
    block = block[:block.index("\n)\n")]
    subs = re.search(r'^SYSOP_SUBSTITUTIONS_FILE="([^"]+)"', body, re.M).group(1)
    listed = {subs if x == "$SYSOP_SUBSTITUTIONS_FILE" else x
              for x in re.findall(r'"([^"]+)"', block)}
    suffixes = body[body.index("declare -A SYSOP_PROJECT_SUFFIXES=("):]
    suffixes = suffixes[:suffixes.index("\n)\n")]
    overlays = set(re.findall(r'\]="([^"]+)"', suffixes))
    assert len(overlays) == 3, overlays
    assert listed == overlays | {subs, ".claude/served_models.local.yml"}, listed


def test_the_layered_scratch_is_cleaned_by_the_exit_trap():
    body = (REPO_ROOT / "install.sh").read_text()
    trap = body[body.index("_cleanup_install_temp() {"):]
    trap = trap[:trap.index("\n}\n")]
    assert 'rm -rf "$DIVERGENCE_LAYER_TMP"' in trap


def test_outputs_committed_before_their_changed_overlay_are_not_reported(setup):
    """The current-layers half of the comparison. The overlay changes, an update applies
    it, and only the regenerated map is committed. The map's last commit then holds the
    OLD overlay, so its anchored shadow differs. Only the shadow built from the layers
    as they stand reproduces the map. The author-side battery's A02 survived without
    this case (Phase 464)."""
    src, tgt = setup
    _steady(src, tgt, ".claude/convention_map.project.md", OVERLAY)
    _write(tgt, ".claude/convention_map.project.md", OVERLAY + "- local rule two\n")
    _update(src, tgt)
    assert "- local rule two" in (tgt / CONV_MAP).read_text()
    _git(tgt, "add", "--", CONV_MAP)
    _git(tgt, "commit", "-qm", "the regenerated map, without its overlay")
    out = _update(src, tgt)
    assert WARN not in out and _listed(out) == [], out


# --- the round's cases (Phase 464) -----------------------------------------------------

NOTE_FALLBACK = "could not rebuild the old install with your .claude layer files"


def test_an_untracked_override_reaches_an_anchor_whose_tracked_layers_changed(setup):
    """The untracked override must be seeded into an ANCHORED build too, not only the
    current one. The overlay changes after the edit, so the edit's anchor is a layer set
    of its own; read without the override, it would match the pin put back to the default
    and hide the edit."""
    src, tgt = setup
    _write(tgt, ".claude/convention_map.project.md", OVERLAY)
    _commit(tgt, "overlay")
    _untracked_override(tgt)
    _update(src, tgt)
    _commit(tgt, "update applying both")
    _sub(tgt, AUTO_BUILD, EXEC_PIN.format(m="haiku"), EXEC_PIN.format(m="sonnet"))
    _commit(tgt, "hand edit back to the default")
    _write(tgt, ".claude/convention_map.project.md", OVERLAY + "- local rule two\n")
    _commit(tgt, "overlay changed after the edit")
    out = _update(src, tgt)
    assert AUTO_BUILD in _listed(out), out


def test_a_failed_anchored_build_falls_back_and_the_update_finishes(setup):
    """A layer set that cannot be rebuilt (here a substitutions file that was malformed
    at the edit's commit and fixed since) must not stop the update. The comparison says
    so once and falls back, and the edit is still reported."""
    src, tgt = setup
    _write(tgt, ".claude/substitutions.project.yml", "substitutions: [unclosed\n")
    _sub(tgt, AUTO_BUILD, EXEC_PIN.format(m="sonnet"), EXEC_PIN.format(m="opus"))
    _commit(tgt, "a hand edit beside a malformed substitutions file")
    _write(tgt, ".claude/substitutions.project.yml", SUBS)
    _commit(tgt, "fix the substitutions file")
    res, out = _run(src, tgt, "--update")
    assert res.returncode == 0, out
    assert NOTE_FALLBACK in out, out
    assert AUTO_BUILD in _listed(out), out


def test_a_symlinked_layer_is_not_rebuilt_from_its_link_text(setup):
    """A committed symlink is a blob holding the target path. Rebuilding the anchor from
    it seeded the path string as the overlay. The anchored build is now refused and
    said so, and the count is taken against the current-layers build."""
    src, tgt = setup
    shared = tgt / "shared"
    shared.mkdir()
    (shared / "ov.md").write_text(OVERLAY)
    os.symlink("../shared/ov.md", tgt / ".claude/convention_map.project.md")
    _commit(tgt, "a symlinked overlay")
    _update(src, tgt)
    _commit(tgt, "update applying it")
    (shared / "ov.md").write_text(OVERLAY + "- local rule two\n")
    _commit(tgt, "the link's target changed, not applied")
    out = _update(src, tgt)
    assert NOTE_FALLBACK in out, out
    assert "../shared/ov.md" not in (tgt / CONV_MAP).read_text()
