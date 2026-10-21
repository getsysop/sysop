"""`Q-676` (Phase 398): the role -> model -> effort table at the front door.

A consumer ran 254 agents on Opus at `high` without knowing a one-key override existed, because
nothing showed the defaults until the bill did. `check_skill_models.py --defaults` prints the
table from `served_models.yml` (and the local overlay), the installer prints it last in every
install and update summary, and `/intake` (fresh and adopting) and `/onboard` run it at Step 0.

What is pinned here:

* the table is DERIVED: each row's model and effort are what the loaders the checker and the
  resolver use return, and every role carries an `about:` line, so the shipped file cannot
  grow a role the table describes with a dash;
* the overlay is marked where it acts and shown only when it is in effect: the installer
  renders it only when the resolver applied it, because on a refusal the skills keep the
  shipped models and a table with the override would contradict the warning above it;
* a checker that cannot render the table (a preserved older copy, no PyYAML) degrades to a
  one-line pointer, never to argparse's error text in the summary;
* a dry run prints no table: it writes nothing, so it has no state to report.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
CHECKER = SCRIPTS / "check_skill_models.py"
CONFIG = REPO_ROOT / "core" / "companion" / ".claude" / "served_models.yml"
INSTALL_SH = REPO_ROOT / "install.sh"
HEADER = "Sysop model roles, as mapped by .claude/"
SKILLS = REPO_ROOT / "core" / "skills"

sys.path.insert(0, str(SCRIPTS))
from _model_roles import load_role_efforts, load_roles_config  # noqa: E402


def _defaults(*extra: str, config: Path = CONFIG) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--defaults", "--config", str(config), *extra],
        capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})


def _header(stdout: str) -> str:
    return next(ln for ln in stdout.splitlines() if ln.startswith(HEADER))


def _rows(stdout: str) -> dict[str, list[str]]:
    """``{role: [model, effort, rest]}`` for each table row."""
    lines = stdout.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.lstrip().startswith("role "))
    rows = {}
    for ln in lines[start + 1:]:
        if not ln.startswith("  "):
            break
        role, model, effort, *rest = ln.split(None, 3)
        rows[role] = [model, effort, rest[0] if rest else ""]
    return rows


# ── the shipped file ────────────────────────────────────────────────────────────

def test_every_shipped_role_has_an_about_line():
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    roles, about = data["roles"], data.get("about") or {}
    missing = sorted(r for r in roles if not str(about.get(r) or "").strip())
    assert not missing, f"roles with no `about:` line print a dash at the front door: {missing}"
    extra = sorted(r for r in about if r not in roles)
    assert not extra, f"`about:` describes roles `roles:` does not have: {extra}"


def test_the_reevaluation_and_cost_lines_are_in_the_file():
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    reval = data.get("reevaluated") or {}
    assert reval.get("last") and reval.get("next"), reval
    assert str(data.get("cost_shape") or "").strip()
    # The comment block above `roles:` carries the same date; one moved without the other is
    # a table telling consumers a different date from the file's own reasons.
    assert f"Last re-evaluated {reval['last']}" in CONFIG.read_text(encoding="utf-8")


# ── the renderer ────────────────────────────────────────────────────────────────

def test_each_row_is_what_the_loaders_resolve():
    r = _defaults()
    assert r.returncode == 0, r.stderr
    rows = _rows(r.stdout)
    models, _served = load_roles_config(CONFIG)
    efforts = load_role_efforts(CONFIG)
    assert set(rows) == set(models), (set(rows), set(models))
    for role, (model, effort, _rest) in rows.items():
        assert model == models[role], (role, model, models[role])
        assert effort == (efforts[role] or "session"), (role, effort, efforts[role])


def test_a_role_that_follows_another_says_so():
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    followers = {r: v for r, v in data["roles"].items() if v in data["roles"]}
    assert followers, "vacuity: the shipped file has no role that follows another"
    rows = _rows(_defaults().stdout)
    for role, target in followers.items():
        assert rows[role][2].startswith(f"(follows {target})"), (role, rows[role])
    leaders = [r for r in data["roles"] if r not in followers]
    assert all("(follows" not in rows[r][2] for r in leaders)


def test_the_overlay_is_marked_where_it_acts(tmp_path):
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  reasoning: fable\nefforts:\n  executor: none\n")
    r = _defaults("--local", str(local))
    assert r.returncode == 0, r.stderr
    assert "served_models.local.yml" in _header(r.stdout)
    rows = _rows(r.stdout)
    assert rows["reasoning"][0] == "fable" and "[your override]" in rows["reasoning"][2]
    assert rows["executor"][1] == "session" and "[your override]" in rows["executor"][2]
    # A follower moves with its leader but was not overridden itself.
    assert rows["planner"][0] == "fable" and "[your override]" not in rows["planner"][2]
    assert "[your override]" not in rows["mechanical"][2]


def test_without_an_overlay_nothing_is_marked():
    r = _defaults("--local", "/nonexistent/served_models.local.yml")
    assert r.returncode == 0, r.stderr
    assert "[your override]" not in r.stdout
    assert "served_models.local.yml" not in _header(r.stdout)


def test_the_table_needs_no_skills_tree(tmp_path):
    r = _defaults("--root", str(tmp_path / "absent"))
    assert r.returncode == 0, r.stderr
    assert HEADER in r.stdout
    assert r.stdout.startswith(f"No Sysop skills under {tmp_path / 'absent'}, so the model-role check was not run.")


def test_it_names_the_override_and_when_it_takes_effect():
    out = _defaults().stdout
    assert ".claude/served_models.local.yml" in out
    assert "sysop-update.sh" in out


def test_it_prints_the_files_notes():
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    out = _defaults().stdout
    assert " ".join(str(data["cost_shape"]).split()) in out
    assert f"Defaults last re-evaluated {data['reevaluated']['last']}; next {data['reevaluated']['next']}." in out


def test_an_unreadable_overlay_is_exit_2_not_a_table(tmp_path):
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles: [x\n")
    r = _defaults("--local", str(local))
    assert r.returncode == 2, (r.returncode, r.stdout, r.stderr)
    assert HEADER not in r.stdout


def test_a_cycle_or_a_bad_effort_is_exit_1_and_names_the_local_file(tmp_path):
    """Round 2, execution lens: these exited 2 where the check mode exits 1, with an error
    naming no file for the skills' "name the file its error names" to follow."""
    for body in ("roles:\n  a: b\n  b: a\n", "efforts:\n  nobody: high\n",
                 "efforts:\n  executor: ultra\n"):
        local = tmp_path / "served_models.local.yml"
        local.write_text(body)
        r = _defaults("--local", str(local))
        assert r.returncode == 1, (body, r.returncode, r.stdout, r.stderr)
        assert HEADER not in r.stdout, body
        assert r.stdout.startswith(VERDICT) and "served_models.local.yml" in r.stdout, (body, r.stdout)


def test_every_shipped_about_line_prints():
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    rows = _rows(_defaults().stdout)
    for role, line in data["about"].items():
        assert rows[role][2].endswith(" ".join(str(line).split())), (role, rows[role])


def test_a_locally_remapped_follower_stops_saying_it_follows(tmp_path):
    """Round 1, guards lens survivor: the raw value ignored the local file, so `planner: opus`
    would still print `(follows reasoning)`."""
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  planner: sonnet\n")
    rows = _rows(_defaults("--local", str(local)).stdout)
    assert rows["planner"][0] == "sonnet"
    assert "(follows" not in rows["planner"][2] and "[your override]" in rows["planner"][2]


def test_the_example_override_is_one_the_checker_accepts(tmp_path):
    """Round 1, guards lens survivor: nothing checked that the printed advice is valid."""
    for extra in ((), ("--root", str(SKILLS))):
        out = _defaults(*extra).stdout
        role, value = (s.strip() for s in out.split("e.g.\n", 1)[1].splitlines()[1].split(":"))
        local = tmp_path / "served_models.local.yml"
        local.write_text(f"roles:\n  {role}: {value}\n")
        r = _defaults("--local", str(local), "--root", str(SKILLS))
        assert r.returncode == 0 and "[refused]" not in r.stdout, (role, value, r.stdout)
        assert _rows(r.stdout)[role][0] == value


def test_effort_is_explained_and_dashed_where_nothing_spawns():
    out = _defaults("--root", str(SKILLS)).stdout
    assert "Effort is what a role's spawned agents run at" in out
    assert "'-' marks a role that spawns no agent here" in out
    rows = _rows(out)
    # `quick` governs frontmatter pins only, so an `efforts:` entry for it sets nothing.
    assert rows["quick"][1] == "-", rows["quick"]
    assert rows["executor"][1] == load_role_efforts(CONFIG)["executor"]


VERDICT = "The model-role check fails here"


def test_a_mapping_the_gate_refuses_is_a_verdict_on_the_whole_file(tmp_path):
    """Rounds 1 and 2. Round 1 found `best` shown as the mapping with the update promised to
    apply it; round 1's per-row `[refused]` mark then missed the valid key beside it (the gate
    refuses the whole file) and every refusal with no row (an undefined role, an unmarked pin).
    The verdict is now the check mode's own, on one line before the table, and exit 1."""
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  executor: best\n  planner: sonnet\nserved:\n  - best\n")
    r = _defaults("--local", str(local), "--root", str(SKILLS))
    assert r.returncode == 1, r.stdout
    assert r.stdout.startswith(VERDICT), r.stdout[:200]
    assert "--managed-only" in r.stdout.split(HEADER)[0]
    assert "[refused]" not in r.stdout and "[not in effect]" not in r.stdout
    # Without a skills tree nothing is checked, and the table says so rather than guessing.
    r = _defaults("--local", str(local), "--root", str(tmp_path / "absent"))
    assert r.returncode == 0 and "the model-role check was not run" in r.stdout, r.stdout[:200]
    assert VERDICT not in r.stdout


def test_a_role_no_installed_skill_pins_is_not_judged(tmp_path):
    """Round 3, execution lens (HIGH): an extra `served:` check over every row fired the verdict
    for a role no managed pin governs, which the gate never judges, so a loop consumer was told
    none of their file applied while the update applied it."""
    import shutil
    root = tmp_path / "skills"
    for name in ("codebase-review", "security-audit", "_shared"):
        shutil.copytree(SKILLS / name, root / name)
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  reasoning: fable\n  executor: claude-sonnet-4-5\n")
    r = _defaults("--local", str(local), "--root", str(root))
    assert r.returncode == 0, r.stdout[:300]
    assert VERDICT not in r.stdout
    assert _rows(r.stdout)["reasoning"][0] == "fable"
    # With no tree every row shows, the off-`served:` one included, and still nothing is judged.
    r = _defaults("--local", str(local), "--root", str(tmp_path / "absent"))
    assert r.returncode == 0 and "the model-role check was not run" in r.stdout, r.stdout[:300]
    assert _rows(r.stdout)["executor"][0] == "claude-sonnet-4-5"


def test_the_verdict_does_not_promise_what_the_update_does(tmp_path):
    """Round 3, execution lens (MEDIUM): a hand-edited shipped pin fails the check, and the update
    re-copies the skill and applies the file, so the line conditions on the post-copy check."""
    import shutil
    root = tmp_path / "skills"
    shutil.copytree(SKILLS, root)
    skill = root / "auto-fix" / "SKILL.md"
    text = skill.read_text()
    m = re.search(r'model[`:\s]*"(sonnet)"', text)
    assert m, "fixture: auto-fix's inline mechanical pin moved"
    skill.write_text(text[:m.start(1)] + "best" + text[m.end(1):])
    r = _defaults("--root", str(root))
    assert r.returncode == 1 and r.stdout.startswith(VERDICT), r.stdout[:300]
    assert "after an update has copied Sysop's" in r.stdout
    assert "--managed-only" in r.stdout.split(HEADER)[0]


def test_a_refusal_with_no_row_is_still_a_verdict(tmp_path):
    """Round 2, guards lens: a marked skill pinning an undefined role fails the gate, and the
    per-row marks had nothing to mark."""
    import shutil
    root = tmp_path / "skills"
    shutil.copytree(SKILLS, root)
    mine = root / "mine" / "SKILL.md"
    mine.parent.mkdir()
    mine.write_text("---\nname: mine\nmodel: opus\n---\n<!-- sysop:model-roles frontmatter=ghost -->\nbody\n")
    r = _defaults("--root", str(root))
    assert r.returncode == 1 and r.stdout.startswith(VERDICT), r.stdout[:300]


def test_a_valid_override_carries_no_verdict(tmp_path):
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  executor: opus\n")
    r = _defaults("--local", str(local), "--root", str(SKILLS))
    assert r.returncode == 0, r.stdout
    assert VERDICT not in r.stdout and r.stdout.startswith(HEADER), r.stdout[:200]


def test_a_tree_with_no_managed_pins_shows_every_role_and_effort(tmp_path):
    """Round 2, guards lens: an existing directory with no Sysop pins dashed every effort."""
    (tmp_path / "empty").mkdir()
    rows = _rows(_defaults("--root", str(tmp_path / "empty")).stdout)
    assert set(rows) == set(load_roles_config(CONFIG)[0])
    assert rows["executor"][1] == load_role_efforts(CONFIG)["executor"]


def test_followed_roles_are_kept_across_every_hop(tmp_path):
    import shutil
    root = tmp_path / "skills"
    for name in ("codebase-review", "security-audit", "_shared"):
        shutil.copytree(SKILLS / name, root / name)
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  plan-review: executor\n  executor: planner\n")
    rows = _rows(_defaults("--local", str(local), "--root", str(root)).stdout)
    assert {"plan-review", "executor", "planner", "reasoning"} <= set(rows), set(rows)


def test_the_check_mode_starts_against_an_older_model_roles(tmp_path):
    """Round 2, execution lens: importing `describe_roles` at the top made the checker unable
    to start against a consumer's preserved `_model_roles.py` from before it, so the
    installer's gate fell to "applying it UNVALIDATED" and wrote `best` into spawns."""
    import shutil
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("check_skill_models.py", "_model_roles.py", "migrate_skill_model.py"):
        shutil.copy(SCRIPTS / name, scripts / name)
    mr = scripts / "_model_roles.py"
    text = mr.read_text()
    start = text.index("@dataclass(frozen=True)\nclass RoleRow:")
    end = text.index("def _as_role_map(")
    mr.write_text(text[:start] + text[end:])
    assert "def describe_roles" not in mr.read_text()
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  executor: best\nserved:\n  - best\n")
    base = [sys.executable, str(scripts / "check_skill_models.py"), "--config", str(CONFIG),
            "--root", str(SKILLS), "--local", str(local)]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([*base, "--managed-only"], capture_output=True, text=True, env=env)
    assert r.returncode == 1 and "ImportError" not in r.stderr, (r.returncode, r.stderr[-500:])
    r = subprocess.run([*base, "--defaults"], capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "needs a newer" in r.stderr, (r.returncode, r.stderr[-500:])


def test_a_skills_tree_limits_the_rows_to_its_pins(tmp_path):
    """Round 1, execution lens: a loop install pins `reasoning` and `plan-review` only, and
    the table listed all eight roles with an example override (`executor`) that changes no pin."""
    import shutil
    root = tmp_path / "skills"
    for name in ("codebase-review", "security-audit", "_shared"):
        shutil.copytree(SKILLS / name, root / name)
    r = _defaults("--root", str(root))
    assert r.returncode == 0, r.stderr
    assert set(_rows(r.stdout)) == {"reasoning", "plan-review"}, _rows(r.stdout)
    example = r.stdout.split("e.g.\n", 1)[1].splitlines()[1].split(":")[0].strip()
    assert example == "reasoning", r.stdout
    full = _defaults("--root", str(SKILLS))
    assert set(_rows(full.stdout)) == set(load_roles_config(CONFIG)[0])


def test_a_config_without_about_still_renders(tmp_path):
    cfg = tmp_path / "served_models.yml"
    cfg.write_text("roles:\n  reasoning: opus\n  planner: reasoning\nserved:\n  - opus\n")
    r = _defaults(config=cfg)
    assert r.returncode == 0, r.stderr
    rows = _rows(r.stdout)
    assert rows["reasoning"] == ["opus", "session", "-"]
    assert rows["planner"][2] == "(follows reasoning) -"


# ── the installer ───────────────────────────────────────────────────────────────

def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _consumer(root: Path) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "commit", "-qm", "seed", "--allow-empty")
    return root


def _install_run(target: Path, *extra: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    # `python3` resolves to the pytest interpreter, so pick_python_with_yaml finds PyYAML.
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    r = subprocess.run(["bash", str(INSTALL_SH), str(target), *extra, "--yes"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0, (r.returncode, r.stdout[-2000:], r.stderr[-2000:])
    return r


def _install(target: Path, *extra: str) -> str:
    return _install_run(target, *extra).stdout


def _table_block(stdout: str) -> str:
    assert HEADER in stdout, stdout[-1500:]
    return stdout[stdout.index(HEADER):]


def test_a_fresh_install_ends_with_the_table(tmp_path):
    root = _consumer(tmp_path / "c")
    out = _install(root, "--packs", "python", "--no-arm-hooks")
    block = _table_block(out)
    assert set(_rows(block)) == set(load_roles_config(CONFIG)[0])
    # Last in the summary: nothing but the table's own lines follows its header.
    assert "Next steps:" not in block and "export SYSOP_SRC" not in block


def test_an_update_shows_an_applied_override(tmp_path):
    root = _consumer(tmp_path / "c")
    _install(root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude" / "served_models.local.yml").write_text("roles:\n  executor: opus\n")
    block = _table_block(_install(root, "--update", "--no-arm-hooks"))
    assert "served_models.local.yml" in block.splitlines()[0]
    assert _rows(block)["executor"][0] == "opus"
    assert "[your override]" in _rows(block)["executor"][2]
    assert "NOT in effect" not in block


def test_a_refused_override_is_not_shown_as_in_effect(tmp_path):
    root = _consumer(tmp_path / "c")
    _install(root, "--packs", "python", "--no-arm-hooks")
    (root / ".claude" / "served_models.local.yml").write_text("roles:\n  executor: best\n")
    out = _install(root, "--update", "--no-arm-hooks")
    assert "REFUSED" in out, "fixture: the mapping was not refused"
    block = _table_block(out)
    assert "served_models.local.yml" not in block.splitlines()[0]
    assert _rows(block)["executor"][0] == load_roles_config(CONFIG)[0]["executor"]
    assert "[your override]" not in block
    assert "NOT in effect" in block


def test_a_checker_without_the_flag_degrades_to_the_pointer(tmp_path):
    root = _consumer(tmp_path / "c")
    _install(root, "--packs", "python", "--no-arm-hooks")
    checker = root / "sysop" / "scripts" / "check_skill_models.py"
    text = checker.read_text()
    start = text.index('    parser.add_argument("--defaults"')
    end = text.index("    args = parser.parse_args(argv)")
    checker.write_text(text[:start] + text[end:])
    # The edit is a consumer modification, which `--update` preserves (Phase 24b).
    run = _install_run(root, "--update", "--no-arm-hooks")
    out = run.stdout
    assert "unrecognized arguments" not in run.stderr, "the checker's stderr reached the terminal"
    assert 'add_argument("--defaults"' not in checker.read_text(), "fixture: the checker was replaced"
    assert HEADER not in out
    assert "unrecognized arguments" not in out
    assert out.rstrip().splitlines()[-1].startswith("Models: .claude/served_models.yml")


def test_efforts_a_preserved_resolver_did_not_apply_are_flagged(tmp_path):
    """Round 1, execution lens: a preserved resolver from before `efforts:` applies the models
    and not the efforts, and the table showed the local effort as in effect."""
    root = _consumer(tmp_path / "c")
    _install(root, "--packs", "python", "--no-arm-hooks")
    resolver = root / "sysop" / "scripts" / "resolve_skill_models.py"
    text = resolver.read_text()
    old = 'and {effort_total} effort(s) '
    assert text.count(old) == 1, "fixture: the resolver's summary line moved"
    resolver.write_text(text.replace(old, ""))
    (root / ".claude" / "served_models.local.yml").write_text("efforts:\n  convention-gate: medium\n")
    out = _install(root, "--update", "--no-arm-hooks")
    assert "predates per-role efforts" in out, "fixture: the resolver was replaced, not preserved"
    block = _table_block(out)
    assert "your `efforts:` overrides are NOT in effect" in block
    # Round 2: with no local file the shipped efforts are what the skills carry.
    (root / ".claude" / "served_models.local.yml").unlink()
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "drop local")
    out = _install(root, "--update", "--no-arm-hooks")
    assert "predates per-role efforts" in out
    assert "your `efforts:` overrides are NOT in effect" not in _table_block(out)
    # Nor does a local file that sets no `efforts:`.
    (root / ".claude" / "served_models.local.yml").write_text("roles:\n  executor: opus\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "local without efforts")
    out = _install(root, "--update", "--no-arm-hooks")
    assert "predates per-role efforts" in out
    assert "overrides are NOT in effect" not in _table_block(out)


def test_a_refusal_with_no_local_file_says_nothing_about_one(tmp_path):
    """Round 2, guards lens: a consumer's own marked skill pinning an undefined role makes the
    gate refuse with no local file, and only the `-f` test kept the summary from naming one."""
    root = _consumer(tmp_path / "c")
    _install(root, "--packs", "python", "--no-arm-hooks")
    mine = root / ".claude" / "skills" / "mine" / "SKILL.md"
    mine.parent.mkdir()
    mine.write_text("---\nname: mine\nmodel: opus\n---\n<!-- sysop:model-roles frontmatter=ghost -->\nbody\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "own skill")
    out = _install(root, "--update", "--no-arm-hooks")
    assert "REFUSED" in out, "fixture: the gate did not refuse"
    assert "served_models.local.yml is NOT in effect" not in out
    assert out.rstrip().splitlines()[-1].startswith("Models: .claude/served_models.yml")


def test_a_failed_resolution_with_no_local_file_says_nothing_about_one(tmp_path):
    """The one path left to the not-in-effect note's `-f` test: the gate passes, the resolver
    fails (here a preserved copy that exits non-zero), and the table still renders."""
    root = _consumer(tmp_path / "c")
    _install(root, "--packs", "python", "--no-arm-hooks")
    resolver = root / "sysop" / "scripts" / "resolve_skill_models.py"
    resolver.write_text("import sys\nsys.exit(3)\n" + resolver.read_text())
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "broken resolver")
    out = _install(root, "--update", "--no-arm-hooks")
    assert "model-role resolution reported an issue" in out, "fixture: the resolver did not fail"
    block = _table_block(out)
    assert "NOT in effect" not in block


def test_a_dry_run_prints_no_table(tmp_path):
    root = _consumer(tmp_path / "c")
    _install(root, "--packs", "python", "--no-arm-hooks")
    out = _install(root, "--update", "--dry-run", "--no-arm-hooks")
    assert HEADER not in out
    assert "Models: .claude/served_models.yml" not in out
