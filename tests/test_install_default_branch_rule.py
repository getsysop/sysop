"""`Q-381`: the default-branch allow rule is seeded for THIS consumer's branch.

`.claude/settings.json` seeds `Bash(git reset --hard origin/main)` for
`/review-close` Step 6 under `pr` policy. It is the only literal-branch rule in
the template and the only `git reset` grant at all, and it is an EXACT match --
"a rule with no `*` matches one exact command" (Claude Code permissions doc).
So once the skill stops emitting the literal `main`, a `master` consumer's Step
6 matches no rule and is prompted or denied.

**Why these tests pin substitution rather than a wildcard.** The filed
recommendation was to widen to `Bash(git reset --hard origin/:*)`. A
`claude-code-guide` probe of the permissions doc refuted it: the `:*` form "is
only recognized at the end of a pattern", and mid-pattern the colon is a
literal character -- so that rule would have bound NOTHING, on every consumer.
The spelling that does bind, `origin/*`, also matches
`git reset --hard origin/main~50`, widening the tree's only destructive grant
from one ref to any revision expression, with no escalation (an allow rule
fully authorizes). Substitution keeps the grant exactly as narrow as it is
today. `test_the_wildcard_spelling_is_not_what_we_ship` pins that reasoning
against a future "simplification" back to the refuted shape.

These drive the real installer against scratch git consumers, because the
substitution is bash + a heredoc and the interesting cases are its interaction
with the fresh-copy path, the merge path, and `--dry-run`.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO_ROOT / "install.sh"
TEMPLATE = REPO_ROOT / "core/companion/.claude/settings.json"
RULE = "Bash(git reset --hard origin/{})"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _consumer(root: Path, branch: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", branch)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    (root / "README.md").write_text("seed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _install(target: Path, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return subprocess.run(
        ["bash", str(INSTALL_SH), str(target), "--packs", "python", *extra, "--yes"],
        capture_output=True, text=True, env=env, cwd=str(REPO_ROOT),
    )


def _allow(target: Path) -> list[str]:
    data = json.loads((target / ".claude/settings.json").read_text())
    return data["permissions"]["allow"]


def _reset_rules(target: Path) -> list[str]:
    return [r for r in _allow(target) if r.startswith("Bash(git reset")]


def test_template_still_carries_the_rule_this_machinery_rewrites():
    """The substitution is keyed on an exact string; if the template renames the
    rule the helper silently rewrites nothing. Pin the premise, not just the
    behaviour -- Phase 254's round found a keep whose subject had moved."""
    assert RULE.format("main") in json.loads(TEMPLATE.read_text())["permissions"]["allow"]


def test_master_consumer_gets_its_own_branch_in_the_reset_grant(tmp_path):
    target = _consumer(tmp_path / "c", "master")
    r = _install(target)
    assert r.returncode == 0, r.stderr
    assert _reset_rules(target) == [RULE.format("master")]


def test_main_consumer_is_untouched(tmp_path):
    """No rewrite, no tempfile, no note -- the overwhelmingly common case must
    take exactly the path it took before this machinery existed."""
    target = _consumer(tmp_path / "c", "main")
    r = _install(target)
    assert r.returncode == 0, r.stderr
    assert _reset_rules(target) == [RULE.format("main")]
    assert "reset grant seeded" not in r.stdout


def test_substitution_changes_only_that_one_line(tmp_path):
    """The helper round-trips the document through json.dump. If the template's
    formatting ever diverges from `indent=2`, every consumer's settings.json
    would be silently reformatted by an install -- a diff nobody asked for in a
    file the divergence sweep deliberately skips."""
    target = _consumer(tmp_path / "c", "master")
    assert _install(target).returncode == 0
    before = TEMPLATE.read_text().splitlines()
    after = (target / ".claude/settings.json").read_text().splitlines()
    differing = [(a, b) for a, b in zip(before, after) if a != b]
    assert len(before) == len(after)
    assert len(differing) == 1
    assert "origin/main" in differing[0][0] and "origin/master" in differing[0][1]


def test_dry_run_reports_the_substitution_and_writes_nothing(tmp_path):
    target = _consumer(tmp_path / "c", "master")
    r = _install(target, "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "git reset --hard origin/master" in r.stdout
    assert not (target / ".claude/settings.json").exists()


def test_merge_path_into_an_existing_settings_json_also_substitutes(tmp_path):
    """The fresh-copy and merge paths are separate writers. The filter re-points
    $src ahead of both so neither can be fixed without the other, and this is
    the test that would fail if it were wired below the fresh-copy return."""
    target = _consumer(tmp_path / "c", "master")
    assert _install(target).returncode == 0
    _git(target, "add", "-A")
    _git(target, "commit", "-qm", "installed")
    assert _install(target).returncode == 0
    assert _reset_rules(target) == [RULE.format("master")]


def test_merge_notes_name_the_template_not_the_tempfile(tmp_path):
    """Both filters re-point $src at a tempfile. A note reading
    `merge: /var/folders/.../sysop-branch-settings.Krx3Gi` tells the consumer
    their permissions came from somewhere they cannot look at."""
    target = _consumer(tmp_path / "c", "master")
    assert _install(target).returncode == 0
    _git(target, "add", "-A")
    _git(target, "commit", "-qm", "installed")
    r = _install(target)
    assert "core/companion/.claude/settings.json" in r.stdout
    assert "sysop-branch-settings" not in r.stdout
    assert "sysop-loop-settings" not in r.stdout


def test_unresolvable_default_branch_keeps_the_template_rule(tmp_path):
    """A repo git cannot decide for (both `main` and `master` present, no
    `origin/HEAD`) must still install. A stale allow rule costs a prompt at Step
    6; an aborted install costs the whole consumer."""
    target = _consumer(tmp_path / "c", "master")
    _git(target, "branch", "main")
    r = _install(target)
    assert r.returncode == 0, r.stderr
    assert _reset_rules(target) == [RULE.format("main")]


def test_loop_mode_ships_no_reset_grant_so_nothing_is_substituted(tmp_path):
    """Loop mode's allow-subset excludes `git reset` entirely. The helper must
    return non-zero there rather than writing an unchanged temp that claims a
    rewrite happened."""
    target = _consumer(tmp_path / "c", "master")
    r = _install(target, "--mode", "loop")
    assert r.returncode == 0, r.stderr
    assert _reset_rules(target) == []


def test_the_wildcard_spelling_is_not_what_we_ship():
    """`Bash(git reset --hard origin/:*)` does not bind (the `:*` form is only
    recognized at the END of a pattern -- mid-pattern the colon is literal), and
    `origin/*` would admit `origin/main~50`. Neither may appear in the template."""
    allow = json.loads(TEMPLATE.read_text())["permissions"]["allow"]
    for rule in allow:
        assert "git reset --hard origin/:*" not in rule
        assert "git reset --hard origin/*" not in rule
        assert "git reset --hard:*" not in rule


# ── the "did anything actually change" property (battery rows A09 + A16) ──────────
#
# The helper's `sys.exit(1)` when the rule is absent is one arm of one branch, and the
# `cmp -s` after the heredoc is its backstop. The author-side battery mutated BOTH and both
# survived, because no test could reach the case: it only shows up when the TEMPLATE lacks
# the rule, and every other test in this module runs against the real one. Closing it needs
# a doctored template, which means a scratch source clone — the `test_install_ref_sh.py`
# fixture shape, reused here for the same reason it exists there.


def _source_clone(tmp_path: Path, template_mutator=None) -> Path:
    """A scratch Sysop source tree, optionally with its settings template doctored."""
    src = tmp_path / "src"
    src.mkdir()
    shutil.copy2(REPO_ROOT / "install.sh", src / "install.sh")
    for d in ("core", "packs"):
        shutil.copytree(REPO_ROOT / d, src / d,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".venv"))
    if template_mutator is not None:
        tpl = src / "core/companion/.claude/settings.json"
        tpl.write_text(template_mutator(tpl.read_text()))
    return src


def _install_from(src: Path, target: Path, *extra):
    env = dict(os.environ)
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    return subprocess.run(
        ["bash", str(src / "install.sh"), str(target), "--packs", "python", *extra, "--yes"],
        capture_output=True, text=True, env=env, cwd=str(src),
    )


def test_a_template_without_the_rule_does_not_report_a_rewrite(tmp_path):
    """`A09`/`A16`: an unchanged filter must not claim it seeded anything.

    If the rule is ever renamed, the substitution silently matches nothing. Reporting
    "reset grant seeded for this repo's default branch" over a file byte-identical to the
    shipped template is a false claim in consumer-facing output — the class this repo keeps
    filing against itself.
    """
    src = _source_clone(
        tmp_path,
        lambda s: s.replace('"Bash(git reset --hard origin/main)",\n', ""),
    )
    target = _consumer(tmp_path / "c", "master")
    r = _install_from(src, target)
    assert r.returncode == 0, r.stderr
    assert "reset grant seeded" not in r.stdout, (
        "the installer claimed it seeded the default-branch grant against a template that "
        "does not carry the rule:\n" + r.stdout
    )
    assert _reset_rules(target) == []


def test_the_scratch_clone_reproduces_the_real_behaviour(tmp_path):
    """Non-vacuity for the fixture above: an UNdoctored clone must still substitute.

    Without this, a `_source_clone` that silently failed to copy the template would make
    the test above pass for the wrong reason — it would find no rule because it found no
    file, and report that as the property holding.
    """
    src = _source_clone(tmp_path)
    target = _consumer(tmp_path / "c", "master")
    r = _install_from(src, target)
    assert r.returncode == 0, r.stderr
    assert "reset grant seeded" in r.stdout
    assert _reset_rules(target) == [RULE.format("master")]


# ── stale-grant accretion across updates (round finding `M4`) ────────────────────
#
# The permissions merge is a deliberate set-union, so it preserves rules the consumer
# added — and, before the pruner, every `git reset --hard origin/<name>` the installer had
# seeded on an earlier run. An independent lens measured three reset grants after a pre-255
# install plus two updates across a rename, with the note claiming a seeding while
# `origin/main` sat untouched at the top of the file.


def _make_pre255(target: Path):
    """Rewrite the installed rule back to the literal, simulating a pre-Phase-255 install."""
    p = target / ".claude/settings.json"
    data = json.loads(p.read_text())
    data["permissions"]["allow"] = [
        RULE.format("main") if r.startswith("Bash(git reset") else r
        for r in data["permissions"]["allow"]
    ]
    p.write_text(json.dumps(data, indent=2) + "\n")
    _git(target, "add", "-A")
    _git(target, "commit", "-qm", "pre-255 install")


def test_updating_a_pre255_install_replaces_the_stale_grant_rather_than_adding_to_it(tmp_path):
    target = _consumer(tmp_path / "c", "master")
    assert _install(target).returncode == 0
    _make_pre255(target)
    assert _reset_rules(target) == [RULE.format("main")]
    assert _install(target).returncode == 0
    assert _reset_rules(target) == [RULE.format("master")], (
        "the set-union merge kept the stale grant beside the new one; a consumer "
        "accumulates one dead `git reset --hard` grant per rename, forever"
    )


def test_pruning_only_touches_grants_of_this_exact_shape(tmp_path):
    """The consumer's own rules are not ours to delete — including a `git reset` of a
    different shape. Only `origin/<a-branch-that-is-not-the-default>` is ours."""
    target = _consumer(tmp_path / "c", "master")
    assert _install(target).returncode == 0
    p = target / ".claude/settings.json"
    data = json.loads(p.read_text())
    data["permissions"]["allow"] += [
        "Bash(git reset --hard HEAD~1)",          # consumer's own, different shape
        "Bash(git reset --soft origin/topic)",    # not --hard
        RULE.format("main"),                      # ours, stale
    ]
    p.write_text(json.dumps(data, indent=2) + "\n")
    _git(target, "add", "-A")
    _git(target, "commit", "-qm", "consumer rules")
    assert _install(target).returncode == 0
    allow = _allow(target)
    assert "Bash(git reset --hard HEAD~1)" in allow
    assert "Bash(git reset --soft origin/topic)" in allow
    # `_reset_rules` is deliberately broad (any `git reset` grant); the pruner's scope is
    # narrower, so assert on that shape rather than on the helper's.
    ours = [r for r in allow if r.startswith("Bash(git reset --hard origin/")]
    assert ours == [RULE.format("master")]


def test_an_undecidable_repo_seeds_nothing_and_claims_nothing(tmp_path):
    """A repo git itself cannot answer for (no remote, no `main`/`master`) must not be
    guessed at — and must not be told a grant was seeded for it."""
    target = _consumer(tmp_path / "c", "master")
    _git(target, "branch", "-m", "master", "develop")
    r = _install(target)
    assert r.returncode == 0, r.stderr
    assert "reset grant seeded" not in r.stdout
    assert _reset_rules(target) == [RULE.format("main")]   # the documented fallback
