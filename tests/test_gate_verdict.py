"""Step 2b's verdict reuse — Phase 394, `Q-667`.

A relaunched `/review-close` used to re-run both Step 2b gates on a branch whose head had not
moved. `core/companion/scripts/gate_verdict.py` records a gate's `APPROVED` (with
`NOTES: none`) against everything the review depended on, and `lookup` reports it again only
when every one of those inputs is unchanged. Wade's answers (2026-10-20): the key carries the
effort and the step's text beside the commit, the copy and the model; both gates; only
`APPROVED` is reused. Phase 379's round added the merge-base.

This module pins, by running the script in scratch repositories:

* a recorded verdict is reused, and each input of the key, moved alone, stops the reuse;
* text outside Step 2b, the one input not in the key, does not;
* `record` refuses an echo that is not the target's commit, so a misplaced lens records nothing;
* a damaged or non-`APPROVED` record is a miss, never a reuse;
* the shipped `SKILL.md` gives both roles one spawn line the script can read, and its commands
  name the script's gates and argument order.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_runner_text import text_of  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "core" / "companion" / "scripts" / "gate_verdict.py"
CLOSE_DIR = REPO / "core" / "skills" / "review-close"

sys.path.insert(0, str(SCRIPT.parent))
import gate_verdict  # noqa: E402

GIT_ENV = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
SECTIONS = ("Prevention Conventions", "Testing Patterns")

SKILL = """# review-close

### 2a. Merit

Text before the step.

### 2b. Prevention Convention Check

   - `model: "sonnet"`, `effort: "high"` (always) <!-- sysop:role=convention-gate -->

   Spawn one Agent with `model: "opus"`, `effort: "high"` <!-- sysop:role=security-gate --> here.

### 2c. Unpushed Main Commits

Text after the step.
"""

CLAUDE = """# Project

## Prevention Conventions

- Rule one.

## Testing Patterns

- Use fixtures.

### Mocks

- Mock the network.

## Commands

- make test
"""


def git(cwd, *args) -> str:
    p = subprocess.run(["git", "-C", str(cwd), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                       capture_output=True, text=True, env=GIT_ENV)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def commit(cwd, name="f", text="x", msg="c") -> str:
    (cwd / name).write_text(text, encoding="utf-8")
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", msg)
    return git(cwd, "rev-parse", "HEAD")


def run(cwd, *args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True,
                          text=True, env=GIT_ENV)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True, env=GIT_ENV)
    (r / "CLAUDE.md").write_text(CLAUDE, encoding="utf-8")
    (r / ".claude").mkdir()
    (r / ".claude" / "security_map.md").write_text("## `a/*.py` — A\n\n- rule\n", encoding="utf-8")
    commit(r, "CLAUDE.md", CLAUDE, "init")
    git(r, "switch", "-q", "-c", "feat")
    commit(r, "work.py", "print(1)\n", "work")
    git(r, "switch", "-q", "main")
    skill = tmp_path / "skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(SKILL, encoding="utf-8")
    return r, skill


def lookup(r, skill, gate="convention", target="feat", sections=SECTIONS):
    return run(r, "lookup", gate, target, "main", str(skill), *(sections if gate == "convention" else ()))


def key_now(r, skill, gate="convention", target="feat", sections=SECTIONS) -> str:
    """The `KEY:` a lookup prints on a miss: what the runner carries to `record`."""
    p = lookup(r, skill, gate=gate, target=target, sections=sections)
    keys = re.findall(r"^KEY: ([0-9a-f]{64})$", p.stdout, re.M)
    assert p.returncode in (0, 3) and (keys or p.returncode == 0), (p.stdout, p.stderr)
    return keys[0] if keys else ""


def record(r, skill, echo=None, gate="convention", target="feat", sections=SECTIONS, key=None):
    if echo is None:
        echo = git(r, "rev-parse", target if target != "unpushed-main" else "HEAD")
    if key is None:
        key = key_now(r, skill, gate=gate, target=target, sections=sections)
    return run(r, "record", gate, target, "main", str(skill), echo, key,
               *(sections if gate == "convention" else ()))


def recorded(r, skill, **kw):
    p = record(r, skill, **kw)
    assert p.returncode == 0 and p.stdout.startswith("RECORDED "), (p.stdout, p.stderr)
    return p


# ── reuse, and each leg of the key ─────────────────────────────────────────────────────

def test_a_missing_record_is_a_miss_and_a_recorded_approval_is_reused(repo):
    r, skill = repo
    p = lookup(r, skill)
    assert p.returncode == 3 and p.stdout.startswith("MISS feat (") and "no recorded verdict" in p.stdout
    assert re.search(r"^KEY: [0-9a-f]{64}$", p.stdout, re.M), p.stdout
    recorded(r, skill)
    p = lookup(r, skill)
    assert p.returncode == 0, p.stdout
    assert re.fullmatch(r"REUSE feat — verdict reused from \d{8}T\d{6}Z \([0-9a-f]{12}\)\n", p.stdout)


def test_the_record_lives_in_the_main_checkout_even_from_a_linked_worktree(repo, tmp_path):
    r, skill = repo
    wt = tmp_path / "linked"
    git(r, "worktree", "add", "-q", "--detach", str(wt), "main")
    recorded(wt, skill)
    assert list((r / "sysop" / "runtime" / "gate-verdicts").glob("convention-*.json"))
    assert not (wt / "sysop").exists()


def test_a_moved_tip_is_a_miss(repo):
    r, skill = repo
    recorded(r, skill)
    git(r, "switch", "-q", "feat")
    commit(r, "work.py", "print(2)\n", "more")
    git(r, "switch", "-q", "main")
    p = lookup(r, skill)
    assert p.returncode == 3 and "tip" in p.stdout.split(":", 1)[1]


def test_an_unrelated_commit_on_main_keeps_the_verdict(repo):
    """The base is the merge-base, not the default branch's tip: `main` moving under an unmoved
    branch leaves the three-dot diff as it was, and must not switch reuse off."""
    r, skill = repo
    recorded(r, skill)
    commit(r, "elsewhere.txt", "e\n", "unrelated")
    assert lookup(r, skill).returncode == 0


def test_two_targets_keep_two_records(repo):
    """A relaunch after one branch blocked is the field report's case: every sibling's
    approval has to survive, not only the last one written."""
    r, skill = repo
    git(r, "branch", "feat2", "feat")
    recorded(r, skill)
    recorded(r, skill, target="feat2")
    assert lookup(r, skill).returncode == 0 and lookup(r, skill, target="feat2").returncode == 0


def test_a_crlf_claude_md_edit_is_a_miss(repo):
    r, skill = repo
    (r / "CLAUDE.md").write_bytes(CLAUDE.replace("\n", "\r\n").encode())
    recorded(r, skill)
    (r / "CLAUDE.md").write_bytes(CLAUDE.replace("Rule one.", "Rule 1ne.").replace("\n", "\r\n").encode())
    p = lookup(r, skill)
    assert p.returncode == 3 and "sources" in p.stdout


def test_a_moved_merge_base_under_an_unmoved_tip_is_a_miss(repo):
    """Main fast-forwards onto a commit the branch already holds: the tip is the same commit
    and the three-dot diff is not the same diff."""
    r, skill = repo
    git(r, "switch", "-q", "feat")
    mid = commit(r, "mid.py", "m\n", "mid")
    commit(r, "top.py", "t\n", "top")
    git(r, "switch", "-q", "main")
    recorded(r, skill)
    git(r, "merge", "-q", "--ff-only", mid)
    p = lookup(r, skill)
    assert p.returncode == 3
    assert p.stdout.split(": ", 1)[1].startswith("base changed"), p.stdout


@pytest.mark.parametrize("old,new", [
    ("Use fixtures.", "Use fakes."),
    # A section outside the named set: step 0 may have added it to what the agent is handed,
    # and a runner that copies the block's two names would leave it out of a section-cut key.
    ("make test", "make check"),
    # The three shapes a heading cut misses, each of which reused a verdict in Phase 394's
    # round: a fenced `## ` line ends the cut early, trailing space hides a heading, and the
    # second of two same-named sections is never read.
    ("- Rule one.\n", "- Rule one.\n\n```markdown\n## Example heading\n```\n\n- Rule two.\n"),
    ("## Testing Patterns\n", "## Testing Patterns \n"),
    ("- make test\n", "- make test\n\n## Prevention Conventions\n\n- Rule again.\n"),
])
def test_any_edit_to_claude_md_is_a_miss(repo, old, new):
    r, skill = repo
    (r / "CLAUDE.md").write_text(CLAUDE.replace(old, new), encoding="utf-8")
    recorded(r, skill)
    edited = (r / "CLAUDE.md").read_text(encoding="utf-8").replace("Rule two.", "Rule two, changed.") \
        .replace("Use fakes.", "Use stubs.").replace("make check", "make lint") \
        .replace("Rule again.", "Rule again, changed.").replace("Use fixtures.", "Use spies.")
    (r / "CLAUDE.md").write_text(edited, encoding="utf-8")
    p = lookup(r, skill)
    assert p.returncode == 3 and "sources" in p.stdout, p.stdout


def test_an_edit_inside_a_subsection_is_a_miss(repo):
    r, skill = repo
    recorded(r, skill)
    (r / "CLAUDE.md").write_text(CLAUDE.replace("Mock the network.", "Never mock."), encoding="utf-8")
    p = lookup(r, skill)
    assert p.returncode == 3 and "sources" in p.stdout


def test_a_widened_section_set_is_a_miss(repo):
    r, skill = repo
    recorded(r, skill)
    p = lookup(r, skill, sections=SECTIONS + ("Commands",))
    assert p.returncode == 3 and "sources" in p.stdout


@pytest.mark.parametrize("name", ["convention_map.md", "convention_map.project.md"])
def test_with_every_section_absent_the_convention_map_is_the_source(repo, name):
    """Step 2b's `TOTAL` 0 arm hands the agent the map and its overlay, so both are hashed."""
    r, skill = repo
    (r / "CLAUDE.md").write_text("# Project\n", encoding="utf-8")
    recorded(r, skill)
    (r / ".claude" / name).write_text("## `x/*` — X\n- r\n", encoding="utf-8")
    p = lookup(r, skill)
    assert p.returncode == 3 and "sources" in p.stdout


@pytest.mark.parametrize("name", ["security_map.md", "security_map.project.md"])
def test_the_security_gate_keys_on_the_map_and_its_overlay(repo, name):
    r, skill = repo
    recorded(r, skill, gate="security")
    assert lookup(r, skill, gate="security").returncode == 0
    with open(r / ".claude" / name, "a", encoding="utf-8") as f:
        f.write("- one more rule\n")
    p = lookup(r, skill, gate="security")
    assert p.returncode == 3 and "sources" in p.stdout


def test_the_two_gates_keep_separate_records(repo):
    r, skill = repo
    recorded(r, skill, gate="security")
    assert lookup(r, skill).returncode == 3
    assert lookup(r, skill, gate="security").returncode == 0


def test_a_changed_step_2b_is_a_miss_and_text_outside_it_is_not(repo):
    r, skill = repo
    recorded(r, skill)
    (skill / "SKILL.md").write_text(SKILL.replace("Text after the step.", "Changed."), encoding="utf-8")
    assert lookup(r, skill).returncode == 0
    (skill / "SKILL.md").write_text(SKILL.replace("Spawn one Agent", "Spawn an Agent"), encoding="utf-8")
    p = lookup(r, skill)
    assert p.returncode == 3 and "template" in p.stdout


@pytest.mark.parametrize("old,new,leg", [('`model: "sonnet"`', '`model: "opus"`', "model"),
                                         ('`effort: "high"` (always)', '`effort: "medium"` (always)', "effort")])
def test_the_role_s_model_and_effort_are_their_own_legs(repo, old, new, leg):
    r, skill = repo
    recorded(r, skill)
    (skill / "SKILL.md").write_text(SKILL.replace(old, new), encoding="utf-8")
    p = lookup(r, skill)
    assert p.returncode == 3
    assert leg in p.stdout.split(": ", 1)[1].split(" changed")[0].split(", ")


def test_the_unpushed_main_group_keys_on_head_and_origin(repo, tmp_path):
    r, skill = repo
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=GIT_ENV)
    git(r, "remote", "add", "origin", str(origin))
    git(r, "push", "-q", "origin", "main")
    commit(r, "local.py", "l\n", "local")
    recorded(r, skill, target="unpushed-main")
    assert lookup(r, skill, target="unpushed-main").returncode == 0
    commit(r, "local.py", "l2\n", "local 2")
    assert lookup(r, skill, target="unpushed-main").returncode == 3


def test_the_unpushed_main_group_s_base_is_origin_not_the_local_branch(repo, tmp_path):
    """Pushing part of the local commits moves `origin/main` onto an ancestor of `HEAD`: the
    commit is the same, and the diff basis `origin/main...HEAD` is not."""
    r, skill = repo
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=GIT_ENV)
    git(r, "remote", "add", "origin", str(origin))
    git(r, "push", "-q", "origin", "main")
    first = commit(r, "a.py", "a\n", "first")
    commit(r, "b.py", "b\n", "second")
    recorded(r, skill, target="unpushed-main")
    git(r, "push", "-q", "origin", f"{first}:refs/heads/main")
    git(r, "fetch", "-q", "origin")
    p = lookup(r, skill, target="unpushed-main")
    assert p.returncode == 3 and p.stdout.split(": ", 1)[1].startswith("base changed"), p.stdout


# ── what is never reused, and what is never recorded ──────────────────────────────────

@pytest.mark.parametrize("move", ["overlay", "claude", "skill"])
def test_an_input_that_moves_while_the_agent_runs_records_nothing(repo, move):
    """The key is the lookup's, from before the spawn. Recomputing it at record time recorded
    a verdict against a rule the agent never had (Phase 394's round, lens A)."""
    r, skill = repo
    gate = "security" if move == "overlay" else "convention"
    key = key_now(r, skill, gate=gate)
    if move == "overlay":
        (r / ".claude" / "security_map.project.md").write_text("## `**/*.py` — A03\n- no eval\n",
                                                                encoding="utf-8")
    elif move == "claude":
        (r / "CLAUDE.md").write_text(CLAUDE + "\n- One more rule.\n", encoding="utf-8")
    else:
        (skill / "SKILL.md").write_text(SKILL.replace("Spawn one Agent", "Spawn an Agent"), encoding="utf-8")
    p = record(r, skill, gate=gate, key=key)
    assert p.returncode == 2 and "an input moved while the agent ran" in p.stderr, (p.stdout, p.stderr)
    assert lookup(r, skill, gate=gate).returncode == 3


def test_a_run_from_a_subdirectory_reads_the_top_level_s_files(repo):
    """Relative to the current directory, every source hashed as absent from a subdirectory,
    and an edit to `CLAUDE.md` reused the verdict (round 2, lens A)."""
    r, skill = repo
    (r / "src").mkdir()
    recorded(r / "src", skill)
    (r / "CLAUDE.md").write_text(CLAUDE + "\n- Never use eval.\n", encoding="utf-8")
    p = lookup(r / "src", skill)
    assert p.returncode == 3 and "sources" in p.stdout


@pytest.mark.parametrize("key", ["KEY: {k}", "{k12}", "", "<key>"])
def test_a_key_that_is_not_one_is_refused_as_such(repo, key):
    r, skill = repo
    k = key_now(r, skill)
    p = record(r, skill, key=key.format(k=k, k12=k[:12]))
    assert p.returncode == 2 and "is not a key" in p.stderr, p.stderr
    assert "an input moved" not in p.stderr


def test_a_branch_named_like_the_group_is_refused(repo):
    r, skill = repo
    git(r, "branch", "unpushed-main", "feat")
    p = lookup(r, skill, target="unpushed-main")
    assert p.returncode == 2 and "a branch is named unpushed-main" in p.stderr


def test_a_spawn_line_with_no_effort_is_never_reused(repo):
    """`served_models.yml`: a role mapped to a model with no effort entry passes none, and the
    spawn then runs at the session's effort, which no key can see."""
    r, skill = repo
    (skill / "SKILL.md").write_text(SKILL.replace('`model: "opus"`, `effort: "high"`', '`model: "sonnet"`'),
                                    encoding="utf-8")
    p = lookup(r, skill, gate="security")
    assert p.returncode == 3 and "names no effort" in p.stdout
    assert "KEY:" not in p.stdout  # the skill records only a target whose lookup printed one
    q = record(r, skill, gate="security", key="0" * 64)
    assert q.returncode == 2 and "names no effort" in q.stderr
    assert lookup(r, skill).returncode == 3  # the convention gate's line still has one

@pytest.mark.parametrize("target", ["feat", "unpushed-main"])
@pytest.mark.parametrize("echo", ["0" * 40, "", "HEAD", "abc1234", "{prefix}"])
def test_record_refuses_an_echo_that_is_not_the_target_s_commit(repo, tmp_path, echo, target):
    """`{prefix}` is the tip's own first 12 characters: an abbreviated echo is not the receipt
    Step 2b asks for, which is the pinned checkout's whole `rev-parse HEAD`."""
    r, skill = repo
    if target == "unpushed-main":
        origin = tmp_path / "origin.git"
        subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=GIT_ENV)
        git(r, "remote", "add", "origin", str(origin))
        git(r, "push", "-q", "origin", "main")
        commit(r, "local.py", "l\n", "local")
    echo = echo.format(prefix=git(r, "rev-parse", "feat" if target == "feat" else "HEAD")[:12])
    p = record(r, skill, echo=echo, target=target)
    assert p.returncode == 2 and "not recorded" in p.stderr
    assert not (r / "sysop" / "runtime" / "gate-verdicts").exists() or not list(
        (r / "sysop" / "runtime" / "gate-verdicts").glob("*.json"))


def test_an_echo_of_the_old_tip_after_the_branch_moved_records_nothing(repo):
    r, skill = repo
    old = git(r, "rev-parse", "feat")
    git(r, "switch", "-q", "feat")
    commit(r, "work.py", "print(3)\n", "moved")
    git(r, "switch", "-q", "main")
    assert record(r, skill, echo=old).returncode == 2
    assert lookup(r, skill).returncode == 3


@pytest.mark.parametrize("damage", ["not json", '{"key": 1}', "VERDICT"])
def test_a_damaged_or_unapproved_record_is_a_miss(repo, damage):
    r, skill = repo
    recorded(r, skill)
    (p,) = (r / "sysop" / "runtime" / "gate-verdicts").glob("convention-*.json")
    if damage == "VERDICT":
        rec = json.loads(p.read_text(encoding="utf-8"))
        rec["verdict"] = "BLOCKED"
        p.write_text(json.dumps(rec), encoding="utf-8")
    else:
        p.write_text(damage, encoding="utf-8")
    q = lookup(r, skill)
    assert q.returncode == 3 and q.stdout.startswith("MISS feat")
    recorded(r, skill)  # the miss printed its key, so the next approval records again


def test_a_target_whose_inputs_moved_records_again(repo):
    """The commonest miss is a relaunch after an input moved. Its `KEY:` line is what lets the
    next approval be recorded; without it the target never reuses again (round 2, lens B)."""
    r, skill = repo
    recorded(r, skill)
    (r / "CLAUDE.md").write_text(CLAUDE + "\n- One more.\n", encoding="utf-8")
    p = lookup(r, skill)
    assert p.returncode == 3 and "changed since" in p.stdout and "\nKEY: " in p.stdout
    recorded(r, skill)
    assert lookup(r, skill).returncode == 0


def test_a_different_whole_key_is_refused(repo):
    r, skill = repo
    p = record(r, skill, key="f" * 64)
    assert p.returncode == 2 and "an input moved" in p.stderr
    assert lookup(r, skill).returncode == 3


def test_workflow_md_row_matches_the_script_s_usage():
    """The § 8.4 row is the documented signature; round 2 found it a key short of `record`'s."""
    row = next(ln for ln in (REPO / "core" / "companion" / "docs" / "WORKFLOW.md")
               .read_text(encoding="utf-8").splitlines() if ln.startswith("| `gate_verdict.py lookup"))
    doc = gate_verdict.__doc__
    for sub in ("lookup", "record"):
        usage = re.search(rf"^    {sub} (.+)$", doc, re.M).group(1)
        words = [w.strip("<>[].").upper().replace("-", "_") for w in usage.split()]
        documented = re.search(rf"`(?:gate_verdict\.py )?{sub} ([^`]+)`", row).group(1)
        got = [w.strip("<>[].") for w in documented.split()]
        assert [w for w in got if w] == [w for w in words if w], (sub, documented, words)


@pytest.mark.parametrize("argv", [
    ["lookup", "security", "feat", "main", "{skill}", "Prevention Conventions"],
    ["lookup", "convention", "feat", "main", "{skill}"],
    ["lookup", "convention", "feat", "main", "{skill}", "## Prevention Conventions"],
    ["lookup", "convention", "<target>", "main", "{skill}", "Prevention Conventions"],
    ["lookup", "convention", "feat", "<default branch>", "{skill}", "Prevention Conventions"],
    ["lookup", "conventions", "feat", "main", "{skill}", "Prevention Conventions"],
    ["lookup", "convention", "no-such-branch", "main", "{skill}", "Prevention Conventions"],
    ["lookup", "convention", "feat", "main", "{nowhere}", "Prevention Conventions"],
    ["record", "convention", "feat", "main", "{skill}"],
    ["record", "convention", "feat", "main", "{skill}", "{tip}", "Prevention Conventions"],
    ["reuse", "convention", "feat", "main", "{skill}"],
    [],
])
def test_a_key_that_cannot_be_computed_exits_2(repo, tmp_path, argv):
    r, skill = repo
    tip = git(r, "rev-parse", "feat")
    argv = [a.format(skill=skill, nowhere=tmp_path / "nowhere", tip=tip) for a in argv]
    p = run(r, *argv)
    assert p.returncode == 2, (p.stdout, p.stderr)
    assert not p.stdout.startswith("REUSE")
    if any(a in ("<target>", "<default branch>") for a in argv):
        assert "substitute the target" in p.stderr, p.stderr


ARMED = SKILL.replace("Text before the step.", "Text before the step.\n\n<!-- sysop:arm=4a-y -->") \
    .replace("   Spawn one Agent", "<!-- sysop:arm=2b-x -->\n\n   Spawn one Agent")


def _armed(skill, x="   Handed to the agent.\n", y="Another step's arm.\n"):
    (skill / "SKILL.md").write_text(ARMED, encoding="utf-8")
    (skill / "steps").mkdir(exist_ok=True)
    (skill / "steps" / "2b-x.md").write_text(x, encoding="utf-8")
    (skill / "steps" / "4a-y.md").write_text(y, encoding="utf-8")


def test_a_changed_arm_inside_step_2b_is_a_miss_and_an_arm_outside_it_is_not(repo):
    """Phase 406 moved Step 2b text the agents are handed into step files; a key over the core
    alone reused a verdict after that text changed."""
    r, skill = repo
    _armed(skill)
    recorded(r, skill)
    _armed(skill, y="Another step's arm, changed.\n")
    assert lookup(r, skill).returncode == 0
    _armed(skill, x="   Handed to the agent, changed.\n")
    p = lookup(r, skill)
    assert p.returncode == 3 and "template" in p.stdout, p.stdout


def test_a_role_line_in_a_step_2b_arm_is_the_one_read(repo):
    """The twin's spawn line moved into an arm (Phase 406): read there, or every security
    lookup refuses with no line for the role."""
    r, skill = repo
    line = '   Spawn one Agent with `model: "opus"`, `effort: "high"` <!-- sysop:role=security-gate --> here.\n'
    (skill / "SKILL.md").write_text(SKILL.replace(line, "<!-- sysop:arm=2b-x -->\n"), encoding="utf-8")
    (skill / "steps").mkdir()
    (skill / "steps" / "2b-x.md").write_text(line, encoding="utf-8")
    recorded(r, skill, gate="security")
    (skill / "steps" / "2b-x.md").write_text(line.replace('"opus"', '"sonnet"'), encoding="utf-8")
    p = lookup(r, skill, gate="security")
    assert p.returncode == 3 and "model" in p.stdout, p.stdout


@pytest.mark.parametrize("arm", ["2b-no-conventions", "2b-large-diff", "2b-twin-spawn", "2b-leak"])
def test_each_shipped_step_2b_arm_is_in_the_shipped_cut(tmp_path, arm):
    """One edit per shipped arm moves the cut (Phase 406's round, lens B: only the equality
    with the test splice covered the shipped arms)."""
    skill = tmp_path / "review-close"
    shutil.copytree(CLOSE_DIR, skill)
    before = gate_verdict.step_2b(str(skill))
    step = skill / "steps" / f"{arm}.md"
    step.write_text(step.read_text(encoding="utf-8") + "x\n", encoding="utf-8")
    assert gate_verdict.step_2b(str(skill)) != before


def test_the_key_docstring_says_the_cut_reads_the_arms():
    """Phase 406's round (lens B, G03): reverting the row to "the core alone" survived."""
    doc = " ".join(gate_verdict.__doc__.split())
    assert ("with each arm marker in it replaced by its step file (Phase 406: the twin's spawn "
            "and two of the convention gate's hand-overs live there)") in doc


def test_a_fenced_marker_is_an_example_and_a_nested_arm_is_read(repo):
    """The cut follows the splice's rules (Phase 406's round, lens A): a fenced marker is not an
    arm, and an arm may sit in a subdirectory of `steps/`."""
    r, skill = repo
    _armed(skill)
    (skill / "SKILL.md").write_text(ARMED.replace("<!-- sysop:arm=2b-x -->",
        "```\n<!-- sysop:arm=example -->\n```\n\n<!-- sysop:arm=sub/x -->"), encoding="utf-8")
    (skill / "steps" / "sub").mkdir()
    (skill / "steps" / "sub" / "x.md").write_text("   Nested.\n", encoding="utf-8")
    recorded(r, skill)
    (skill / "steps" / "sub" / "x.md").write_text("   Nested, changed.\n", encoding="utf-8")
    p = lookup(r, skill)
    assert p.returncode == 3 and "template" in p.stdout, (p.stdout, p.stderr)


@pytest.mark.parametrize("name,want", [("2b-gone", "does not exist"), ("../escape", "not a step file's name"),
                                       ("sub/../x", "not a step file's name")])
def test_an_arm_the_cut_cannot_read_is_refused(repo, name, want):
    r, skill = repo
    (skill / "SKILL.md").write_text(ARMED.replace("sysop:arm=2b-x", f"sysop:arm={name}"), encoding="utf-8")
    p = lookup(r, skill)
    assert p.returncode == 2 and want in p.stderr, p.stderr


def test_a_skill_with_two_step_2b_headings_is_refused(repo):
    r, skill = repo
    (skill / "SKILL.md").write_text(SKILL + "\n### 2b. Again\n\nMore.\n", encoding="utf-8")
    p = lookup(r, skill)
    assert p.returncode == 2 and "2 `### 2b.` headings" in p.stderr


def test_a_skill_with_two_lines_for_one_role_is_refused(repo):
    r, skill = repo
    (skill / "SKILL.md").write_text(SKILL.replace("here.", "here.\n   `model: \"haiku\"`, `effort: \"low\"` "
                                                  "<!-- sysop:role=convention-gate -->"), encoding="utf-8")
    p = lookup(r, skill)
    assert p.returncode == 2 and "2 lines marked" in p.stderr


# ── the shipped skill ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["convention-gate", "security-gate"])
def test_the_shipped_step_2b_names_one_readable_spawn_line_per_role(role):
    """Reuse turns itself off quietly (exit 2, then a spawn) if the spawn line stops parsing,
    so the shipped text is held to it here."""
    section = gate_verdict.step_2b(str(CLOSE_DIR))
    got = gate_verdict.spawn_line(section, role)
    assert all(got), got


def test_the_shipped_cut_ends_at_step_2c():
    """The cut stops at the next `### ` line, fenced or not, so a fenced column-0 `### ` in
    Step 2b would end it early and leave the rest of the step out of the key. Since Phase 406
    the cut splices Step 2b's arms, so it is found in the spliced text."""
    section = gate_verdict.step_2b(str(CLOSE_DIR))
    text = text_of(CLOSE_DIR / "SKILL.md")
    after = text[text.index(section) + len(section):]
    assert after.startswith("### 2c. "), after[:80]


def test_the_skill_s_commands_name_the_script_s_gates_and_argument_order():
    text = text_of(CLOSE_DIR / "SKILL.md")
    cmds = re.findall(r"^\s*python3 sysop/scripts/gate_verdict\.py (.+)$", text, re.M)
    assert len(cmds) == 4, cmds
    for c in cmds:
        sub, gate, target, default, skill, *rest = re.findall(r'"[^"]*"|\S+', c)
        assert sub in gate_verdict.COMMANDS and gate in gate_verdict.GATES, c
        assert (target, default, skill) == ('"<target>"', '"<default branch>"', '"${CLAUDE_SKILL_DIR}"'), c
        if sub == "record":
            assert rest[:2] == ['"<echoed SHA>"', '"<key>"'], c
            rest = rest[2:]
        assert rest == ([] if gate == "security" else ['"Prevention Conventions"', '"Testing Patterns"']), c


def test_both_lookups_come_before_anything_is_read_for_the_target():
    """Round 2, lens A: a lookup after step 1's reads left a move between them covered by no
    key, so the agent could review an older diff or rule set than the one recorded."""
    text = text_of(CLOSE_DIR / "SKILL.md")
    loop = text.index("**For each remaining target:**")
    conv = text.index("python3 sysop/scripts/gate_verdict.py lookup convention")
    assert loop < conv < text.index("1. Read the **entire** convention-bearing set", loop)
    sec = text.index("python3 sysop/scripts/gate_verdict.py lookup security")
    assert sec < text.index('python3 sysop/scripts/security_map_filter.py "<target>"')
    assert "A target whose lookup printed no `KEY:` is not recorded." in text


def test_the_shipped_skill_records_only_a_notes_free_approval():
    text = text_of(CLOSE_DIR / "SKILL.md")
    assert "**Record each `VERDICT: APPROVED` whose `NOTES:` is `none`**" in text
    assert "create no checkout and spawn no agent for this target" in text
    assert re.search(r"^Conventions: +<N checked, N reused, N skipped \(doc-only\)>", text, re.M)
    assert ("Tally `<N checked, N reused, N skipped (doc-only)>` for the `Conventions:` line, and "
            "`<N checked, N reused, N skipped (no map match)>` for the `Security map:` line") in text
    # Item 4's stop on a BLOCKED must not come before the record: a relaunch after one branch
    # blocked is the case this exists for (Phase 394's round, lens B).
    assert "first record the approvals as the paragraph below says, then list every violation" in text
    assert "A `REUSE` verdict is not that case" in text
