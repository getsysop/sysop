"""A pin carrying a per-pin `sysop:role=` marker is managed, in a file with no file marker (`Q-700`).

`review-close/steps/4a-fix.md` is such a file: a step file has no frontmatter, so it carries
no `sysop:model-roles` marker, and the resolver rewrites its pin anyway. Four sites judged
"managed" by the file marker alone: `find_role_violations(managed_only=True)` (the update's
gate), `check_skill_models.py`'s population count and `--defaults` table, and
`resolve_skill_models.py`'s refusal. A hand edit of the step file's pin passed the gate, and
a role whose only pin sits in a step file would have passed it under any mapping.

A per-pin marker hands over its own pin and nothing else (`managed_pins`): round 1's execution
lens showed that counting the whole file as managed refused a consumer's entire local override
over an unmarked pin of its own, in a skill that had copied one marked line from Sysop.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
CONFIG = REPO_ROOT / "core" / "companion" / ".claude" / "served_models.yml"
SKILLS = REPO_ROOT / "core" / "skills"
STEP = Path("review-close") / "steps" / "4a-fix.md"

sys.path.insert(0, str(SCRIPTS))
import check_skill_models as c  # noqa: E402
import resolve_skill_models as r  # noqa: E402

MANAGED = ('---\nmodel: opus\n---\n<!-- sysop:model-roles frontmatter=reasoning -->\n')
# The shape `review-close/steps/4a-fix.md` carries: an inline pin, a per-pin marker, no file marker.
STEP_PIN = ('   - `model: "sonnet"`, `effort: "high"` (the gate) <!-- sysop:role={role} -->\n')
CFG = ("roles:\n  reasoning: opus\n  security-gate: sonnet\n  executor: sonnet\n"
       "served:\n  - opus\n  - sonnet\ninline_models:\n  - opus\n  - sonnet\n")


def _tree(tmp_path: Path, step_role: str = "security-gate") -> Path:
    root = tmp_path / "skills"
    (root / "s" / "steps").mkdir(parents=True)
    (root / "s" / "SKILL.md").write_text(MANAGED)
    (root / "s" / "steps" / "twin.md").write_text("# step\n" + STEP_PIN.format(role=step_role))
    return root


def _cfg(tmp_path: Path, text: str = CFG) -> Path:
    p = tmp_path / "served_models.yml"
    p.write_text(text)
    return p


# A consumer skill that copied one marked line from a Sysop skill beside a pin of its own.
MIXED = ('# mine\n\n`model`: `"opus"`, `effort`: `"high"` <!-- sysop:role={role} -->\n'
         'Then my own reviewer with `model: "best"`.\n')


def test_the_helper_owns_the_file_under_a_file_marker_and_the_pin_under_a_pin_marker():
    from _model_roles import managed_pins
    assert [p.role for p in managed_pins(MANAGED)] == ["reasoning"]
    assert [p.role for p in managed_pins(STEP_PIN.format(role="executor"))] == ["executor"]
    assert [(p.lineno, p.role) for p in managed_pins(MIXED.format(role="reasoning"))] == [(3, "reasoning")]
    assert managed_pins('---\nmodel: opus\n---\nSpawn with `model: "best"`.\n') == []
    # Under a file marker an unmarked pin is Sysop's, and an error.
    assert [p.role for p in managed_pins(MANAGED + 'Spawn with `model: "best"`.\n')] == ["reasoning", None]


def test_a_hand_edited_step_file_pin_fails_the_gate(tmp_path):
    """The entry's own repro, on a copy of the shipped tree."""
    root = tmp_path / "skills"
    shutil.copytree(SKILLS, root)
    step = root / STEP
    text = step.read_text()
    assert text.count('`model: "sonnet"`') == 1, "the step file's pin moved; re-point this test"
    step.write_text(text.replace('`model: "sonnet"`', '`model: "best"`'))
    assert c.main(["--root", str(root), "--config", str(CONFIG), "--managed-only"]) == 1
    # The vacuity control: the same tree unedited passes.
    step.write_text(text)
    assert c.main(["--root", str(root), "--config", str(CONFIG), "--managed-only"]) == 0


def test_a_role_pinned_only_in_a_step_file_is_judged(tmp_path, capsys):
    """Phase 404's case: the role's only pin moves into a step file, and a mapping refuses it."""
    root = _tree(tmp_path)
    cfg = _cfg(tmp_path)
    assert c.main(["--root", str(root), "--config", str(cfg), "--managed-only"]) == 0
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  security-gate: haiku\n")  # not served
    capsys.readouterr()
    rc = c.main(["--root", str(root), "--config", str(cfg), "--local", str(local),
                 "--managed-only"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "twin.md" in out and "security-gate" in out


def test_a_tree_whose_only_pins_are_per_pin_marked_is_not_empty(tmp_path, capsys):
    """The population count: before, `--managed-only` called this tree empty (exit 2)."""
    root = tmp_path / "skills"
    (root / "s" / "steps").mkdir(parents=True)
    (root / "s" / "steps" / "twin.md").write_text(STEP_PIN.format(role="security-gate"))
    rc = c.main(["--root", str(root), "--config", str(_cfg(tmp_path)), "--managed-only"])
    assert rc == 0, capsys.readouterr()


def test_a_consumer_skill_with_no_marker_stays_out_of_scope(tmp_path):
    """The reason `--managed-only` exists: a consumer's own skill is not Sysop's to judge."""
    root = _tree(tmp_path)
    own = root / "mine"
    own.mkdir()
    # Naming Sysop's marker syntax in prose is not carrying a marker.
    (own / "SKILL.md").write_text('---\nmodel: best\n---\nSpawn with `model: "best"`; Sysop '
                                  'files use sysop:role markers, this one does not.\n')
    cfg = _cfg(tmp_path)
    assert c.main(["--root", str(root), "--config", str(cfg), "--managed-only"]) == 0
    # The vacuity control: the full check does judge it.
    assert c.main(["--root", str(root), "--config", str(cfg)]) == 1


# Round 2, lens D: a real skill has frontmatter, and round 1's fixtures had none.
@pytest.mark.parametrize("head", ["", "---\nname: mine\nmodel: best\n---\n"],
                         ids=["no-frontmatter", "frontmatter"])
def test_a_consumer_skill_with_one_copied_marker_keeps_its_own_pins(tmp_path, capsys, head):
    """Round 1's repro: the unmarked pin is the consumer's, and the override still applies."""
    root = _tree(tmp_path)
    own = root / "mine" / "SKILL.md"
    own.parent.mkdir()
    own.write_text(head + MIXED.format(role="reasoning"))
    line = 3 + head.count("\n")
    cfg = _cfg(tmp_path)
    assert c.main(["--root", str(root), "--config", str(cfg), "--managed-only"]) == 0
    assert r.main(["--root", str(root), "--config", str(cfg), "--apply"]) == 0
    assert 'Then my own reviewer with `model: "best"`.' in own.read_text()
    # The vacuity control: its marked pin is still judged.
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  reasoning: haiku\n")  # not served
    capsys.readouterr()
    assert c.main(["--root", str(root), "--config", str(cfg), "--local", str(local),
                   "--managed-only"]) == 1
    assert f"mine/SKILL.md:{line}" in capsys.readouterr().out


def test_every_marked_line_in_a_marker_less_file_is_judged(tmp_path, capsys):
    """Round 2, lens D: every fixture had one marker; Phase 404's step file is where two meet."""
    from _model_roles import managed_pins
    root = _tree(tmp_path)
    twin = root / "s" / "steps" / "twin.md"
    twin.write_text(twin.read_text() + STEP_PIN.format(role="executor"))
    assert [p.role for p in managed_pins(twin.read_text())] == ["security-gate", "executor"]
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  executor: haiku\n")  # not served
    rc = c.main(["--root", str(root), "--config", str(_cfg(tmp_path)), "--local", str(local),
                 "--managed-only"])
    assert rc == 1 and "twin.md:3" in capsys.readouterr().out


def test_defaults_does_not_fail_over_a_consumers_unmarked_skill(tmp_path):
    """Round 2, lens D: `--defaults` reports the gate's verdict, which a consumer skill is
    outside of; the full check would have failed on this tree."""
    root = _tree(tmp_path)
    (root / "mine").mkdir()
    (root / "mine" / "SKILL.md").write_text('# mine\nSpawn with `model: "best"`.\n')
    p = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_skill_models.py"), "--defaults",
         "--config", str(CONFIG), "--root", str(root)],
        capture_output=True, text=True,
    )
    assert p.returncode == 0 and "check fails here" not in p.stdout, p.stdout + p.stderr


def test_the_resolver_refuses_an_unmarked_pin_under_a_file_marker(tmp_path, capsys):
    """Round 2, lens D: the refusal's file-marker half, at the site the phase rewrote."""
    root = _tree(tmp_path)
    skill = root / "s" / "SKILL.md"
    skill.write_text(MANAGED + 'Spawn with `model: "sonnet"`.\n')
    before = skill.read_text()
    cfg = _cfg(tmp_path, CFG.replace("reasoning: opus", "reasoning: sonnet"))
    assert r.main(["--root", str(root), "--config", str(cfg), "--apply"]) == 1
    assert "s/SKILL.md:5" in capsys.readouterr().err
    assert skill.read_text() == before


def test_the_resolver_refuses_an_undefined_role_in_a_step_file(tmp_path, capsys):
    """Before, the resolver rewrote the managed pins and left this one: a half-applied tree."""
    root = _tree(tmp_path, step_role="bogus")
    skill = root / "s" / "SKILL.md"
    before = skill.read_text()
    cfg = _cfg(tmp_path, CFG.replace("reasoning: opus", "reasoning: sonnet"))
    rc = r.main(["--root", str(root), "--config", str(cfg), "--apply"])
    err = capsys.readouterr().err
    assert rc == 1
    assert "twin.md" in err and "bogus" in err
    assert skill.read_text() == before, "the resolver wrote with a refused pin in the tree"


def test_defaults_shows_a_role_pinned_only_in_a_step_file(tmp_path):
    root = _tree(tmp_path)
    p = subprocess.run(
        [sys.executable, str(SCRIPTS / "check_skill_models.py"), "--defaults",
         "--config", str(CONFIG), "--root", str(root)],
        capture_output=True, text=True,
    )
    assert p.returncode == 0, p.stdout + p.stderr
    rows = [ln.split()[0] for ln in p.stdout.splitlines() if ln.startswith("  ") and ln.split()]
    assert "security-gate" in rows, p.stdout


def _aged_scripts(tmp_path: Path) -> Path:
    """The scripts beside a `_model_roles.py` from before `Q-700`: no helper, file marker only."""
    scripts = tmp_path / "scripts"
    shutil.copytree(SCRIPTS, scripts)
    mr = scripts / "_model_roles.py"
    text = mr.read_text()
    start = text.index("def managed_pins(")
    # The def ends at the first non-blank line that is not indented, however its body is written.
    lines = text[start:].splitlines(keepends=True)
    end = start + sum(len(ln) for ln in lines[:next(
        i for i, ln in enumerate(lines[1:], 1) if ln.strip() and not ln.startswith((" ", "\t")))])
    site = "        for r in (managed_pins(text) if managed_only else analyze_text(text)):"
    assert text.count(site) == 1, "the gate's call site moved; re-point this aging"
    mr.write_text((text[:start] + text[end:]).replace(site, (
        "        if managed_only and _FILE_MARKER_RE.search(text) is None:\n"
        "            continue\n"
        "        for r in analyze_text(text):")))
    assert "managed_pins(" not in mr.read_text(), "the aging left a call to the helper"
    return scripts


def _run(scripts: Path, script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(scripts / script), *args],
                          capture_output=True, text=True)


def test_a_preserved_model_roles_without_the_helper_still_starts(tmp_path):
    """A consumer's preserved `_model_roles.py` from before `Q-700` keeps the gate starting."""
    scripts = _aged_scripts(tmp_path)
    for script, extra in (("check_skill_models.py", ["--managed-only"]),
                          ("resolve_skill_models.py", [])):
        p = _run(scripts, script, "--root", str(SKILLS), "--config", str(CONFIG), *extra)
        assert p.returncode == 0, f"{script}: {p.stdout}{p.stderr}"
        assert "Traceback" not in p.stderr


def test_the_fallback_judges_the_file_marker_as_it_did(tmp_path):
    """What the fallbacks decide, not only that they start: a consumer's unmarked skill is out
    of scope for both scripts, and a file-marked pin with an undefined role is refused."""
    scripts = _aged_scripts(tmp_path / "a")
    root = tmp_path / "skills"
    (root / "s").mkdir(parents=True)
    (root / "s" / "SKILL.md").write_text(MANAGED)
    (root / "mine").mkdir()
    (root / "mine" / "SKILL.md").write_text('# mine\nSpawn with `model: "best"`.\n')
    cfg = _cfg(tmp_path)
    assert _run(scripts, "check_skill_models.py", "--root", str(root), "--config", str(cfg),
                "--managed-only").returncode == 0
    assert _run(scripts, "resolve_skill_models.py", "--root", str(root), "--config", str(cfg),
                "--apply").returncode == 0
    # The checker's fallback feeds its population count: a tree holding only the consumer's
    # skill has no Sysop pins, which the gate reports as an empty tree, not as a pass.
    alone = tmp_path / "alone"
    shutil.copytree(root / "mine", alone / "mine")
    assert _run(scripts, "check_skill_models.py", "--root", str(alone), "--config", str(cfg),
                "--managed-only").returncode == 2
    (root / "s" / "SKILL.md").write_text(MANAGED.replace("frontmatter=reasoning", "frontmatter=bogus"))
    p = _run(scripts, "resolve_skill_models.py", "--root", str(root), "--config", str(cfg), "--apply")
    assert p.returncode == 1 and "bogus" in p.stderr, p.stdout + p.stderr


def test_the_fallback_judges_a_step_files_only_pin(tmp_path):
    """Round 2, lens C: under a preserved module, a role whose only pin sits in a marker-less
    step file was passed by the gate under any mapping, and the update reported APPLIED."""
    scripts = _aged_scripts(tmp_path / "a")
    root = tmp_path / "skills"
    (root / "s" / "steps").mkdir(parents=True)
    (root / "s" / "steps" / "twin.md").write_text(STEP_PIN.format(role="security-gate"))
    cfg = _cfg(tmp_path)
    base = ["--root", str(root), "--config", str(cfg), "--managed-only"]
    assert _run(scripts, "check_skill_models.py", *base).returncode == 0
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  security-gate: haiku\n")  # not served
    p = _run(scripts, "check_skill_models.py", *base, "--local", str(local))
    assert p.returncode == 1 and "twin.md:1" in p.stdout, p.stdout + p.stderr
    p = _run(scripts, "check_skill_models.py", "--defaults", "--config", str(cfg),
             "--local", str(local), "--root", str(root))
    assert "check fails here" in p.stdout, p.stdout + p.stderr
