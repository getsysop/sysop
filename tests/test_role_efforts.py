"""Phase 381 (`Q-675`): a role carries an effort, and the resolver carries it into every inline spawn.

The Agent tool takes a per-spawn `effort` since Claude Code 2.1.292. `served_models.yml` gains a
sibling `efforts:` map; an inline pin carries the level as an effort segment written right after
its model pin, in the pin's own style; `resolve_skill_models.py` inserts, rewrites or removes that
segment; `check_skill_models.py` refuses a level outside the tool's enum and an `efforts:` key that
names no role. These tests drive the real functions and the real scripts.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
CONFIG = REPO_ROOT / "core/companion/.claude/served_models.yml"
SKILLS = REPO_ROOT / "core/skills"
sys.path.insert(0, str(SCRIPTS))
import _model_roles as m  # noqa: E402  (path set above)

STYLE_A = '- `model`: `"opus"` <!-- sysop:role=executor -->\n'
STYLE_B = '- `model: "opus"` <!-- sysop:role=executor --> (prose)\n'
MARKED = "<!-- sysop:model-roles frontmatter=reasoning inline=reasoning -->\n"
ROLES = {"reasoning": "opus", "executor": "sonnet"}


def _cfg(tmp_path, body, name="local.yml"):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


# ── the segment: parsed, inserted, rewritten, removed ─────────────────────────
@pytest.mark.parametrize("line,segment", [
    (STYLE_A, ', `effort`: `"high"`'),
    (STYLE_B, ', `effort: "high"`'),
])
def test_an_effort_is_inserted_in_the_pins_own_style(line, segment):
    out, changes = m.resolve_text(MARKED + line, ROLES, {"reasoning": None, "executor": "high"})
    assert segment in out, out
    assert ("effort", "executor", None, "high") == changes[-1][1:], changes
    pins = [p for p in m.analyze_text(out) if p.kind == "inline"]
    assert [(p.value, p.effort) for p in pins] == [("sonnet", "high")], pins


def test_an_effort_is_rewritten_then_removed_and_the_round_trip_is_exact():
    src = MARKED + STYLE_A
    high, _ = m.resolve_text(src, ROLES, {"executor": "high"})
    low, changes = m.resolve_text(high, ROLES, {"executor": "low"})
    assert '`effort`: `"low"`' in low and '"high"' not in low, low
    assert [c[1:] for c in changes] == [("effort", "executor", "high", "low")]
    gone, _ = m.resolve_text(low, {"reasoning": "opus", "executor": "opus"}, {"executor": None})
    assert gone == src, gone


def test_a_resolve_with_no_efforts_map_leaves_every_segment_alone():
    """A caller predating `Q-675` passes no efforts; it must not strip the shipped ones."""
    src = MARKED + '- `model`: `"sonnet"`, `effort`: `"high"` <!-- sysop:role=executor -->\n'
    out, changes = m.resolve_text(src, ROLES)
    assert out == src and changes == [], (out, changes)


def test_the_resolve_is_idempotent():
    once, _ = m.resolve_text(MARKED + STYLE_A + STYLE_B, ROLES, {"executor": "max"})
    twice, changes = m.resolve_text(once, ROLES, {"executor": "max"})
    assert twice == once and changes == [], changes


def test_an_effort_elsewhere_on_the_line_is_prose_not_a_pin():
    """Position is the binding: only a segment right after the model pin belongs to it."""
    line = '- `model`: `"opus"` <!-- sysop:role=executor --> then `effort: "max"` in prose\n'
    pins = [p for p in m.analyze_text(MARKED + line) if p.kind == "inline"]
    assert [p.effort for p in pins] == [None], pins
    out, _ = m.resolve_text(MARKED + line, ROLES, {"executor": None})
    assert '`effort: "max"` in prose' in out, out


# ── the config: inheritance, overrides, refusals ──────────────────────────────
def test_the_shipped_efforts_resolve_with_inheritance(tmp_path):
    base = _cfg(tmp_path, "roles:\n  reasoning: opus\n  plan-review: reasoning\n"
                          "  executor: sonnet\nefforts:\n  reasoning: high\n", "base.yml")
    efforts = m.load_role_efforts(base, None)
    assert efforts == {"reasoning": "high", "plan-review": "high", "executor": None}, efforts


def test_a_local_entry_wins_and_none_means_no_argument(tmp_path):
    base = _cfg(tmp_path, "roles:\n  reasoning: opus\n  plan-review: reasoning\n"
                          "efforts:\n  reasoning: high\n", "base.yml")
    local = _cfg(tmp_path, "efforts:\n  plan-review: none\n  reasoning: max\n")
    assert m.load_role_efforts(base, local) == {"reasoning": "max", "plan-review": None}


def test_an_explicit_none_stops_the_follow(tmp_path):
    base = _cfg(tmp_path, "roles:\n  reasoning: opus\n  planner: reasoning\n"
                          "efforts:\n  reasoning: high\n  planner:\n", "base.yml")
    assert m.load_role_efforts(base, None)["planner"] is None


@pytest.mark.parametrize("body,needle", [
    ("efforts:\n  exectuor: high\n", "'exectuor'"),
    ("efforts:\n  executor: ultra\n", "'ultra'"),
    ("efforts:\n  executor: High\n", "'High'"),
])
def test_a_wrong_entry_is_a_named_refusal(tmp_path, body, needle):
    local = _cfg(tmp_path, body)
    with pytest.raises(m.EffortConfigError, match=needle):
        m.load_role_efforts(CONFIG, local)


def test_a_non_mapping_efforts_is_a_shape_error(tmp_path):
    with pytest.raises(m.ConfigShapeError, match="must be a mapping"):
        m.load_role_efforts(CONFIG, _cfg(tmp_path, "efforts: high\n"))


# ── the scripts ───────────────────────────────────────────────────────────────
def _run(script, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                          capture_output=True, text=True)


@pytest.mark.parametrize("script", ["check_skill_models.py", "resolve_skill_models.py"])
def test_both_scripts_refuse_a_bad_effort_with_exit_1(tmp_path, script):
    local = _cfg(tmp_path, "efforts:\n  executor: ultra\n")
    r = _run(script, "--root", SKILLS, "--config", CONFIG, "--local", local)
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "efforts:" in r.stderr and "Traceback" not in r.stderr, r.stderr


def test_the_checker_refuses_an_illegal_literal_effort(tmp_path):
    """The plugin path has no resolver, so the literal in the file is what the tool gets."""
    root = tmp_path / "skills" / "x"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        MARKED + '- `model`: `"sonnet"`, `effort`: `"ultra"` <!-- sysop:role=executor -->\n')
    r = _run("check_skill_models.py", "--root", tmp_path / "skills", "--config", CONFIG,
             "--local", tmp_path / "absent.yml")
    assert r.returncode == 1 and "'ultra'" in r.stdout, r.stdout


def test_the_listing_shows_each_inline_pins_effort():
    r = _run("check_skill_models.py", "--root", SKILLS, "--config", CONFIG,
             "--local", REPO_ROOT / "absent.yml", "--list")
    assert r.returncode == 0, r.stderr
    executor = [l for l in r.stdout.splitlines() if "executor -> sonnet" in l]
    assert len(executor) == 3 and all("@ high" in l for l in executor), executor
    # Phase 389: `planner` follows `reasoning: high`; `mechanical` has no entry.
    assert all("@ high" in l for l in r.stdout.splitlines() if "planner ->" in l)
    assert all("@ session" in l for l in r.stdout.splitlines() if "mechanical ->" in l and "(inline)" in l)


def test_the_resolver_counts_efforts_apart_from_pins(tmp_path):
    import shutil
    skills = tmp_path / "skills"
    shutil.copytree(SKILLS, skills)
    local = _cfg(tmp_path, "efforts:\n  executor: none\n")
    r = _run("resolve_skill_models.py", "--root", skills, "--config", CONFIG,
             "--local", local, "--apply")
    assert r.returncode == 0, r.stderr
    # The three executor pins drop their segment; the ten reasoning-tier and three gate
    # pins keep theirs (Phase 389), so the summary names those roles and not the executor.
    assert "APPLIED: 0 pin(s) and 3 effort(s)" in r.stdout, r.stdout
    assert "[efforts: convention-gate=high, plan-review=high, planner=high, reasoning=high, security-gate=high]" in r.stdout, r.stdout


def test_every_line_that_copies_7a_says_where_effort_comes_from():
    """`/claim-task` 7b, 7e and 8c, and `/auto-build`'s Step 7b, say "same agent
    parameters as 7a except …". With a planner effort set and theirs at `none`, an agent
    copying 7a would pass the planner's. The round's execution lens found the two
    plan-review lines missing the clause after the executor lines had it, so the
    population is every such line, not a role."""
    lines = []
    for skill in ("claim-task", "auto-build"):
        text = (SKILLS / f"{skill}/SKILL.md").read_text(encoding="utf-8")
        lines += [l for l in text.splitlines()
                  if re.search(r"[Ss]ame agent param(?:eter)?s as (?:Step )?7a", l)]
    assert len(lines) == 4, lines
    # The whole parenthetical, closed: lens 3 kept the clause and appended "; if 7a set one,
    # reuse it" inside the same parentheses, which a substring pin read as compliant.
    assert all("(the `effort` is this line's, never 7a's: with none here, pass none)" in l
               for l in lines), lines


@pytest.mark.parametrize("body", ["efforts: high\n", "roles: [oops\n"])
def test_the_resolver_reports_a_malformed_config_as_usage_not_a_traceback(tmp_path, body):
    """Round lens 2: `ConfigShapeError` escaped `resolve_skill_models.py` as a traceback with
    exit 1, the verdict code, for `roles:` before this phase and for the scalar `efforts:` it
    added. The checker already said exit 2; the resolver now agrees."""
    local = _cfg(tmp_path, body)
    r = _run("resolve_skill_models.py", "--root", SKILLS, "--config", CONFIG, "--local", local)
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert "Traceback" not in r.stderr and r.stderr.startswith("error: "), r.stderr


# ── Phase 381 round, lens 3: survivors closed ──────────────────────────────────
def test_the_levels_are_the_agent_tools_enum():
    """The Agent tool's `effort` parameter is the closed enum low / medium / high / xhigh /
    max (read off its schema in the session that built this). Dropping a level refuses a
    legal config; adding one ships a value the tool rejects mid-skill."""
    assert m.EFFORT_LEVELS == ("low", "medium", "high", "xhigh", "max")


def test_a_model_override_keeps_the_shipped_effort(tmp_path):
    """The docs say moving `executor` to another model keeps its `high`. Lens 3 made a local
    `roles:` key drop the role's shipped effort, and nothing went red."""
    local = _cfg(tmp_path, "roles:\n  executor: opus\n")
    assert m.load_role_efforts(CONFIG, local)["executor"] == "high"
    import shutil
    skills = tmp_path / "skills"
    shutil.copytree(SKILLS, skills)
    r = _run("resolve_skill_models.py", "--root", skills, "--config", CONFIG,
             "--local", local, "--apply")
    assert r.returncode == 0, r.stderr
    lines = [l for l in (skills / "claim-task/SKILL.md").read_text(encoding="utf-8").splitlines()
             if "sysop:role=executor" in l]
    assert lines and all('`model`: `"opus"`, `effort`: `"high"`' in l for l in lines), lines


def test_a_dry_run_that_changes_only_efforts_offers_the_apply(tmp_path):
    local = _cfg(tmp_path, "efforts:\n  executor: none\n")
    r = _run("resolve_skill_models.py", "--root", SKILLS, "--config", CONFIG, "--local", local)
    assert r.returncode == 0, r.stderr
    assert "0 pin(s) and 3 effort(s)" in r.stdout and "Re-run with --apply" in r.stdout, r.stdout


@pytest.mark.parametrize("script", ["check_skill_models.py", "resolve_skill_models.py"])
def test_a_scalar_roles_is_a_shape_error_from_both_scripts(tmp_path, script):
    """Lens 3: `roles: high` raised `AttributeError` at exit 1 in both scripts, which
    `install.sh` reads as `REFUSED (invalid mapping)`. Pre-existing; shares this phase's fix."""
    local = _cfg(tmp_path, "roles: high\n")
    r = _run(script, "--root", SKILLS, "--config", CONFIG, "--local", local)
    assert r.returncode == 2 and "Traceback" not in r.stderr, (r.returncode, r.stderr)
    assert "`roles:` must be a mapping" in r.stderr, r.stderr


_QUOTED_EFFORT = re.compile(r"""effort[`:\s]*["']""")


def _stray_efforts(text):
    """Lines where a quoted `effort` value is not the segment bound to a pin."""
    pins = [p for p in m.analyze_text(text) if p.kind == "inline"]
    out = []
    lines = text.splitlines()
    for n in sorted({p.lineno for p in pins}):
        bound = sum(1 for p in pins if p.lineno == n and p.effort is not None)
        if len(_QUOTED_EFFORT.findall(lines[n - 1])) != bound:
            out.append(n)
    return out


def test_every_quoted_effort_on_a_pinned_line_is_the_bound_segment():
    """Lens 3: an effort in the model's own span, after a stray space, single-quoted, or
    joined by `;` is read as no effort, so the checker cannot see its value and the resolver
    inserts a second segment. No shipped line has one; this keeps it so."""
    offenders = []
    for entry in sorted(SKILLS.rglob("*.md")):
        text = entry.read_text(encoding="utf-8")
        if "sysop:model-roles" in text:
            offenders += [f"{entry.relative_to(SKILLS)}:{n}" for n in _stray_efforts(text)]
    assert not offenders, offenders


@pytest.mark.parametrize("line", [
    '- `model: "sonnet", effort: "high"` <!-- sysop:role=executor -->',
    '- `model`: `"sonnet"` , `effort`: `"ultra"` <!-- sysop:role=executor -->',
    "- `model`: `\"sonnet\"`, `effort`: `'ultra'` <!-- sysop:role=executor -->",
    '- `model`: `"sonnet"`; `effort`: `"high"` <!-- sysop:role=executor -->',
])
def test_the_stray_effort_check_sees_each_near_miss(line):
    assert _stray_efforts(MARKED + line + "\n") == [2], line


def test_the_stray_effort_check_passes_the_bound_shapes():
    text = MARKED + '- `model`: `"sonnet"`, `effort`: `"high"` <!-- sysop:role=executor --> (the `effort` is this line\'s)\n'
    assert _stray_efforts(text) == []
