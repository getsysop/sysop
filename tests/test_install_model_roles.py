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

import pytest
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


def _indented_payload(stdout):
    """The checker's own output, which the installer prints indented under its
    headline. Every message this phase touches is a headline PLUS a payload, and
    the round showed the payload was entirely unguarded: dropping `2>&1` from the
    capture (the checker writes its diagnostics to stderr) leaves the headline
    intact with an empty body, and every assertion in this module still passed.
    """
    return [
        line for line in stdout.splitlines()
        if line.startswith("    ") and line.strip()
        and not line.lstrip().startswith("•")
    ]


def _model_role_block(stdout):
    """The `── resolve model roles ──` section of an install run, as a list.

    Phase 244's central property is about what the PREVIEW says, and several of
    these tests assert that a fixture cannot change it. Comparing the whole
    stdout would fail on paths and counts from unrelated steps; comparing this
    block compares the thing under test.
    """
    out, inside = [], False
    for line in stdout.splitlines():
        if line.strip().startswith("── resolve model roles"):
            inside = True
            continue
        if inside and line.strip().startswith("── "):
            break
        if inside and line.strip():
            out.append(line)
    return out


def _source_copy(tmp_path, name="sysop-src", commit=True):
    """A real Sysop SOURCE tree the test may mutate.

    `install.sh` reads only `core/` and `packs/` from `$REPO_ROOT` (verified by
    grep, not assumed), so a source tree is `install.sh` plus those two.

    **It is a git repo, and that is load-bearing rather than incidental.** A
    non-git source records no `sysop_commit` anchor in the lock, so Phase 125's
    no-anchor `--update` fail-closed aborts before the model-role step is
    reached — measured, both arms symmetrically, so it is not a preview/apply
    disagreement. `_stale_source_tree` learned this the same way and carried its
    own copy of the three git commands; this is that step, shared.

    Pass `commit=False` to mutate the tree before the first commit.
    """
    import shutil

    src = tmp_path / name
    src.mkdir()
    shutil.copy2(INSTALL_SH, src / "install.sh")
    for d in ("core", "packs"):
        shutil.copytree(REPO_ROOT / d, src / d, symlinks=True)
    if commit:
        _commit_source(src)
    return src


def _commit_source(src):
    _git(src, "init", "-q")
    _git(src, "config", "user.email", "test@test")
    _git(src, "config", "user.name", "test")
    _git(src, "add", "-A")
    _git(src, "commit", "-qm", "sysop source")


def _source_served_models(src):
    return src / "core/companion/.claude/served_models.yml"


def _rewrite_served(src, mutate):
    """Load the source's served_models.yml, hand it to *mutate*, write it back.

    A YAML round-trip rather than string surgery: the two fixtures below add and
    remove entries, and a regex over a file whose `served:` list carries inline
    comments is the kind of fixture that silently stops reproducing.
    """
    import yaml

    path = _source_served_models(src)
    data = yaml.safe_load(path.read_text())
    mutate(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


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
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            # The `Q-346` fixtures put a consumer's own latin-1 file in this tree
            # on purpose. This helper had the same unguarded read the shipped
            # code did, so it crashed on the fixture written to prove the shipped
            # code no longer does.
            continue
        for m in re.finditer(r'model[`:\s]*["\']([^"\']+)["\']', text):
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


def test_the_preview_states_uncertainty_instead_of_a_verdict(tmp_path):
    """`Q-345` § High, and the reversal of what this test used to assert.

    It previously required the preview to reach the refusal the apply reaches.
    That is not a property a preview can hold: every input the gate reads —
    `served_models.yml`, the skills tree, the resolver — is target-side state the
    update REPLACES, so the preview judges the tree being replaced. Three
    reproductions, each measured on one target minutes apart, showed the verdict
    wrong in both directions and over a readable config; the worst is a
    fabricated refusal on the documented one-key override, whose documented
    reaction is to abort the update.

    Wade's call, 2026-08-29: a preview states uncertainty and never a verdict it
    cannot stand behind. The accepted cost is exactly what the old assertion was
    buying — early warning — and it is bought back at apply, where the gate
    already refuses without touching a pin.

    Kept as a test rather than deleted, per the Phase 204 convention: a guard a
    phase falsifies is REPLACED by the property that now holds, or the coverage
    disappears with the claim.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude/served_models.local.yml").write_text(
        "roles:\n  reasoning: best\nserved:\n  - best\n"
    )

    preview = _run_install(root, "--update", "--dry-run", "--no-arm-hooks")

    assert "would REFUSE" not in preview.stdout, (
        "the preview issued a verdict it cannot stand behind"
    )
    assert "no-op under default mapping" not in preview.stdout, (
        "the preview claimed a clean no-op, which is the OTHER direction of the "
        "same defect"
    )
    assert "the mapping is NOT judged here" in preview.stdout, (
        "the preview reached no verdict AND did not say so — silence is not the "
        "fix; stating the limit is"
    )
    assert "an install or update checks it instead" in preview.stdout, (
        "the preview does not tell the consumer where the mapping IS judged"
    )

    # And the verdict still exists — at apply. Without this the test above is
    # satisfied by a gate that stopped judging anywhere.
    applied = _run_install(root, "--update", "--no-arm-hooks")
    assert "REFUSED" in applied.stdout, (
        "the apply no longer refuses an invalid mapping — the preview was made "
        "honest by removing the gate rather than by moving the claim"
    )
    # The DURABLE record, which nothing pinned. Every other record string in this
    # function is asserted somewhere; `model-roles: refused` was not, so the guards
    # lens rewrote it to `model-roles: APPLIED (invalid mapping; …)` and the summary
    # certified the opposite of the warning above it — the exact shape
    # `test_an_invalid_mapping_is_refused_and_nothing_is_rewritten`'s docstring
    # names as the worse of round 2's two mutations.
    assert "model-roles: refused (invalid mapping" in applied.stdout, (
        "the install summary no longer records the refusal, or records it as an "
        "apply"
    )
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "opus"


def test_a_fresh_dry_run_does_not_report_the_step_as_skipped(tmp_path):
    """`Q-344`. The precondition tested `$TARGET/sysop/scripts/resolve_skill_models.py`,
    `$TARGET/.claude/skills` and `$TARGET/.claude/served_models.yml` — three files
    the SAME RUN creates. On a fresh `--dry-run` none exists, so the preview
    printed `skipping: resolver, skills tree, or served_models.yml not present`
    while the apply on the same target resolved normally. Measured both ways.

    Who it bites: a consumer who commits `.claude/served_models.local.yml` before
    installing — the documented path, and the one
    `test_local_override_resolves_at_install` covers — and previews first. They
    are told their override will not be resolved, when it will be.
    """
    root = _make_consumer(tmp_path / "consumer")

    preview = _run_install(root, "--packs", "python", "--no-arm-hooks", "--dry-run")

    assert "skipping: resolver, skills tree, or served_models.yml not present" \
        not in preview.stdout, (
            "a fresh preview reported the step skipped because the files this run "
            "creates do not exist yet"
        )
    assert "would resolve skill model-role markers" in preview.stdout, (
        "the preview says nothing about a step the apply will run"
    )

    # The apply half, so the disagreement is measured rather than assumed.
    applied = _run_install(root, "--packs", "python", "--no-arm-hooks")
    assert "model-roles: APPLIED" in applied.stdout, (
        "vacuity: the apply did not run the step either, so there was no "
        "disagreement to fix"
    )


def test_dry_run_stays_quiet_on_a_valid_mapping(tmp_path):
    """The over-strict direction: a legal override must not read as a refusal.

    Phase 244: the absence assertion alone is now satisfied by a preview that
    says nothing at all, so the positive half is pinned too. The preview must
    still tell the consumer that their override exists and will be resolved.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: fable\n")
    result = _run_install(root, "--update", "--dry-run", "--no-arm-hooks")
    assert "would REFUSE" not in result.stdout
    assert "would resolve skill model-role markers" in result.stdout, (
        "the preview went silent on a step the apply performs"
    )
    assert "served_models.local.yml" in result.stdout, (
        "the preview never mentions the consumer's own override file"
    )


def test_a_malformed_config_is_not_reported_as_an_invalid_mapping(tmp_path):
    """`ConfigShapeError` exists so a YAML typo is not reported as a model-pin
    failure. The gate initially collapsed every non-zero exit into "invalid
    mapping", re-losing the distinction one layer up."""
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: [oops\n")
    result = _run_install(root, "--update", "--no-arm-hooks")
    # Phase 244 (`Q-346` leg 2): the headline used to be
    # `REFUSED (unreadable config)`, which asserted BOTH halves wrongly. rc 2 is
    # four different states — config missing, root missing, malformed config,
    # empty population — so it is not a verdict on the mapping at all, and
    # `Q-345`'s reproduction (c) hit that wording over a perfectly readable
    # config. The distinction this test exists for survives: a YAML typo is still
    # not reported as a model-pin failure.
    assert "invalid mapping" not in result.stdout, (
        "a YAML typo was reported as the consumer's model mapping being wrong"
    )
    assert "cannot evaluate the model-role mapping" in result.stdout, (
        "rc 2 no longer says the gate could not evaluate the mapping"
    )
    assert "nothing is claimed about your mapping" in result.stdout
    assert "model-roles: APPLIED" not in result.stdout, (
        "rc 2 stopped declining and the rewrite ran anyway"
    )
    # The outcome, not the wording: rc 2 still declines to apply. Phase 244
    # changed the CLAIM, deliberately not the control flow.
    assert "model-roles: not applied" in result.stdout, (
        "the durable record no longer discloses that the mapping was not applied"
    )
    # THE CONTROL FLOW, observed directly. Asserting the pins are still `opus` does
    # NOT establish that the gate declined: the resolver would fail on the same
    # malformed config and write nothing either way, so that assertion is satisfied
    # by the executor falling over. The author battery deleted the rc-2 `return 0`
    # and walked through the whole module on exactly that gap. `APPLIED` is emitted
    # only by the resolver's own success line, so its ABSENCE is the honest oracle.
    assert "model-roles: APPLIED" not in result.stdout, (
        "rc 2 stopped declining — the gate could not read its inputs and let the "
        "rewrite run anyway"
    )
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "opus", (
        "a gate that could not read its inputs rewrote pins anyway"
    )


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


# ─────────────────────────────────────────────────────────────────────────────
# Phase 242 (Q-330, reported by a consumer): the gate must judge the CONSUMER'S MAPPING,
# never the age of the checker that happens to sit in their vendor dir.
#
# The fixture gap that let this ship: every test above installs from the CURRENT
# source, so the target's vendored checker is always current too, and the whole
# version-skew dimension was unreachable. These build the state every consumer
# installed before Phase 223 is actually in — a vendored checker that predates a
# flag `install.sh` now passes — and assert on OUTCOMES, so they survive any
# rewording of the messages.
# ─────────────────────────────────────────────────────────────────────────────

def _age_vendored_checker(root):
    """Strip `--managed-only` from the TARGET's vendored checker.

    Not a contrived edit: this is byte-for-byte the state of any consumer whose
    last install predates Phase 223, and `--dry-run` copies nothing, so this is
    the copy a pre-fix preview reached for.
    """
    p = root / "sysop/scripts/check_skill_models.py"
    text = p.read_text()
    start = text.index('    parser.add_argument("--managed-only"')
    end = text.index('    parser.add_argument("--list"')
    aged = (text[:start] + text[end:]).replace("args.managed_only", "False")
    # The REGISTRATION, not any mention of the string. Asserting the bare literal
    # was absent made this fixture break on a comment in the checker that merely
    # named the flag — which is what happened when Phase 244 added one, and cost
    # a cycle to diagnose. The real control is `_assert_checker_is_really_stale`
    # below, which runs the aged checker and requires argparse's exit 2.
    assert 'add_argument("--managed-only"' not in aged, (
        "aging failed: the flag is still registered with argparse"
    )
    p.write_text(aged)
    return p


def _assert_checker_is_really_stale(checker, root):
    """Positive control. Without this the tests above pass on a fixture that
    never reproduced anything — which is how a sweep docstring'd "the class, not
    the instance" once killed 0 of 7."""
    proc = subprocess.run(
        [sys.executable, str(checker),
         "--root", str(root / ".claude/skills"),
         "--config", str(root / ".claude/served_models.yml"),
         "--managed-only"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 2, (
        f"fixture is not stale: expected argparse exit 2, got {proc.returncode}"
    )
    assert "unrecognized arguments" in proc.stderr, (
        "fixture does not reproduce the flag-surface mismatch this test exists for"
    )


def test_the_vendored_checker_cannot_change_what_the_preview_says(tmp_path):
    """`Q-330`, now held by construction rather than by choosing a copy.

    The original defect: `--dry-run` invoked the target-side checker the same
    update was about to replace, so an old checker met a new flag, argparse
    exited 2, and the exit-code-only reading printed "would REFUSE … your
    override would NOT be applied" at a consumer whose mapping was fine. Phase
    242 fixed it by running the SOURCE copy in the preview; Phase 244 removed the
    preview's judge entirely (`Q-345`), which makes the property total: no
    checker runs in a preview, so no checker's state can reach it.

    Asserted as an EQUALITY against a healthy tree rather than as an absence.
    An absence assertion ("no `would REFUSE`") is satisfied by a preview that
    degrades to some other wrong thing; this one fails if the stale fixture
    perturbs the preview at all.
    """
    healthy = _make_consumer(tmp_path / "healthy")
    _run_install(healthy, "--packs", "python", "--no-arm-hooks")
    baseline = _model_role_block(
        _run_install(healthy, "--update", "--dry-run", "--no-arm-hooks").stdout)

    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    checker = _age_vendored_checker(root)
    _assert_checker_is_really_stale(checker, root)

    result = _run_install(root, "--update", "--dry-run", "--no-arm-hooks")

    assert baseline, "vacuity: the healthy preview printed nothing to compare against"
    assert _model_role_block(result.stdout) == baseline, (
        "a stale vendored checker changed what the preview said\n"
        f"--- stale ---\n{_model_role_block(result.stdout)}\n"
        f"--- healthy ---\n{baseline}"
    )
    assert "would REFUSE" not in result.stdout, (
        "the preview fabricated a refusal from a stale vendored checker"
    )
    assert "unrecognized arguments" not in result.stdout, (
        "argparse's own failure text was surfaced to the consumer as a verdict"
    )


def test_a_stale_vendored_checker_is_not_applied_as_an_unreadable_config(tmp_path):
    """The apply arm was NOT hypothetically exposed, which the filing called
    latent. A consumer-modified checker is PRESERVED by the Phase 24b divergence
    guard, so `install_companion_scripts` leaves the stale copy in place and the
    gate then reports `REFUSED (unreadable config)` — argparse's exit 2 read as
    the checker's own exit 2, in the arm written to stop conflating causes.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    checker = _age_vendored_checker(root)
    _assert_checker_is_really_stale(checker, root)
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: fable\n")

    result = _run_install(root, "--update", "--no-arm-hooks")

    assert "REFUSED" not in result.stdout, (
        "a valid mapping was refused because the vendored checker was old"
    )
    assert "unreadable config" not in result.stdout
    # The outcome, not the wording: the mapping actually landed.
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "fable"
    # And the skipped gate is DISCLOSED. Aging the vendored checker means editing
    # it, which makes the Phase 24b divergence guard preserve it — so the copy
    # that runs beside the executor really is stale, and the honest outcome is
    # "applied, gate could not run, and here is why", not a silent pass and not a
    # refusal. Asserting UNVALIDATED is ABSENT here is what the first cut did, and
    # it is what drove the apply arm onto the source checker — which then let a
    # consumer-modified `_model_roles.py` write `model: best` across the tree.
    assert "UNVALIDATED" in result.stdout, (
        "the gate could not run and the run did not say so"
    )


def test_the_preview_makes_no_claim_the_apply_could_contradict(tmp_path):
    """The property that replaces "the preview and the apply agree".

    Agreement was the right goal and the wrong mechanism. The two arms ran
    different copies of the checker over target-side state one of them was about
    to replace, so they agreed only when nothing relevant changed — and `Q-345`
    measured three ordinary situations where they did not. Phase 244 removes the
    disagreement at its source: the preview makes no verdict claim at all, so
    there is nothing for the apply to contradict.

    The weakening is deliberate and stated: the preview no longer warns about a
    bad mapping. What replaces the warning is the apply's refusal, asserted here
    in the same test so the pair cannot be silently reduced to nothing.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: fable\n")

    preview = _run_install(root, "--update", "--dry-run", "--no-arm-hooks")

    block = "\n".join(_model_role_block(preview.stdout))
    assert block, "vacuity: the preview printed no model-role block to inspect"
    for verdict in ("would REFUSE", "REFUSED", "invalid mapping",
                    "unreadable config", "no-op under default mapping"):
        assert verdict not in block, (
            f"the preview still issues the verdict token {verdict!r}:\n{block}"
        )

    applied = _run_install(root, "--update", "--no-arm-hooks")
    assert "UNVALIDATED" not in applied.stdout, "the apply ran with the gate skipped"
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "fable", (
        "the valid override did not land, so this run exercised no gate at all"
    )


def test_a_consumer_modified_model_roles_cannot_smuggle_an_illegal_mapping(tmp_path):
    """The regression the adversarial round caught, and the reason the two arms
    run different copies.

    The checker is the JUDGE; `resolve_skill_models.py` + `_model_roles.py` are
    the EXECUTOR, and on the apply path the executor is always the vendored copy.
    All three sit at `sysop/scripts/*`, inside the Phase 24b preserve scope. A
    first cut of this phase judged with the SOURCE stack in both arms — so a
    consumer whose vendored `_model_roles.py` resolves every role to `best` got
    `model: best` written across 21 files, green, with no refusal, where the
    previous release refused and left every pin at `opus`.

    `best` is rejected by the Agent tool's `model` enum at spawn time, which is
    the exact failure the gate exists to prevent, so this is stricter than a
    preview cosmetic: the phase's own fix had reopened the hole it was built
    beside. Measured against `main` both ways before and after.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    before = _fm_model(root / ".claude/skills/auto-build/SKILL.md")
    assert before == "opus", f"fixture assumption broken: shipped pin is {before!r}"

    roles = root / "sysop/scripts/_model_roles.py"
    text = roles.read_text()
    anchor = '    data = _load_yaml_mapping(config_path)\n'
    assert anchor in text, "the _model_roles anchor moved — re-derive before trusting this test"
    text = text.replace(
        anchor,
        anchor
        + '    return ({"reasoning": "best", "mechanical": "best", "quick": "best"},\n'
          '            ["best"])  # consumer edit, preserved by the Phase 24b guard\n',
        1,
    )
    roles.write_text(text)

    result = _run_install(root, "--update", "--no-arm-hooks")

    assert "REFUSED" in result.stdout, (
        "the gate certified a mapping the executor will not produce — the judge "
        "and the executor are reading different copies of _model_roles.py"
    )
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "opus"
    assert not any("best" in v for v in _inline_pins(root).values()), (
        "an Agent-tool-illegal model literal reached the installed skills tree"
    )


def test_an_absent_vendored_checker_cannot_change_the_preview(tmp_path):
    """What replaces "a genuine refusal survives the vendored checker being absent".

    That test required the PREVIEW to refuse when the vendor dir had no checker,
    which pinned the preview to reaching a verdict — the thing `Q-345` retired.
    What still matters, and is now total: the vendor dir is irrelevant to the
    preview, because the preview runs no checker.

    The refusal itself did not disappear; it moved to the arm that can stand
    behind it, and is asserted below on the same fixture.
    """
    healthy = _make_consumer(tmp_path / "healthy")
    _run_install(healthy, "--packs", "python", "--no-arm-hooks")
    (healthy / ".claude/served_models.local.yml").write_text(
        "roles:\n  reasoning: best\nserved:\n  - best\n"
    )
    baseline = _model_role_block(
        _run_install(healthy, "--update", "--dry-run", "--no-arm-hooks").stdout)

    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    (root / "sysop/scripts/check_skill_models.py").unlink()
    (root / ".claude/served_models.local.yml").write_text(
        "roles:\n  reasoning: best\nserved:\n  - best\n"
    )

    result = _run_install(root, "--update", "--dry-run", "--no-arm-hooks")

    assert baseline, "vacuity: the healthy preview printed nothing to compare against"
    assert _model_role_block(result.stdout) == baseline, (
        "deleting the vendored checker changed what the preview said"
    )

    # The verdict, where it belongs. `--update` re-copies the vendor dir before
    # the gate runs, so the apply has a checker again and refuses for real.
    applied = _run_install(root, "--update", "--no-arm-hooks")
    assert "REFUSED" in applied.stdout, (
        "an invalid mapping was applied because the vendored checker had been "
        "deleted before the run"
    )
    assert not any("best" in v for v in _inline_pins(root).values())


def test_the_no_override_pyyaml_skip_does_not_invent_an_override(tmp_path):
    """The other polarity, which nothing asserted.

    `test_a_missing_pyyaml_is_previewed_instead_of_reported_as_a_no_op` pins the
    override-PRESENT branch. The guards lens passed `_preview_skill_models` the
    wrong argument (`$config` instead of `$localcfg`) and the preview warned a
    consumer with NO override that "your served_models.local.yml override would
    NOT be applied" — the false-positive twin of the polarity class that test's own
    comment discusses at length.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    assert not (root / ".claude/served_models.local.yml").exists()

    shim_dir = tmp_path / "nopyyaml"
    shim_dir.mkdir()
    shim = shim_dir / "python3"
    shim.write_text(
        "#!/bin/sh\n"
        'case "$*" in *"import yaml"*) exit 1 ;; esac\n'
        f'exec "{sys.executable}" "$@"\n'
    )
    shim.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = str(shim_dir) + os.pathsep + env["PATH"]
    preview = subprocess.run(
        ["bash", str(INSTALL_SH), str(root), "--update", "--dry-run",
         "--no-arm-hooks", "--yes"],
        capture_output=True, text=True, env=env,
    )
    assert preview.returncode == 0, preview.stdout + preview.stderr

    assert "your served_models.local.yml override would NOT be applied" \
        not in preview.stdout, (
            "the preview warned about an override file that does not exist"
        )
    assert "default mapping is a no-op anyway" in preview.stdout, (
        "vacuity: the no-PyYAML branch never fired"
    )


def test_a_missing_pyyaml_is_previewed_instead_of_reported_as_a_no_op(tmp_path):
    """Found by running the fix, not by reading the filing: the same
    preview-disagrees-with-apply defect as Q-330, pointing the other way, in the
    same function. With no PyYAML interpreter the apply arm warns that the
    override will NOT be applied, while the preview fell through to the benign
    "no-op under default mapping" — so the preview UNDERSTATED.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: fable\n")

    # A python3 that answers "no yaml" to pick_python_with_yaml's probe and is
    # otherwise the real interpreter. Deterministic, and local to this test.
    shim_dir = tmp_path / "nopyyaml"
    shim_dir.mkdir()
    shim = shim_dir / "python3"
    shim.write_text(
        "#!/bin/sh\n"
        'case "$*" in *"import yaml"*) exit 1 ;; esac\n'
        f'exec "{sys.executable}" "$@"\n'
    )
    shim.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = str(shim_dir) + os.pathsep + env["PATH"]
    preview = subprocess.run(
        ["bash", str(INSTALL_SH), str(root), "--update", "--dry-run",
         "--no-arm-hooks", "--yes"],
        capture_output=True, text=True, env=env,
    )
    assert preview.returncode == 0, preview.stdout + preview.stderr
    assert "no-op under default mapping" not in preview.stdout, (
        "the preview reported a clean no-op while the apply would warn the "
        "override is not applied"
    )
    # NOT `"PyYAML" in stdout`. Both branches of this arm say "PyYAML", so that
    # assertion passes with the polarity inverted — the override-present case
    # falling through to the no-override wording and the guard staying green.
    # `Q-340`'s class (a guard asserting a token its own neighbour also contains),
    # caught here by the battery rather than by reading. Pin the sentence that
    # only the override-present branch can produce.
    assert "your served_models.local.yml override would NOT be applied" in preview.stdout, (
        "an override IS present, so the preview must say that one exists and will "
        "not be applied — not the generic no-override skip"
    )
    # MUTUAL EXCLUSIVITY. The guards lens deleted the `return 0` that ends this
    # branch and the preview printed BOTH the "override would NOT be applied"
    # warning and the "would resolve … the mapping is NOT judged here" block, in
    # one section, contradicting itself. A presence assertion and an absence
    # assertion do not forbid a contradicting continuation.
    assert "would resolve skill model-role markers" not in preview.stdout, (
        "the preview warned the override cannot be applied and then announced it "
        "would resolve the markers anyway"
    )


def _stale_source_tree(tmp_path):
    """A Sysop SOURCE tree whose own checker predates `--managed-only`.

    The battery's verdict on the first cut of this module was the reason it
    exists: every fixture above ages the VENDORED checker, and after the fix
    nothing reads the vendored checker — so the capability probe and both rc-3
    arms, the entire second half of the fix, were unreachable and eight
    mutations against them survived. `install.sh` reads only `core/` and
    `packs/` from `$REPO_ROOT` (verified by grep, not assumed), so a real source
    tree is a 3.5 MB copy.
    """
    src = _source_copy(tmp_path, commit=False)

    checker = src / "core/companion/scripts/check_skill_models.py"
    text = checker.read_text()
    start = text.index('    parser.add_argument("--managed-only"')
    end = text.index('    parser.add_argument("--list"')
    aged = (text[:start] + text[end:]).replace("args.managed_only", "False")

    # Hostile on purpose. A probe that greps the help output for a bare
    # "managed" instead of the exact flag is indistinguishable from a correct one
    # on any ordinary checker, because the only place the word occurs IS the flag
    # — so that mutation survived a battery run against a merely-stale fixture.
    # Putting the word in a DIFFERENT option's help makes the loose probe declare
    # the flag supported, pass it, and collect argparse's exit 2 as a verdict.
    aged = aged.replace(
        'help="skills directory to scan (default: .claude/skills/)"',
        'help="skills directory to scan, managed or otherwise (default: .claude/skills/)"',
    )
    checker.write_text(aged)
    assert "--managed-only" not in checker.read_text(), "the flag survived aging"
    assert "managed" in checker.read_text(), (
        "the decoy is gone: a substring-matching probe would be indistinguishable "
        "from an exact one against this fixture"
    )

    # The source has to be a git repo or the install records no `sysop_commit`
    # anchor in the lock, and Phase 125's no-anchor `--update` fail-closed aborts
    # before the model-role step is reached. Found by running it: the first cut
    # of this fixture failed on that refusal, not on the property under test.
    # Phase 244 hoisted the three commands into `_commit_source` after writing a
    # second fixture that did not know this and hit the same refusal.
    _commit_source(src)

    # Positive control, mirroring `_assert_checker_is_really_stale` for the
    # vendored fixture. The round neutered that control and all three of its
    # tests still passed, so a fixture whose aging silently stopped working would
    # be invisible. Assert this one reproduces BOTH halves: argparse rejects the
    # flag (exit 2, what install.sh collides with) and the file still parses
    # (otherwise the test proves only that a broken file fails).
    probe = subprocess.run(
        [sys.executable, str(checker), "--managed-only"],
        capture_output=True, text=True,
    )
    assert probe.returncode == 2 and "unrecognized arguments" in probe.stderr, (
        "the source fixture is not stale in the way install.sh trips over: "
        f"rc={probe.returncode} stderr={probe.stderr[:200]!r}"
    )
    syntax = subprocess.run(
        [sys.executable, "-c", f"import ast; ast.parse(open({str(checker)!r}).read())"],
        capture_output=True, text=True,
    )
    assert syntax.returncode == 0, (
        "the fixture produced a file that does not parse, so the tests would pass "
        "for the wrong reason — 'old checker' and 'broken file' are different states"
    )
    return src / "install.sh"


def _run_install_from(install_sh, target, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    result = subprocess.run(
        ["bash", str(install_sh), str(target), *extra, "--yes"],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_a_stale_source_checker_cannot_change_the_preview(tmp_path):
    """The preview half of the stale-checker state, after `Q-345`.

    Phase 242 made the preview run the SOURCE checker, so a stale SOURCE tree
    could still perturb it — the arm this test used to pin printed "cannot
    preview the model-role gate". Phase 244 removed the preview's checker
    entirely, so neither copy can reach it, and the honest assertion is equality
    against a healthy source rather than the presence of a degradation message.

    The apply half is unchanged and is asserted by the sibling below, which is
    where the capability probe and both rc-3 arms are still exercised.
    """
    healthy_src = _source_copy(tmp_path, "healthy-src")
    healthy = _make_consumer(tmp_path / "healthy")
    _run_install_from(healthy_src / "install.sh", healthy, "--packs", "python",
                      "--no-arm-hooks")
    (healthy / ".claude/served_models.local.yml").write_text(
        "roles:\n  reasoning: fable\n")
    baseline = _model_role_block(_run_install_from(
        healthy_src / "install.sh", healthy, "--update", "--dry-run",
        "--no-arm-hooks").stdout)

    install_sh = _stale_source_tree(tmp_path)
    root = _make_consumer(tmp_path / "consumer")
    _run_install_from(install_sh, root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: fable\n")

    result = _run_install_from(install_sh, root, "--update", "--dry-run", "--no-arm-hooks")

    assert baseline, "vacuity: the healthy preview printed nothing to compare against"
    assert _model_role_block(result.stdout) == baseline, (
        "a stale SOURCE checker changed what the preview said\n"
        f"--- stale ---\n{_model_role_block(result.stdout)}\n"
        f"--- healthy ---\n{baseline}"
    )
    assert "would REFUSE" not in result.stdout, (
        "a Sysop-side checker failure was reported to the consumer as their "
        "mapping being refused — this is Q-330"
    )


def test_a_stale_source_checker_applies_unvalidated_rather_than_refusing(tmp_path):
    """The apply arm's half of the same state. A gate that cannot run is not a
    refusal, and must not silently drop a valid mapping either — the consumer is
    told the gate was skipped and the mapping still lands."""
    install_sh = _stale_source_tree(tmp_path)
    root = _make_consumer(tmp_path / "consumer")
    _run_install_from(install_sh, root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: fable\n")

    result = _run_install_from(install_sh, root, "--update", "--no-arm-hooks")

    assert "REFUSED" not in result.stdout, "an unusable checker was read as a refusal"
    # BOTH disclosure sites, not the token. `UNVALIDATED` is emitted by the
    # warning AND by the `record` line that reaches the install summary, so an
    # assertion on the bare word is satisfied by either one alone — delete the
    # other and the guard stays green. That is Q-340's shape, and the round
    # demonstrated it by deleting each in turn.
    assert "applying it UNVALIDATED" in result.stdout, (
        "the inline warning that the gate could not run is gone"
    )
    assert "model-roles: applied UNVALIDATED" in result.stdout, (
        "the durable record line is gone — the install summary no longer "
        "discloses that the gate was skipped"
    )
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "fable", (
        "a valid mapping was silently dropped because the gate could not run"
    )


def test_the_apply_distinguishes_a_malformed_config_from_an_invalid_mapping(tmp_path):
    """The distinction Phase 223 built (`ConfigShapeError` is exit 2, a bad
    mapping is exit 1), asserted in the arm that can still make it.

    This test used to demand the distinction from the PREVIEW. It cannot make it:
    the config it reads is the one the update replaces, and `Q-345`'s
    reproduction (c) showed the preview stating `unreadable config` over a
    perfectly readable one. So the property moves to the apply, where both inputs
    are final, and the preview is asserted to claim neither.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: [\n")

    preview = _run_install(root, "--update", "--dry-run", "--no-arm-hooks")
    assert "would REFUSE" not in preview.stdout
    assert "unreadable config" not in preview.stdout, (
        "the preview classified a config it reads before the update replaces it"
    )

    result = _run_install(root, "--update", "--no-arm-hooks")

    assert "cannot evaluate the model-role mapping" in result.stdout, (
        "a malformed YAML file was not distinguished from a bad mapping"
    )
    assert "invalid mapping" not in result.stdout, (
        "a malformed YAML file was reported as the consumer's model mapping "
        "being wrong"
    )
    # The PAYLOAD, and this is the one path where capturing it is load-bearing.
    # `check_skill_models.py` prints its exit-1 `FAIL:` block to stdout but every
    # exit-2 diagnostic to STDERR, so dropping `2>&1` from the capture leaves this
    # headline with an empty body and dumps the real error out of band. A
    # reviewer removed `2>&1` and the whole module stayed green — every assertion
    # read the note, none read what the note was introducing.
    payload = _indented_payload(result.stdout)
    assert payload, (
        "the warning printed a headline with no body: the consumer is told the "
        "gate could not read its inputs and not which file, line, or error"
    )
    assert any("error:" in line for line in payload), (
        f"the checker's own diagnostic did not reach the consumer: {payload!r}"
    )


def test_dry_run_writes_nothing_to_the_consumer_tree(tmp_path):
    """`--dry-run` prints "(dry-run mode — nothing will be written)". Nothing in
    the suite checked that.

    Found by the adversarial round, not by the author: deleting the `return 0`
    that ends the dry-run block lets the preview fall through into the resolver
    and REWRITE 30 pins in the consumer's tree — and that mutation survived 297
    tests across the twelve most relevant install modules, because every one of
    them asserts on stdout. A grep over `tests/` found no assertion anywhere that
    the command documented as read-only is read-only.

    Asserted against git rather than against a file list, so it covers deletions
    and additions too, and it is deliberately about the WHOLE tree rather than
    the model-role step that motivated it.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "installed")

    # An override that a real run WOULD act on, so the preview has work to skip.
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: fable\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "override")

    before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
    ).stdout.strip()
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "opus", (
        "vacuity: the pin is already at the value a real run would write, so this "
        "test could not observe the rewrite it exists to forbid"
    )

    _run_install(root, "--update", "--dry-run", "--no-arm-hooks")

    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True,
    ).stdout.strip()
    after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
    ).stdout.strip()

    assert not dirty, f"--dry-run modified the consumer's working tree:\n{dirty}"
    assert after == before, "--dry-run committed to the consumer's repository"
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "opus", (
        "--dry-run resolved the model-role markers for real"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 244 (`Q-345` § High): the three reproductions, each measured on one
# target minutes apart before any of this was written. They are separate tests
# because they fail in DIFFERENT directions — (a) fabricates a refusal, (b)
# promises a clean no-op where the apply refuses, (c) asserts an unreadable
# config over a readable one — and a single test would let two of the three be
# lost to a fix that only closed one.
# ─────────────────────────────────────────────────────────────────────────────

def test_the_preview_does_not_fabricate_a_refusal_when_the_source_adds_a_model(tmp_path):
    """Reproduction (a), the one with a cost: the documented one-key override.

    A release adds a model to `served:`/`inline_models:` — exactly what Phase 95
    did for `fable` — and the consumer maps `reasoning` to it, which is the
    override the config's own comments prescribe. Pre-fix the preview read the
    TARGET's `served_models.yml`, which the update is about to replace and which
    does not carry the new model yet, so it printed
    `⚠ would REFUSE … (30 FAIL lines)`. The apply then wrote every pin.

    Biased in the worst available direction: the documented reaction to "your
    override would NOT be applied" is to abort the update.
    """
    src = _source_copy(tmp_path)
    root = _make_consumer(tmp_path / "consumer")
    _run_install_from(src / "install.sh", root, "--packs", "python", "--no-arm-hooks")

    # Install FIRST, then add the model to the source, so the target's config is
    # the pre-release one. That ordering IS the mechanism: reversed, the target
    # already knows the model and there is nothing to fabricate.
    _rewrite_served(src, lambda d: (d["served"].append("newmodel"),
                                    d["inline_models"].append("newmodel")))
    (root / ".claude/served_models.local.yml").write_text(
        "roles:\n  reasoning: newmodel\n")

    preview = _run_install_from(src / "install.sh", root, "--update", "--dry-run",
                                "--no-arm-hooks")

    assert "would REFUSE" not in preview.stdout, (
        "the preview fabricated a refusal on the documented one-key override"
    )
    applied = _run_install_from(src / "install.sh", root, "--update", "--no-arm-hooks")
    assert "REFUSED" not in applied.stdout, (
        "vacuity check failed: the apply refused too, so the preview was not "
        "fabricating anything and this fixture reproduces nothing"
    )
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "newmodel", (
        "the override the preview would have warned against did not actually land"
    )


def test_the_preview_does_not_promise_a_no_op_when_the_source_sunsets_a_model(tmp_path):
    """Reproduction (b): Phase 223's ORIGINAL false negative, re-armed.

    The source SUNSETS a model — drops it from `served:`, which is what `served:`
    is for — and the consumer has a role mapped to it. Pre-fix the preview read
    the target's config, where the model is still served, and printed the literal
    `no-op under default mapping`; the apply REFUSED.
    """
    src = _source_copy(tmp_path)
    root = _make_consumer(tmp_path / "consumer")
    _run_install_from(src / "install.sh", root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: fable\n")

    def _sunset(d):
        d["served"] = [s for s in d["served"] if s != "fable"]
        d["inline_models"] = [s for s in d["inline_models"] if s != "fable"]
    _rewrite_served(src, _sunset)

    preview = _run_install_from(src / "install.sh", root, "--update", "--dry-run",
                                "--no-arm-hooks")

    assert "no-op under default mapping" not in preview.stdout, (
        "the preview promised a clean no-op for a mapping the apply refuses"
    )
    applied = _run_install_from(src / "install.sh", root, "--update", "--no-arm-hooks")
    assert "REFUSED" in applied.stdout, (
        "vacuity check failed: the apply did not refuse, so the sunset fixture "
        "never reproduced the disagreement"
    )


def test_a_partial_install_is_not_previewed_as_an_unreadable_config(tmp_path):
    """Reproduction (c): `⚠ would REFUSE … (unreadable config)` over a perfectly
    readable config.

    `.claude/skills` present but without the Sysop skills — a partial install,
    which is the state `--update` repairs. The checker's empty-population guard
    fires (exit 2), the preview rendered exit 2 as `unreadable config`, and the
    apply passed once the skills were reinstalled.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    import shutil
    shutil.rmtree(root / ".claude/skills")
    (root / ".claude/skills/my-own").mkdir(parents=True)
    (root / ".claude/skills/my-own/SKILL.md").write_text(
        "---\nname: mine\n---\n\nMy own skill.\n")

    preview = _run_install(root, "--update", "--dry-run", "--no-arm-hooks")

    assert "would REFUSE" not in preview.stdout
    assert "unreadable config" not in preview.stdout, (
        "a readable config was previewed as unreadable because the SKILLS tree "
        "was the thing that was missing"
    )
    # The config really is readable — otherwise the message would have been true.
    import yaml
    assert yaml.safe_load((root / ".claude/served_models.yml").read_text())["roles"], (
        "vacuity: the config this test calls readable does not parse"
    )
    applied = _run_install(root, "--update", "--no-arm-hooks")
    assert "REFUSED" not in applied.stdout, (
        "vacuity check failed: the apply refused too, so there was no "
        "disagreement to fix"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 244 (`Q-346`): the gate's exit-code vocabulary. Every non-zero exit it
# does not recognise used to be printed as a verdict on the consumer's mapping.
# ─────────────────────────────────────────────────────────────────────────────

def test_a_consumers_undecodable_file_is_not_reported_as_an_invalid_mapping(tmp_path):
    """`Q-346` leg 1, reproduced by execution before it was fixed.

    `.claude/skills/` is Claude Code's standard USER skill directory, so a
    consumer's own latin-1 note sits beside the shipped skills. The checker's
    `read_text(encoding="utf-8")` over `rglob("*.md")` raised, Python exited 1,
    and `install.sh` reads 1 as "invalid mapping" — so a consumer with NO
    override at all got `⚠ model-role mapping REFUSED (invalid mapping)` with a
    `UnicodeDecodeError` traceback indented beneath it.

    Guarding only the checker moved the crash into `resolve_skill_models.py`,
    which is how the other three sites in the family were found — by running the
    fix, not by reading the filing.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude/skills/my-own").mkdir(parents=True)
    (root / ".claude/skills/my-own/NOTES.md").write_bytes(
        "# Notas del café, año 2026\n".encode("latin-1"))

    result = _run_install(root, "--update", "--no-arm-hooks")

    assert "REFUSED" not in result.stdout, (
        "a consumer's own undecodable file was reported as their mapping being "
        "refused"
    )
    assert "Traceback" not in result.stdout, (
        "a Python traceback reached the consumer as install output"
    )
    assert "resolution skipped" not in result.stdout, (
        "the EXECUTOR crashed instead of the checker — the same defect one "
        "script over"
    )
    assert "model-roles: APPLIED" in result.stdout, (
        "the model-role step did not complete"
    )


def test_an_undecodable_file_does_not_blunt_a_real_refusal(tmp_path):
    """The over-permissive direction of the same fix, which is the half a
    skip-everything implementation would break.

    Same latin-1 file, but the consumer ALSO has a genuinely invalid mapping.
    The gate must still refuse, and must disclose the file it skipped rather
    than absorbing it.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude/skills/my-own").mkdir(parents=True)
    (root / ".claude/skills/my-own/NOTES.md").write_bytes(
        "# Notas del café, año 2026\n".encode("latin-1"))
    (root / ".claude/served_models.local.yml").write_text(
        "roles:\n  reasoning: best\nserved:\n  - best\n"
    )

    result = _run_install(root, "--update", "--no-arm-hooks")

    assert "REFUSED" in result.stdout, (
        "the read guard swallowed a real refusal along with the crash"
    )
    assert "not valid UTF-8 or not readable" in result.stdout, (
        "the skipped file was absorbed silently — a green-looking scan whose "
        "scope the reader cannot see"
    )
    assert not any("best" in v for v in _inline_pins(root).values())


def test_an_absent_checker_records_that_the_gate_was_skipped(tmp_path):
    """`Q-346` leg 4. The rc-3 sibling writes a `record`; this branch did not, so
    the install summary read `model-roles: APPLIED: …` with no trace that the
    gate had been skipped. The inline warning scrolls past; the summary is what a
    consumer reads back.

    Reachable only with the checker absent from BOTH trees, which is why it takes
    a source copy — `--update` re-copies the vendor dir before the gate runs.
    """
    src = _source_copy(tmp_path)
    (src / "core/companion/scripts/check_skill_models.py").unlink()

    root = _make_consumer(tmp_path / "consumer")
    _run_install_from(src / "install.sh", root, "--packs", "python", "--no-arm-hooks")

    result = _run_install_from(src / "install.sh", root, "--update", "--no-arm-hooks")

    assert "not present in the source tree or the vendor dir" in result.stdout, (
        "vacuity: the absent-checker branch never fired"
    )
    assert "model-roles: applied UNVALIDATED (checker not present" in result.stdout, (
        "the install summary does not record that the gate was skipped"
    )


def test_an_undefined_gate_exit_is_not_read_as_a_refusal(tmp_path):
    """`Q-346` leg 3. The apply arm tested `-eq 3` then `-ne 0`, so every exit
    code outside {0,1,2,3} became `REFUSED (invalid mapping)` — a verdict
    invented out of a code the gate does not understand. Measured at `da002b5`
    with a checker patched to exit 5: `⚠ model-role mapping REFUSED (invalid
    mapping)`.

    Not reachable with today's checker (0/1/2 only). Surviving a future
    checker's new code is the fix's stated purpose, so the fixture supplies one.
    An uncommitted edit, because that is what makes the Phase 24b divergence
    guard PRESERVE the stub instead of overwriting it — measured; a committed
    stub is replaced and the branch never fires.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "installed")
    # A VALID override, so "applies it UNVALIDATED" has an observable consequence.
    # Without one the default mapping is a byte-for-byte no-op and the outcome
    # assertion below cannot tell an apply from a decline — which is how the
    # guards lens got a `return 0` into this arm and survived.
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: fable\n")
    (root / "sysop/scripts/check_skill_models.py").write_text(
        "import sys\n"
        'if "--help" in sys.argv:\n'
        '    print("usage: check --managed-only"); raise SystemExit(0)\n'
        'print("checker says something new", file=sys.stderr); raise SystemExit(5)\n'
    )

    result = _run_install(root, "--update", "--no-arm-hooks")

    assert "REFUSED" not in result.stdout, (
        "an exit code the gate does not define was printed as a verdict on the "
        "consumer's mapping"
    )
    assert "exited 5, which is not one of its defined outcomes" in result.stdout, (
        "vacuity: the stub checker was overwritten and the catch-all never fired"
    )
    assert "model-roles: applied UNVALIDATED (gate returned undefined exit 5" \
        in result.stdout, (
            "the install summary does not record that the gate returned "
            "something it could not classify"
        )
    # THE OUTCOME, not the strings. The guards lens added a `return 0` to this arm
    # and it survived: both assertions above still passed while the mapping was
    # silently NOT applied. The rc-3 sibling has an outcome oracle and this arm —
    # the one this phase newly created — did not. "Applies unvalidated" has to mean
    # the pins actually moved.
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "fable", (
        "the arm says it applied the mapping UNVALIDATED and applied nothing"
    )


def test_the_capability_probe_survives_a_large_help_text(tmp_path):
    """`Q-347`. `producer | grep -q` under `set -o pipefail`: `grep -q` exits at
    the first match, the producer takes SIGPIPE, and `pipefail` returns ITS
    status — so a checker that prints the flag early and a large help text after
    is reported as NOT supporting the flag (rc 3, "applying it UNVALIDATED").

    Not reachable with the shipped checker, whose `--help` is ~811 bytes against
    a 64 KiB pipe buffer, which is why it was filed rather than fixed there. The
    probe is exercised directly, with a small-help control, because an
    end-to-end fixture cannot reach it.
    """
    big = tmp_path / "bigflag.py"
    big.write_text(
        "import sys\n"
        'sys.stdout.write("usage: check --managed-only\\n")\n'
        "sys.stdout.flush()\n"
        'sys.stdout.write("X" * (4 * 1024 * 1024) + "\\n")\n'
    )
    small = tmp_path / "smallflag.py"
    small.write_text('print("usage: check --managed-only")\n')

    # The function is SOURCED out of install.sh, not retyped here: a copy of the
    # idiom in the test would keep passing after the shipped one regressed.
    script = (
        "set -euo pipefail\n"
        f'eval "$(sed -n "/^_model_role_checker_supports() {{/,/^}}/p" {INSTALL_SH})"\n'
        f'if _model_role_checker_supports "{sys.executable}" "$1" "--managed-only"; '
        "then echo SUPPORTED; else echo UNSUPPORTED; fi\n"
    )

    def _run_probe(checker):
        proc = subprocess.run(
            ["bash", "-c", script, "bash", str(checker)],
            capture_output=True, text=True,
        )
        return proc.stdout.strip()

    assert _run_probe(small) == "SUPPORTED", (
        "control failed: the probe cannot detect the flag even on a small help "
        "text, so the assertion below proves nothing"
    )
    assert _run_probe(big) == "SUPPORTED", (
        "the probe reported a supported flag as unsupported because the help "
        "text outran the pipe buffer — Q-347"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Phase 244's own adversarial round. Every test below exists because a lens
# demonstrated the fix wrong, not because the filings asked for it.
# ─────────────────────────────────────────────────────────────────────────────

def test_the_preview_does_not_promise_more_than_the_apply_delivers(tmp_path):
    """The round's § High, and the sharpest finding against this phase.

    The preview's second line said, unconditionally, that a bad mapping "is
    refused and every pin keeps its current value". **Three of the apply arm's
    six outcomes contradict that** — rc 3, an undefined rc, and a checker missing
    from both trees all print `applying it UNVALIDATED` and DO rewrite pins. On
    the rc-3 path — a consumer whose vendored checker is preserved-as-modified,
    which is `Q-330`'s own population — the parent commit printed a TRUE early
    warning and this phase replaced it with a FALSE reassurance: `model: best`
    across 21 files behind a preview that said the apply would refuse it.

    A preview that states a limit and then overstates what happens next has not
    stopped making claims it cannot stand behind. It has moved them one sentence
    along.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    checker = _age_vendored_checker(root)
    _assert_checker_is_really_stale(checker, root)
    (root / ".claude/served_models.local.yml").write_text(
        "roles:\n  reasoning: best\n  mechanical: best\n  quick: best\n"
        "served:\n  - best\n"
    )

    preview = _run_install(root, "--update", "--dry-run", "--no-arm-hooks")
    applied = _run_install(root, "--update", "--no-arm-hooks")

    # The fixture must actually reach the arm this test is about, or the
    # assertions below are about a path nothing took.
    assert "applying it UNVALIDATED" in applied.stdout, (
        "vacuity: the apply did not take an unvalidated path, so the preview had "
        "nothing to overstate"
    )
    # NOT the bare token. The guards lens defeated `"UNVALIDATED" in stdout` with a
    # sentence that CONTAINS it and states the opposite — "the run refuses rather
    # than applying the mapping UNVALIDATED" — which re-arms this test's own § High
    # while staying green. Pin the clause that only the honest wording produces.
    assert "applies the mapping UNVALIDATED" in preview.stdout, (
        "the preview promises the apply refuses a bad mapping and keeps every "
        "pin, on a run where the apply applies it unvalidated and rewrites them"
    )
    assert "refuses rather than applying" not in preview.stdout, (
        "the preview states the OPPOSITE outcome while still carrying the token "
        "this assertion used to look for"
    )


def test_adopt_does_not_promise_a_step_it_never_takes(tmp_path):
    """`cmd_adopt` runs the pipeline under `DRY_RUN=1` to compute managed_paths
    and writes only the lock, so a forward reference to what "an install or
    update" does is a promise about a run that will not happen."""
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "installed")
    (root / ".claude/sysop.lock").unlink()

    result = _run_install(root, "--adopt", "--packs", "python", "--no-arm-hooks")

    assert "an install or update checks it instead" not in result.stdout, (
        "--adopt forward-references an apply it never performs"
    )


@pytest.mark.parametrize("missing", [
    "core/companion/.claude/served_models.yml",
    "core/skills",
    "core/companion/scripts/resolve_skill_models.py",
])
def test_a_source_missing_a_piece_the_target_has_is_not_a_skip(tmp_path, missing):
    """`Q-344`'s fix, over-corrected. The predicate that decides whether the step
    runs is *(this source installs it) OR (the target already has it)*. Testing
    only the target was the filed bug; testing only the source reversed the
    direction of the same false skip, which the round demonstrated with a source
    clone whose `served_models.yml` had been deleted."""
    # PARAMETRIZED over all three legs. The first cut deleted only
    # `served_models.yml`, and the guards lens reproduced the filed defect verbatim
    # on either of the other two: a disjunction guarded on one of its three terms
    # is guarded on none of them.
    import shutil

    src = _source_copy(tmp_path, commit=False)
    target = src / missing
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    _commit_source(src)

    root = _make_consumer(tmp_path / "consumer")
    # Install from the REAL source so the target ends up complete...
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "installed")

    preview = _run_install_from(src / "install.sh", root, "--update", "--dry-run",
                                "--no-arm-hooks")
    applied = _run_install_from(src / "install.sh", root, "--update", "--no-arm-hooks")

    assert "would skip model-role resolution" not in preview.stdout, (
        "the preview announced a skip because THIS SOURCE lacks a file the "
        "target already has"
    )
    assert "model-roles: APPLIED" in applied.stdout, (
        "vacuity: the apply skipped too, so there was no disagreement"
    )


def test_rc2_declines_to_apply_even_when_the_rewrite_would_succeed(tmp_path):
    """The author battery's `RC06`, which survived TWICE before this test existed.

    rc 2 means the gate could not read its inputs, and Phase 244 deliberately kept
    the control flow that declines to apply. Nothing observed it. The first oracle
    asserted the pins were still `opus`; the second asserted `model-roles: APPLIED`
    was absent. **Both are satisfied by the RESOLVER failing**, because every
    natural rc-2 cause — a missing, malformed or unreadable config, a missing
    skills root — breaks the resolver too, so deleting the rc-2 `return 0` changed
    nothing observable.

    The one rc-2 cause that leaves the resolver perfectly able to run is an empty
    managed population, and `--update` repairs that before the gate sees it. So
    the fixture supplies a checker that returns 2 over inputs that are entirely
    valid: now the rewrite WOULD land, and only the `return 0` stops it.

    Uncommitted, because that is what makes the Phase 24b divergence guard
    preserve the stub instead of overwriting it — measured; a committed stub is
    replaced and the branch never fires.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "installed")
    # A VALID override the resolver would happily apply.
    (root / ".claude/served_models.local.yml").write_text("roles:\n  reasoning: fable\n")
    (root / "sysop/scripts/check_skill_models.py").write_text(
        "import sys\n"
        'if "--help" in sys.argv:\n'
        '    print("usage: check --managed-only"); raise SystemExit(0)\n'
        'print("error: config not found: nowhere.yml", file=sys.stderr)\n'
        "raise SystemExit(2)\n"
    )

    result = _run_install(root, "--update", "--no-arm-hooks")

    assert "cannot evaluate the model-role mapping" in result.stdout, (
        "vacuity: the stub checker was overwritten and the rc-2 arm never fired"
    )
    assert "model-roles: APPLIED" not in result.stdout, (
        "rc 2 stopped declining: the gate could not read its inputs and the "
        "rewrite ran anyway"
    )
    assert _fm_model(root / ".claude/skills/auto-build/SKILL.md") == "opus", (
        "the override landed behind a gate that never evaluated it — this is the "
        "assertion the earlier oracles could not make, because every other rc-2 "
        "cause also breaks the resolver"
    )


def test_the_capability_probe_leaves_no_bytecode_in_the_consumer_tree(tmp_path):
    """`PYTHONDONTWRITEBYTECODE` on the probe, which the guards lens deleted and
    walked through the whole suite.

    Phase 212 closed exactly this: `check_skill_models.py` top-level-imports
    `_model_roles` and `migrate_skill_model`, so those execute before argparse
    sees `--help`, and without the guard CPython leaves
    `sysop/scripts/__pycache__/*.pyc` in the consumer's tree — which a consumer
    with no bytecode ignore then tracks, and which `--update` rewrites on every
    run, dirtying a clean tree. The probe is a NEW invocation added by the same
    phase that carries the comment explaining the rule ten lines below it, and
    `test_dry_run_writes_nothing_to_the_consumer_tree` cannot reach it because the
    probe now runs only on the apply path.
    """
    root = _make_consumer(tmp_path / "consumer")
    _run_install(root, "--packs", "python", "--no-arm-hooks")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "installed")

    _run_install(root, "--update", "--no-arm-hooks")

    stray = sorted(p.name for p in (root / "sysop/scripts").rglob("*.pyc"))
    assert not stray, (
        f"the install left bytecode in the consumer's vendor dir: {stray}"
    )
    assert not (root / "sysop/scripts/__pycache__").exists(), (
        "the install created __pycache__ in the consumer's vendor dir"
    )
