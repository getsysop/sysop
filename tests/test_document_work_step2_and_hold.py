"""`/document-work` Step 2's trailer probe and Step 3's pre-merge-condition line.

**Step 2 (`Q-053`'s trailer leg).** Step 2 used to read `git log -1` and treat the tip as the
close-out commit. A shipped sequence breaks that: `/claim-task`'s executor commits with
`Doc-Work: <ID>`, `/document-work` pushes the branch, `/review-close` Step 2a commits an ignored
file the branch reads (`feature_branch.py keep-ignored … commit`, no trailer), Step 3b refuses
the now-stale doc and says to re-run `/document-work`. The re-run's Step 2 then read the trailer
as absent and wrote a trailer-only commit on a pushed branch, or amended the close's commit on an
unpushed one. The probe now reads every commit the branch adds to the default branch and prints
what it found. These tests run the shipped block on real git fixtures.

**Step 3 (`Q-755`).** A condition that must be met before the merge belongs in a channel
`/review-close` Step 3c reads before the merge, never in `hold:`. The test reads the channel
names out of the skill's own line, writes a pending doc each way, and runs `smoke_detect.py`
on it, so a heading the gate cannot see fails here.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _heredoc_population import heredoc_containing  # noqa: E402
from skill_runner_text import text_of  # noqa: E402
from test_review_close_smoke_gate import _run as _smoke_run, _seed_main  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "core" / "skills" / "document-work" / "SKILL.md"
TASK = "FEAT-0001"


# ── Step 2: the trailer probe ────────────────────────────────────────────────────────────────

def _env() -> dict:
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    for k in [k for k in env if k.startswith(("GIT_CONFIG_KEY", "GIT_CONFIG_VALUE"))]:
        del env[k]
    env.pop("GIT_CONFIG_COUNT", None)
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    return env


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=_env())
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def _commit(cwd: Path, name: str, message: str) -> str:
    (cwd / name).write_text(name + "\n", encoding="utf-8")
    _git(cwd, "add", "-f", name)
    _git(cwd, "commit", "-q", "-m", message)
    return _git(cwd, "rev-parse", "HEAD")


def _probe_body() -> str:
    return heredoc_containing(SKILL, 'print("NOT CARRIED: no commit in "')


def _probe(cwd: Path, task: str = TASK, base: str = "main") -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-", task, base], input=_probe_body(), cwd=str(cwd),
                          capture_output=True, text=True, env=_env())


@pytest.fixture
def pushed_branch(tmp_path: Path) -> tuple[Path, str]:
    """The shipped sequence up to the re-run: executor commit with the trailer, the branch
    pushed with an upstream (interactive Step 5), then Step 2a's keep-ignored commit."""
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    main = tmp_path / "main"
    _git(tmp_path, "clone", "-q", str(origin), str(main))
    _git(main, "checkout", "-q", "-B", "main")
    _git(main, "config", "user.name", "t")
    _git(main, "config", "user.email", "t@example.invalid")
    _git(main, "config", "commit.gpgsign", "false")
    _commit(main, "README", "seed")
    _git(main, "push", "-q", "origin", "main")
    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", "feat/feat-0001", str(wt))
    work = _commit(wt, "a.py", f"feat: the work ({TASK})\n\nDoc-Work: {TASK}")
    _git(wt, "push", "-q", "-u", "origin", "HEAD")
    _commit(wt, "x.json", "fix: commit fixtures/x.json, which the branch reads")
    return wt, work


def test_a_trailer_below_the_tip_is_found_and_nothing_is_written(pushed_branch) -> None:
    wt, work = pushed_branch
    tip = _git(wt, "rev-parse", "HEAD")
    r = _probe(wt)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"CARRIED: {work[:12]} feat: the work ({TASK})", r.stdout
    assert _git(wt, "rev-parse", "HEAD") == tip, "the probe moved HEAD"


def test_no_trailer_on_the_branch_prints_not_carried(tmp_path: Path, pushed_branch) -> None:
    wt, _ = pushed_branch
    r = _probe(wt, task="FEAT-0002")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ("NOT CARRIED: no commit in the commits HEAD adds to main "
                                "carries Doc-Work: FEAT-0002"), r.stdout


def test_another_tasks_trailer_does_not_count(pushed_branch) -> None:
    wt, _ = pushed_branch
    _commit(wt, "b.py", "feat: other (FEAT-0010)\n\nDoc-Work: FEAT-0010")
    assert _probe(wt, task="FEAT-0001").stdout.startswith("CARRIED: ")
    assert _probe(wt, task="FEAT-001").stdout.startswith("NOT CARRIED: "), "a prefix matched"


def test_a_trailer_outside_the_last_paragraph_is_not_a_trailer(pushed_branch) -> None:
    """git's own trailer parser, as `git interpret-trailers --parse` read it before."""
    wt, _ = pushed_branch
    _commit(wt, "c.py", "feat: x\n\nDoc-Work: FEAT-0003\n\nbody prose after it")
    assert _probe(wt, task="FEAT-0003").stdout.startswith("NOT CARRIED: ")


def test_a_commit_already_on_origins_default_branch_is_not_the_branchs(pushed_branch) -> None:
    """/sitrep reads the branch's commits past both the local and origin's default branch."""
    wt, _ = pushed_branch
    up = wt.parent / "up"
    _git(wt.parent, "clone", "-q", "-b", "main", str(wt.parent / "origin.git"), str(up))
    _git(up, "config", "user.name", "t")
    _git(up, "config", "user.email", "t@example.invalid")
    _git(up, "config", "commit.gpgsign", "false")
    _commit(up, "d.py", "feat: landed (FEAT-0004)\n\nDoc-Work: FEAT-0004")
    _git(up, "push", "-q", "origin", "main")
    _git(wt, "fetch", "-q", "origin")
    _git(wt, "merge", "-q", "--no-edit", "refs/remotes/origin/main")
    assert _probe(wt, task="FEAT-0004").stdout.startswith("NOT CARRIED: ")


def test_on_the_default_branch_it_reads_the_tip(pushed_branch) -> None:
    wt, _ = pushed_branch
    main = wt.parent / "main"
    _commit(main, "e.py", "fix: on main (FEAT-0005)\n\nDoc-Work: FEAT-0005")
    r = _probe(main, task="FEAT-0005")
    assert r.returncode == 0 and r.stdout.startswith("CARRIED: "), (r.stdout, r.stderr)
    _commit(main, "f.py", "chore: later")
    r = _probe(main, task="FEAT-0005")
    assert r.stdout.strip() == "NOT CARRIED: no commit in the tip of main carries Doc-Work: FEAT-0005"


def test_a_second_id_in_the_same_trailer_block_is_found(pushed_branch) -> None:
    wt, _ = pushed_branch
    sha = _commit(wt, "g.py", "feat: two (FEAT-0006)\n\nDoc-Work: FEAT-0006\nDoc-Work: TECH-0007\n"
                              "Co-Authored-By: a <a@example.invalid>")
    assert _probe(wt, task="TECH-0007").stdout.strip() == f"CARRIED: {sha[:12]} feat: two (FEAT-0006)"


def test_a_commit_in_a_recorded_merged_pr_head_is_not_the_branchs(pushed_branch) -> None:
    """/review-close Step 4d records a merged PR's head; /sitrep reads past it too."""
    wt, work = pushed_branch
    _git(wt, "update-ref", "refs/sysop/merged-pr-heads/7", work)
    assert _probe(wt).stdout.startswith("NOT CARRIED: ")


def test_a_workspace_without_a_local_default_branch_reads_origins(pushed_branch) -> None:
    wt, work = pushed_branch
    clone = wt.parent / "clone"
    _git(wt.parent, "clone", "-q", "-b", "feat/feat-0001", str(wt.parent / "origin.git"), str(clone))
    assert _git(clone, "branch", "--list", "main") == "", "the fixture kept a local main"
    r = _probe(clone)
    assert r.returncode == 0 and r.stdout.strip() == f"CARRIED: {work[:12]} feat: the work ({TASK})", (
        r.stdout, r.stderr)


def test_a_branch_with_no_commits_of_its_own_is_not_amended(pushed_branch) -> None:
    """NOT CARRIED here would send Step 2 to amend a default-branch commit."""
    wt, _ = pushed_branch
    main = wt.parent / "main"
    _git(main, "branch", "feat/empty", "main")
    empty = wt.parent / "empty"
    _git(main, "worktree", "add", "-q", str(empty), "feat/empty")
    r = _probe(empty)
    # Exit 1: under `--non-interactive`, /auto-build reads a non-zero /document-work as FAILED.
    assert r.returncode == 1 and r.stdout.strip() == (
        "NO COMMITS: HEAD adds no commit to main, so nothing can carry the trailer"), r.stdout


@pytest.mark.parametrize("task, base, code", [
    ("<TASK_ID>", "main", 3),
    (TASK, "<default branch>", 3),
    ("", "main", 3),
    (TASK, "", 3),
    (TASK, "trunk", 2),
])
def test_an_operand_it_cannot_use_stops_and_never_reads_as_none(pushed_branch, task, base,
                                                                  code) -> None:
    """A "none" here leads to an amend, so an unusable operand must not print one."""
    wt, _ = pushed_branch
    r = _probe(wt, task=task, base=base)
    assert r.returncode == code, (r.returncode, r.stdout, r.stderr)
    assert r.stdout == "" and r.stderr.startswith("ERROR: "), (r.stdout, r.stderr)


def _make(cwd: Path) -> None:
    _git(cwd, "config", "user.name", "t")
    _git(cwd, "config", "user.email", "t@example.invalid")
    _git(cwd, "config", "commit.gpgsign", "false")


def test_a_sole_remote_not_named_origin_is_the_one_read(tmp_path: Path) -> None:
    """A clone made with `-o upstream`, local main stale: the trailer commit is already on the
    default branch, so it is not the branch's. /sitrep reads the sole remote the same way."""
    origin = tmp_path / "up.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    _git(seed, "checkout", "-q", "-B", "main")
    _make(seed)
    _commit(seed, "README", "seed")
    _git(seed, "push", "-q", "origin", "main")
    repo = tmp_path / "repo"
    _git(tmp_path, "clone", "-q", "-o", "upstream", "-b", "main", str(origin), str(repo))
    _make(repo)
    _commit(seed, "h.py", "feat: landed (FEAT-8)\n\nDoc-Work: FEAT-8")
    _git(seed, "push", "-q", "origin", "main")
    _git(repo, "fetch", "-q", "upstream")
    _git(repo, "checkout", "-q", "-b", "feat/x", "refs/remotes/upstream/main")
    _commit(repo, "i.py", "feat: mine")
    r = _probe(repo, task="FEAT-8")
    assert r.returncode == 0 and r.stdout.startswith("NOT CARRIED: "), (r.stdout, r.stderr)


def test_a_repo_with_no_remote_reads_its_local_default_branch(tmp_path: Path) -> None:
    """Round 2's survivor DW6: with no remote the probe names `origin` (as /sitrep's callers
    fall back) and reads the local default branch alone; it must not crash."""
    repo = tmp_path / "solo"
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    _make(repo)
    _commit(repo, "README", "seed")
    _git(repo, "checkout", "-q", "-b", "feat/x")
    _commit(repo, "a.py", "feat: mine (FEAT-1)\n\nDoc-Work: FEAT-1")
    _commit(repo, "b.py", "chore: later")
    r = _probe(repo, task="FEAT-1")
    assert r.returncode == 0 and r.stdout.startswith("CARRIED: "), (r.stdout, r.stderr)


def test_a_local_default_branch_ahead_of_origin_is_excluded_too(pushed_branch) -> None:
    wt, _ = pushed_branch
    main = wt.parent / "main"
    _commit(main, "j.py", "fix: local only (FEAT-0009)\n\nDoc-Work: FEAT-0009")
    _git(main, "branch", "feat/after", "main")
    after = wt.parent / "after"
    _git(main, "worktree", "add", "-q", str(after), "feat/after")
    _commit(after, "k.py", "feat: after")
    r = _probe(after, task="FEAT-0009")
    assert r.returncode == 0 and r.stdout.startswith("NOT CARRIED: "), (r.stdout, r.stderr)


def test_a_failed_walk_is_exit_2_never_no_commits(pushed_branch) -> None:
    """An unborn HEAD: the base resolves, `git log HEAD` fails."""
    wt, _ = pushed_branch
    _git(wt, "checkout", "-q", "--orphan", "feat/unborn")
    r = _probe(wt)
    assert r.returncode == 2 and r.stdout == "", (r.returncode, r.stdout, r.stderr)
    assert r.stderr.startswith("ERROR: git log failed"), r.stderr


def test_a_base_ref_that_names_no_commit_does_not_resolve(pushed_branch) -> None:
    """A remote-tracking ref at a tree: `git log --not <tree>` would run and answer."""
    wt, _ = pushed_branch
    _git(wt, "update-ref", "refs/remotes/origin/trunk", _git(wt, "rev-parse", "HEAD^{tree}"))
    r = _probe(wt, base="trunk")
    assert r.returncode == 2 and "neither refs/heads/trunk nor refs/remotes/origin/trunk" in r.stderr, (
        r.returncode, r.stdout, r.stderr)


def _answers() -> str:
    text = text_of(SKILL)
    lead = "**Read the line it prints: `CARRIED:` and `NOT CARRIED:` both exit 0.**"
    assert text.count(lead) == 1, "Step 2's answer paragraph is missing or doubled"
    start = text.index(lead)
    return text[start:text.index("\n\n", start)]


def test_step_2_acts_on_the_printed_line() -> None:
    text = text_of(SKILL)
    step2 = text[text.index("## Step 2: Commit Code Changes"):text.index("## Step 3: Write Pending")]
    assert "git log -1 --format=%B" not in step2, "the tip-only probe is back"
    assert "the most recent commit IS the close-out commit" not in step2
    assert "rule above to the most recent commit" not in step2
    para = _answers()
    carried = para[para.index("`CARRIED: <commit> <subject>`"):para.index("`NO COMMITS:`")]
    assert "writes nothing — no amend, no new commit" in carried, carried
    assert "upstream" not in carried and "--trailer" not in carried, carried
    nocommits = para[para.index("`NO COMMITS:`"):para.index("**Any other non-zero exit")]
    assert "write nothing — no amend, no commit — and stop" in nocommits, nocommits
    assert "under `--non-interactive` end the run as failed" in nocommits, nocommits
    assert "upstream" not in nocommits and "--trailer" not in nocommits, nocommits
    tail = para[para.index("**Any other non-zero exit"):]
    assert tail.endswith("On `NOT CARRIED:`, and only then, **probe for an upstream first**:"), tail
    # The upstream probe's two arms are the only writes, and they follow that line.
    arms = step2[step2.index(para) + len(para):]
    assert arms.index("git rev-parse --abbrev-ref --quiet") < arms.index("--amend --no-edit --trailer")


def test_the_trailer_rule_applies_only_with_a_task_id() -> None:
    text = text_of(SKILL)
    step2 = text[text.index("## Step 2: Commit Code Changes"):text.index("## Step 3: Write Pending")]
    assert ("already committed) and a `<TASK_ID>` resolves for the current branch (per the "
            "derivation rule below), look for") in step2
    tails = re.findall(r"If there are no uncommitted changes[^.]*\.[^\n]*", step2)
    assert len(tails) == 2, tails
    for line in tails:
        assert line.startswith("If there are no uncommitted changes and a `<TASK_ID>` resolves, "
                               "apply the trailer-placement rule above; with no `<TASK_ID>` there "
                               "is no trailer to place."), line


# ── Step 3: a pre-merge condition is not a `hold:` ────────────────────────────────────────────

def _premerge_line() -> str:
    text = text_of(SKILL)
    lead = "**A condition that must be met before the merge never goes in `hold:`**"
    assert text.count(lead) == 1, "Step 3's pre-merge-condition line is missing or doubled"
    start = text.index(lead)
    return text[start:text.index("\n\n", start)]


def _channels() -> tuple[str, str]:
    line = _premerge_line()
    headings = re.findall(r"`(#{1,6} [^`]+)`", line)
    keys = re.findall(r"`(\w+: true)`", line)
    assert len(headings) == 1 and len(keys) == 1, (headings, keys)
    return headings[0], keys[0]


def _doc(main: Path, frontmatter: str, body: str) -> None:
    (main / "sysop/runtime/pending-docs" / "feat-x.md").write_text(
        f'---\nbranch: "feat/x"\nroadmap_ids: [FEAT-X]\ntype: feature\nsummary: "s"\n{frontmatter}---\n'
        f"# Summary\n\nThe work.\n{body}", encoding="utf-8")


def test_the_heading_channel_stops_the_close_and_shows_the_condition(tmp_path: Path) -> None:
    heading, _ = _channels()
    main = _seed_main(tmp_path)
    _doc(main, "", f"\n{heading}\n\nRun the migration on staging first.\n")
    out = _smoke_run(main, [], ["feat/x"])
    assert out.startswith("SMOKE_REQUIRED: 1 signal"), out
    assert heading in out and "Run the migration on staging first." in out, out


def test_the_frontmatter_channel_stops_the_close(tmp_path: Path) -> None:
    _, key = _channels()
    main = _seed_main(tmp_path)
    _doc(main, key + "\n", "")
    out = _smoke_run(main, [], ["feat/x"])
    assert out.startswith("SMOKE_REQUIRED: 1 signal"), out
    assert "frontmatter `manual_smoke: true`" in out, out


def test_the_same_condition_in_hold_is_not_read_before_the_merge(tmp_path: Path) -> None:
    """The control: why the line exists. A merging doc's `hold:` reaches no pre-merge gate."""
    main = _seed_main(tmp_path)
    _doc(main, 'hold: "run the migration on staging before merge"\n', "")
    assert _smoke_run(main, [], ["feat/x"]).strip() == "NO_SMOKE_REQUIRED"


def test_the_pre_merge_line_names_the_gate_that_reads_it() -> None:
    """Step 3c runs before the merge; 4c runs after it, which is where `hold:` is read."""
    line = _premerge_line()
    assert "`/review-close` Step 3c stop and ask the human before it merges" in line, line


# ── Hash pins over the decided runner text ───────────────────────────────────────────────────
# A deliberate change moves its pin in the same commit (`_print_pins()`).

from _reversal import slice_between  # noqa: E402
from test_fix_in_branch_tier import _anchor_count, _pin_hash, _pin_norm, _pin_span  # noqa: E402

SPANS: dict[str, tuple[str, str]] = {
    "step 2 answers": ("**Read the line it prints: `CARRIED:` and `NOT CARRIED:` both exit 0.**",
                       "\n\n```bash\ngit rev-parse --abbrev-ref"),
    "step 3 pre-merge line": ("**A condition that must be met before the merge never goes in `hold:`**",
                              "\n\n"),
}

PINS = {
    "step 2 answers": "482c6b417a8c4aa0",
    "step 3 pre-merge line": "17db09670d9c2422",
}


def _span(label: str) -> str:
    start, end = SPANS[label]
    text = text_of(SKILL)
    span = slice_between(text, start, end, label)
    span = _pin_span(SKILL, text, text.index(span), span)
    assert len(_pin_norm(span)) > 60, f"{label}: the pinned span is nearly empty"
    return span


def _print_pins() -> None:
    for label in SPANS:
        print(f'    "{label}": "{_pin_hash(_span(label))}",')


@pytest.mark.parametrize("label", sorted(SPANS))
def test_the_decided_text_is_pinned(label: str) -> None:
    assert _anchor_count(text_of(SKILL), SPANS[label][0]) == 1, label
    got = _pin_hash(_span(label))
    assert got == PINS[label], (
        f"{label} changed (hash {got}, pinned {PINS[label]}). If the edit is deliberate, "
        "move the pin in the same commit.")
