"""Phase 262 (GDP brief § D): the 2b convention agent gets a role of its own.

`/review-close` Step 2b spawns two deep agents per target — a convention gate
and a security twin — and both were pinned to `reasoning`. GDP measured the
convention agent at a median 8.6M cache-read and ~$7.60 a spawn against ~$3.00
on Sonnet 5, across 43 transcripts; it is the deep spawn a close runs most
often. Splitting it onto `convention-gate` makes it the one pin a consumer can
move from `served_models.local.yml` without moving the security twin beside it
or anything else on `reasoning`.

**The default is `opus`, so this phase ships a knob and no behaviour change.**
That is deliberate — an upgrade must not silently downgrade anybody's review —
and it is also what these tests must pin, because a role whose default drifted
to `sonnet` would change every consumer's convention gate on their next
`--update` with nothing to catch it.

The consequential test is the last one: it runs the real resolver under a real
consumer override and asserts exactly one pin moves. Everything above it is
structure that could be true while the knob does nothing.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "core/skills/review-close/SKILL.md"
CONFIG = REPO_ROOT / "core/companion/.claude/served_models.yml"
RESOLVER = REPO_ROOT / "core/companion/scripts/resolve_skill_models.py"
MARKER = "<!-- sysop:role=convention-gate -->"


def _cfg():
    return yaml.safe_load(CONFIG.read_text())


def _resolved_roles():
    """The roles map AS THE RESOLVER SEES IT, with aliases followed.

    Reading the raw YAML is not the same question and was the first version of
    these two tests: `convention-gate` ships as the role NAME `reasoning`, so a
    raw read says `'reasoning'` and tells you nothing about what a pin becomes.
    """
    sys.path.insert(0, str(REPO_ROOT / "core/companion/scripts"))
    import _model_roles as m  # noqa: E402  (path set above)

    roles, _ = m.load_roles_config(CONFIG, None)
    return roles


def test_the_role_exists_and_defaults_to_opus():
    """A default install must be unchanged. If this ever RESOLVES to `sonnet`,
    every consumer's convention gate moved on an update they did not ask for."""
    assert _resolved_roles()["convention-gate"] == "opus"


def test_the_role_resolves_to_a_served_and_inline_legal_model():
    """`check_skill_models.py`'s two allowlists. The inline one is the sharp
    edge: the Agent tool's `model` parameter is a closed enum, so a role
    governing an inline pin that resolves outside it fails at spawn time,
    mid-skill, in every close."""
    cfg = _cfg()
    resolved = _resolved_roles()["convention-gate"]
    assert resolved in cfg["served"]
    assert resolved in cfg["inline_models"]


def test_exactly_one_pin_in_the_tree_carries_the_marker():
    """Scoped to the 2b convention spawn and nothing else. A second marker means
    somebody widened the role by copy-paste, which silently re-couples the
    security twin to a knob labelled for the convention gate."""
    hits = [(p.relative_to(REPO_ROOT), p.read_text().count(MARKER))
            for p in (REPO_ROOT / "core/skills").rglob("*.md")
            if MARKER in p.read_text()]
    assert hits == [(SKILL.relative_to(REPO_ROOT), 1)], hits


def test_the_marker_sits_on_the_convention_spawn_not_the_security_twin():
    """The two spawns are ~120 lines apart and structurally identical. Binding
    the marker to the wrong one is the single most plausible authoring error
    here, and it would move the security agent while leaving the expensive one
    on opus — the exact inverse of the intent.

    **The round defeated the first version of this test with a DECOY.** It moved
    the marker onto a new bullet two lines down and gave that bullet its own
    `description: "Convention check: <target>"` — and every assertion still
    passed, because a nearby description is not identity. Through the real
    resolver, the consumer's override then rewrote the decoy while the actual
    Step 2b spawn kept `model: "opus"`: the knob disconnected, silently, with the
    guards green. So identity is now pinned to the SPAWN BLOCK — the marked pin
    must sit in the same bullet list as the convention agent's prompt, above the
    text only that agent's prompt contains.
    """
    lines = SKILL.read_text().splitlines()
    marked = [i for i, l in enumerate(lines) if MARKER in l]
    assert len(marked) == 1
    idx = marked[0]
    assert 'model: "opus"' in lines[idx]

    # The convention spawn is the block whose prompt opens with this sentence —
    # it appears once in the file and belongs to no other agent.
    prompt_anchor = "You are the final convention gate before this branch merges"
    anchors = [i for i, l in enumerate(lines) if prompt_anchor in l]
    assert len(anchors) == 1, f"the convention prompt moved or was duplicated: {anchors}"

    # The pin must PRECEDE that prompt and belong to the same spawn: no other
    # `description:` bullet may intervene, which is exactly what a decoy is.
    assert idx < anchors[0], "the marked pin is not above the convention prompt"
    between = lines[idx + 1:anchors[0]]
    descriptions = [l for l in between if "description:" in l]
    assert len(descriptions) == 1, (
        f"expected exactly one `description:` between the marked pin and the "
        f"convention prompt; found {len(descriptions)} — a second one means the "
        f"marker may be riding a decoy bullet:\n  " + "\n  ".join(descriptions)
    )
    assert 'description: "Convention check:' in descriptions[0], descriptions[0]
    assert "Security check" not in "\n".join(between)


def test_the_security_twin_is_still_governed_by_reasoning():
    """The twin must carry NO per-pin marker, so it inherits the file-level
    `inline=reasoning`. If it ever gains one, the split has stopped being a
    split."""
    text = SKILL.read_text()
    twin = [l for l in text.splitlines() if 'description: "Security check:' in l]
    assert twin, "the security spawn moved or was renamed"
    idx = text.splitlines().index(twin[0])
    block = "\n".join(text.splitlines()[max(0, idx - 8):idx + 2])
    assert 'model: "opus"' in block, block
    assert "sysop:role=" not in block, block


def test_a_consumer_override_moves_the_convention_pin_and_only_it(tmp_path):
    """The knob, exercised end to end through the shipped resolver.

    This is the test that fails if the marker, the role, the resolver's marker
    regex, or the local-config layering ever stop lining up — the four things
    that must all agree for a one-key override to reach one pin.
    """
    skills = tmp_path / "skills"
    (skills / "review-close").mkdir(parents=True)
    shutil.copy(SKILL, skills / "review-close" / "SKILL.md")
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    shutil.copy(CONFIG, cfg_dir / "served_models.yml")
    (cfg_dir / "served_models.local.yml").write_text(
        "roles:\n  convention-gate: sonnet\n")

    r = subprocess.run(
        [sys.executable, str(RESOLVER), "--root", str(skills),
         "--config", str(cfg_dir / "served_models.yml"),
         "--local", str(cfg_dir / "served_models.local.yml"), "--apply"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    out = (skills / "review-close" / "SKILL.md").read_text().splitlines()
    moved = [l for l in out if 'model: "sonnet"' in l]
    assert len(moved) == 1, moved
    assert MARKER in moved[0]
    assert 'description: "Security check:' not in "\n".join(out[out.index(moved[0]):][:6])
    # ...and the twin did NOT move. Its pin and its description share one line,
    # so this reads the twin directly rather than inferring it from a window.
    twin = [l for l in out if 'description: "Security check:' in l]
    assert len(twin) == 1, twin
    assert 'model: "opus"' in twin[0], twin[0]
    assert 'model: "sonnet"' not in twin[0], twin[0]
    assert "APPLIED: 1 pin(s)" in r.stdout, r.stdout


def test_the_default_config_is_a_no_op_for_this_role(tmp_path):
    """No local override → zero bytes changed. A default install must not
    diverge from source, which is the property `resolve_skill_models.py`
    documents for the whole tree and this role must not break."""
    skills = tmp_path / "skills"
    (skills / "review-close").mkdir(parents=True)
    shutil.copy(SKILL, skills / "review-close" / "SKILL.md")
    before = (skills / "review-close" / "SKILL.md").read_bytes()
    r = subprocess.run(
        [sys.executable, str(RESOLVER), "--root", str(skills),
         "--config", str(CONFIG), "--local", str(tmp_path / "absent.yml"), "--apply"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (skills / "review-close" / "SKILL.md").read_bytes() == before


# ── Phase 262's review round, lens 1 (execution) ─────────────────────────────
# The round installed a PRE-262 tree, set the documented cheap lever
# (`reasoning: sonnet`), ran a real `--update` to 262, and watched the 2b
# convention pin move sonnet -> opus. The phase's record claimed "no behaviour
# change"; that was true only on the default map. The fix is that the role's
# shipped value is the ROLE NAME `reasoning`, not a literal model.

def _resolve(tmp_path, local_text):
    skills = tmp_path / "skills"
    (skills / "review-close").mkdir(parents=True)
    shutil.copy(SKILL, skills / "review-close" / "SKILL.md")
    local = tmp_path / "served_models.local.yml"
    if local_text is not None:
        local.write_text(local_text)
    r = subprocess.run(
        [sys.executable, str(RESOLVER), "--root", str(skills), "--config", str(CONFIG),
         "--local", str(local), "--apply"], capture_output=True, text=True)
    body = (skills / "review-close" / "SKILL.md").read_text().splitlines()
    conv = [l for l in body if MARKER in l]
    twin = [l for l in body if 'description: "Security check:' in l]
    assert len(conv) == 1 and len(twin) == 1
    def model(line):
        import re
        m = re.search(r'model: "([a-z0-9-]+)"', line)
        return m.group(1) if m else None
    return r, model(conv[0]), model(twin[0])


def test_the_role_is_an_alias_not_a_literal():
    """The shipped value must be the role NAME. A literal here is what silently
    raised the pin back to opus for consumers who had chosen the cheap lever."""
    raw = yaml.safe_load(CONFIG.read_text())["roles"]["convention-gate"]
    assert raw == "reasoning", (
        f"convention-gate ships as {raw!r}; a literal model here re-introduces "
        "the upgrade regression the round found"
    )


def test_a_reasoning_override_still_reaches_the_convention_pin(tmp_path):
    """THE REGRESSION. A consumer on `reasoning: sonnet` had both 2b agents on
    sonnet before this phase; they must still, or the phase silently raised the
    most-run deep spawn back to opus on their next update."""
    r, conv, twin = _resolve(tmp_path, "roles:\n  reasoning: sonnet\n")
    assert r.returncode == 0, r.stderr
    assert (conv, twin) == ("sonnet", "sonnet"), (conv, twin)


def test_an_explicit_convention_gate_override_wins_over_reasoning(tmp_path):
    """The knob still has to be reachable independently — that is the point of
    the split, and an alias that could not be overridden would have removed it."""
    r, conv, twin = _resolve(
        tmp_path, "roles:\n  reasoning: sonnet\n  convention-gate: haiku\n")
    assert r.returncode == 0, r.stderr
    assert (conv, twin) == ("haiku", "sonnet"), (conv, twin)


def test_the_alias_resolves_to_opus_by_default(tmp_path):
    """Vacuity control: the two tests above could both pass with the alias
    resolving to nothing useful. On the default map it must be opus."""
    r, conv, twin = _resolve(tmp_path, None)
    assert r.returncode == 0, r.stderr
    assert (conv, twin) == ("opus", "opus"), (conv, twin)


def test_a_misspelled_role_value_still_fails_closed(tmp_path):
    """Fail-closed is why this is an alias TABLE and not a fallback. A value that
    is neither a role name nor a served model must be rejected, not inherited."""
    (tmp_path / "local.yml").write_text("roles:\n  convention-gate: sonnett\n")
    r = subprocess.run(
        [sys.executable, str(REPO_ROOT / "core/companion/scripts/check_skill_models.py"),
         "--root", str(REPO_ROOT / "core/skills"), "--config", str(CONFIG),
         "--local", str(tmp_path / "local.yml")], capture_output=True, text=True)
    assert r.returncode == 1, r.stdout


def test_an_alias_cycle_is_a_named_refusal_not_a_traceback(tmp_path):
    """A cycle must not hang, and must not reach the operator as a stack trace."""
    (tmp_path / "local.yml").write_text("roles:\n  reasoning: convention-gate\n")
    skills = tmp_path / "skills"
    (skills / "review-close").mkdir(parents=True)
    shutil.copy(SKILL, skills / "review-close" / "SKILL.md")
    r = subprocess.run(
        [sys.executable, str(RESOLVER), "--root", str(skills), "--config", str(CONFIG),
         "--local", str(tmp_path / "local.yml"), "--apply"], capture_output=True, text=True)
    assert r.returncode == 1, r.stdout
    assert "alias cycle" in r.stderr, r.stderr
    assert "Traceback" not in r.stderr, r.stderr


# ── Phase 262's review round, lens 3 (record truth) ──────────────────────────

# The shape that matters is an ENUMERATION — the role names joined by a list
# delimiter — not any line using both words. The first cut of this predicate
# swept in four legitimate sites (`/auto-fix`'s own mechanical pin, and three
# prose lines of the form "Reasoning role, not quick. The core is mechanical,
# but ..."), which is the over-strictness half of the same mistake.
_ROLE_ENUM = re.compile(
    r"`?reasoning`?\s*(?:/|,|·|\band\b)\s*"
    r"(?:`?convention-gate`?\s*(?:/|,|·|\band\b)\s*)?`?mechanical",
    re.I,
)


def _role_enumeration_offenders():
    offenders = []
    for root in ("core", "docs"):
        for path in sorted((REPO_ROOT / root).rglob("*")):
            if not path.is_file() or path.suffix not in {".md", ".yml", ".html", ".example", ".py"}:
                continue
            if "tests" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for n, line in enumerate(text.splitlines(), 1):
                if "convention-gate" in line:
                    continue
                if _ROLE_ENUM.search(line):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{n}  {line.strip()[:110]}")
    return offenders


def test_the_role_enumeration_predicate_is_not_vacuous():
    """Positive control. A guard that sweeps a whole tree and finds nothing is
    indistinguishable from a guard whose regex matches nothing — which is the
    failure mode this repo's record calls a vacuous guard. These are the exact
    shapes the round found shipped, so if the predicate ever stops matching them
    it fails here rather than going quietly green over the tree."""
    was_shipped = [
        "`reasoning` and `mechanical` both govern inline pins today, so mapping either",
        "Skills pin a ROLE (`reasoning`/`mechanical`/`quick`) via a body marker",
        "Skills pin *roles* (`reasoning` / `mechanical` / `quick`), and served_models.yml",
        "Pinned skills declare <em>roles</em> — reasoning, mechanical, quick — not models",
        "# WHY: skills pin a ROLE (reasoning / mechanical / quick), not a model",
        "**Map `reasoning` and `mechanical` to one of `opus` / `sonnet`.**",
    ]
    for line in was_shipped:
        assert _ROLE_ENUM.search(line), f"predicate no longer matches a real shipped shape: {line}"
    # ...and the four legitimate lines it must NOT match.
    legitimate = [
        "mixes roles — e.g. /auto-fix's mechanical fix agents vs. its reasoning",
        '- Set `model: "sonnet"` <!-- sysop:role=mechanical --> — the **mechanical** role',
        "**Reasoning role, not quick.** The git-log→classify core is mechanical, but the value",
        "**Reasoning role.** The git-log→classify core is mechanical, but the value is synthesis",
    ]
    for line in legitimate:
        assert not _ROLE_ENUM.search(line), f"predicate is over-strict on: {line}"


def test_no_shipped_file_enumerates_the_roles_without_convention_gate():
    """The class the round found, made mechanical.

    The phase corrected `docs/configuration.md`'s "Map `reasoning` and
    `mechanical` to one of ..." warning and wrote that up as *the* consumer-facing
    defect. It was one instance of a class: SEVEN more shipped files enumerated
    the role set, including `WORKFLOW.md`'s copy of the identical safety warning
    and both public-monograph mentions. The round named six; a sweep run after
    fixing those found two more. So the fix is not a longer list of sites — it is
    this guard, which fails on the next one.

    Scoped to files that enumerate roles ALONGSIDE `served_models`/marker
    vocabulary, so ordinary prose using the English word "mechanical" (the
    convention-promotion sections, `/auto-fix`'s own pin, "mechanically
    searchable") is not swept in.
    """
    offenders = _role_enumeration_offenders()
    assert not offenders, (
        "shipped files enumerate the model roles without `convention-gate`:\n  "
        + "\n  ".join(offenders)
        + "\n\nEvery one of these is read by a consumer deciding what to put in "
          "served_models.local.yml. A role that governs an INLINE pin and is "
          "missing from these lists is a spawn-time break the docs do not warn about."
    )


def test_this_module_is_still_collected():
    """The twin of `test_worktree_root_env`'s collection guard, and the same
    finding: the round deleted BOTH new modules and the whole suite produced one
    unrelated failure. Nothing asserted they exist. Three of the round's thirteen
    survivors were produced by weakening a guard rather than the code — dropping
    a parametrize entry, stubbing a body, renaming the test the docstring calls
    "the consequential" one — each of which let one of the AUTHOR's own scored
    mutations back in, silently."""
    import test_convention_gate_role as mod

    tests = [n for n in dir(mod) if n.startswith("test_")]
    assert len(tests) >= 15, (
        f"this module collects {len(tests)} test functions; it had 15 when the round "
        f"closed. A drop means a guard was renamed or removed — say which in the commit."
    )
    for required in (
        "test_a_consumer_override_moves_the_convention_pin_and_only_it",
        "test_the_marker_sits_on_the_convention_spawn_not_the_security_twin",
        "test_a_reasoning_override_still_reaches_the_convention_pin",
        "test_no_shipped_file_enumerates_the_roles_without_convention_gate",
        "test_the_role_enumeration_predicate_is_not_vacuous",
    ):
        assert required in tests, f"a named round-closing guard is gone: {required}"
