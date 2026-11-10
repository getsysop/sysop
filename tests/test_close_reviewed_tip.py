"""`Q-737` (Phase 477): `/review-close` merges a branch only at the commit Step 2 reviewed, or on
a person's answer.

Step 2a step 1 records each branch's commit with `close_arms.py reviewed`, a resume copies the
prepare's with `close_run.py reviewed`, and Step 4a item 1 compares with `close_arms.py tip`
before the merge. A mismatch makes the `4a-moved` arm due: attended, the person is asked to
merge or 4a-SKIP; under `--headless` or `--unattended` the branch is 4a-SKIPped (Wade's ruling,
2026-11-08). The PR-reuse probe runs the same check as its sixth condition, because Step 4a
does not run under that shape.

Each behaviour test drives the real scripts as subprocesses against a scratch repository.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "core" / "companion" / "scripts"
ARMS_SCRIPT = SCRIPTS / "close_arms.py"
RUN_SCRIPT = SCRIPTS / "close_run.py"
CLOSE_DIR = REPO / "core" / "skills" / "review-close"
CORE = CLOSE_DIR / "SKILL.md"
STEPS = CLOSE_DIR / "steps"

sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import close_arms  # noqa: E402
from skill_runner_text import text_of  # noqa: E402

ENV = {k: v for k, v in os.environ.items()
       if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
ENV.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, (args, r.stderr)
    return r.stdout.strip()


def arms(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(ARMS_SCRIPT), *args], cwd=cwd,
                          capture_output=True, text=True, env=ENV)


def commit(cwd: Path, name: str, msg: str) -> str:
    (cwd / name).write_text(msg + "\n", encoding="utf-8")
    git(cwd, "add", name)
    git(cwd, "commit", "-qm", msg)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        git(r, *args)
    (r / ".gitignore").write_text("sysop/runtime/\n", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    git(r, "checkout", "-qb", "feat")
    commit(r, "f.py", "feat work")
    git(r, "checkout", "-q", "main")
    return r


def begin(cwd: Path) -> str:
    p = arms(cwd, "begin", "", *sorted(close_arms.ARMS))
    assert p.returncode == 0, p.stderr
    return re.search(r"^CLOSE: (\S+)$", p.stdout, re.M).group(1)


def receipt_lines(cwd: Path, cid: str) -> list[list[str]]:
    p = cwd / "sysop" / "runtime" / "close-arms" / f"{cid}.tsv"
    return [ln.split("\t") for ln in p.read_text(encoding="utf-8").splitlines()]


def required(cwd: Path, cid: str) -> list[str]:
    return [r[1] for r in receipt_lines(cwd, cid) if r[0] == "required"]


def on_feat(repo: Path, name: str, msg: str) -> str:
    git(repo, "checkout", "-q", "feat")
    sha = commit(repo, name, msg)
    git(repo, "checkout", "-q", "main")
    return sha


# ── the record and the check ─────────────────────────────────────────────────────────────

def test_an_unmoved_branch_is_its_reviewed_commit_and_makes_nothing_due(repo):
    cid = begin(repo)
    tip = git(repo, "rev-parse", "refs/heads/feat")
    r = arms(repo, "reviewed", cid, "feat")
    assert r.returncode == 0 and r.stdout == f"REVIEWED: feat {tip}\n", r.stdout + r.stderr
    t = arms(repo, "tip", cid, "feat")
    assert t.returncode == 0 and t.stdout == f"TIP: feat {tip}\nARM: none\n", t.stdout + t.stderr
    assert required(repo, cid) == []


def test_a_commit_after_review_is_listed_and_makes_the_arm_due(repo):
    cid = begin(repo)
    was = git(repo, "rev-parse", "refs/heads/feat")
    arms(repo, "reviewed", cid, "feat")
    now = on_feat(repo, "late.py", "pushed after review")
    t = arms(repo, "tip", cid, "feat")
    assert t.returncode == 0, t.stderr
    lines = t.stdout.splitlines()
    assert lines[0] == f"MOVED: feat was {was} at review and is {now}: 1 commit(s) added since"
    assert f"{now[:7]} pushed after review" in t.stdout and "late.py" in t.stdout
    assert lines[-1] == "ARM: 4a-moved"
    assert required(repo, cid) == ["4a-moved"]


def test_a_rewritten_branch_shows_both_sides(repo):
    cid = begin(repo)
    was = git(repo, "rev-parse", "refs/heads/feat")
    arms(repo, "reviewed", cid, "feat")
    git(repo, "checkout", "-q", "feat")
    git(repo, "commit", "-q", "--amend", "-m", "feat work, reworded")
    now = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    t = arms(repo, "tip", cid, "feat")
    assert t.returncode == 0, t.stderr
    assert t.stdout.startswith(f"REWRITTEN: feat was {was} at review and is {now}, and the "
                               "reviewed commit is no longer in its history: 1 reviewed commit(s) "
                               "are gone (`<`) and 1 are new (`>`)")
    assert t.stdout.index(f"< {was[:7]} feat work\n") < t.stdout.index(f"> {now[:7]} feat work, reworded\n")
    assert t.stdout.endswith("ARM: 4a-moved\n")


def test_a_branch_with_no_record_is_unrecorded_and_makes_the_arm_due(repo):
    cid = begin(repo)
    git(repo, "branch", "other")
    arms(repo, "reviewed", cid, "other")  # another branch's record does not stand in
    t = arms(repo, "tip", cid, "feat")
    assert t.returncode == 0, t.stderr
    assert t.stdout.startswith("UNRECORDED: feat is at ")
    assert t.stdout.endswith("ARM: 4a-moved\n")
    assert required(repo, cid) == ["4a-moved"]


def test_the_latest_record_for_the_branch_is_the_one_compared(repo):
    """A resume copies the prepare's commit, and a Step 2a re-run records again: the re-run's
    record is what that review read."""
    cid = begin(repo)
    arms(repo, "reviewed", cid, "feat")
    on_feat(repo, "late.py", "re-reviewed")
    arms(repo, "reviewed", cid, "feat")
    t = arms(repo, "tip", cid, "feat")
    assert t.stdout.endswith("ARM: none\n"), t.stdout
    assert required(repo, cid) == []


def test_a_same_named_tag_is_not_read_for_the_branch(repo):
    cid = begin(repo)
    git(repo, "tag", "feat", "main")
    tip = git(repo, "rev-parse", "refs/heads/feat")
    assert arms(repo, "reviewed", cid, "feat").stdout == f"REVIEWED: feat {tip}\n"
    assert arms(repo, "tip", cid, "feat").stdout == f"TIP: feat {tip}\nARM: none\n"


@pytest.mark.parametrize("cmd", ["reviewed", "tip"])
@pytest.mark.parametrize("branch", ["", "  ", "<branch>", "no-such-branch"])
def test_a_branch_that_is_not_one_is_refused_and_records_nothing(repo, cmd, branch):
    cid = begin(repo)
    before = receipt_lines(repo, cid)
    r = arms(repo, cmd, cid, branch)
    assert r.returncode == 2 and r.stdout == "", r.stdout
    assert receipt_lines(repo, cid) == before


def test_a_tag_alone_is_not_a_branch(repo):
    cid = begin(repo)
    git(repo, "tag", "only-a-tag", "main")
    assert arms(repo, "reviewed", cid, "only-a-tag").returncode == 2


def test_a_long_run_of_commits_names_the_rest_by_count(repo):
    cid = begin(repo)
    was = git(repo, "rev-parse", "refs/heads/feat")
    arms(repo, "reviewed", cid, "feat")
    git(repo, "checkout", "-q", "feat")
    for i in range(close_arms.TIP_LOG_MAX + 3):
        commit(repo, f"n{i}.py", f"late {i}")
    now = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    t = arms(repo, "tip", cid, "feat")
    assert f"{close_arms.TIP_LOG_MAX + 3} commit(s) added since" in t.stdout
    assert f"... and 3 more: git log {was}..{now}\n" in t.stdout
    assert t.stdout.count(" | ") == close_arms.TIP_LOG_MAX  # one --stat line per listed commit


def test_a_rewrite_shows_the_reviewed_side_however_long_the_new_side(repo):
    """Round 1, lens A F6: one log capped at 20 listed only the newer side."""
    cid = begin(repo)
    was = git(repo, "rev-parse", "refs/heads/feat")
    arms(repo, "reviewed", cid, "feat")
    git(repo, "checkout", "-q", "-B", "feat", "main")
    for i in range(close_arms.TIP_LOG_MAX + 5):
        commit(repo, f"r{i}.py", f"rewritten {i}")
    now = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    t = arms(repo, "tip", cid, "feat").stdout
    assert f"< {was[:7]} feat work\n" in t
    assert t.count("\n> ") == close_arms.TIP_LOG_MAX
    assert f"... and 5 more: git log {was}..{now}\n" in t


def test_peek_prints_the_line_and_records_nothing(repo):
    """Round 1, lens A F4 / lens B 4: the reuse probe's `tip` must not make the arm due."""
    cid = begin(repo)
    tip = git(repo, "rev-parse", "refs/heads/feat")
    arms(repo, "reviewed", cid, "feat")
    assert arms(repo, "tip", cid, "feat", "--peek").stdout == f"TIP: feat {tip}\n"
    now = on_feat(repo, "late.py", "late")
    before = receipt_lines(repo, cid)
    t = arms(repo, "tip", cid, "feat", "--peek")
    assert t.returncode == 0 and t.stdout == (f"MOVED: feat was {tip} at review and is {now}: "
                                              "1 commit(s) added since\n"), t.stdout
    assert receipt_lines(repo, cid) == before


@pytest.mark.parametrize("extra", [["--peak"], ["--peek", "x"]])
def test_tip_refuses_an_unknown_option(repo, extra):
    cid = begin(repo)
    assert arms(repo, "tip", cid, "feat", *extra).returncode == 2


@pytest.mark.parametrize("name", ["feat~1", "feat^", "feat@{0}", "HEAD"])
def test_a_revision_is_not_a_branch(repo, name):
    """Round 1, lens A F5: `rev-parse refs/heads/<x>^{commit}` took revision syntax."""
    cid = begin(repo)
    assert arms(repo, "reviewed", cid, name).returncode == 2
    assert arms(repo, "tip", cid, name).returncode == 2


def test_reviewed_refuses_a_close_with_no_receipt(repo):
    """Round 1, lens B Y09: `reviewed` must not create a receipt for a mistyped id."""
    begin(repo)
    r = arms(repo, "reviewed", "20990101T000000Z-0000", "feat")
    assert r.returncode == 2
    assert not (repo / "sysop/runtime/close-arms/20990101T000000Z-0000.tsv").exists()


@pytest.mark.parametrize("sha", ["", "abc", "g" * 40, "A" * 40])
def test_record_reviewed_refuses_what_is_not_a_commit_id(tmp_path, sha):
    """Round 1, lens B Y03."""
    p = tmp_path / "r.tsv"
    p.write_text("", encoding="utf-8")
    with pytest.raises(close_arms.Refuse):
        close_arms.record_reviewed(p, "feat", sha)
    assert p.read_text(encoding="utf-8") == ""


def test_the_log_runs_no_program_the_consumers_config_names(repo, tmp_path):
    """`tip` prints `--stat`, which runs no textconv driver or external diff (measured at Phase
    477: 0 calls, where `log -p` makes 2), so the flags are inert today. This pins that the log
    stays program-free if it ever prints a patch (Phase 451's class)."""
    mark = tmp_path / "ran"
    conv = tmp_path / "conv.sh"
    conv.write_text(f"#!/bin/sh\necho ran >> '{mark}'\ncat \"$1\"\n", encoding="utf-8")
    conv.chmod(0o755)
    git(repo, "config", "diff.x.textconv", str(conv))
    git(repo, "config", "diff.external", str(conv))
    cid = begin(repo)
    arms(repo, "reviewed", cid, "feat")
    git(repo, "checkout", "-q", "feat")
    (repo / ".gitattributes").write_text("*.bin diff=x\n", encoding="utf-8")
    commit(repo, "data.bin", "binary-ish")
    git(repo, "checkout", "-q", "main")
    # The precondition: without the flags, this config does run the program.
    subprocess.run(["git", "log", "-p", "-1", "refs/heads/feat"], cwd=repo, capture_output=True, env=ENV)
    assert mark.exists(), "the fixture's config runs nothing, so the test below is vacuous"
    mark.unlink()
    t = arms(repo, "tip", cid, "feat")
    assert t.returncode == 0 and "data.bin" in t.stdout, t.stdout + t.stderr
    assert not mark.exists()


def test_a_subject_that_is_not_utf8_is_printed_and_still_decides(repo):
    cid = begin(repo)
    arms(repo, "reviewed", cid, "feat")
    git(repo, "checkout", "-q", "feat")
    (repo / "x.py").write_text("x\n", encoding="utf-8")
    git(repo, "add", "x.py")
    subprocess.run(["git", "-c", "i18n.commitEncoding=latin-1", "commit", "-q", "-m", "caf\xe9"],
                   cwd=repo, env=ENV, check=True)
    git(repo, "checkout", "-q", "main")
    r = subprocess.run([sys.executable, str(ARMS_SCRIPT), "tip", cid, "feat"], cwd=repo,
                       capture_output=True, env=ENV)
    assert r.returncode == 0 and r.stdout.endswith(b"ARM: 4a-moved\n"), r.stdout + r.stderr


def test_a_receipt_with_reviewed_records_is_still_read_and_checked(repo):
    cid = begin(repo)
    arms(repo, "reviewed", cid, "feat")
    c = arms(repo, "check", cid)
    assert c.returncode == 0 and c.stdout == "ARMS: required 0, loaded 0\n", c.stdout + c.stderr


def test_a_due_arm_that_loads_checks_clean(repo):
    cid = begin(repo)
    arms(repo, "reviewed", cid, "feat")
    on_feat(repo, "late.py", "late")
    arms(repo, "tip", cid, "feat")
    digest = close_arms.digest_of((STEPS / "4a-moved.md").read_text(encoding="utf-8"))
    assert arms(repo, "loaded", cid, "4a-moved", digest, str(CLOSE_DIR)).returncode == 0
    assert arms(repo, "check", cid).returncode == 0



# ── Step 2a step 3a's own commit ─────────────────────────────────────────────────────────

def test_the_closes_own_commit_one_past_the_record_is_recorded(repo):
    """Step 2a step 3a's `Commit it to the branch` adds one commit the person chose; recording
    it keeps Step 4a from asking about it again, and an unattended resume from skipping it."""
    cid = begin(repo)
    arms(repo, "reviewed", cid, "feat")
    own = on_feat(repo, "fixture.json", "the ignored fixture, committed by the close")
    r = arms(repo, "reviewed", cid, "feat", "--own-commit")
    assert r.returncode == 0 and r.stdout == f"REVIEWED: feat {own}\n", r.stdout + r.stderr
    assert arms(repo, "tip", cid, "feat").stdout.endswith("ARM: none\n")


def test_own_commit_chains_one_commit_at_a_time(repo):
    cid = begin(repo)
    arms(repo, "reviewed", cid, "feat")
    on_feat(repo, "a.json", "first")
    assert arms(repo, "reviewed", cid, "feat", "--own-commit").returncode == 0
    on_feat(repo, "b.json", "second")
    assert arms(repo, "reviewed", cid, "feat", "--own-commit").returncode == 0
    assert arms(repo, "tip", cid, "feat").stdout.endswith("ARM: none\n")


@pytest.mark.parametrize("shape", ["foreign commit underneath", "no record"])
def test_own_commit_takes_in_no_commit_someone_else_made(repo, shape):
    cid = begin(repo)
    if shape != "no record":
        arms(repo, "reviewed", cid, "feat")
        on_feat(repo, "owner.py", "the owner's commit, after review")
    on_feat(repo, "fixture.json", "the close's own commit")
    before = receipt_lines(repo, cid)
    r = arms(repo, "reviewed", cid, "feat", "--own-commit")
    assert r.returncode == 1 and r.stdout.startswith("NOT RECORDED: feat is at "), r.stdout + r.stderr
    assert receipt_lines(repo, cid) == before
    assert arms(repo, "tip", cid, "feat").stdout.endswith("ARM: 4a-moved\n")


def test_own_commit_takes_in_no_merge(repo):
    """Round 1, lens A F3: a merge's first parent can be the record while it brings in work."""
    cid = begin(repo)
    arms(repo, "reviewed", cid, "feat")
    git(repo, "checkout", "-qb", "evil", "main")
    commit(repo, "evil.py", "unreviewed")
    git(repo, "checkout", "-q", "feat")
    git(repo, "merge", "-q", "--no-edit", "evil")
    git(repo, "checkout", "-q", "main")
    r = arms(repo, "reviewed", cid, "feat", "--own-commit")
    assert r.returncode == 1 and r.stdout.startswith("NOT RECORDED: feat is at "), r.stdout


def test_own_commit_compares_with_the_latest_record_only(repo):
    """Round 1, lens B Y02: a commit on an earlier record, not the latest, is not the close's."""
    cid = begin(repo)
    a = git(repo, "rev-parse", "refs/heads/feat")
    arms(repo, "reviewed", cid, "feat")
    on_feat(repo, "b.json", "own")
    assert arms(repo, "reviewed", cid, "feat", "--own-commit").returncode == 0
    git(repo, "branch", "-f", "feat", a)
    on_feat(repo, "c.py", "someone else's, on the earlier commit")
    assert arms(repo, "reviewed", cid, "feat", "--own-commit").returncode == 1


@pytest.mark.parametrize("extra", [["--own"], ["--own-commit", "x"], ["x"]])
def test_reviewed_refuses_an_unknown_option(repo, extra):
    cid = begin(repo)
    assert arms(repo, "reviewed", cid, "feat", *extra).returncode == 2


def test_step_3as_commit_is_recorded_as_the_closes_own():
    text = (STEPS / "2a-ignored-refs.md").read_text(encoding="utf-8")
    cmd = '   python3 sysop/scripts/close_arms.py reviewed "<close-id>" "<branch>" --own-commit\n'
    assert text.count(cmd) == 1
    assert text.index('feature_branch.py keep-ignored "<workspace>" "<path>" "<commit or copy>"') \
        < text.index("After each `commit` that exited 0, record the branch's new commit") < text.index(cmd)
    assert "**Exit 0** or **exit 1** (`NOT RECORDED:`, which Step 4a's tip check then shows): go on." in text

# ── the resume's copy of the prepare's commits ───────────────────────────────────────────

def run_script(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(RUN_SCRIPT), *args], cwd=cwd,
                          capture_output=True, text=True, env=ENV)


def finished_run(repo: Path, record: bool = True) -> str:
    """A prepare: `close_run.py begin`, the prepare's own receipt with Step 2a step 1's record
    of `feat` (unless `record` is false), and `finish` carrying it."""
    r = run_script(repo, "begin", "main", "feat")
    assert r.returncode == 0, r.stderr
    out = dict(ln.split(": ", 1) for ln in r.stdout.splitlines())
    for ln in r.stdout.splitlines():
        if ln.startswith("STATE "):
            Path(ln.split(": ", 1)[1]).write_text("verdict: approve\n", encoding="utf-8")
    (Path(out["DIR"]) / "questions.md").write_text("", encoding="utf-8")
    prep = begin(repo)
    if record:
        assert arms(repo, "reviewed", prep, "feat").returncode == 0
    f = run_script(repo, "finish", out["RUN"], prep)
    assert f.returncode == 0, f.stdout + f.stderr
    return out["RUN"]


def test_a_resume_records_the_commit_the_prepare_reviewed(repo):
    was = git(repo, "rev-parse", "refs/heads/feat")
    run_id = finished_run(repo)
    now = on_feat(repo, "late.py", "pushed between the prepare and the resume")
    cid = begin(repo)
    r = run_script(repo, "reviewed", run_id, cid)
    assert r.returncode == 0 and r.stdout == f"REVIEWED: feat {was}\n", r.stdout + r.stderr
    t = arms(repo, "tip", cid, "feat")
    assert t.stdout.startswith(f"MOVED: feat was {was} at review and is {now}"), t.stdout


def test_a_branch_that_moved_after_begin_and_back_is_not_merged_unasked(repo):
    """Round 1, lens A F1: `begin` takes its tip before Step 2a, so a branch that moved, was
    reviewed at the new commit, and moved back reads CURRENT to `check`. The resume copies the
    prepare's own record, and the branch then reads REWRITTEN at Step 4a."""
    x = git(repo, "rev-parse", "refs/heads/feat")
    r = run_script(repo, "begin", "main", "feat")
    out = dict(ln.split(": ", 1) for ln in r.stdout.splitlines())
    for ln in r.stdout.splitlines():
        if ln.startswith("STATE "):
            Path(ln.split(": ", 1)[1]).write_text("verdict: approve\n", encoding="utf-8")
    (Path(out["DIR"]) / "questions.md").write_text("", encoding="utf-8")
    y = on_feat(repo, "fix.py", "moved after begin")  # before the prepare's Step 2a
    prep = begin(repo)
    arms(repo, "reviewed", prep, "feat")  # Step 2a reads y
    assert run_script(repo, "finish", out["RUN"], prep).returncode == 0
    git(repo, "branch", "-f", "feat", x)  # back to begin's tip
    assert run_script(repo, "check", out["RUN"], "main").stdout.strip() == "CURRENT"
    cid = begin(repo)
    r = run_script(repo, "reviewed", out["RUN"], cid)
    assert r.stdout == f"REVIEWED: feat {y}\n", r.stdout + r.stderr
    t = arms(repo, "tip", cid, "feat")
    assert t.stdout.startswith(f"REWRITTEN: feat was {y} at review and is {x}"), t.stdout
    assert t.stdout.endswith("ARM: 4a-moved\n")


def test_a_branch_the_prepare_did_not_record_is_not_reviewed(repo):
    run_id = finished_run(repo, record=False)
    cid = begin(repo)
    r = run_script(repo, "reviewed", run_id, cid)
    assert r.returncode == 0 and r.stdout == "NOT REVIEWED: feat\n", r.stdout + r.stderr
    assert arms(repo, "tip", cid, "feat").stdout.startswith("UNRECORDED: feat is at ")


def test_finish_carries_the_last_record_per_branch(repo):
    r = run_script(repo, "begin", "main", "feat")
    out = dict(ln.split(": ", 1) for ln in r.stdout.splitlines())
    for ln in r.stdout.splitlines():
        if ln.startswith("STATE "):
            Path(ln.split(": ", 1)[1]).write_text("verdict: approve\n", encoding="utf-8")
    (Path(out["DIR"]) / "questions.md").write_text("", encoding="utf-8")
    prep = begin(repo)
    arms(repo, "reviewed", prep, "feat")
    later = on_feat(repo, "rerun.py", "re-reviewed")
    arms(repo, "reviewed", prep, "feat")
    git(repo, "branch", "other")
    arms(repo, "reviewed", prep, "other")  # not in the run: not carried
    assert run_script(repo, "finish", out["RUN"], prep).returncode == 0
    m = json.loads((Path(out["DIR"]) / "manifest.json").read_text(encoding="utf-8"))
    assert m["reviewed"] == {"feat": later}


@pytest.mark.parametrize("bad", ["20990101T000000Z-0000", "not-a-close"])
def test_finish_refuses_a_close_id_with_no_receipt(repo, bad):
    r = run_script(repo, "begin", "main", "feat")
    out = dict(ln.split(": ", 1) for ln in r.stdout.splitlines())
    for ln in r.stdout.splitlines():
        if ln.startswith("STATE "):
            Path(ln.split(": ", 1)[1]).write_text("verdict: approve\n", encoding="utf-8")
    (Path(out["DIR"]) / "questions.md").write_text("", encoding="utf-8")
    f = run_script(repo, "finish", out["RUN"], bad)
    assert f.returncode == 2, f.stdout + f.stderr
    assert "finished" not in json.loads((Path(out["DIR"]) / "manifest.json").read_text(encoding="utf-8"))


def test_a_run_an_older_finish_wrote_records_nothing(repo):
    run_id = finished_run(repo)
    mp = repo / "sysop" / "runtime" / "close" / run_id / "manifest.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    del m["reviewed"]
    mp.write_text(json.dumps(m), encoding="utf-8")
    cid = begin(repo)
    assert run_script(repo, "reviewed", run_id, cid).stdout == "NOT REVIEWED: feat\n"


@pytest.mark.parametrize("bad", ["20990101T000000Z-0000", "not-a-close"])
def test_a_resume_with_no_receipt_for_the_close_is_refused(repo, bad):
    run_id = finished_run(repo)
    r = run_script(repo, "reviewed", run_id, bad)
    assert r.returncode == 2 and r.stdout == "", r.stdout


def test_a_consumed_run_is_refused(repo):
    run_id = finished_run(repo)
    assert run_script(repo, "consume", run_id).returncode == 0
    cid = begin(repo)
    r = run_script(repo, "reviewed", run_id, cid)
    assert r.returncode == 2 and "already resumed" in r.stderr, r.stderr
    assert not [x for x in receipt_lines(repo, cid) if x[0] == "reviewed"]


# ── where the skill runs each command ─────────────────────────────────────────────────────

def flat(text: str) -> str:
    return " ".join(text.split())


def test_step_2a_records_the_commit_before_reading_the_branch():
    core = text_of(CORE)
    step = core[core.index("### 2a. Feature Branches"):core.index("### 2b. Prevention Convention Check")]
    rec = 'Then `python3 sysop/scripts/close_arms.py reviewed "<close-id>" "<branch>"`'
    assert step.count(rec) == 1
    assert step.index("0b. **Landed check.**") \
        < step.index('1. `python3 sysop/scripts/feature_branch.py base "<branch>" "<default branch>"`') \
        < step.index(rec) < step.index("python3 sysop/scripts/git_ro.py . log <base>..refs/heads/<branch>") \
        < step.index("2. `git diff <base> refs/heads/<branch> --stat`")


def test_step_4a_checks_the_tip_after_routing_and_before_the_merge():
    core = text_of(CORE)
    step = core[core.index("### 4a. Merge Approved Feature Branches"):core.index("### 4a-fix.")]
    cmd = '   python3 sysop/scripts/close_arms.py tip "<close-id>" "<branch>"\n'
    assert step.count(cmd) == 1
    assert step.index('python3 sysop/scripts/pr_head_check.py "<branch>" "<merge target>"') \
        < step.index("**Then, for a branch item 2 will merge, ask whether it is still the commit Step 2 reviewed**") \
        < step.index(cmd) < step.index("**Load this arm when it printed `ARM: 4a-moved`**") \
        < step.index('python3 sysop/scripts/close_arms.py loaded "<close-id>" 4a-moved ') \
        < step.index("2. **Merge — rebase-then-ff")


def test_the_resume_copies_the_prepares_commits_after_its_first_check():
    text = (STEPS / "prepare-resume.md").read_text(encoding="utf-8")
    cmd = '   python3 sysop/scripts/close_run.py reviewed "<run-id>" "<close-id>"\n'
    assert text.count(cmd) == 1
    assert text.index("3. **Check what moved.**") \
        < text.index('   python3 sysop/scripts/close_run.py check "<run-id>" "<default branch>"\n') \
        < text.index(cmd) < text.index("4. **Ask the recorded questions**") \
        < text.index("6. **Check again**")


def test_the_reuse_probe_takes_the_integration_shape_when_the_branch_moved():
    text = flat((STEPS / "4-pre-pr.md").read_text(encoding="utf-8"))
    assert "Reuse the existing PR when **all six** conditions hold" in text
    assert "6. the branch is **still the commit Step 2 reviewed**." in text
    cond = text.index('python3 sysop/scripts/close_arms.py tip "<close-id>" "<approved branch name>" --peek')
    assert text.index("Only when a PR exists are conditions 4, 5 and 6 worth checking") < cond \
        < text.index("and condition 6's check printed `TIP:`") \
        < text.index('git checkout "<approved branch name>"')
    assert ("A `TIP:` line meets condition 6. Any other line leaves it unmet: take the "
            "integration-branch shape, where Step 4a item 1 runs the check again.") in text
    assert text.count('close_arms.py tip "<close-id>"') == 1


def test_the_arm_skips_headless_and_asks_attended():
    text = flat((STEPS / "4a-moved.md").read_text(encoding="utf-8"))
    assert ("**Under `--headless` or `--unattended`**: 4a-SKIP the branch, per *When a branch "
            "really is skipped at 4a* in `SKILL.md`") in text
    assert "**Attended**: show the person the `tip` lines (on an `UNRECORDED:` line" in text
    assert "and ask with `AskUserQuestion`:" in text
    assert "`Merge it`: merge the branch as it is now, by item 2's arm" in text
    assert "Step 8's `Merged after review:` row" in text
    assert "`Skip it`: 4a-SKIP it" in text
    assert "Decide once per branch per close" in text
    # Round 1, lens B 3: the UNRECORDED rule sits before the ask it governs.
    assert text.index("on an `UNRECORDED:` line, which lists no commits, show the branch's commits "
                      "since its `<base>` instead") < text.index("ask with `AskUserQuestion`")


def test_step_8_reports_what_the_arm_merged_and_skipped():
    core = text_of(CORE)
    report = core[core.index("## Step 8: Report"):]
    assert flat(report).count("Merged after review: <each branch a person chose to merge at Step 4a's "
                              "`4a-moved` ask, with `tip`'s line and the commits it listed> (or \"none\")") == 1
    assert "the `CLOSED TASK` line's path or `tip`'s line" in report


def test_a_sole_skipped_branch_still_stops_at_4a_post():
    """Round 2, ruled 2026-11-09: leaving the arm's skip out of 4a-post's count let a `pr` close
    push an empty integration branch. The count keeps it, the arm says so, and the stop names
    the skip as a cause."""
    core = flat(text_of(CORE))
    post = core[core.index("### 4a-post. Verify the Merged Tree"):core.index("### 4b. Close Merged Batches")]
    count = post[post.index("**An empty list here is not automatically a pass"):post.index("Something did not land")]
    assert "4a-moved" not in count
    assert "Something did not land: Step 4a skipped it (Step 8's 4a-SKIP item says why)," in post
    arm = flat((STEPS / "4a-moved.md").read_text(encoding="utf-8"))
    assert ("After a 4a-SKIP of the only approved branch, Step 4a-post's empty-list rule stops the "
            "close before anything is pushed, as for any approved branch that did not merge; under "
            "`--unattended` that stop is a durable park.") in arm
