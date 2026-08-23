"""Integration tests for install.sh's model-role resolution (Phase 69).

Invokes the real installer against a scratch git consumer in tmp_path. Two
guarantees the unit suite can't cover because they live in the install pipeline:

  1. A DEFAULT install ships the role layer (served_models.yml + resolver +
     _model_roles) and leaves skills at their shipped literals — the resolver is
     a byte-for-byte no-op, so nothing diverges.
  2. A consumer-seeded served_models.local.yml override is applied AT INSTALL
     TIME — install copies skills (opus literals), then resolve_skill_models.py
     rewrites them to the overridden models.

`python3` resolves to the pytest interpreter via a PATH prefix so the installer's
`pick_python_with_yaml()` finds pyyaml (same trick as test_install_concat.py).
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _make_consumer(root, files=None):
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    for rel, content in (files or {}).items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed", "--allow-empty")
    return root


def _run_install(target, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    result = subprocess.run(
        ["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, (
        f"install.sh failed (rc={result.returncode})\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    return result


def _fm_model(path):
    for line in path.read_text().splitlines():
        if line.startswith("model:"):
            return line.split(":", 1)[1].strip()
    return None


def test_default_install_ships_role_layer_as_noop(tmp_path):
    root = _make_consumer(tmp_path / "consumer")
    result = _run_install(root, "--packs", "python", "--no-arm-hooks")

    # The pieces ship.
    for rel in (".claude/served_models.yml",
                "sysop/scripts/resolve_skill_models.py",
                "sysop/scripts/_model_roles.py",
                "sysop/scripts/check_skill_models.py"):
        assert (root / rel).is_file(), f"installer did not ship {rel}"

    # Skills keep their shipped literals + their role markers.
    auto_build = root / ".claude/skills/auto-build/SKILL.md"
    assert _fm_model(auto_build) == "opus"
    assert "sysop:model-roles frontmatter=reasoning" in auto_build.read_text()
    assert _fm_model(root / ".claude/skills/next-task/SKILL.md") == "haiku"

    # The resolver ran (PATH carries pyyaml) and the installed tree validates.
    assert "model-roles" in result.stdout
    check = subprocess.run(
        [sys.executable, str(root / "sysop/scripts/check_skill_models.py"),
         "--root", str(root / ".claude/skills"),
         "--config", str(root / ".claude/served_models.yml")],
        capture_output=True, text=True,
    )
    assert check.returncode == 0, check.stdout + check.stderr


def test_local_override_resolves_at_install(tmp_path):
    # Consumer commits a local override BEFORE installing: reasoning -> sonnet.
    root = _make_consumer(
        tmp_path / "consumer",
        {".claude/served_models.local.yml":
         "roles:\n  reasoning: sonnet\nserved:\n  - sonnet\n"},
    )
    _run_install(root, "--packs", "python", "--no-arm-hooks")

    # Reasoning-role skills are rewritten to sonnet at install time...
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "sonnet"
    assert _fm_model(root / ".claude/skills/review-close/SKILL.md") == "sonnet"
    # ...the quick role is untouched by a reasoning override...
    assert _fm_model(root / ".claude/skills/next-task/SKILL.md") == "haiku"
    # ...and the consumer's override file is never overwritten by the installer.
    assert "reasoning: sonnet" in (root / ".claude/served_models.local.yml").read_text()


def _inline_pins(root):
    """Every inline `model: "<x>"` literal in the installed skills tree."""
    import re

    out = {}
    for path in sorted((root / ".claude/skills").rglob("*.md")):
        for m in re.finditer(r'model[`:\s]*["\']([^"\']+)["\']', path.read_text()):
            out.setdefault(str(path.relative_to(root)), []).append(m.group(1))
    return out


def test_an_invalid_mapping_is_refused_and_nothing_is_rewritten(tmp_path):
    """Phase 223's gate, observed by OUTCOME rather than by the shape of the text
    that implements it.

    Round 2 walked two mutations through the shape-based test: a `|| true` tail on
    the checker (the gate can never fire, and this repo has shipped that tail
    before — Phases 84 and 153), and deleting the `return 0` after the refusal, so
    the installer prints "nothing was rewritten" and then rewrites them. The
    second is worse than the first: it leaves a durable `record` line certifying
    the opposite of what happened.

    The asymmetry mattered. A gate that ALWAYS refuses was already caught, by
    `test_local_override_resolves_at_install` above — so the only coverage the
    gate had pointed the wrong way: over-refusal caught, never-refusing not.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    before = _inline_pins(root)
    assert before, "vacuity: the installed tree carries no inline pins to protect"
    assert any("opus" in v for v in before.values())

    # The documented remedy, with a value the Agent tool's enum rejects.
    (root / ".claude/served_models.local.yml").write_text(
        "roles:\n  reasoning: best\nserved:\n  - best\n"
    )
    result = _run_install(root, "--update", "--no-arm-hooks")

    assert "REFUSED" in result.stdout, "the gate did not announce a refusal"
    assert _inline_pins(root) == before, (
        "the mapping was applied despite the refusal — every inline pin now holds a "
        "value the Agent tool rejects at spawn time"
    )
    assert not any("best" in v for v in _inline_pins(root).values())


def test_a_valid_override_is_still_applied_after_the_gate(tmp_path):
    """The other direction, so the gate cannot be satisfied by refusing always."""
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")

    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: fable\n")
    result = _run_install(root, "--update", "--no-arm-hooks")

    assert "REFUSED" not in result.stdout, "a legal mapping was refused"
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "fable"
    pins = _inline_pins(root)
    assert any("fable" in v for v in pins.values()), "inline pins were not resolved"


def test_dry_run_previews_the_refusal(tmp_path):
    """`--dry-run` is the documented way to preview an update. Round 2 found this
    branch returning BEFORE the gate, so a dry-run with an invalid override
    printed "no-op under default mapping" while the real run refused."""
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude/served_models.local.yml").write_text(
        "roles:\n  reasoning: best\nserved:\n  - best\n"
    )
    result = _run_install(root, "--update", "--dry-run", "--no-arm-hooks")
    assert "would REFUSE" in result.stdout, (
        "dry-run did not preview the refusal the real run performs"
    )
    assert "no-op under default mapping" not in result.stdout


def test_dry_run_stays_quiet_on_a_valid_mapping(tmp_path):
    """The over-strict direction: a legal override must not read as a refusal."""
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: fable\n")
    result = _run_install(root, "--update", "--dry-run", "--no-arm-hooks")
    assert "would REFUSE" not in result.stdout


def test_a_malformed_config_is_not_reported_as_an_invalid_mapping(tmp_path):
    """`ConfigShapeError` exists so a YAML typo is not reported as a model-pin
    failure. The gate initially collapsed every non-zero exit into "invalid
    mapping", re-losing the distinction one layer up."""
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: [oops\n")
    result = _run_install(root, "--update", "--no-arm-hooks")
    assert "REFUSED (unreadable config)" in result.stdout
    assert "invalid mapping" not in result.stdout


# NOT tested here, deliberately, and recorded rather than contorted: the gate's
# `else` branch (checker absent from the vendor dir → apply UNVALIDATED, loudly).
# `--update` re-copies the vendor dir BEFORE resolve_skill_models runs, so a
# normal install restores the checker and the branch has no live path through
# this harness. It is defensive code for a partial tree, kept because a silent
# fail-open there is the exact shape the gate exists to end — but its liveness
# claim is the kind this project files as latent rather than asserting.


def test_a_consumers_own_skill_does_not_block_the_mapping(tmp_path):
    """`.claude/skills/` is Claude Code's standard user-skill directory, not
    Sysop's private tree. Round 2 found that a consumer's own skill carrying a
    `model:` field made the gate refuse forever: it has no `sysop:model-roles`
    marker, so it failed the no-marker arm, and a perfectly valid
    `reasoning: fable` mapping could never apply on this or any future update.
    The prescribed remedy — "add the missing marker" — would have handed their
    private skill to Sysop's resolver to rewrite on every update.

    Before this phase the checker had no installer invoker, so the shape was
    inert. The gate is what made it blocking, which is over-strictness in the
    direction that hides.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")

    own = root / ".claude/skills/my-own-skill"
    own.mkdir(parents=True)
    (own / "SKILL.md").write_text(
        "---\nname: my-own-skill\nmodel: sonnet\n---\n\n"
        'Spawn a helper with `model`: `"sonnet"` and let it work.\n'
    )
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: fable\n")

    result = _run_install(root, "--update", "--no-arm-hooks")
    assert "REFUSED" not in result.stdout, (
        "a consumer's own skill blocked a valid mapping:\n" + result.stdout
    )
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "fable"
    # And Sysop did not touch the consumer's own skill.
    assert _fm_model(own / "SKILL.md") == "sonnet"


def test_the_refusal_message_does_not_claim_more_than_it_did(tmp_path):
    """The gate said "skills keep their current models, nothing was rewritten".
    Round 2 showed that is false whenever a previous override HAD been applied:
    `install_skills` re-copies the shipped tree ~130 lines before the gate runs,
    so a consumer sitting on `fable` who then writes an invalid override ends the
    run at Sysop's shipped defaults, not where they started.

    The state is safe — shipped defaults are valid — but the sentence was not
    true, and this phase's own record repeated it. The message now says what
    actually happens.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: fable\n")
    _run_install(root, "--update", "--no-arm-hooks")
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "fable"

    (root / ".claude/served_models.local.yml").write_text(
        "roles:\n  reasoning: best\nserved:\n  - best\n"
    )
    result = _run_install(root, "--update", "--no-arm-hooks")

    assert "REFUSED" in result.stdout
    assert "nothing was rewritten" not in result.stdout, (
        "the refusal still claims the tree is untouched; it is at shipped defaults"
    )
    assert "shipped defaults" in result.stdout
    # The observable truth: shipped defaults, and no illegal literal anywhere.
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "opus"
    assert not any("best" in v for v in _inline_pins(root).values())
