"""Extract `/claim-task`'s prescribed heredocs and RUN them.

**Why this exists, and it is the one measured result from three adversarial
rounds that should change what gets built.** Phase 171's guards were rebuilt
twice and reviewed three times. The batteries ran 52, 100 and 120 mutations. The
defects that actually mattered were not found by any of them:

  * the classification write carried a hard PyYAML dependency and died with
    `ModuleNotFoundError` on a PEP-668 consumer -- the default Phase 131
    documents -- halting the pipeline after the planner and reviewer had run;
  * `<PARK_REASON>` is free text returned by a sub-agent and was substituted into
    a **double-quoted** shell argument, where a `$(...)` in it executes;
  * three blocks claimed a loud failure on an unsubstituted placeholder that they
    did not produce -- they created a literally-named directory instead;
  * a shipped paragraph asserted that an uncommitted `.gitignore` entry is not
    honoured by git. It is.

Every one came from *running the command* (`_shared/adversarial-review.md`
§ *Before you spawn anyone*, rule 3), and rule 3 is a manual pass that runs only
when its author remembers. A different-model review of all three rounds put it
plainly: the highest-fidelity guard for the code half of a skill is **execution,
not `ast.parse`** -- and nothing in the suite ran these blocks.

So this module is the mechanisation. It reads the blocks out of the shipped
`SKILL.md` **verbatim** -- retyping them would test a copy, which is the failure
mode rule 3 exists to prevent -- resolves their placeholders the way the document
tells an operator to, and executes them against a real git repo with a real
linked worktree.

Scope, stated so it is not over-read: this reaches *does the command run* and
*does it do what the skill says it does*. It does not reach whether the
prescribed command is the right one, and it is one fixture rather than the
general case.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "core/skills/claim-task/SKILL.md"

_FENCE_RE = re.compile(r"^\s*```(\S*)")
_HEREDOC_OPEN_RE = re.compile(r"^python3\s+-\s+<<'PY'(?P<args>.*)$")


def _bash_blocks(text: str) -> list[str]:
    out, buf, in_fence, live = [], [], False, False
    for raw in text.splitlines():
        m = _FENCE_RE.match(raw)
        if m:
            if in_fence:
                if live:
                    out.append("\n".join(buf))
                buf, in_fence, live = [], False, False
            else:
                in_fence, live = True, m.group(1).lower() in ("bash", "sh", "shell")
            continue
        if in_fence and live:
            buf.append(raw.rstrip())
    return out


def _prescribed_heredocs() -> list[str]:
    """Every `python3 - <<'PY'` body in the skill, covered or not."""
    out = []
    for block in _bash_blocks(SKILL.read_text(encoding="utf-8")):
        body, collecting = [], False
        for ln in block.splitlines():
            if not collecting:
                if _HEREDOC_OPEN_RE.match(ln.strip()):
                    collecting = True
                continue
            if ln.strip() == "PY":
                out.append("\n".join(body))
                body, collecting = [], False
                continue
            body.append(ln)
    return out


def heredocs() -> dict[str, tuple[str, str]]:
    """`{needle: (arg_spec, body)}` for each prescribed `python3 - <<'PY'` block.

    Keyed by a needle in the body rather than by position, so inserting a step
    does not silently re-point a case at a different block.
    """
    found: list[tuple[str, str]] = []
    for block in _bash_blocks(SKILL.read_text(encoding="utf-8")):
        args, body, collecting = None, [], False
        for ln in block.splitlines():
            if not collecting:
                m = _HEREDOC_OPEN_RE.match(ln.strip())
                if m:
                    args, collecting = m.group("args").strip(), True
                continue
            if ln.strip() == "PY":
                found.append((args or "", "\n".join(body)))
                args, body, collecting = None, [], False
                continue
            body.append(ln)
    out = {}
    # Keyed by name; the integrity check's key is not its needle, because Step 7a's pre-plan
    # record names `planner-integrity.md` too (Phase 343) and only the check prints a verdict.
    # Step 8c's record block is keyed by its print, because the prepare block and 8b's archive
    # both read an `answers_status:` line (Phase 345).
    needles = {"planner-integrity": 'print("planner-integrity: "',
               "answers-outcome record": 'print("answers_status: "'}
    for key in ("MOVED_PRIOR_ENVELOPES", "classified_by", '"parked"', "PRE_PLAN_SOURCE",
                "planner-integrity", "RESUME_OK", "executor_status",
                "strip_sections", "plan-only.md", "NOT ON BRANCH",
                "ANSWERS_TO_FIX", "TIP_BEFORE=", "answers-outcome record"):
        needle = needles.get(key, key)
        matches = [(a, b) for a, b in found if needle in b]
        assert len(matches) == 1, (
            f"expected exactly one prescribed block containing {needle!r}, found "
            f"{len(matches)} — a duplicate would let a check bind the wrong one"
        )
        out[key] = matches[0]
    return out


def run_block(needle: str, subs: dict[str, str], cwd: Path):
    """Run one prescribed block with its placeholders substituted, verbatim."""
    arg_spec, body = heredocs()[needle]
    for placeholder, value in subs.items():
        arg_spec = arg_spec.replace(placeholder, value)
    assert "<" not in arg_spec, f"unsubstituted placeholder left in {arg_spec!r}"
    script = f"python3 - <<'PY' {arg_spec}\n{body}\nPY\n"
    return subprocess.run(["bash", "-c", script], cwd=cwd, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """A main checkout with a real linked worktree, built from the shipped scripts."""
    main = tmp_path / "main"
    main.mkdir()

    def git(*a, cwd=main):
        return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True)

    git("init", "-q", ".")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (main / ".gitignore").write_text("sysop/runtime/\n")
    (main / "f.txt").write_text("x\n")
    git("add", "-A")
    git("commit", "-qm", "init")
    git("worktree", "add", "-q", str(tmp_path / "wt"), "-b", "tech/t")
    return main, tmp_path / "wt"


IDS = {"<CLAIM_ID>": "TECH-0007"}


def _mint(repo_dir, cwd=None):
    r = run_block("MOVED_PRIOR_ENVELOPES",
                  {**IDS, '"<RESUME_RUN_ID or empty>"': '""'}, cwd or repo_dir)
    assert r.returncode == 0, r.stderr
    return re.search(r"^RUN_ID=(.+)$", r.stdout, re.M).group(1)


def test_the_artifact_directory_lands_in_the_main_checkout_from_a_worktree(repo):
    """The defect that made `--resume` inert was a worktree-side path. Run the
    block from INSIDE the worktree — the resolution must still land in main."""
    main, wt = repo
    run_id = _mint(main, cwd=wt)
    assert (main / "sysop/runtime/claim/TECH-0007" / run_id).is_dir()
    assert not (wt / "sysop/runtime/claim").exists()


def test_a_resume_adopts_the_named_run_and_refuses_an_unknown_one(repo):
    main, _ = repo
    run_id = _mint(main)
    ok = run_block("MOVED_PRIOR_ENVELOPES",
                   {**IDS, '"<RESUME_RUN_ID or empty>"': f'"{run_id}"'}, main)
    assert ok.returncode == 0 and "RESUMED=1" in ok.stdout
    assert f"RUN_ID={run_id}" in ok.stdout, "a resume must ADOPT, not mint"

    bad = run_block("MOVED_PRIOR_ENVELOPES",
                    {**IDS, '"<RESUME_RUN_ID or empty>"': '"no-such-run"'}, main)
    assert bad.returncode == 2, bad.stdout


def test_a_fresh_run_moves_stale_envelopes_aside_and_a_resume_does_not(repo):
    """Step 8 reads an envelope keyed with no run component, so a re-claim must
    not be able to see the previous run's. Moving, never deleting."""
    main, _ = repo
    box = main / "sysop/runtime/subagent-envelopes"
    box.mkdir(parents=True)
    (box / "TECH-0007.exec.json").write_text('{"stale": true}')
    (box / "TECH-00071.exec.json").write_text('{"other claim": true}')

    run_id = _mint(main)
    moved = main / "sysop/runtime/claim/TECH-0007" / run_id / "prior-envelopes"
    assert (moved / "TECH-0007.exec.json").is_file(), "stale envelope not moved aside"
    assert (box / "TECH-00071.exec.json").is_file(), "a prefix-sharing claim was touched"
    assert not (box / "TECH-0007.exec.json").exists()

    (box / "TECH-0007.plan.json").write_text('{"this run": true}')
    run_block("MOVED_PRIOR_ENVELOPES", {**IDS, '"<RESUME_RUN_ID or empty>"': f'"{run_id}"'}, main)
    assert (box / "TECH-0007.plan.json").is_file(), "a resume must leave the mailbox alone"


def test_the_classification_write_needs_no_pyyaml(repo, tmp_path):
    """The crux rule-3 finding: a hard PyYAML import halted the pipeline at 7c on
    a PEP-668 consumer, AFTER the planner and reviewer had already run."""
    main, _ = repo
    run_id = _mint(main)
    stub = tmp_path / "nopyyaml"
    stub.mkdir()
    (stub / "yaml.py").write_text("raise ImportError('PyYAML is not installed')\n")
    env = {**os.environ, "PYTHONPATH": str(stub)}
    arg_spec, body = heredocs()["classified_by"]
    arg_spec = arg_spec.replace("<CLAIM_ID>", "TECH-0007").replace("<RUN_ID>", run_id)
    r = subprocess.run(["bash", "-c", f"python3 - <<'PY' {arg_spec}\n{body}\nPY\n"],
                       cwd=main, capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"the classification write still needs PyYAML: {r.stderr}"
    written = main / "sysop/runtime/claim/TECH-0007" / run_id / "classification.md"
    assert written.is_file()


def test_the_classification_block_round_trips_through_a_yaml_parser(repo):
    """It emits JSON on the argument that JSON is a subset of YAML 1.2. Check it."""
    yaml = pytest.importorskip("yaml")
    main, _ = repo
    run_id = _mint(main)
    r = run_block("classified_by", {**IDS, "<RUN_ID>": run_id}, main)
    assert r.returncode == 0, r.stderr
    text = (main / "sysop/runtime/claim/TECH-0007" / run_id / "classification.md").read_text()
    body = re.search(r"```yaml\n(.*?)\n```", text, re.S).group(1)
    parsed = yaml.safe_load(body)
    assert parsed["claim_id"] == "TECH-0007" and parsed["run_id"] == run_id


def test_the_park_reason_cannot_execute(repo):
    """`<PARK_REASON>` is free text returned by a sub-agent. Inside double quotes
    a `$(...)` in it RUNS; it is single-quoted for that reason."""
    main, _ = repo
    run_id = _mint(main)
    canary = main / "PWNED"
    payload = f"F3: is $(touch {canary}) authoritative?"
    r = run_block('"parked"',
                  {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t", "<PARK_REASON>": payload},
                  main)
    assert r.returncode == 0, r.stderr
    assert not canary.exists(), "the park reason executed — it is not single-quoted"
    marker = main / "sysop/runtime/parked" / f"TECH-0007__{run_id}.md"
    assert marker.is_file()
    assert payload in marker.read_text(), "the reason was not recorded verbatim"


def test_the_park_marker_matches_the_reader_that_removes_it(repo):
    """`/review-close` Step 4c globs `{tid}__*.md`. The earlier directory-shaped
    park could never match it, so parks accumulated forever."""
    main, _ = repo
    run_id = _mint(main)
    run_block('"parked"',
              {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t", "<PARK_REASON>": "why"}, main)
    hits = sorted(p.name for p in (main / "sysop/runtime/parked").glob("TECH-0007__*.md"))
    assert hits == [f"TECH-0007__{run_id}.md"], hits


def test_the_integrity_check_records_its_verdict_and_the_original_baseline(repo):
    """Held only in context the verdict is lost to a crash, and the plan it gates
    then routes to a reviewer with nothing recording it was never re-gated."""
    main, wt = repo
    run_id = _mint(main)
    pre = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"],
                         capture_output=True, text=True, check=True).stdout.strip()
    subs = {**IDS, "<RUN_ID>": run_id, "<WORKTREE_PATH>": str(wt), "<PRE_PLAN_HEAD>": pre,
            "<PRE_PLAN_BASE>": _head(main), "<BRANCH_NAME>": "tech/t"}
    r = run_block("planner-integrity", subs, main)
    assert "planner-integrity: OK" in r.stdout, r.stdout
    verdict_file = main / "sysop/runtime/claim/TECH-0007" / run_id / "planner-integrity.md"
    assert f"pre_plan_head: {pre}" in verdict_file.read_text()

    # The planner commits, in breach of its contract.
    (wt / "z").write_text("z")
    for a in (["add", "z"], ["commit", "-qm", "planner broke its contract"]):
        subprocess.run(["git", "-C", str(wt), *a], check=True, capture_output=True)
    r = run_block("planner-integrity", subs, main)
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout
    body = verdict_file.read_text()
    assert "verdict: VIOLATED" in body
    assert f"pre_plan_head: {pre}" in body, (
        "the re-check re-baselined onto the rogue commit — a re-entry at 7a would "
        "then compare against the planner's own commit and pass"
    )


def _default_branch(main):
    return subprocess.run(["git", "-C", str(main), "rev-parse", "--abbrev-ref", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _head(d):
    return subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _commit(d, name):
    (d / name).write_text(name)
    for a in (["add", name], ["commit", "-qm", name]):
        subprocess.run(["git", "-C", str(d), *a], check=True, capture_output=True)


def _ff(wt, base):
    subprocess.run(["git", "-C", str(wt), "merge", "-q", "--ff-only", base],
                   check=True, capture_output=True)


def _capture(main, wt):
    """Step 7a's two captures, taken before the planner runs: the worktree's HEAD and the
    default branch's tip (`git rev-parse --verify refs/heads/<default branch>`)."""
    base = subprocess.run(["git", "-C", str(wt), "rev-parse", "--verify",
                           "refs/heads/" + _default_branch(main)],
                          capture_output=True, text=True, check=True).stdout.strip()
    return _head(wt), base


def _integrity(main, wt, run_id, pre, base, branch="tech/t"):
    subs = {**IDS, "<RUN_ID>": run_id, "<WORKTREE_PATH>": str(wt), "<PRE_PLAN_HEAD>": pre,
            "<PRE_PLAN_BASE>": base, "<BRANCH_NAME>": branch}
    r = run_block("planner-integrity", subs, main)
    body = (main / "sysop/runtime/claim/TECH-0007" / run_id / "planner-integrity.md").read_text()
    return r, body


def test_a_fast_forward_onto_what_the_default_branch_already_held_is_not_a_planner_commit(repo):
    """`Q-574` (internal tracker #680). The consumer's worktree sits behind the default branch
    when planning starts, and it fast-forwards during 7a. Nothing the fast-forward brought was
    made after planning began, so none of it is the planner's; the bare SHA compare parked the
    claim anyway and discarded the plan."""
    main, wt = repo
    run_id = _mint(main)
    _commit(main, "landed-before-planning")
    pre, base = _capture(main, wt)
    assert pre != base
    _ff(wt, _default_branch(main))
    r, body = _integrity(main, wt, run_id, pre, base)
    assert "planner-integrity: OK" in r.stdout, r.stdout + r.stderr
    assert "verdict: OK" in body and f"pre_plan_base: {base}" in body
    assert "reason: HEAD moved only onto commits the default branch held before planning" in body

    # The same fast-forward with a planner commit on top is still the breach.
    _commit(wt, "planner-broke-its-contract")
    r, body = _integrity(main, wt, run_id, pre, base)
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout
    assert "verdict: VIOLATED" in body


def test_a_commit_the_default_branch_gained_during_planning_is_not_accepted(repo):
    """Phase 342's round (both lenses): with the default branch read at CHECK time, a planner
    that commits on the default branch in the main checkout, followed by the consumer's own
    fast-forward, read OK. The tip is captured before the spawn, so it cannot include it."""
    main, wt = repo
    run_id = _mint(main)
    pre, base = _capture(main, wt)
    _commit(main, "planner-committed-on-the-default-branch")
    _ff(wt, _default_branch(main))
    r, body = _integrity(main, wt, run_id, pre, base)
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout
    assert "verdict: VIOLATED" in body


def test_a_planner_that_moves_the_default_branch_over_its_own_commit_is_violated(repo):
    main, wt = repo
    run_id = _mint(main)
    pre, base = _capture(main, wt)
    _commit(wt, "planner-commit")
    subprocess.run(["git", "-C", str(main), "merge", "-q", "--ff-only", "tech/t"],
                   check=True, capture_output=True)
    r, _ = _integrity(main, wt, run_id, pre, base)
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout


@pytest.mark.parametrize("own_work", [True, False], ids=["with-own-commits", "below-pre"])
def test_a_head_that_moved_backwards_is_still_violated(repo, own_work):
    """Nothing is gained when HEAD moves BACK onto the default branch, so only the ancestry
    check tells that from a fast-forward. The `below-pre` case has no commits of its own: a
    worktree fast-forwarded to the tip, then reset to an older commit on it (Phase 342's
    round: an ancestry check against the base instead of `now` passed the first case only)."""
    main, wt = repo
    run_id = _mint(main)
    older = _head(main)
    if own_work:
        _commit(wt, "earlier-branch-work")
    else:
        _commit(main, "newer-on-default")
        _ff(wt, _default_branch(main))
    pre, base = _capture(main, wt)
    subprocess.run(["git", "-C", str(wt), "reset", "-q", "--hard", older],
                   check=True, capture_output=True)
    r, body = _integrity(main, wt, run_id, pre, base)
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout
    assert "verdict: VIOLATED" in body


@pytest.mark.parametrize("bad_base", ["none", "tech/t", "HEAD", "", "deadbeef" * 5],
                         ids=["none", "task-branch-name", "HEAD", "empty", "absent-object"])
def test_a_base_that_is_not_a_captured_object_id_keeps_the_check_armed(repo, bad_base):
    """A name is resolved at check time, so it can include the planner's commit: the task's
    own branch did (Phase 342's round). Only a full object id counts, and anything else keeps
    the SHA compare's verdict, OK for an unmoved HEAD and VIOLATED for a moved one. A
    well-formed id git cannot find is the git-error arm: it must keep VIOLATED too."""
    main, wt = repo
    run_id = _mint(main)
    _commit(main, "landed-before-planning")
    pre, _ = _capture(main, wt)
    r, _ = _integrity(main, wt, run_id, pre, bad_base)
    assert "planner-integrity: OK (HEAD unmoved)" in r.stdout, r.stdout + r.stderr
    _ff(wt, _default_branch(main))
    r, _ = _integrity(main, wt, run_id, pre, bad_base)
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout


def test_an_unsubstituted_base_is_refused(repo):
    main, wt = repo
    run_id = _mint(main)
    arg_spec, body = heredocs()["planner-integrity"]
    for placeholder, value in {**IDS, "<RUN_ID>": run_id, "<WORKTREE_PATH>": str(wt),
                               "<PRE_PLAN_HEAD>": _head(wt), "<BRANCH_NAME>": "tech/t"}.items():
        arg_spec = arg_spec.replace(placeholder, value)
    assert "<PRE_PLAN_BASE>" in arg_spec
    r = subprocess.run(["bash", "-c", f"python3 - <<'PY' {arg_spec}\n{body}\nPY\n"],
                       cwd=main, capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr


def test_only_step_7pre_mints_a_run(repo):
    """A mistyped `<RUN_ID>` used to manufacture a run directory, which Step 1's
    `--resume` validator then blessed because its whole test is 'does it exist'."""
    main, wt = repo
    _mint(main)
    ghost = "20990101T000000Z-cafebabe"
    for needle, subs in (
        ("classified_by", {**IDS, "<RUN_ID>": ghost}),
        ('"parked"', {**IDS, "<RUN_ID>": ghost, "<BRANCH_NAME>": "tech/t", "<PARK_REASON>": "x"}),
        ("executor_status", {**IDS, "<RUN_ID>": ghost, "<EXEC_STATUS>": "EXECUTED"}),
        ("planner-integrity", {**IDS, "<RUN_ID>": ghost, "<WORKTREE_PATH>": str(wt),
                               "<PRE_PLAN_HEAD>": "deadbeef", "<PRE_PLAN_BASE>": "none",
                               "<BRANCH_NAME>": "tech/t"}),
    ):
        r = run_block(needle, subs, main)
        assert r.returncode == 3, f"{needle} minted a run it should have refused: {r.stdout}"
    assert not (main / "sysop/runtime/claim/TECH-0007" / ghost).exists()

    bad = run_block("RESUME_OK", {**IDS, "<RUN_ID>": ghost}, main)
    assert bad.returncode == 3 and "available runs" in bad.stderr


def test_resume_refuses_an_auto_build_cycle_directory(repo):
    """Phase 344's round (lens 3): `/auto-build` Phase 6a now mints
    `claim/<id>/<UTC stamp>/` with no hex half. It is not a `/claim-task` run -- it has
    no `planner-integrity.md`, so Step 7-pre would route it to 7a, re-plan, and drop the
    blocker the human was asked about. The validator must refuse it and list only runs."""
    main, _ = repo
    cycle = main / "sysop/runtime/claim/TECH-0007/20260928T120000Z"
    cycle.mkdir(parents=True)
    (cycle / "plan.md").write_text("the reviewed plan\n")
    r = run_block("RESUME_OK", {**IDS, "<RUN_ID>": cycle.name}, main)
    assert r.returncode == 3, r.stdout + r.stderr
    assert "available runs: (none)" in r.stderr, r.stderr
    run = main / "sysop/runtime/claim/TECH-0007/20260928T120001Z-0123abcd"
    run.mkdir()
    ok = run_block("RESUME_OK", {**IDS, "<RUN_ID>": run.name}, main)
    assert ok.returncode == 0 and "RESUME_OK=" in ok.stdout, ok.stderr


def test_an_unsubstituted_placeholder_is_refused_not_materialised(repo):
    """Quoting alone does not make one loud in a block that CREATES its path — it
    would quietly become a directory of that literal name."""
    main, _ = repo
    for needle in ("MOVED_PRIOR_ENVELOPES", "classified_by", '"parked"', "NOT ON BRANCH"):
        arg_spec, body = heredocs()[needle]
        r = subprocess.run(["bash", "-c", f"python3 - <<'PY' {arg_spec}\n{body}\nPY\n"],
                           cwd=main, capture_output=True, text=True)
        assert r.returncode == 2, f"{needle} accepted an unsubstituted placeholder"
    assert not (main / "sysop/runtime/claim/<CLAIM_ID>").exists()


def test_the_test_decision_readback_runs_from_the_main_checkout(repo):
    """Phase 249 (`Q-369`), Step 8's branch-tip read-back. This module's invariant is
    that a prescribed block RUNS as written; the six outcomes it distinguishes are
    covered by `tests/test_test_decision_readback.py`. Both matter — a block can be
    behaviourally correct and still be unrunnable from the CWD its caller occupies,
    which is the failure this module exists for."""
    main, _ = repo
    _mint(main)
    (main / "tasks" / "open").mkdir(parents=True, exist_ok=True)
    (main / "tasks" / "open" / "TECH-0007.md").write_text(
        "# TECH-0007\n\n## Test decision\ntest tests/test_x.py::test_y proves it\n",
        encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=main, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "body"], cwd=main, check=True, capture_output=True)
    branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=main,
                            capture_output=True, text=True, check=True).stdout.strip()
    r = run_block("NOT ON BRANCH",
                  {**IDS, "<BRANCH_NAME>": branch,
                   "<BODY_PATH_AS_RESOLVED>": "tasks/open/TECH-0007.md"}, main)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    assert "record present" in r.stdout, r.stdout


def test_an_uncommitted_gitignore_entry_is_honoured(repo):
    """A shipped paragraph asserted the opposite, and the artifact directory's
    'is this expected dirt' guidance rests on it."""
    main, _ = repo
    subprocess.run(["git", "rm", "-q", "--cached", ".gitignore"], cwd=main, check=True,
                   capture_output=True)
    subprocess.run(["git", "commit", "-qm", "drop gitignore from the index"], cwd=main,
                   check=True, capture_output=True)
    run_id = _mint(main)
    run_block("classified_by", {**IDS, "<RUN_ID>": run_id}, main)
    porcelain = subprocess.run(["git", "status", "--porcelain"], cwd=main,
                               capture_output=True, text=True, check=True).stdout
    assert "sysop/" not in porcelain, (
        "an uncommitted .gitignore entry was not honoured — the skill's guidance "
        f"about expected untracked state is wrong. status: {porcelain!r}"
    )


def test_the_extractor_actually_found_the_blocks():
    """Non-vacuity: every case above is a no-op if extraction silently returns
    nothing, and a renamed fence language would do exactly that."""
    blocks = heredocs()
    # NOT `len(blocks) == 8`: `heredocs()` builds its dict from a fixed needle
    # tuple and already asserts one match per needle, so that number is a
    # constant restating the tuple's length and has never been able to fail.
    # What CAN fail is the shipped file gaining a prescribed block no needle
    # covers -- the round added a ninth that `shutil.rmtree`s the run directory
    # and nothing noticed.
    covered = {body for _args, body in blocks.values()}
    uncovered = [b for b in _prescribed_heredocs() if b not in covered]
    # A NAMED baseline, not a count. These four predate Phase 238 and are debt, not
    # a verdict: Step 2's index read, Step 4a's status flip, Step 7b's transport
    # receipt, and Step 8's stranded-body check. What this assertion is for is a
    # NEW uncovered block -- the round added a ninth that `shutil.rmtree`s the run
    # directory and nothing in the suite noticed. Close one by adding its needle
    # and an execution test, and delete its line here.
    UNCOVERED_BASELINE = {
        "tasks/index.yml not found": "Step 2's index read (PyYAML bootstrap)",
        "refusing to flip status": "Step 4a's status flip",
        "review-transport.md": "Step 7b's transport receipt",
        "STRANDED": "Step 8's stranded-body check",
    }
    unexplained = [b for b in uncovered
                   if not any(k in b for k in UNCOVERED_BASELINE)]
    assert not unexplained, (
        f"{len(unexplained)} prescribed python3 heredoc(s) in the skill are covered by no "
        f"needle and are not in the baseline -- an uncovered block runs against a "
        f"consumer's tree with no test reaching it. First lines: "
        f"{[b.splitlines()[:2] for b in unexplained]}")
    stale = [k for k in UNCOVERED_BASELINE if not any(k in b for b in uncovered)]
    assert not stale, (
        f"baseline entries no longer match any uncovered block: {stale}. If they gained "
        f"coverage, delete their lines; a stale baseline excuses a future gap.")
    for needle, (_args, body) in blocks.items():
        assert body.strip(), f"{needle} extracted an empty body"
        assert "sys.argv" in body, f"{needle} takes no substituted arguments"


# --------------------------------------------------------- Step 7f (option C)
#
# The plan-only write-back is the one block in this skill that edits a TRACKED
# file, and it edits it in the main checkout rather than the worktree. Every
# case below came from running it: the in-place replacement, the blank-line
# accretion and the fence-length rule were all wrong on the first cut and none
# of them is visible by reading.

PLAN_WITH_A_FENCE = """\
# Plan for TECH-0007

## Constraints & Risks
- risk one

## Test decision
test tests/test_b.py::test_it proves the flag round-trips

## Implementation Steps
1. Edit `a/b.py`:
```bash
echo hi
```
2. Done.
"""

BODY = """\
# TECH-0007

## Context
Something needs doing.

## Key files
- `a/b.py`

## Test decision
<recorded at /claim-task plan time>

## Surfaced by
prose
"""

TD = "test tests/test_b.py::test_it proves the flag round-trips"


def _stage_plan_only(main, *, plan=PLAN_WITH_A_FENCE, body=BODY, sealed=True):
    """A run directory with a plan, a task body, and optionally a review envelope."""
    run_id = _mint(main)
    run_dir = main / "sysop/runtime/claim/TECH-0007" / run_id
    (run_dir / "plan.md").write_text(plan, encoding="utf-8")
    (main / "tasks/open").mkdir(parents=True, exist_ok=True)
    (main / "tasks/open/TECH-0007.md").write_text(body, encoding="utf-8")
    if sealed:
        box = main / "sysop/runtime/subagent-envelopes"
        box.mkdir(parents=True, exist_ok=True)
        (box / "TECH-0007.review.json").write_text(
            '{"status": "EXECUTED", "review_report_raw": '
            '"REVIEW_REPORT:\\n  findings: []\\n  verdict: CLEAN"}')
    return run_id


def _write_back(main, run_id, *, body_path="open/TECH-0007.md", test_decision=TD):
    return run_block("strip_sections",
                     {**IDS, "<RUN_ID>": run_id, "<BODY_PATH>": body_path,
                      "<TEST_DECISION>": test_decision}, main)


def _headings(text: str, wanted: str) -> int:
    """Count `## <wanted>` headings OUTSIDE any fence.

    A raw `str.count` is fence-blind, and the embedded plan legitimately
    contains its own `## Test decision` line inside the wrapper fence — so a
    naive count reads 2 and says nothing about whether the body is well formed.
    """
    n, fence = 0, None
    for ln in text.split("\n"):
        s = ln.lstrip()
        mark = None
        for ch in ("`", "~"):
            if s.startswith(ch * 3):
                run = 0
                while run < len(s) and s[run] == ch:
                    run += 1
                mark = (ch, run)
                break
        if fence is None:
            if mark:
                fence = mark
            elif ln.strip().lower() == "## " + wanted.lower():
                n += 1
        elif mark and mark[0] == fence[0] and mark[1] >= fence[1] and not ln.strip().strip(mark[0]):
            fence = None
    return n


def test_the_plan_write_back_lands_in_the_main_checkout_body(repo):
    main, _ = repo
    run_id = _stage_plan_only(main)
    r = _write_back(main, run_id)
    assert r.returncode == 0, r.stderr
    text = (main / "tasks/open/TECH-0007.md").read_text()
    assert "## Plan" in text and PLAN_WITH_A_FENCE.strip() in text, (
        "the plan was not embedded verbatim")
    assert "verdict: CLEAN" in text, "the sealed report was not carried into the body"
    assert "sealed_report: present" in r.stdout


def test_the_write_back_lands_in_the_main_checkout_when_run_from_a_worktree(repo):
    """The block's own paragraph calls this "the one write in this skill that is
    deliberately not a worktree write". Every other test ran it with cwd=main,
    which cannot tell "main checkout" from "the current directory" -- so
    replacing the git-common-dir resolution with a bare relative path was green.
    The sibling pattern already existed one screen up
    (test_the_artifact_directory_lands_in_the_main_checkout_from_a_worktree) and
    was not reused. Found by the round."""
    main, wt = repo
    run_id = _stage_plan_only(main)
    # A decoy tree under the worktree: a CWD-relative resolution finds THIS.
    (wt / "tasks/open").mkdir(parents=True, exist_ok=True)
    (wt / "tasks/open/TECH-0007.md").write_text("# decoy\n", encoding="utf-8")
    r = run_block("strip_sections",
                  {**IDS, "<RUN_ID>": run_id, "<BODY_PATH>": "open/TECH-0007.md",
                   "<TEST_DECISION>": TD}, wt)
    assert r.returncode == 0, r.stderr
    assert "## Plan" in (main / "tasks/open/TECH-0007.md").read_text(), (
        "the write-back did not reach the main checkout when run from a worktree")
    assert (wt / "tasks/open/TECH-0007.md").read_text() == "# decoy\n", (
        "the write-back resolved its body relative to the CWD and wrote the worktree copy "
        "-- an edit there is on no branch and reaches no PR")


def test_the_body_path_resolves_the_canonical_tasks_relative_form(repo):
    """`body:` is `open/<ID>.md` RELATIVE TO `tasks/`. Assuming the other form is
    the documented way to pass a fixture and fail a real queue."""
    main, _ = repo
    run_id = _stage_plan_only(main)
    assert _write_back(main, run_id, body_path="open/TECH-0007.md").returncode == 0
    # The legacy repo-relative form still resolves, as /review-close Step 2d does.
    run_id2 = _stage_plan_only(main)
    assert _write_back(main, run_id2, body_path="tasks/open/TECH-0007.md").returncode == 0
    # A body that exists under neither is a hard refusal, not a silent create.
    run_id3 = _stage_plan_only(main)
    bad = _write_back(main, run_id3, body_path="open/NOPE-0001.md")
    assert bad.returncode == 5, bad.stdout
    assert not (main / "tasks/open/NOPE-0001.md").exists()


def test_a_second_option_c_run_replaces_the_section_rather_than_appending(repo):
    """Appending yields two `## Plan` sections and Step 7a's presence test reads
    the FIRST — the stale one. The rewrite must also be byte-idempotent."""
    main, _ = repo
    run_id = _stage_plan_only(main)
    assert _write_back(main, run_id).returncode == 0
    once = (main / "tasks/open/TECH-0007.md").read_text()

    run_id2 = _stage_plan_only(main, body=once)
    assert _write_back(main, run_id2).returncode == 0
    twice = (main / "tasks/open/TECH-0007.md").read_text()

    assert _headings(twice, "Plan") == 1, "a second run left two Plan sections"
    assert _headings(twice, "Test decision") == 1, "a second run left two records"
    assert once.replace(run_id, "R") == twice.replace(run_id2, "R"), (
        "the rewrite is not idempotent — it accretes on every run")


def test_the_real_test_decision_precedes_the_one_inside_the_embedded_plan(repo):
    """The embedded plan carries its own `## Test decision` line inside the
    wrapper fence, so the body holds two textual occurrences and only one real
    heading. `tasks/schema.md` orders the sections so the REAL one comes first,
    which is what keeps a fence-blind FIRST-match reader correct. Stated as a
    residual: a fence-blind LAST-match reader would still be wrong."""
    main, _ = repo
    run_id = _stage_plan_only(main)
    assert _write_back(main, run_id).returncode == 0
    text = (main / "tasks/open/TECH-0007.md").read_text()
    assert _headings(text, "Test decision") == 1, "more than one real heading"
    assert text.count("## Test decision") == 2, (
        "the embedded plan no longer carries its own record — if the plan shape "
        "changed, this test's premise needs rechecking, not deleting")
    first, last = text.index("## Test decision"), text.rindex("## Test decision")
    assert first < text.index("## Plan"), "the real record is not the first occurrence"
    assert last > text.index("````"), "the second occurrence is not the fenced one"


def test_the_sections_land_in_place_not_appended_after_surfaced_by(repo):
    """`tasks/schema.md` documents an order. Appending at EOF breaks it."""
    main, _ = repo
    run_id = _stage_plan_only(main)
    assert _write_back(main, run_id).returncode == 0
    text = (main / "tasks/open/TECH-0007.md").read_text()
    assert text.index("\n## Test decision\n") < text.index("\n## Plan\n")
    assert text.index("\n## Plan\n") < text.index("\n## Surfaced by\n"), (
        "the write-back was appended at EOF rather than replacing in place")


def test_a_body_with_no_prior_sections_appends_them(repo):
    main, _ = repo
    bare = "# TECH-0007\n\n## Context\nx\n"
    run_id = _stage_plan_only(main, body=bare)
    assert _write_back(main, run_id).returncode == 0
    text = (main / "tasks/open/TECH-0007.md").read_text()
    assert text.startswith("# TECH-0007") and "## Plan" in text


def test_the_plan_fence_outlives_a_code_block_inside_the_plan(repo):
    """The plan contains ```bash. A 3-backtick wrapper would be closed by it,
    spilling the rest of the plan into the body as live markdown."""
    main, _ = repo
    run_id = _stage_plan_only(main)
    assert _write_back(main, run_id).returncode == 0
    text = (main / "tasks/open/TECH-0007.md").read_text()
    assert "````markdown" in text, "the wrapper fence was not widened past the plan's own"
    # The plan's trailing line must be INSIDE the wrapper, not after it.
    body_after_plan = text.split("````", 2)[2]
    assert "2. Done." not in body_after_plan


def test_the_strip_is_fence_aware_and_keeps_neighbouring_sections(repo):
    """A fence-blind slice either stops early or eats every section after it.
    The body here hides a `## ` line inside a fenced block."""
    main, _ = repo
    tricky = (
        "# TECH-0007\n\n## Context\nx\n\n## Test decision\n"
        "```\n## Plan\nnot a heading — it is inside a fence\n```\n"
        "no test because docs\n\n## Surfaced by\nkeep me\n"
    )
    run_id = _stage_plan_only(main, body=tricky)
    assert _write_back(main, run_id).returncode == 0
    text = (main / "tasks/open/TECH-0007.md").read_text()
    assert "## Surfaced by" in text and "keep me" in text, (
        "a fence-blind strip ate the sections after the one it replaced")
    assert "not a heading" not in text, "the fenced decoy survived the strip"


def test_the_test_decision_argument_cannot_execute(repo):
    """Same class as `<PARK_REASON>`: free text from a sub-agent, single-quoted."""
    main, _ = repo
    run_id = _stage_plan_only(main)
    canary = main / "PWNED"
    r = _write_back(main, run_id, test_decision=f"no test because $(touch {canary}) docs")
    assert r.returncode == 0, r.stderr
    assert not canary.exists(), "the test decision executed — it is not single-quoted"


def test_an_absent_sealed_report_is_recorded_not_omitted(repo):
    """A review whose verdict never arrived must not read like one that had none."""
    main, _ = repo
    run_id = _stage_plan_only(main, sealed=False)
    r = _write_back(main, run_id)
    assert r.returncode == 0, r.stderr
    assert "sealed_report: ABSENT" in r.stdout
    text = (main / "tasks/open/TECH-0007.md").read_text()
    assert "No sealed `REVIEW_REPORT:` block reached the orchestrator" in text


def test_the_write_back_refuses_a_missing_or_empty_plan(repo):
    """Writing an empty `## Plan` would satisfy nothing and skip 7a forever."""
    main, _ = repo
    run_id = _stage_plan_only(main)
    (main / "sysop/runtime/claim/TECH-0007" / run_id / "plan.md").unlink()
    assert _write_back(main, run_id).returncode == 4

    run_id2 = _stage_plan_only(main, plan="   \n")
    assert _write_back(main, run_id2).returncode == 4


def test_the_write_back_refuses_an_unsubstituted_test_decision(repo):
    """Option C has no executor, so this is the record's only chance to exist.

    Built without `run_block`, which refuses to launch an arg spec still holding
    a `<`. That refusal is the harness protecting its other cases; here the
    unsubstituted value IS the case.
    """
    main, _ = repo
    run_id = _stage_plan_only(main)
    arg_spec, body = heredocs()["strip_sections"]
    for k, v in {"<CLAIM_ID>": "TECH-0007", "<RUN_ID>": run_id,
                 "<BODY_PATH>": "open/TECH-0007.md"}.items():
        arg_spec = arg_spec.replace(k, v)
    before = (main / "tasks/open/TECH-0007.md").read_text()
    r = subprocess.run(["bash", "-c", f"python3 - <<'PY' {arg_spec}\n{body}\nPY\n"],
                       cwd=main, capture_output=True, text=True)
    assert r.returncode == 2, r.stdout
    assert "no executor" in r.stderr
    assert (main / "tasks/open/TECH-0007.md").read_text() == before, (
        "it refused AFTER writing — the refusal must come before any mutation")


def test_the_write_back_needs_no_pyyaml(repo, tmp_path):
    """The 7c crux, one step later: a hard PyYAML import here would halt option C
    after the planner and reviewer had both run."""
    main, _ = repo
    run_id = _stage_plan_only(main)
    stub = tmp_path / "nopyyaml2"
    stub.mkdir()
    (stub / "yaml.py").write_text("raise ImportError('PyYAML is not installed')\n")
    arg_spec, body = heredocs()["strip_sections"]
    for k, v in {"<CLAIM_ID>": "TECH-0007", "<RUN_ID>": run_id,
                 "<BODY_PATH>": "open/TECH-0007.md", "<TEST_DECISION>": TD}.items():
        arg_spec = arg_spec.replace(k, v)
    r = subprocess.run(["bash", "-c", f"python3 - <<'PY' {arg_spec}\n{body}\nPY\n"],
                       cwd=main, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": str(stub)})
    assert r.returncode == 0, f"the plan write-back needs PyYAML: {r.stderr}"


def test_the_plan_only_record_carries_the_release_state(repo):
    """7-pre routes a resumed option-C run off this file. `released: no` means the
    plan is committed and the release did not finish — never route it to 7e."""
    main, _ = repo
    run_id = _mint(main)
    subs = {**IDS, "<RUN_ID>": run_id, "<PLAN_COMMIT_SHA>": "abc1234"}
    r = run_block("plan-only.md", subs, main)
    assert r.returncode == 0, r.stderr
    rec = main / "sysop/runtime/claim/TECH-0007" / run_id / "plan-only.md"
    text = rec.read_text()
    assert "plan_commit: abc1234" in text and "released: no" in text
    assert "plan-only: released=no" in r.stdout


# ---- the round's execute-lens findings, each pinned by the failure it caused ----

SEALED_WITH_A_FENCE = (
    "REVIEW_REPORT:\n"
    "  findings:\n"
    "    - id: F1\n"
    "      summary: \"the loop is unbounded\"\n"
    "      evidence: |\n"
    "        ```bash\n"
    "        while true; do echo hi; done\n"
    "        ```\n"
    "  verdict: FINDINGS"
)


def _stage_with_sealed(main, sealed_raw, *, body=BODY, plan=PLAN_WITH_A_FENCE):
    run_id = _mint(main)
    run_dir = main / "sysop/runtime/claim/TECH-0007" / run_id
    (run_dir / "plan.md").write_text(plan, encoding="utf-8")
    (main / "tasks/open").mkdir(parents=True, exist_ok=True)
    (main / "tasks/open/TECH-0007.md").write_text(body, encoding="utf-8")
    box = main / "sysop/runtime/subagent-envelopes"
    box.mkdir(parents=True, exist_ok=True)
    (box / "TECH-0007.review.json").write_text(
        json.dumps({"status": "EXECUTED", "review_report_raw": sealed_raw}))
    return run_id


def test_a_sealed_report_quoting_a_fence_does_not_destroy_the_body(repo):
    """The round's first HIGH, and it needed no adversarial payload.

    A reviewer quoting a fenced snippet in a finding's `evidence:` field is
    ordinary output. An earlier cut computed the wrapper fence over the PLAN
    only and wrapped the sealed report in a bare ```yaml, so the report's own
    fence closed it -- and the NEXT run's section strip then desynced and
    dropped every section after the break.
    """
    main, _ = repo
    run_id = _stage_with_sealed(main, SEALED_WITH_A_FENCE)
    assert _write_back(main, run_id).returncode == 0
    once = (main / "tasks/open/TECH-0007.md").read_text()
    assert "## Surfaced by" in once and "prose" in once

    # The second run is where the loss landed.
    run_id2 = _stage_with_sealed(main, SEALED_WITH_A_FENCE, body=once)
    assert _write_back(main, run_id2).returncode == 0
    twice = (main / "tasks/open/TECH-0007.md").read_text()
    assert "## Surfaced by" in twice, (
        "a second run deleted a section it never touched -- the sealed report's "
        "fence broke the wrapper and the strip ran to EOF")
    assert _headings(twice, "Plan") == 1
    assert "while true" in twice, "the sealed report was lost"


def test_the_wrapper_fence_is_computed_over_the_sealed_report_too(repo):
    main, _ = repo
    run_id = _stage_with_sealed(main, "REVIEW_REPORT:\n  x: |\n    ````\n    y\n    ````")
    assert _write_back(main, run_id).returncode == 0
    text = (main / "tasks/open/TECH-0007.md").read_text()
    # Scoped to the SEALED block. Asserting the widened fence appears anywhere in
    # the file is satisfied by the PLAN's wrapper, which is widened by the same
    # arithmetic -- so the check passed on the broken code. Incidental hit, caught
    # by reverting the fix and watching this test stay green.
    sealed_block = text.split("### Sealed review report", 1)[1]
    opener = sealed_block.strip().split("\n", 1)[0]
    assert opener.startswith("`````"), (
        f"the sealed report opens with {opener!r} -- a 4-backtick run inside it did "
        f"not widen its own wrapper, so the report's fence closes it")


def test_an_unterminated_fence_is_refused_rather_than_silently_truncated(repo):
    """The backstop under the fix. A body whose fencing is unbalanced cannot be
    scanned for headings, so the strip would drop every later section."""
    main, _ = repo
    broken = ("# TECH-0007\n\n## Context\nx\n\n## Test decision\n"
              "```\nunterminated\n\n## Surfaced by\nkeep me\n")
    run_id = _stage_plan_only(main, body=broken)
    before = (main / "tasks/open/TECH-0007.md").read_text()
    r = _write_back(main, run_id)
    assert r.returncode == 6, r.stdout
    assert "unterminated code fence" in r.stderr
    assert (main / "tasks/open/TECH-0007.md").read_text() == before, (
        "it refused AFTER writing")


def test_a_crlf_body_keeps_its_line_endings(repo):
    """Silent LF normalisation showed the whole file as changed rather than the
    ~20 added lines -- real diff noise for a WSL/Windows consumer."""
    main, _ = repo
    run_id = _stage_plan_only(main, body=BODY.replace("\n", "\r\n"))
    assert _write_back(main, run_id).returncode == 0
    raw = (main / "tasks/open/TECH-0007.md").read_bytes()
    assert b"\r\n" in raw, "the body's CRLF endings were normalised away"
    assert b"\n" not in raw.replace(b"\r\n", b""), "mixed endings were produced"


def test_a_symlinked_body_is_written_through_not_replaced(repo):
    main, _ = repo
    run_id = _stage_plan_only(main)
    real = main / "tasks/real-TECH-0007.md"
    real.write_text(BODY, encoding="utf-8")
    link = main / "tasks/open/TECH-0007.md"
    link.unlink()
    link.symlink_to(real)
    assert _write_back(main, run_id).returncode == 0
    assert link.is_symlink(), "the symlink was replaced by a regular file"
    assert "## Plan" in real.read_text(), "the real target was left stale"


def test_the_plan_only_record_refuses_a_run_it_did_not_mint(repo):
    main, _ = repo
    r = run_block("plan-only.md",
                  {**IDS, "<RUN_ID>": "20260101T000000Z-nosuchrun",
                   "<PLAN_COMMIT_SHA>": "abc1234"}, main)
    assert r.returncode == 3, r.stdout


# ---------------------------------------------------------------------------
# Q-461: `## Also fixed` must survive option C, BETWEEN the two sections it
# writes. Reached independently by two of Phase 276's three lenses and confirmed
# by executing the extracted helper; the existing guard read only schema.md's
# fenced example, so nothing in the suite saw the writer that violated it. These
# run the shipped block, which is what the filing asked for.

BODY_WITH_ALSO = """\
# TECH-0007

## Context
Something needs doing.

## Test decision
<recorded at /claim-task plan time>

## Also fixed
- `a/b.py`: dropped a stale comment (PR 3)

## Plan

old plan text

## Surfaced by
prose
"""


def _order(text: str, *wanted: str) -> list[str]:
    """The wanted headings in the order they appear OUTSIDE any fence.

    Fence-aware for the reason the block itself is: the embedded plan carries its
    own `## Test decision` line, so a positional `str.find` reads the quotation
    and reports an order the body does not have.
    """
    seen, fence = [], None
    for ln in text.split("\n"):
        s = ln.lstrip()
        mark = None
        for ch in ("`", "~"):
            if s.startswith(ch * 3):
                run = 0
                while run < len(s) and s[run] == ch:
                    run += 1
                mark = (ch, run)
                break
        if fence is None:
            if mark:
                fence = mark
            else:
                # Level-flexible, because the live corpus carries `### Also fixed` as
                # well as `## `, and `preserve` matches at any level. An h2-only
                # matcher here reported the section as ABSENT on a body where it was
                # present and correctly placed -- a false negative in the test, which
                # is the direction that wastes a debugging pass.
                low = ln.strip().lower()
                n = 0
                while n < len(low) and low[n] == "#":
                    n += 1
                if 0 < n <= 6 and low[n:n + 1] == " ":
                    txt = low[n:].strip()
                    for w in wanted:
                        if txt == w.lower() or txt.startswith(w.lower() + " "):
                            seen.append(w)
                            break
        elif mark and mark[0] == fence[0] and mark[1] >= fence[1] and not ln.strip().strip(mark[0]):
            fence = None
    return seen


def test_also_fixed_is_re_emitted_between_test_decision_and_plan(repo):
    """The Q-461 defect, run rather than described.

    Before the fix this produced `Test decision / Plan / Also fixed`: the section
    was not stripped, so it survived into `out` AFTER `insert_at` was captured at
    the earlier heading, and the reinserted contiguous block landed in front of it.
    """
    main, _ = repo
    run_id = _stage_plan_only(main, body=BODY_WITH_ALSO)
    r = _write_back(main, run_id)
    assert r.returncode == 0, r.stderr
    text = (main / "tasks/open/TECH-0007.md").read_text()
    assert _order(text, "Test decision", "Also fixed", "Plan") == [
        "Test decision", "Also fixed", "Plan",
    ], (
        "option C did not leave the body in the schema's order. `## Plan` embeds a "
        "reviewed plan verbatim in a fence and that plan can quote either heading, so "
        "a first-match heading reader must meet the real section first -- which is why "
        "tasks/schema.md calls this order load-bearing.\n\n" + text
    )


def test_also_fixed_content_survives_option_c(repo):
    """Preserving the heading while dropping its lines would be silent data loss.

    `strip_sections` has produced exactly that twice before, recorded in its own
    inline comments, which is why this asserts the content and not the heading.
    """
    main, _ = repo
    run_id = _stage_plan_only(main, body=BODY_WITH_ALSO)
    r = _write_back(main, run_id)
    assert r.returncode == 0, r.stderr
    text = (main / "tasks/open/TECH-0007.md").read_text()
    assert "- `a/b.py`: dropped a stale comment (PR 3)" in text, (
        "the `## Also fixed` line was lost by the option-C rewrite. The section is a "
        "record of work that happened; losing it makes the close read the diff hunk as "
        "unexplained scope.\n\n" + text
    )
    assert _headings(text, "Also fixed") == 1, (
        "the option-C rewrite left more than one `## Also fixed` heading outside a "
        "fence -- it re-emitted the section without removing the original.\n\n" + text
    )


def test_a_suffixed_also_fixed_heading_is_preserved_and_placed(repo):
    """`## Also fixed (PR 1)` is a real heading in a live consumer corpus.

    An equality match would leave it in place -- still after `## Plan` -- and report
    nothing, because the absence branch here is silent by design. Step 2d's arm
    matches by search for this same reason.
    """
    main, _ = repo
    body = BODY_WITH_ALSO.replace("## Also fixed\n", "## Also fixed (PR 1)\n")
    run_id = _stage_plan_only(main, body=body)
    r = _write_back(main, run_id)
    assert r.returncode == 0, r.stderr
    text = (main / "tasks/open/TECH-0007.md").read_text()
    assert "## Also fixed (PR 1)" in text, (
        "the suffixed heading was not carried through verbatim -- the original heading "
        "line is what gets re-emitted, so the suffix must survive.\n\n" + text
    )
    assert _order(text, "Test decision", "Also fixed", "Plan") == [
        "Test decision", "Also fixed", "Plan",
    ], ("a suffixed `## Also fixed` was not placed between the two sections.\n\n" + text)


def test_a_quoted_also_fixed_inside_the_plan_fence_is_not_hoisted(repo):
    """A heading inside the embedded plan is a quotation, not a section.

    Hoisting it would invent an `## Also fixed` record for fixes that never
    happened -- a fabricated record, which is the worst outcome at this class of
    site. The walk is fence-aware; this proves the preserve path did not break that.
    """
    main, _ = repo
    plan = PLAN_WITH_A_FENCE + "\n## Also fixed\n- fabricated line from inside the plan\n"
    body = BODY_WITH_ALSO.replace(
        "## Also fixed\n- `a/b.py`: dropped a stale comment (PR 3)\n\n", "")
    run_id = _stage_plan_only(main, plan=plan, body=body)
    r = _write_back(main, run_id)
    assert r.returncode == 0, r.stderr
    text = (main / "tasks/open/TECH-0007.md").read_text()
    assert _headings(text, "Also fixed") == 0, (
        "an `## Also fixed` heading quoted inside the embedded plan was treated as a "
        "real section and hoisted out of the fence. That invents a record of adjacent "
        "fixes nobody made.\n\n" + text
    )
    assert "fabricated line from inside the plan" in text, (
        "the plan was supposed to be embedded verbatim, fence and all")


def test_option_c_is_idempotent_with_an_also_fixed_section(repo):
    """Two runs must not accrete sections or blank lines.

    The blank-line accretion this guards was a real defect on the first cut of the
    insertion-point normalisation, found by running it twice; adding a second
    re-emitted section is a fresh chance to reintroduce it.
    """
    main, _ = repo
    run_id = _stage_plan_only(main, body=BODY_WITH_ALSO)
    assert _write_back(main, run_id).returncode == 0
    first = (main / "tasks/open/TECH-0007.md").read_text()
    run_id2 = _stage_plan_only(main, body=first)
    assert _write_back(main, run_id2).returncode == 0
    second = (main / "tasks/open/TECH-0007.md").read_text()

    # The provenance sentence records WHICH run wrote the section, so two runs
    # legitimately differ by that token and only that token. Normalising it keeps the
    # comparison byte-exact everywhere else -- which is what catches the blank-line
    # accretion this test exists for. Comparing raw text instead made this test fail
    # on correct behaviour.
    stamp = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]+")
    first, second = stamp.sub("RUN_ID", first), stamp.sub("RUN_ID", second)
    assert first == second, (
        "a second option-C run changed the body. Re-emitting `## Also fixed` must be "
        "idempotent like the two sections beside it.\n\n--- first ---\n" + first
        + "\n--- second ---\n" + second
    )
    for h in ("Test decision", "Also fixed", "Plan"):
        assert _headings(second, h) == 1, (
            f"a second option-C run left more than one `## {h}` heading.\n\n" + second)


def test_an_unterminated_fence_still_refuses_with_an_also_fixed_section(repo):
    """The backstop must survive the preserve path.

    An unterminated fence means the scan cannot tell a heading from fenced text, so
    `skipping` never resets and every remaining section is dropped -- silent data
    loss in a tracked file. Adding a second sink is precisely the kind of change
    that could turn that refusal into a partial write.
    """
    main, _ = repo
    body = BODY_WITH_ALSO.replace("old plan text", "```markdown\nnever closed")
    run_id = _stage_plan_only(main, body=body)
    r = _write_back(main, run_id)
    assert r.returncode == 6, (
        f"expected the unterminated-fence refusal (exit 6), got {r.returncode}. "
        f"stdout={r.stdout!r} stderr={r.stderr!r}"
    )
    assert (main / "tasks/open/TECH-0007.md").read_text() == body, (
        "the block refused but had already written the body -- the refusal has to "
        "happen before any write, or it is data loss with a message attached")


def test_two_also_fixed_sections_are_both_preserved(repo):
    """Round M17: `saved.setdefault` -> overwrite silently drops the FIRST section.

    Not hypothetical, and that is why it earns an execution test rather than a filing:
    the live consumer corpus has a body carrying `## Also fixed (PR 1)` AND
    `## Also fixed (PR 0)` -- the two-section shape is the very evidence the docstring
    cites for search-matching. No fixture had two, so the accumulate-vs-overwrite
    property was untested. Verified against the mutant: it keeps the second and drops
    the first, with no error -- section loss in a tracked file, which the surrounding
    comments say this helper has produced twice before.
    """
    main, _ = repo
    body = ("# TECH-0007\n\n## Context\nc\n\n## Test decision\n<recorded>\n\n"
            "## Also fixed\n- FIRST LINE\n\n## Also fixed (PR 1)\n- SECOND LINE\n\n"
            "## Plan\n\nold\n\n## Surfaced by\np\n")
    run_id = _stage_plan_only(main, body=body)
    r = _write_back(main, run_id)
    assert r.returncode == 0, r.stderr
    text = (main / "tasks/open/TECH-0007.md").read_text()
    for line in ("- FIRST LINE", "- SECOND LINE"):
        assert line in text, (
            f"{line!r} was dropped. Both `## Also fixed` sections are the consumer's "
            "record of work that happened; losing either makes the close read a diff "
            "hunk as unexplained scope.\n\n" + text)
    assert _order(text, "Test decision", "Also fixed", "Plan")[0] == "Test decision", (
        "the two preserved sections did not land after `## Test decision`.\n\n" + text)
    assert text.index("- FIRST LINE") < text.index("- SECOND LINE"), (
        "the two sections were re-emitted out of their original order.\n\n" + text)


def test_a_preserved_section_before_the_test_decision_sets_the_insertion_point(repo):
    """Round M29: no fixture had `## Also fixed` BEFORE `## Test decision`.

    `insert_at` is captured at the EARLIEST removed section, which is what makes the
    rewrite land where the body already had these sections rather than at EOF. With
    the preserved section first, that property is only exercised if `preserve` also
    sets `insert_at` -- and nothing tested it, so an edit dropping that could push the
    whole block below unrelated trailing sections.
    """
    main, _ = repo
    body = ("# TECH-0007\n\n## Context\nc\n\n## Also fixed\n- adjacent fix\n\n"
            "## Test decision\n<recorded>\n\n## Plan\n\nold\n\n## Surfaced by\nkeep last\n")
    run_id = _stage_plan_only(main, body=body)
    r = _write_back(main, run_id)
    assert r.returncode == 0, r.stderr
    text = (main / "tasks/open/TECH-0007.md").read_text()
    assert text.index("## Context") < text.index("## Test decision"), (
        "the rewritten block did not land at the earliest removed section's "
        "position.\n\n" + text)
    assert text.index("## Surfaced by") > text.index("## Plan"), (
        "the block was appended past unrelated trailing sections instead of being "
        "replaced in place -- `## Surfaced by` must stay last.\n\n" + text)
    assert "- adjacent fix" in text, "the preserved content was lost\n\n" + text


def test_the_preserve_match_requires_a_word_boundary(repo):
    """Round M19: `startswith(k)` without the space strips a different heading.

    `## Also fixedness of the thing` is not an `## Also fixed` section, and hoisting it
    between the two written sections would relocate a section the consumer wrote
    somewhere else -- an edit to their content, reported nowhere.
    """
    main, _ = repo
    body = ("# TECH-0007\n\n## Context\nc\n\n## Test decision\n<recorded>\n\n"
            "## Also fixedness of the thing\n- not an also-fixed section\n\n"
            "## Plan\n\nold\n\n## Surfaced by\np\n")
    run_id = _stage_plan_only(main, body=body)
    r = _write_back(main, run_id)
    assert r.returncode == 0, r.stderr
    text = (main / "tasks/open/TECH-0007.md").read_text()
    assert text.index("## Also fixedness") > text.index("## Plan"), (
        "`## Also fixedness of the thing` was treated as an `## Also fixed` section and "
        "hoisted above `## Plan`. The match needs a word boundary, not a prefix.\n\n"
        + text)


def test_step_7a_records_both_shas_before_the_spawn_as_written():
    """The check's tests supply both SHAs themselves, so nothing else would notice the runner
    no longer being told to record one, or told to record the tip AFTER the spawn, where it
    can hold the planner's commit (Phase 342's round 2 reworded the hold sentence that way and
    an order-only pin stayed green). So the record block's invocation and the hold sentence are
    pinned verbatim, and both must precede the spawn (Phase 343, `Q-616`)."""
    text = SKILL.read_text(encoding="utf-8")
    block = ("python3 - <<'PY' \"<WORKTREE_PATH>\" \"<CLAIM_ID>\" \"<RUN_ID>\" "
             "\"<default branch>\"\n")
    hold = ("Hold `PRE_PLAN_HEAD` as `<PRE_PLAN_HEAD>` and `PRE_PLAN_BASE` as `<PRE_PLAN_BASE>`, "
            "and substitute both literally below. `none` means the default branch could not be "
            "read; the check then accepts only an unmoved HEAD.")
    every = ("Run this block before 7a's first spawn in a run, and again each time Step 7-pre "
             "routes the run back here. The first run of it in a run directory captures both "
             "SHAs into `<ARTIFACT_DIR>/pre-plan.md`; every later one holds what that file "
             "records.")
    assert text.count(block) == 1, "Step 7a's pre-plan record block changed or moved"
    assert text.count(hold) == 1, "Step 7a's hold instruction changed"
    assert text.count(every) == 1, "Step 7a no longer runs the record on every spawn"
    spawn = text.index("Spawning planner for <CLAIM_ID>")
    check = text.index('"<PRE_PLAN_BASE>" "<BRANCH_NAME>"')
    assert text.index(every) < text.index(block) < text.index(hold) < spawn < check
    # No bare capture may come back anywhere in Step 7a, in any spelling: a runner told to
    # capture by hand takes a baseline no record holds (Phase 343's round, lens 1, m30).
    step = text[text.index("### Step 7a"):text.index("### Step 7b")]
    bare = [ln for ln in step.splitlines() if re.search(r"rev-parse\s+(?:HEAD|--verify|@)", ln)]
    assert not bare, bare


@pytest.mark.parametrize("pre_name", ["HEAD", "@", "tech/t"])
def test_a_name_for_the_pre_plan_head_keeps_the_check_armed(repo, pre_name):
    """Phase 342's round 2: a name resolves at check time, to the commit being judged, so a
    planner commit read OK when `<PRE_PLAN_HEAD>` was substituted as `HEAD`, `@` or the task
    branch. It read VIOLATED before the phase."""
    main, wt = repo
    run_id = _mint(main)
    _commit(main, "landed-before-planning")
    _, base = _capture(main, wt)
    _ff(wt, _default_branch(main))
    _commit(wt, "planner-commit")
    r, _ = _integrity(main, wt, run_id, pre_name, base)
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout


@pytest.mark.parametrize("move", ["detach", "other-branch", "detach-in-place",
                                  "new-branch-in-place", "rename"])
def test_a_planner_that_leaves_the_task_branch_is_violated(repo, move):
    """Round 2: with the worktree behind the default branch, a planner that detached onto it
    or switched to another branch inside the captured tip read OK, and the executor would then
    commit off the task branch. Round 3: the same without moving HEAD read `OK (HEAD
    unmoved)`, because the branch was checked only on the forward arm."""
    main, wt = repo
    run_id = _mint(main)
    _commit(main, "landed-before-planning")
    pre, base = _capture(main, wt)
    if move == "other-branch":
        subprocess.run(["git", "-C", str(main), "branch", "scratch-inspect"],
                       check=True, capture_output=True)
    args = {"detach": ["checkout", "-q", "--detach", _default_branch(main)],
            "other-branch": ["checkout", "-q", "scratch-inspect"],
            "detach-in-place": ["checkout", "-q", "--detach"],
            "new-branch-in-place": ["switch", "-q", "-c", "scratch"],
            "rename": ["branch", "-m", "tech/t", "tech/renamed"]}[move]
    subprocess.run(["git", "-C", str(wt), *args], check=True, capture_output=True)
    r, _ = _integrity(main, wt, run_id, pre, base)
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout


def test_the_fast_forward_arm_uses_the_branch_it_is_given(repo):
    """Round 3: every other test's branch is `tech/t`, so a check hard-coded to it passed
    them all while false-parking every real consumer's fast-forward."""
    main, _ = repo
    wt2 = main.parent / "wt2"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", str(wt2), "-b", "feat/x"],
                   check=True, capture_output=True)
    run_id = _mint(main)
    _commit(main, "landed-before-planning")
    pre, base = _capture(main, wt2)
    _ff(wt2, _default_branch(main))
    r, _ = _integrity(main, wt2, run_id, pre, base, branch="feat/x")
    assert "planner-integrity: OK" in r.stdout, r.stdout + r.stderr
    r, _ = _integrity(main, wt2, run_id, pre, base, branch="tech/t")
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout


def test_a_planner_merge_commit_is_violated(repo):
    """`REFERENCE.md` says a `--no-ff` merge of the default branch false-parks; it also must,
    because the merge commit is the planner's (round 2: `--no-merges` on the count passed)."""
    main, wt = repo
    run_id = _mint(main)
    _commit(main, "landed-before-planning")
    pre, base = _capture(main, wt)
    subprocess.run(["git", "-C", str(wt), "merge", "-q", "--no-ff", "--no-edit",
                    _default_branch(main)], check=True, capture_output=True)
    r, _ = _integrity(main, wt, run_id, pre, base)
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout


def test_a_sha256_repository_gets_the_same_verdicts(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    init = subprocess.run(["git", "init", "-q", "--object-format=sha256", "."], cwd=main,
                          capture_output=True, text=True)
    if init.returncode != 0:
        pytest.skip("this git cannot create a SHA-256 repository")
    for a in (["config", "user.email", "t@example.invalid"], ["config", "user.name", "t"]):
        subprocess.run(["git", *a], cwd=main, check=True, capture_output=True)
    (main / ".gitignore").write_text("sysop/runtime/\n")
    _commit(main, "f.txt")
    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "tech/t"], cwd=main,
                   check=True, capture_output=True)
    run_id = _mint(main)
    _commit(main, "landed-before-planning")
    pre, base = _capture(main, wt)
    assert len(base) == 64
    _ff(wt, _default_branch(main))
    r, _ = _integrity(main, wt, run_id, pre, base)
    assert "planner-integrity: OK" in r.stdout, r.stdout + r.stderr
    _commit(wt, "planner-commit")
    r, _ = _integrity(main, wt, run_id, pre, base)
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout


def test_a_leaked_git_dir_does_not_read_another_checkouts_head(repo):
    """Phase 342's round 2 (record lens): with `GIT_DIR` pointing at the main checkout, the
    check read the main checkout's HEAD as the worktree's, so a planner commit read
    `OK (HEAD unmoved)`. Phase 124's env strip is how this skill's other heredocs avoid it."""
    main, wt = repo
    run_id = _mint(main)
    pre, base = _capture(main, wt)
    _commit(wt, "planner-commit")
    arg_spec, body = heredocs()["planner-integrity"]
    for placeholder, value in {**IDS, "<RUN_ID>": run_id, "<WORKTREE_PATH>": str(wt),
                               "<PRE_PLAN_HEAD>": _head(main), "<PRE_PLAN_BASE>": base,
                               "<BRANCH_NAME>": "tech/t"}.items():
        arg_spec = arg_spec.replace(placeholder, value)
    env = {**os.environ, "GIT_DIR": str(main / ".git")}
    r = subprocess.run(["bash", "-c", f"python3 - <<'PY' {arg_spec}\n{body}\nPY\n"],
                       cwd=main, capture_output=True, text=True, env=env)
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout + r.stderr


def _record(main, wt, run_id, default=None, env=None):
    """Step 7a's pre-plan record block, run verbatim (Phase 343, `Q-616`)."""
    subs = {**IDS, "<RUN_ID>": run_id, "<WORKTREE_PATH>": str(wt),
            "<default branch>": default if default is not None else _default_branch(main)}
    arg_spec, body = heredocs()["PRE_PLAN_SOURCE"]
    for placeholder, value in subs.items():
        arg_spec = arg_spec.replace(placeholder, value)
    assert "<" not in arg_spec, arg_spec
    r = subprocess.run(["bash", "-c", f"python3 - <<'PY' {arg_spec}\n{body}\nPY\n"],
                       cwd=main, capture_output=True, text=True, env=env)
    held = dict(re.findall(r"^(PRE_PLAN_\w+)=(.*)$", r.stdout, re.M))
    return r, held


def _run_dir(main, run_id):
    return main / "sysop/runtime/claim/TECH-0007" / run_id


def test_the_record_captures_what_the_bare_captures_read_and_writes_it_down(repo):
    main, wt = repo
    run_id = _mint(main)
    _commit(main, "landed-before-planning")
    r, held = _record(main, wt, run_id)
    assert r.returncode == 0, r.stderr
    pre, base = _capture(main, wt)
    assert held == {"PRE_PLAN_SOURCE": "captured", "PRE_PLAN_HEAD": pre, "PRE_PLAN_BASE": base}
    text = (_run_dir(main, run_id) / "pre-plan.md").read_text()
    assert f"- pre_plan_head: {pre}\n" in text and f"- pre_plan_base: {base}\n" in text


def _rogue_after_record(main, wt):
    run_id = _mint(main)
    _commit(main, "landed-before-planning")
    r, first = _record(main, wt, run_id)
    assert r.returncode == 0, r.stderr
    _commit(wt, "rogue-planner-commit")
    return run_id, first


def test_q616_a_crash_before_the_check_holds_the_original_baseline(repo):
    """`Q-616`, route 1: the orchestrator dies between the planner's return and the check, so
    no `planner-integrity.md` exists and 7-pre routes the resume to 7a. The record holds the
    SHAs written before the spawn, and the check parks on the rogue commit. A fresh capture,
    which is what 7a did before Phase 343, reads it `OK (HEAD unmoved)`."""
    main, wt = repo
    run_id, first = _rogue_after_record(main, wt)
    assert not (_run_dir(main, run_id) / "planner-integrity.md").exists()
    r, held = _record(main, wt, run_id)
    assert r.returncode == 0, r.stderr
    assert held["PRE_PLAN_SOURCE"] == "held from pre-plan.md"
    assert (held["PRE_PLAN_HEAD"], held["PRE_PLAN_BASE"]) == (
        first["PRE_PLAN_HEAD"], first["PRE_PLAN_BASE"])
    r, _ = _integrity(main, wt, run_id, held["PRE_PLAN_HEAD"], held["PRE_PLAN_BASE"])
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout
    fresh_pre, fresh_base = _capture(main, wt)
    r, _ = _integrity(main, wt, run_id, fresh_pre, fresh_base)
    assert "planner-integrity: OK (HEAD unmoved)" in r.stdout, r.stdout


def test_q616_a_check_that_exits_2_leaves_the_record_to_hold(repo):
    """`Q-616`, route 2: the check refuses an unsubstituted `<BRANCH_NAME>` (exit 2) and
    writes nothing. The record still holds on the next pass."""
    main, wt = repo
    run_id, first = _rogue_after_record(main, wt)
    arg_spec, body = heredocs()["planner-integrity"]
    for placeholder, value in {**IDS, "<RUN_ID>": run_id, "<WORKTREE_PATH>": str(wt),
                               "<PRE_PLAN_HEAD>": first["PRE_PLAN_HEAD"],
                               "<PRE_PLAN_BASE>": first["PRE_PLAN_BASE"]}.items():
        arg_spec = arg_spec.replace(placeholder, value)
    r = subprocess.run(["bash", "-c", f"python3 - <<'PY' {arg_spec}\n{body}\nPY\n"],
                       cwd=main, capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    assert not (_run_dir(main, run_id) / "planner-integrity.md").exists()
    r, held = _record(main, wt, run_id)
    assert held["PRE_PLAN_HEAD"] == first["PRE_PLAN_HEAD"], held
    r, _ = _integrity(main, wt, run_id, held["PRE_PLAN_HEAD"], held["PRE_PLAN_BASE"])
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout


def test_q616_a_re_spawn_keeps_the_held_shas_and_catches_a_rewritten_record(repo):
    """`Q-616`, route 3, and Phase 343's round (lenses 2 and 3, independently): a planner that
    commits, rewrites `pre-plan.md` to its own commit and fails is re-spawned. Re-running the
    record for the re-spawn would hold the rewritten SHA and the check would read the commit
    `OK`; the SHAs the orchestrator already holds catch it. A later resume then stops on the
    two files' disagreement rather than holding the rewrite."""
    main, wt = repo
    run_id, first = _rogue_after_record(main, wt)
    rec = _run_dir(main, run_id) / "pre-plan.md"
    rec.write_text(rec.read_text().replace(first["PRE_PLAN_HEAD"], _head(wt)))
    # Why the rule exists: a re-run of the record reads what the planner wrote.
    _, reread = _record(main, wt, run_id)
    r, _ = _integrity(main, wt, run_id, reread["PRE_PLAN_HEAD"], reread["PRE_PLAN_BASE"])
    assert "planner-integrity: OK (HEAD unmoved)" in r.stdout, r.stdout
    # The rule: the re-spawn keeps the SHAs held since the first record.
    r, _ = _integrity(main, wt, run_id, first["PRE_PLAN_HEAD"], first["PRE_PLAN_BASE"])
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout
    r, held = _record(main, wt, run_id)
    assert r.returncode == 4 and "PRE_PLAN_HEAD" not in held, r.stdout + r.stderr
    text = SKILL.read_text(encoding="utf-8")
    for s in ("Re-spawn once, keeping the pre-plan SHAs you already hold (do not re-run 7a's "
              "record for it).",
              "**A re-spawn in the same run keeps the SHAs you already hold: do not re-run this "
              "block for it.**"):
        assert text.count(s) == 1, s[:50]


def test_q616_a_stop_after_a_second_failure_resumes_on_the_first_record(repo):
    """`Q-616`, route 3's loss: the failure table stops after a second planner failure, and the
    resume re-enters 7a with no integrity file. The record holds the first capture and leaves
    the file as it was written."""
    main, wt = repo
    run_id, first = _rogue_after_record(main, wt)
    before = (_run_dir(main, run_id) / "pre-plan.md").read_bytes()
    r, again = _record(main, wt, run_id)
    assert again["PRE_PLAN_HEAD"] == first["PRE_PLAN_HEAD"] != _head(wt)
    assert (_run_dir(main, run_id) / "pre-plan.md").read_bytes() == before
    r, _ = _integrity(main, wt, run_id, again["PRE_PLAN_HEAD"], again["PRE_PLAN_BASE"])
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout


def test_a_violated_run_holds_the_record_and_removing_the_commit_passes(repo):
    """Phase 342's re-entry after `VIOLATED`, now through the record: it parks again while
    the rogue commit is in the branch and passes once a human removes it."""
    main, wt = repo
    run_id, first = _rogue_after_record(main, wt)
    r, _ = _integrity(main, wt, run_id, first["PRE_PLAN_HEAD"], first["PRE_PLAN_BASE"])
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout
    r, held = _record(main, wt, run_id)
    assert r.returncode == 0, r.stderr
    r, _ = _integrity(main, wt, run_id, held["PRE_PLAN_HEAD"], held["PRE_PLAN_BASE"])
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout
    subprocess.run(["git", "-C", str(wt), "reset", "-q", "--hard", first["PRE_PLAN_HEAD"]],
                   check=True, capture_output=True)
    r, held = _record(main, wt, run_id)
    r, _ = _integrity(main, wt, run_id, held["PRE_PLAN_HEAD"], held["PRE_PLAN_BASE"])
    assert "planner-integrity: OK" in r.stdout, r.stdout


def test_a_run_recorded_before_pre_plan_md_holds_its_integrity_shas(repo):
    """A `VIOLATED` run parked by a Sysop that predates the record has only
    `planner-integrity.md`. The record holds its SHAs and writes `pre-plan.md` from them."""
    main, wt = repo
    run_id = _mint(main)
    pre, base = _capture(main, wt)
    _commit(wt, "rogue-planner-commit")
    r, _ = _integrity(main, wt, run_id, pre, base)
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout
    r, held = _record(main, wt, run_id)
    assert r.returncode == 0, r.stderr
    assert held["PRE_PLAN_SOURCE"].startswith("held from planner-integrity.md"), held
    assert (held["PRE_PLAN_HEAD"], held["PRE_PLAN_BASE"]) == (pre, base)
    assert f"- pre_plan_head: {pre}\n" in (_run_dir(main, run_id) / "pre-plan.md").read_text()


def test_a_legacy_integrity_file_with_no_base_line_holds_none(repo):
    main, wt = repo
    run_id = _mint(main)
    pre = _head(wt)
    (_run_dir(main, run_id) / "planner-integrity.md").write_text(
        f"# Planner integrity\n\n- pre_plan_head: {pre}\n- post_plan_head: x\n- verdict: VIOLATED\n")
    r, held = _record(main, wt, run_id)
    assert r.returncode == 0, r.stderr
    assert (held["PRE_PLAN_HEAD"], held["PRE_PLAN_BASE"]) == (pre, "none"), held


def test_the_skip_paths_integrity_ok_records_no_baseline_so_the_record_captures(repo):
    """The skip-the-planner path hand-writes `OK` with no SHAs: no planner ran, so there is
    no baseline to hold, and a later spawn in the run captures."""
    main, wt = repo
    run_id = _mint(main)
    (_run_dir(main, run_id) / "planner-integrity.md").write_text(
        "- verdict: OK\n- reason: plan recovered from body, no planner spawned\n")
    r, held = _record(main, wt, run_id)
    assert r.returncode == 0, r.stderr
    assert held["PRE_PLAN_SOURCE"] == "captured" and held["PRE_PLAN_HEAD"] == _head(wt)


def test_two_records_that_disagree_stop_with_exit_4(repo):
    main, wt = repo
    run_id, first = _rogue_after_record(main, wt)
    r, _ = _integrity(main, wt, run_id, first["PRE_PLAN_HEAD"], first["PRE_PLAN_BASE"])
    rec = _run_dir(main, run_id) / "pre-plan.md"
    rec.write_text(rec.read_text().replace(first["PRE_PLAN_HEAD"], _head(wt)))
    r, held = _record(main, wt, run_id)
    assert r.returncode == 4 and "PRE_PLAN_HEAD" not in held, r.stdout + r.stderr


def test_a_base_disagreement_alone_also_stops(repo):
    main, wt = repo
    run_id, first = _rogue_after_record(main, wt)
    _integrity(main, wt, run_id, first["PRE_PLAN_HEAD"], first["PRE_PLAN_BASE"])
    rec = _run_dir(main, run_id) / "pre-plan.md"
    rec.write_text(rec.read_text().replace("- pre_plan_base: " + first["PRE_PLAN_BASE"],
                                           "- pre_plan_base: none"))
    r, _ = _record(main, wt, run_id)
    assert r.returncode == 4, r.stdout + r.stderr


@pytest.mark.parametrize("field", ["<PRE_PLAN_HEAD>", "<PRE_PLAN_BASE>"])
def test_a_check_run_with_a_bad_argument_does_not_poison_a_good_record(repo, field):
    """Rule 4's corpus: the check writes whatever it was handed, and an unsubstituted
    `<PRE_PLAN_HEAD>` records `VIOLATED` with that text. A value that is not an object id is
    no baseline, so the record keeps holding `pre-plan.md` rather than stopping on a
    'disagreement' with it."""
    main, wt = repo
    run_id, first = _rogue_after_record(main, wt)
    pre = "<PRE_PLAN_HEAD>" if field == "<PRE_PLAN_HEAD>" else first["PRE_PLAN_HEAD"]
    base = "main" if field == "<PRE_PLAN_BASE>" else first["PRE_PLAN_BASE"]
    arg_spec, body = heredocs()["planner-integrity"]
    for placeholder, value in {**IDS, "<RUN_ID>": run_id, "<WORKTREE_PATH>": str(wt),
                               "<BRANCH_NAME>": "tech/t", "<PRE_PLAN_BASE>": base}.items():
        arg_spec = arg_spec.replace(placeholder, value)
    arg_spec = arg_spec.replace('"<PRE_PLAN_HEAD>"', f"'{pre}'")
    r = subprocess.run(["bash", "-c", f"python3 - <<'PY' {arg_spec}\n{body}\nPY\n"],
                       cwd=main, capture_output=True, text=True)
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout + r.stderr
    r, held = _record(main, wt, run_id)
    assert r.returncode == 0, r.stdout + r.stderr
    assert held["PRE_PLAN_HEAD"] == first["PRE_PLAN_HEAD"], held
    r, _ = _integrity(main, wt, run_id, held["PRE_PLAN_HEAD"], held["PRE_PLAN_BASE"])
    assert "planner-integrity: VIOLATED" in r.stdout, r.stdout


def test_a_pre_343_record_whose_head_is_not_an_id_stops(repo):
    """With no `pre-plan.md`, Phase 342's rule stands: a recorded head that is not an id is
    no baseline to hold, and a re-plan against it would park forever."""
    main, wt = repo
    run_id = _mint(main)
    (_run_dir(main, run_id) / "planner-integrity.md").write_text(
        "- pre_plan_head: <PRE_PLAN_HEAD>\n- pre_plan_base: none\n- verdict: VIOLATED\n")
    r, held = _record(main, wt, run_id)
    assert r.returncode == 4 and "PRE_PLAN_HEAD" not in held, r.stdout + r.stderr


@pytest.mark.parametrize("bad", ["", "HEAD", "abc123", "<PRE_PLAN_HEAD>", "0123456789ab",
                                 "0123456789abcdef0123456789abcdef0123456"])
def test_a_recorded_head_that_is_not_an_object_id_stops_with_exit_4(repo, bad):
    main, wt = repo
    run_id = _mint(main)
    (_run_dir(main, run_id) / "pre-plan.md").write_text(
        f"- pre_plan_head: {bad}\n- pre_plan_base: none\n")
    r, held = _record(main, wt, run_id)
    assert r.returncode == 4 and "PRE_PLAN_HEAD" not in held, r.stdout + r.stderr


@pytest.mark.parametrize("which", ["pre-plan.md", "planner-integrity.md"])
def test_a_record_that_is_not_utf8_stops_with_exit_4_and_names_it(repo, which):
    """`Q-612`'s rule for a shipped heredoc: a byte that is not UTF-8 is a stop that names the
    file, not a traceback."""
    main, wt = repo
    run_id = _mint(main)
    (_run_dir(main, run_id) / which).write_bytes(b"- pre_plan_head: \xff\xfe\n")
    r, held = _record(main, wt, run_id)
    assert r.returncode == 4 and "PRE_PLAN_HEAD" not in held, r.stdout + r.stderr
    assert which in r.stderr and "Traceback" not in r.stderr, r.stderr


def test_an_empty_record_is_not_absent(repo):
    """A crash inside the record's own write leaves an empty `pre-plan.md`. Reading that as
    absent would capture afresh over a planner's commit (Phase 343's round, lens 1, m33)."""
    main, wt = repo
    run_id, _ = _rogue_after_record(main, wt)
    (_run_dir(main, run_id) / "pre-plan.md").write_text("")
    r, held = _record(main, wt, run_id)
    assert r.returncode == 4 and "PRE_PLAN_HEAD" not in held, r.stdout + r.stderr


def test_the_record_refuses_placeholders_and_a_run_it_did_not_mint(repo):
    main, wt = repo
    run_id = _mint(main)
    # `_record` asserts no placeholder is left, so leave `<default branch>` by hand:
    arg_spec, body = heredocs()["PRE_PLAN_SOURCE"]
    spec = arg_spec.replace("<WORKTREE_PATH>", str(wt)).replace("<CLAIM_ID>", "TECH-0007")
    spec = spec.replace("<RUN_ID>", run_id)
    r = subprocess.run(["bash", "-c", f"python3 - <<'PY' {spec}\n{body}\nPY\n"],
                       cwd=main, capture_output=True, text=True)
    assert r.returncode == 2, r.stdout + r.stderr
    ghost = "20990101T000000Z-deadbeef"
    r, _ = _record(main, wt, ghost)
    assert r.returncode == 3, r.stdout + r.stderr
    assert not _run_dir(main, ghost).exists()


def test_an_unreadable_default_branch_records_none(repo):
    main, wt = repo
    run_id = _mint(main)
    r, held = _record(main, wt, run_id, default="no-such-branch")
    assert r.returncode == 0, r.stderr
    assert held["PRE_PLAN_BASE"] == "none" and held["PRE_PLAN_HEAD"] == _head(wt)


def test_the_record_ignores_a_leaked_git_dir(repo):
    main, wt = repo
    run_id = _mint(main)
    _commit(wt, "work-on-the-branch")
    env = {**os.environ, "GIT_DIR": str(main / ".git")}
    r, held = _record(main, wt, run_id, env=env)
    assert r.returncode == 0, r.stderr
    assert held["PRE_PLAN_HEAD"] == _head(wt) != _head(main)


def test_step_7a_tells_a_re_entry_to_hold_and_the_skip_to_stand_aside():
    text = SKILL.read_text(encoding="utf-8")
    stop = ("**On exit 4, stop and report it:** the run's record is not a baseline (a "
            "`pre_plan_head` that is not a full object id, two files recording different object "
            "ids, or a record it cannot read). **On any other non-zero exit, stop and report it "
            "too; never capture the SHAs by hand instead.**")
    skip = ("**Not on a run whose `<ARTIFACT_DIR>` already holds `pre-plan.md`, that Step 7-pre "
            "sent back after `VIOLATED`, or that Step 7d's *revise* minted:** go straight to the "
            "pre-plan record below.")
    park = ("**A held baseline parks on any move of HEAD except onto commits the recorded tip "
            "held**, a fast-forward made after the record as well as a planner commit; the park "
            "report says which, and the remedy is to reset the worktree to `pre_plan_head`, "
            "resume, and fast-forward after the check passes.")
    for s in (stop, skip, park):
        assert text.count(s) == 1, s[:60]
    # Round 3 of Phase 342: the skip section comes first, and a `## Plan` in the body would
    # otherwise hand-write OK over the record of a planner that ran.
    assert text.index(skip) < text.index("PRE_PLAN_SOURCE") < text.index(stop)
    assert text.index(stop) < text.index("Spawning planner for <CLAIM_ID>")


def test_the_sentences_that_say_where_the_shas_live_are_pinned():
    """Phase 343's round (lens 1, m37/m39/m40): each of these could be reverted to the old
    fresh-capture reading with every behavioural test green."""
    text = SKILL.read_text(encoding="utf-8")
    for s in (
        "The pre-plan SHAs get the same treatment one step earlier: 7a writes them to "
        "`pre-plan.md` before it spawns the planner, so a re-entry at 7a re-baselines on them "
        "whether or not the check ever ran.",
        "the rows above reach 7a only when it is absent, or when `planner-integrity.md` is "
        "absent or reads `VIOLATED`,",
        "and 7a re-baselines on the `pre_plan_head` and `pre_plan_base` in `pre-plan.md`, "
        "**not** on the rogue commit.",
        "and run Step 7a in it (the pre-plan record, then the spawn) with the human's note "
        "appended to the Planner Prompt,",
        "passing `planner-integrity VIOLATED in 7a: <the check's reason> (<PRE_PLAN_HEAD> -> "
        "<NOW>)` as the recorded reason.",
    ):
        assert text.count(s) == 1, s[:60]

    # The VIOLATED-only hold it replaced read planner-integrity.md with a grep.
    assert "grep -E '^- pre_plan_(head|base): '" not in text


# --------------------------------------------------------------------------
# Steps 8b and 8c -- the ask and the answers run (Phase 345, `Q-593`)
# --------------------------------------------------------------------------

QUESTIONS = """## the retry loop swallows a timeout
- filed as: TECH-0101
- where: src/net.py:40
- question: retry or surface the timeout?
- recommended: surface it
- alternative: retry twice

## the migration renames a column
- filed as: TECH-0102
- where: db/0007.sql:3
- question: may this branch change the migration?
- recommended: leave it filed
"""


def _run_with(key: str, args: str, cwd: Path):
    """Run a prescribed block with an argument string written by the test. 8b's arity is
    one pair per `questions.md` entry, so its spec cannot be substituted one-to-one."""
    _spec, body = heredocs()[key]
    return subprocess.run(["bash", "-c", f"python3 - <<'PY' {args}\nPY_BODY\nPY\n".replace("PY_BODY", body)],
                          cwd=cwd, capture_output=True, text=True)


def _art(main: Path, run_id: str) -> Path:
    return main / "sysop/runtime/claim/TECH-0007" / run_id


def _asked(main: Path, questions: str = QUESTIONS) -> str:
    run_id = _mint(main)
    (_art(main, run_id) / "questions.md").write_text(questions, encoding="utf-8")
    return run_id


def _git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def test_8b_records_each_answer_under_the_executors_own_question(repo):
    main, _ = repo
    run_id = _asked(main)
    r = _run_with("ANSWERS_TO_FIX", f'"TECH-0007" "{run_id}" "fix" \'surface it\' "leave" \'no answer\'', main)
    assert r.returncode == 0, r.stderr
    assert "ANSWERS_TO_FIX=1" in r.stdout
    text = (_art(main, run_id) / "answers.md").read_text(encoding="utf-8")
    assert re.search(r"(?m)^- asked: \d{4}-\d{2}-\d{2}$", text)
    first, second = text.split("\n## ")[1:]
    assert "- question: retry or surface the timeout?" in first and "- decision: fix" in first
    assert "- answer: surface it" in first and "- filed as: TECH-0101" in first
    assert "- decision: leave" in second and "- answer: no answer" in second


@pytest.mark.parametrize("args,code", [
    ('"fix" \'surface it\'', 1),                               # one pair for two entries
    ('"fix" \'surface it\' "maybe" \'x\'', 1),                 # not fix or leave
    ('"fix" \'\' "leave" \'no answer\'', 1),                   # a fix with nothing to do
    ('"<DECISION_1>" \'<ANSWER_1>\' "leave" \'x\'', 2),        # unsubstituted
])
def test_8b_refuses_answers_that_do_not_match_the_questions(repo, args, code):
    main, _ = repo
    run_id = _asked(main)
    r = _run_with("ANSWERS_TO_FIX", f'"TECH-0007" "{run_id}" {args}', main)
    assert r.returncode == code, (r.stdout, r.stderr)
    assert not (_art(main, run_id) / "answers.md").exists()


def test_8b_refuses_a_run_with_no_questions(repo):
    main, _ = repo
    run_id = _mint(main)
    r = _run_with("ANSWERS_TO_FIX", f'"TECH-0007" "{run_id}" "fix" \'x\'', main)
    assert r.returncode == 1 and "nothing is recorded" in r.stderr


def test_8b_an_answer_cannot_execute(repo):
    """Answers are human free text and ride a single-quoted argument, as <PARK_REASON> does."""
    main, _ = repo
    run_id = _asked(main)
    canary = main / "PWNED"
    r = _run_with("ANSWERS_TO_FIX",
                  f'"TECH-0007" "{run_id}" "fix" \'surface $(touch {canary}) it\' "leave" \'x\'', main)
    assert r.returncode == 0, r.stderr
    assert not canary.exists()
    assert f"surface $(touch {canary}) it" in (_art(main, run_id) / "answers.md").read_text(encoding="utf-8")


def test_8b_does_not_overwrite_answers_a_resume_should_carry_out(repo):
    main, _ = repo
    run_id = _asked(main)
    args = f'"TECH-0007" "{run_id}" "fix" \'surface it\' "leave" \'x\''
    assert _run_with("ANSWERS_TO_FIX", args, main).returncode == 0
    again = _run_with("ANSWERS_TO_FIX", args, main)
    assert again.returncode == 3 and "8c" in again.stderr
    (_art(main, run_id) / "answers-outcome.md").write_text("- answers_status: EXECUTED\n", encoding="utf-8")
    assert _run_with("ANSWERS_TO_FIX", args, main).returncode == 3


def test_8b_archives_a_blocked_pair_when_it_records_again(repo):
    main, _ = repo
    run_id = _asked(main)
    art = _art(main, run_id)
    args = f'"TECH-0007" "{run_id}" "fix" \'surface it\' "leave" \'x\''
    assert _run_with("ANSWERS_TO_FIX", args, main).returncode == 0
    (art / "answers-outcome.md").write_text("- answers_status: BLOCKED\n- blocker_question: which log?\n",
                                            encoding="utf-8")
    r = _run_with("ANSWERS_TO_FIX", f'"TECH-0007" "{run_id}" "fix" \'surface to stderr\' "leave" \'x\'', main)
    assert r.returncode == 0, r.stderr
    assert "BLOCKED" in (art / "answers-outcome.1.md").read_text(encoding="utf-8")
    assert "surface it" in (art / "answers.1.md").read_text(encoding="utf-8")
    assert "surface to stderr" in (art / "answers.md").read_text(encoding="utf-8")
    assert not (art / "answers-outcome.md").exists()


def test_8b_finishes_an_archive_a_crash_left_half_done(repo):
    """Answers are renamed first, so a crash between the renames leaves the BLOCKED outcome,
    which routes a resume back to 8b; this run must complete the archive, not skip it."""
    main, _ = repo
    run_id = _asked(main)
    art = _art(main, run_id)
    (art / "answers.1.md").write_text("old\n", encoding="utf-8")
    (art / "answers-outcome.md").write_text("- answers_status: BLOCKED\n", encoding="utf-8")
    r = _run_with("ANSWERS_TO_FIX", f'"TECH-0007" "{run_id}" "leave" \'x\' "leave" \'y\'', main)
    assert r.returncode == 0, r.stderr
    assert (art / "answers-outcome.1.md").is_file() and not (art / "answers-outcome.md").exists()
    assert (art / "answers.1.md").read_text(encoding="utf-8") == "old\n"


def _answered(main: Path, decisions: str = '"fix" \'surface it\' "leave" \'x\'') -> str:
    run_id = _asked(main)
    r = _run_with("ANSWERS_TO_FIX", f'"TECH-0007" "{run_id}" {decisions}', main)
    assert r.returncode == 0, r.stderr
    return run_id


def test_8c_records_nothing_to_fix_and_does_not_spawn(repo):
    main, _ = repo
    run_id = _answered(main, '"leave" \'x\' "leave" \'y\'')
    r = run_block("TIP_BEFORE=", {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t"}, main)
    assert r.returncode == 0, r.stderr
    assert "SPAWN=no" in r.stdout and "TIP_BEFORE=" not in r.stdout
    assert "answers_status: NOTHING_TO_FIX" in (_art(main, run_id) / "answers-outcome.md").read_text(encoding="utf-8")


def test_8c_moves_an_earlier_answers_envelope_aside_and_prints_the_tip(repo):
    """Step 8c reads <CLAIM_ID>.answers.json first-hit, so a stale one must not be there."""
    main, _ = repo
    run_id = _answered(main)
    box = main / "sysop/runtime/subagent-envelopes"
    box.mkdir(parents=True)
    (box / "TECH-0007.answers.json").write_text('{"stale": true}')
    (box / "TECH-0007.exec.json").write_text('{"first executor": true}')
    r = run_block("TIP_BEFORE=", {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t"}, main)
    assert r.returncode == 0, r.stderr
    assert "SPAWN=yes (1 to fix)" in r.stdout
    assert f"TIP_BEFORE={_git(main, 'rev-parse', 'tech/t')}" in r.stdout
    assert not (box / "TECH-0007.answers.json").exists()
    assert (_art(main, run_id) / "prior-envelopes/TECH-0007.answers.1.json").is_file()
    assert (box / "TECH-0007.exec.json").is_file(), "the first executor's envelope was touched"


def test_8c_prepare_refuses_without_answers_or_over_a_recorded_outcome(repo):
    main, _ = repo
    run_id = _mint(main)
    subs = {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t"}
    assert run_block("TIP_BEFORE=", subs, main).returncode == 3
    run_id = _answered(main)
    (_art(main, run_id) / "answers-outcome.md").write_text("- answers_status: EXECUTED\n", encoding="utf-8")
    assert run_block("TIP_BEFORE=", {**subs, "<RUN_ID>": run_id}, main).returncode == 3


def _record_answers(main, run_id, status, before, question="none"):
    return run_block("answers-outcome record",
                     {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t", "<ANSWERS_STATUS>": status,
                      "<TIP_BEFORE>": before, "<BLOCKER_QUESTION>": question}, main)


def test_8c_a_success_claim_with_no_new_commit_records_no_commit(repo):
    """Phase 323's disqualifying defect: a failed fix read as success. EXECUTED is the agent's
    word; the branch is the evidence."""
    main, _ = repo
    run_id = _answered(main)
    tip = _git(main, "rev-parse", "tech/t")
    r = _record_answers(main, run_id, "EXECUTED", tip)
    assert r.returncode == 1 and "answers_status: NO_COMMIT" in r.stdout
    assert "NO_COMMIT" in (_art(main, run_id) / "answers-outcome.md").read_text(encoding="utf-8")


def test_8c_a_rewritten_branch_records_rewritten(repo):
    main, wt = repo
    run_id = _answered(main)
    (wt / "a.txt").write_text("a\n")
    _git(wt, "add", "a.txt")
    _git(wt, "commit", "-qm", "work")
    before = _git(main, "rev-parse", "tech/t")
    _git(wt, "commit", "-q", "--amend", "-m", "work, amended")
    r = _record_answers(main, run_id, "EXECUTED", before)
    assert r.returncode == 1 and "answers_status: REWRITTEN" in r.stdout


def test_8c_a_forward_commit_records_executed(repo):
    main, wt = repo
    run_id = _answered(main)
    before = _git(main, "rev-parse", "tech/t")
    (wt / "b.txt").write_text("b\n")
    _git(wt, "add", "b.txt")
    _git(wt, "commit", "-qm", "answers")
    r = _record_answers(main, run_id, "EXECUTED", before)
    assert r.returncode == 0, r.stderr
    text = (_art(main, run_id) / "answers-outcome.md").read_text(encoding="utf-8")
    assert "- answers_status: EXECUTED" in text
    assert f"- tip_after: {_git(main, 'rev-parse', 'tech/t')}" in text
    assert _record_answers(main, run_id, "EXECUTED", before).returncode == 3, "an outcome was overwritten"


def test_8c_a_blocked_run_records_its_question_inertly(repo):
    main, _ = repo
    run_id = _answered(main)
    canary = main / "PWNED"
    tip = _git(main, "rev-parse", "tech/t")
    r = _record_answers(main, run_id, "BLOCKED", tip, f"which log, $(touch {canary})?")
    assert r.returncode == 0, r.stderr
    assert not canary.exists()
    assert f"- blocker_question: which log, $(touch {canary})?" in (
        _art(main, run_id) / "answers-outcome.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("status,before,question", [
    ("DONE", "0" * 40, "none"),                 # not a status the envelope carries
    ("EXECUTED", "tech/t", "none"),             # a name, not an object id
    ("BLOCKED", "0" * 40, "<BLOCKER_QUESTION>"),
])
def test_8c_record_refuses_what_it_cannot_judge(repo, status, before, question):
    main, _ = repo
    run_id = _answered(main)
    args = f'"TECH-0007" "{run_id}" "tech/t" "{status}" "{before}" \'{question}\''
    r = _run_with("answers-outcome record", args, main)
    assert r.returncode == 2, (r.stdout, r.stderr)
    assert not (_art(main, run_id) / "answers-outcome.md").exists()


def test_the_park_marker_lists_the_run_artifacts_it_stands_on(repo):
    """`Q-324`: the marker named three artifacts. The four every park expects are present or
    MISSING; the rest appear only when present, so an early park names no Step 8 file."""
    main, _ = repo
    run_id = _answered(main)
    art = _art(main, run_id)
    (art / "plan.md").write_text("p\n")
    (art / "pre-plan.md").write_text("s\n")
    (art / "outcome.md").write_text("- executor_status: EXECUTED\n")
    r = run_block('"parked"', {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t",
                               "<PARK_REASON>": "which log?"}, main)
    assert r.returncode == 0, r.stderr
    marker = (main / "sysop/runtime/parked" / f"TECH-0007__{run_id}.md").read_text(encoding="utf-8")
    for line in ("- plan.md: present", "- planner-integrity.md: MISSING", "- review.md: MISSING",
                 "- pre-plan.md: present", "- outcome.md: present", "- questions.md: present",
                 "- answers.md: present"):
        assert line in marker, line
    assert "answers-outcome.md" not in marker

    early = _mint(main)
    run_block('"parked"', {**IDS, "<RUN_ID>": early, "<BRANCH_NAME>": "tech/t",
                           "<PARK_REASON>": "blocker"}, main)
    marker = (main / "sysop/runtime/parked" / f"TECH-0007__{early}.md").read_text(encoding="utf-8")
    assert "outcome.md" not in marker and "pre-plan.md" not in marker
    assert "answers-started.md" not in marker, "an early park names an artifact only 8c writes"
    assert "- planner-integrity.md: MISSING" in marker


def test_8b_the_shipped_spec_single_quotes_every_answer():
    """The execution tests above write their own argument strings, so they cannot see the
    shipped spec double-quote an answer, where a `$(...)` in human text would run."""
    spec, _body = heredocs()["ANSWERS_TO_FIX"]
    answers = re.findall(r"""(['"])<ANSWER_\d+>\1""", spec)
    assert answers and set(answers) == {"'"}, spec
    decisions = re.findall(r"""(['"])<DECISION_\d+>\1""", spec)
    assert len(decisions) == len(answers), spec


def test_8b_reads_the_questions_file_the_executor_can_actually_write(repo):
    """Rule 4's corpus, built before the parser: a `## ` inside a fence is not an entry, and a
    question wrapped onto an indented line is still one question."""
    main, _ = repo
    run_id = _asked(main, """## the parser drops a header
- filed as: TECH-0103
- where: src/parse.py:12
- question: should a header with no value be kept, or dropped
  with a warning in the log?
- recommended: keep it

```text
## not an entry
```
""")
    r = _run_with("ANSWERS_TO_FIX", f'"TECH-0007" "{run_id}" "fix" \'keep it\'', main)
    assert r.returncode == 0, r.stderr
    text = (_art(main, run_id) / "answers.md").read_text(encoding="utf-8")
    assert "## not an entry" not in text
    assert ("- question: should a header with no value be kept, or dropped with a warning in the log?"
            in text), text


# Round 1 of Phase 345: the menu is built from the block's own listing, and the listing is
# where a recorded outcome stops the ask.

def _list(main, run_id):
    return _run_with("ANSWERS_TO_FIX", f'"TECH-0007" "{run_id}"', main)


def test_8b_lists_what_it_will_record_and_writes_nothing(repo):
    main, _ = repo
    run_id = _asked(main)
    r = _list(main, run_id)
    assert r.returncode == 0, r.stderr
    assert "ASK=yes (2 entries)" in r.stdout
    assert "ENTRY 1: the retry loop swallows a timeout" in r.stdout
    assert "  alternative: retry twice" in r.stdout
    assert "ENTRY 2: the migration renames a column" in r.stdout
    assert not (_art(main, run_id) / "answers.md").exists()


@pytest.mark.parametrize("status", ["NOTHING_TO_FIX", "EXECUTED", "FAILED", "NO_COMMIT", "REWRITTEN"])
def test_8b_a_final_outcome_stops_the_ask(repo, status):
    """The first cut asked on every resume, then refused to record: the answers were lost."""
    main, _ = repo
    run_id = _answered(main)
    (_art(main, run_id) / "answers-outcome.md").write_text(f"- answers_status: {status}\n", encoding="utf-8")
    r = _list(main, run_id)
    assert r.returncode == 0 and f"ASK=no (answers-outcome.md records {status}" in r.stdout, r.stdout
    assert "ENTRY" not in r.stdout


def test_8b_recorded_answers_without_an_outcome_are_not_asked_again(repo):
    main, _ = repo
    run_id = _answered(main)
    r = _list(main, run_id)
    assert "ASK=no (answers.md is recorded" in r.stdout, r.stdout


def test_8b_a_run_with_no_questions_lists_ask_no(repo):
    main, _ = repo
    run_id = _mint(main)
    r = _list(main, run_id)
    assert r.returncode == 0 and "ASK=no (questions.md holds no entry)" in r.stdout


def test_8b_a_blocked_run_shows_the_current_blocker_question(repo):
    """Round 1: the first cut pointed at the ARCHIVED outcome, which the record writes only
    after the ask, so the human saw nothing, or the previous cycle's question."""
    main, _ = repo
    run_id = _answered(main)
    art = _art(main, run_id)
    (art / "answers-outcome.1.md").write_text("- answers_status: BLOCKED\n- blocker_question: old one?\n")
    (art / "answers-outcome.md").write_text("- answers_status: BLOCKED\n- blocker_question: which log?\n")
    r = _list(main, run_id)
    assert "BLOCKER_QUESTION: which log?" in r.stdout and "old one" not in r.stdout
    assert "ASK=yes" in r.stdout


def test_8b_a_crash_after_both_archive_renames_still_shows_the_blocker(repo):
    main, _ = repo
    run_id = _asked(main)
    art = _art(main, run_id)
    (art / "answers.1.md").write_text("old\n")
    (art / "answers-outcome.1.md").write_text("- answers_status: BLOCKED\n- blocker_question: first?\n")
    (art / "answers.2.md").write_text("old\n")
    (art / "answers-outcome.2.md").write_text("- answers_status: BLOCKED\n- blocker_question: second?\n")
    r = _list(main, run_id)
    assert "BLOCKER_QUESTION: second?" in r.stdout and "ASK=yes" in r.stdout, r.stdout


@pytest.mark.parametrize("name,text,expect", [
    ("wrapped in the fence 7e shows", "```markdown\n" + QUESTIONS + "```\n", 2),
    ("indented under a list item", "\n".join("   " + ln if ln else "" for ln in QUESTIONS.split("\n")), 2),
    # Q-468: a ```json line inside a plain ``` fence does not close it.
    ("an info-string line inside a fence", QUESTIONS.replace(
        "- alternative: retry twice\n",
        "- alternative: retry twice\n```\n```json\n## hidden\n```\n")
     + "\n## a third\n- filed as: TECH-0105\n- question: third?\n- recommended: yes\n", 3),
    # A longer fence is closed only by one at least as long.
    ("a four-backtick fence holding a three", QUESTIONS.replace(
        "- alternative: retry twice\n",
        "- alternative: retry twice\n````\n```yaml\n## Also fixed\n```\n````\n"), 2),
    ("a BOM", "\ufeff" + QUESTIONS, 2),
])
def test_8b_parses_the_questions_file_an_executor_can_write(repo, name, text, expect):
    main, _ = repo
    run_id = _asked(main, text)
    r = _list(main, run_id)
    assert f"ASK=yes ({expect} entries)" in r.stdout, (name, r.stdout, r.stderr)
    assert "hidden" not in r.stdout and "Also fixed" not in r.stdout
    if expect == 3:
        assert "ENTRY 3: a third" in r.stdout


def test_8c_a_second_prepare_reads_the_spawn_record_and_moves_nothing(repo):
    """Round 1: a crash after the answers executor returned re-spawned it over committed
    fixes, and the prepare block moved aside the envelope that showed it had run."""
    main, _ = repo
    run_id = _answered(main)
    subs = {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t"}
    first = run_block("TIP_BEFORE=", subs, main)
    assert "SPAWN=yes" in first.stdout, first.stdout
    tip = re.search(r"^TIP_BEFORE=(\S+)$", first.stdout, re.M).group(1)
    box = main / "sysop/runtime/subagent-envelopes"
    box.mkdir(parents=True, exist_ok=True)
    (box / "TECH-0007.answers.json").write_text('{"this spawn": true}')
    second = run_block("TIP_BEFORE=", subs, main)
    assert second.returncode == 0, second.stderr
    assert "SPAWNED_BEFORE" in second.stdout and "SPAWN=yes" not in second.stdout
    assert f"TIP_BEFORE={tip}" in second.stdout
    assert (box / "TECH-0007.answers.json").is_file(), "the spawn's own envelope was moved aside"


# Round 1 of Phase 345, guards lens: the code arms its battery walked through.

THREE = QUESTIONS + """
## a third finding
- filed as: TECH-0104
- where: src/c.py:1
- question: third?
- recommended: do it
"""


def test_8b_refuses_too_many_answer_pairs(repo):
    """R31: `<` in place of `!=` let three pairs record against two entries, shifting a `fix`
    onto the never-list migration entry -- which check 2 would then read as approved."""
    main, _ = repo
    run_id = _asked(main)
    r = _run_with("ANSWERS_TO_FIX",
                  f'"TECH-0007" "{run_id}" "leave" \'x\' "fix" \'surface it\' "leave" \'y\'', main)
    assert r.returncode == 1 and "need 4 arguments" in r.stderr
    assert not (_art(main, run_id) / "answers.md").exists()


def test_8b_counts_fixes_and_normalises_what_it_records(repo):
    """R23, R24, R25, R26, R27: the count, the one-line collapse, the case, the default."""
    main, _ = repo
    run_id = _asked(main, THREE)
    r = _run_with("ANSWERS_TO_FIX",
                  f'"TECH-0007" "{run_id}" "FIX" \'surface\nit\' "leave" \'\' "fix" \'do it\'', main)
    assert r.returncode == 0, r.stderr
    assert "ANSWERS_TO_FIX=2" in r.stdout
    text = (_art(main, run_id) / "answers.md").read_text(encoding="utf-8")
    assert "- answer: surface it\n" in text
    assert text.count("- decision: fix") == 2
    assert "- decision: leave\n- answer: no answer" in text
    assert "- where: src/net.py:40" in text and "- recommended: surface it" in text


def test_8b_writes_through_a_temp_file_it_replaces(repo):
    """R34: a non-atomic write that keeps the `mkstemp(` string passes a string count."""
    _spec, body = heredocs()["ANSWERS_TO_FIX"]
    assert "os.replace(tmp, str(ans))" in body
    assert "with os.fdopen(fd, \"w\", encoding=\"utf-8\") as fh:" in body


def test_8b_a_crash_between_the_archive_renames_keeps_the_blocked_outcome(repo, tmp_path):
    """R22: answers are renamed first. A crash before the second rename must leave the BLOCKED
    outcome, which routes a resume back to 8b; the other order leaves answers.md with no
    outcome, which routes to 8c and spawns on the answers the human is about to replace."""
    main, _ = repo
    run_id = _answered(main)
    art = _art(main, run_id)
    (art / "answers-outcome.md").write_text("- answers_status: BLOCKED\n", encoding="utf-8")
    hook = tmp_path / "crash"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(
        "import pathlib\n_real = pathlib.Path.rename\n_n = [0]\n"
        "def _rename(self, target):\n    _n[0] += 1\n"
        "    if _n[0] == 2:\n        raise SystemExit('crash between renames')\n"
        "    return _real(self, target)\n"
        "pathlib.Path.rename = _rename\n")
    spec, body = heredocs()["ANSWERS_TO_FIX"]
    args = f'"TECH-0007" "{run_id}" "leave" \'x\' "leave" \'y\''
    r = subprocess.run(["bash", "-c", f"python3 - <<'PY' {args}\n{body}\nPY\n"], cwd=main,
                       capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(hook)})
    assert r.returncode != 0, "the crash hook did not fire"
    assert (art / "answers-outcome.md").is_file(), "the BLOCKED outcome was moved before the answers"
    assert not (art / "answers.md").exists()


def test_8b_takes_no_entry_from_a_heading_indented_four_spaces(repo):
    """R36: four spaces is an indented code line, not a heading."""
    main, _ = repo
    run_id = _asked(main, QUESTIONS.replace("- alternative: retry twice\n",
                                            "- alternative: retry twice\n\n    ## not an entry\n"))
    r = _list(main, run_id)
    assert "ASK=yes (2 entries)" in r.stdout and "not an entry" not in r.stdout, r.stdout


def test_8b_and_8c_write_the_main_checkout_from_the_worktree(repo):
    """R30, R45: `--show-toplevel` would resolve the worktree, where no run exists."""
    main, wt = repo
    run_id = _answered(main)
    r = _run_with("ANSWERS_TO_FIX", f'"TECH-0007" "{run_id}"', wt)
    assert r.returncode == 0 and "ASK=no (answers.md is recorded" in r.stdout, (r.stdout, r.stderr)
    subs = {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t"}
    prep = run_block("TIP_BEFORE=", subs, wt)
    assert prep.returncode == 0 and "SPAWN=yes" in prep.stdout, prep.stderr
    tip = re.search(r"^TIP_BEFORE=(\S+)$", prep.stdout, re.M).group(1)
    rec = run_block("answers-outcome record", {**subs, "<ANSWERS_STATUS>": "FAILED",
                                               "<TIP_BEFORE>": tip, "<BLOCKER_QUESTION>": "none"}, wt)
    assert rec.returncode == 0, rec.stderr
    assert (_art(main, run_id) / "answers-outcome.md").is_file()


def test_8c_resolves_the_branch_not_a_tag_of_the_same_name(repo):
    """R48: without `refs/heads/`, git's DWIM prefers a same-named tag."""
    main, wt = repo
    _git(main, "tag", "tech/t", "HEAD")
    (wt / "c.txt").write_text("c\n")
    _git(wt, "add", "c.txt")
    _git(wt, "commit", "-qm", "on the branch")
    run_id = _answered(main)
    r = run_block("TIP_BEFORE=", {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t"}, main)
    assert f"TIP_BEFORE={_git(main, 'rev-parse', 'refs/heads/tech/t')}" in r.stdout, r.stdout


def test_8c_ignores_a_leaked_git_dir(repo, tmp_path):
    """R39: an inherited GIT_DIR overrides -C (Phase 124's rule)."""
    main, _ = repo
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q", ".")
    run_id = _answered(main)
    _spec, body = heredocs()["TIP_BEFORE="]
    r = subprocess.run(["bash", "-c", f"python3 - <<'PY' \"TECH-0007\" \"{run_id}\" \"tech/t\"\n{body}\nPY\n"],
                       cwd=main, capture_output=True, text=True,
                       env={**os.environ, "GIT_DIR": str(other / ".git")})
    assert f"TIP_BEFORE={_git(main, 'rev-parse', 'refs/heads/tech/t')}" in r.stdout, (r.stdout, r.stderr)


def test_8c_keeps_every_earlier_answers_envelope(repo):
    """R37: a second BLOCKED cycle must not overwrite the first cycle's moved envelope."""
    main, _ = repo
    run_id = _answered(main)
    box = main / "sysop/runtime/subagent-envelopes"
    box.mkdir(parents=True)
    prior = _art(main, run_id) / "prior-envelopes"
    prior.mkdir()
    (prior / "TECH-0007.answers.1.json").write_text('{"cycle": 1}')
    (box / "TECH-0007.answers.json").write_text('{"cycle": 2}')
    run_block("TIP_BEFORE=", {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t"}, main)
    assert (prior / "TECH-0007.answers.1.json").read_text() == '{"cycle": 1}'
    assert (prior / "TECH-0007.answers.2.json").read_text() == '{"cycle": 2}'


def test_8c_nothing_to_fix_is_not_fooled_by_the_word_fix(repo):
    """R38: a count keyed to the word, not the decision line, spawns for nothing."""
    main, _ = repo
    run_id = _answered(main, '"leave" \'no fix needed\' "leave" \'fix later\'')
    r = run_block("TIP_BEFORE=", {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t"}, main)
    assert "SPAWN=no" in r.stdout, r.stdout


@pytest.mark.parametrize("status", ["FAILED", "MALFORMED"])
def test_8c_records_a_failed_answers_run(repo, status):
    """R41, R42: without a record a resume routes to 8c and spawns again."""
    main, _ = repo
    run_id = _answered(main)
    r = _record_answers(main, run_id, status, _git(main, "rev-parse", "tech/t"))
    assert r.returncode == 0, r.stderr
    assert f"- answers_status: {status}" in (_art(main, run_id) / "answers-outcome.md").read_text(encoding="utf-8")


def test_8c_record_refuses_a_run_with_no_answers(repo):
    """R44."""
    main, _ = repo
    run_id = _mint(main)
    r = _record_answers(main, run_id, "EXECUTED", "0" * 40)
    assert r.returncode == 3 and "no answers.md" in r.stderr


def test_8c_the_blocker_question_is_recorded_on_one_line(repo):
    """R43."""
    main, _ = repo
    run_id = _answered(main)
    r = _record_answers(main, run_id, "BLOCKED", _git(main, "rev-parse", "tech/t"), "which\nlog?")
    assert r.returncode == 0, r.stderr
    assert "- blocker_question: which log?\n" in (_art(main, run_id) / "answers-outcome.md").read_text(encoding="utf-8")


def test_the_park_marker_names_every_fixed_artifact_and_the_answers_outcome(repo):
    """R49, R50: the park 8c's BLOCKED arm makes stands on answers-outcome.md."""
    main, _ = repo
    run_id = _answered(main)
    art = _art(main, run_id)
    (art / "answers-outcome.md").write_text("- answers_status: BLOCKED\n")
    run_block('"parked"', {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t",
                           "<PARK_REASON>": "which log?"}, main)
    marker = (main / "sysop/runtime/parked" / f"TECH-0007__{run_id}.md").read_text(encoding="utf-8")
    for line in ("- plan.md: MISSING", "- planner-integrity.md: MISSING", "- review.md: MISSING",
                 "- classification.md: MISSING", "- answers-outcome.md: present"):
        assert line in marker, line


def test_8c_record_resolves_the_branch_not_a_tag_of_the_same_name(repo):
    """R48, the record block's half: a tag at the old tip would read the answers commit as
    NO_COMMIT, recording completed work as a failure."""
    main, wt = repo
    run_id = _answered(main)
    before = _git(main, "rev-parse", "refs/heads/tech/t")
    _git(main, "tag", "tech/t", before)
    (wt / "d.txt").write_text("d\n")
    _git(wt, "add", "d.txt")
    _git(wt, "commit", "-qm", "answers")
    r = _record_answers(main, run_id, "EXECUTED", before)
    assert r.returncode == 0 and "answers_status: EXECUTED" in r.stdout, (r.stdout, r.stderr)


@pytest.mark.parametrize("reask", ["fix", "leave"])
def test_a_blocked_answers_run_is_re_asked_and_spawned_again_end_to_end(repo, reask):
    """Round 2 of Phase 345, HIGH: 8b archived the answers and the outcome but not the start
    record, so after a re-ask 8c printed SPAWNED_BEFORE, re-read the BLOCKED cycle's envelope,
    parked again -- forever, and an all-`leave` re-ask could not escape it. Driven through the
    shipped blocks in the order the skill runs them, never from a hand-built state."""
    main, wt = repo
    run_id = _answered(main)
    subs = {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t"}
    first = run_block("TIP_BEFORE=", subs, main)
    assert "SPAWN=yes" in first.stdout, first.stdout
    tip1 = re.search(r"^TIP_BEFORE=(\S+)$", first.stdout, re.M).group(1)
    box = main / "sysop/runtime/subagent-envelopes"
    box.mkdir(parents=True, exist_ok=True)
    (box / "TECH-0007.answers.json").write_text('{"status": "BLOCKED", "cycle": 1}')
    (wt / "partial.txt").write_text("p\n")
    _git(wt, "add", "partial.txt")
    _git(wt, "commit", "-qm", "partial answers work")
    assert _record_answers(main, run_id, "BLOCKED", tip1, "which log?").returncode == 0

    listing = _list(main, run_id)
    assert "BLOCKER_QUESTION: which log?" in listing.stdout and "ASK=yes" in listing.stdout
    decisions = ('"fix" \'surface to stderr\' "leave" \'x\'' if reask == "fix"
                 else '"leave" \'x\' "leave" \'y\'')
    rec = _run_with("ANSWERS_TO_FIX", f'"TECH-0007" "{run_id}" {decisions}', main)
    assert rec.returncode == 0, rec.stderr
    art = _art(main, run_id)
    assert (art / "answers-started.1.md").is_file() and not (art / "answers-started.md").exists()

    second = run_block("TIP_BEFORE=", subs, main)
    assert second.returncode == 0, second.stderr
    assert "SPAWNED_BEFORE" not in second.stdout, "the BLOCKED cycle's start record was read again"
    if reask == "fix":
        assert "SPAWN=yes" in second.stdout
        assert f"TIP_BEFORE={_git(main, 'rev-parse', 'refs/heads/tech/t')}" in second.stdout
        assert not (box / "TECH-0007.answers.json").exists(), "cycle 1's envelope is still readable"
    else:
        assert "SPAWN=no" in second.stdout
        assert "NOTHING_TO_FIX" in (art / "answers-outcome.md").read_text(encoding="utf-8")


def test_8b_an_interrupted_three_file_archive_converges(repo, tmp_path):
    """The outcome is archived last. Crash after the answers moved and before the start record
    did: the BLOCKED outcome still routes back to 8b, and the next record finishes the archive
    under the same number."""
    main, _ = repo
    run_id = _answered(main)
    art = _art(main, run_id)
    (art / "answers-started.md").write_text("- tip_before: " + "0" * 40 + "\n")
    (art / "answers-outcome.md").write_text("- answers_status: BLOCKED\n")
    (art / "answers.md").rename(art / "answers.1.md")
    r = _run_with("ANSWERS_TO_FIX", f'"TECH-0007" "{run_id}" "leave" \'x\' "leave" \'y\'', main)
    assert r.returncode == 0, r.stderr
    for name in ("answers.1.md", "answers-started.1.md", "answers-outcome.1.md", "answers.md"):
        assert (art / name).is_file(), name
    assert not (art / "answers-started.md").exists() and not (art / "answers-outcome.md").exists()


# Round 2 of Phase 345, execution-and-guards lens: layouts the parser met, and its survivors.

ONE = """## finding one
- filed as: T-9
- where: a.py:1
- question: q1?
- recommended: r1
- alternative: a1
"""
TWO = """## finding two
- filed as: T-10
- where: b.py:2
- question: q2?
- recommended: r2
"""


@pytest.mark.parametrize("name,text,reason", [
    ("a `###` entry merges into the one above", ONE + "\n" + TWO.replace("## finding two", "### finding two"), "heading that is not `## `"),
    ("a heading with no space", ONE + "\n" + TWO.replace("## finding two", "##finding two"), "heading that is not `## `"),
    ("a repeated key", ONE + "- question: again?\n", "repeats `question:`"),
    ("no question", ONE.replace("- question: q1?\n", ""), "has no `question:`"),
    ("no filing", ONE.replace("- filed as: T-9\n", ""), "has no `filed as:`"),
    ("a lazy continuation line", ONE.replace("- question: q1?\n", "- question: should the parser accept X,\nor Y?\n"), "unindented line"),
    ("two fenced blocks", "```markdown\n" + ONE + "```\n\n```markdown\n" + TWO + "```\n", "2 fenced blocks"),
    ("prose only", "Nothing to ask here after all.\n", "no `## ` entry in the shape"),
])
def test_8b_refuses_a_layout_it_would_have_to_guess_at(repo, name, text, reason):
    """Refused with the reason printed, never merged: the merge paired one entry's filing with
    another's fix and exited 0. The findings stay filed either way."""
    main, _ = repo
    run_id = _asked(main, text)
    r = _list(main, run_id)
    assert r.returncode == 0 and "ASK=no (questions.md:" in r.stdout and reason in r.stdout, (name, r.stdout)
    rec = _run_with("ANSWERS_TO_FIX", f'"TECH-0007" "{run_id}" "fix" \'r1\' "fix" \'r2\'', main)
    assert rec.returncode == 1 and "nothing is recorded" in rec.stderr, (name, rec.stderr)


@pytest.mark.parametrize("name,text", [
    ("a preamble and postamble around a fence", "Questions for the human:\n\n```markdown\n" + ONE + "\n" + TWO + "```\n\nThat is all.\n"),
    ("a bare fence", "```\n" + ONE + "\n" + TWO + "```\n"),
    ("an `md` fence with a title", "```md title=questions\n" + ONE + "\n" + TWO + "```\n"),
    ("capitalised and bold keys", ONE.replace("- question:", "- Question:") + "\n" + TWO.replace("- recommended:", "- **recommended:**")),
    ("`*`, `+` and numbered bullets", ONE.replace("- where:", "* where:").replace("- question:", "+ question:") + "\n" + TWO.replace("- ", "1. ")),
    ("tab continuation", ONE.replace("- question: q1?\n", "- question: q1,\n\tcontinued?\n") + "\n" + TWO),
])
def test_8b_lists_the_layouts_it_accepts(repo, name, text):
    main, _ = repo
    run_id = _asked(main, text)
    r = _list(main, run_id)
    assert "ASK=yes (2 entries)" in r.stdout, (name, r.stdout, r.stderr)
    assert "  filed as: T-9" in r.stdout and "  filed as: T-10" in r.stdout
    assert "  recommended: r2" in r.stdout
    if name == "tab continuation":
        assert "  question: q1, continued?" in r.stdout


def test_8b_drops_an_alternative_that_names_none(repo):
    main, _ = repo
    run_id = _asked(main, ONE.replace("- alternative: a1", "- alternative: none"))
    r = _list(main, run_id)
    assert "ASK=yes (1 entries)" in r.stdout and "alternative" not in r.stdout, r.stdout


def test_8b_refuses_a_decision_that_is_neither_fix_nor_leave(repo):
    """R02 of round 2: a third decision word would reach 8c as neither."""
    main, _ = repo
    run_id = _asked(main)
    r = _run_with("ANSWERS_TO_FIX", f'"TECH-0007" "{run_id}" "skip" \'x\' "leave" \'y\'', main)
    assert r.returncode == 1 and "must be fix or leave" in r.stderr


def test_8b_a_second_blocked_archive_takes_the_next_number(repo):
    """R05: a fixed number overwrote the first cycle's files, which check 2 accepts as evidence."""
    main, _ = repo
    run_id = _asked(main)
    art = _art(main, run_id)
    for cycle in (1, 2):
        rec = _run_with("ANSWERS_TO_FIX", f'"TECH-0007" "{run_id}" "fix" \'cycle {cycle}\' "leave" \'x\'', main)
        assert rec.returncode == 0, rec.stderr
        (art / "answers-outcome.md").write_text(f"- answers_status: BLOCKED\n- blocker_question: b{cycle}?\n")
    last = _run_with("ANSWERS_TO_FIX", f'"TECH-0007" "{run_id}" "leave" \'x\' "leave" \'y\'', main)
    assert last.returncode == 0, last.stderr
    assert "cycle 1" in (art / "answers.1.md").read_text() and "cycle 2" in (art / "answers.2.md").read_text()
    assert "b2?" in (art / "answers-outcome.2.md").read_text()


def test_8b_the_blocker_comes_from_the_numerically_newest_archive(repo):
    """L18: a name sort puts `.10` before `.9`."""
    main, _ = repo
    run_id = _asked(main)
    art = _art(main, run_id)
    for n in range(1, 11):
        (art / f"answers-outcome.{n}.md").write_text(f"- answers_status: BLOCKED\n- blocker_question: b{n}?\n")
    r = _list(main, run_id)
    assert "BLOCKER_QUESTION: b10?" in r.stdout, r.stdout


def test_8c_counts_only_decision_lines(repo):
    """P02: an unanchored count reads an answer that quotes `decision: fix` as a fix."""
    main, _ = repo
    run_id = _answered(main, '"leave" \'decision: fix later\' "leave" \'y\'')
    r = run_block("TIP_BEFORE=", {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t"}, main)
    assert "SPAWN=no" in r.stdout, r.stdout


def test_8c_refuses_a_branch_that_does_not_resolve(repo):
    """P06: an empty tip would be written as the start record and printed as SPAWN=yes."""
    main, _ = repo
    run_id = _answered(main)
    r = run_block("TIP_BEFORE=", {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "no/such-branch"}, main)
    assert r.returncode == 3 and "SPAWN=yes" not in r.stdout
    assert not (_art(main, run_id) / "answers-started.md").exists()


def test_8c_refuses_a_start_record_with_no_tip(repo):
    """P07."""
    main, _ = repo
    run_id = _answered(main)
    (_art(main, run_id) / "answers-started.md").write_text("# Answers started\n")
    r = run_block("TIP_BEFORE=", {**IDS, "<RUN_ID>": run_id, "<BRANCH_NAME>": "tech/t"}, main)
    assert r.returncode == 4 and "records no tip_before" in r.stderr


def test_8c_record_ignores_a_leaked_git_dir(repo, tmp_path):
    """Q07: the record block's own strip; round 1 tested only the prepare block's."""
    main, wt = repo
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q", ".")
    run_id = _answered(main)
    before = _git(main, "rev-parse", "refs/heads/tech/t")
    (wt / "e.txt").write_text("e\n")
    _git(wt, "add", "e.txt")
    _git(wt, "commit", "-qm", "answers")
    _spec, body = heredocs()["answers-outcome record"]
    args = f'"TECH-0007" "{run_id}" "tech/t" "EXECUTED" "{before}" \'none\''
    r = subprocess.run(["bash", "-c", f"python3 - <<'PY' {args}\n{body}\nPY\n"], cwd=main,
                       capture_output=True, text=True, env={**os.environ, "GIT_DIR": str(other / ".git")})
    assert r.returncode == 0 and "answers_status: EXECUTED" in r.stdout, (r.stdout, r.stderr)


def test_nothing_shipped_carries_a_literal_bom():
    """Phase 345 wrote `.lstrip("\\ufeff")` into Step 8b twice and got an invisible U+FEFF both
    times: a file-writing step converted the escape into the character. It worked, and nothing
    showed it. Shipped text holds the escape, never the character."""
    files = subprocess.run(["git", "ls-files", "core"], cwd=REPO_ROOT, capture_output=True,
                           text=True, check=True).stdout.split()
    hits = []
    for rel in files:
        try:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "﻿" in text:
            hits.append(rel)
    assert not hits, f"literal U+FEFF in shipped files: {hits}"


def test_8b_a_crash_before_the_last_archive_rename_keeps_the_blocked_outcome(repo, tmp_path):
    """The outcome is renamed LAST of three. A crash before that rename must leave it, so the
    resume routes back to 8b; renamed earlier, the crash leaves a start record and no outcome."""
    main, _ = repo
    run_id = _answered(main)
    art = _art(main, run_id)
    (art / "answers-started.md").write_text("- tip_before: " + "0" * 40 + "\n")
    (art / "answers-outcome.md").write_text("- answers_status: BLOCKED\n")
    hook = tmp_path / "crash3"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(
        "import pathlib\n_real = pathlib.Path.rename\n_n = [0]\n"
        "def _rename(self, target):\n    _n[0] += 1\n"
        "    if _n[0] == 3:\n        raise SystemExit('crash before the last rename')\n"
        "    return _real(self, target)\n"
        "pathlib.Path.rename = _rename\n")
    _spec, body = heredocs()["ANSWERS_TO_FIX"]
    args = f'"TECH-0007" "{run_id}" "leave" \'x\' "leave" \'y\''
    r = subprocess.run(["bash", "-c", f"python3 - <<'PY' {args}\n{body}\nPY\n"], cwd=main,
                       capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(hook)})
    assert r.returncode != 0, "the crash hook did not fire"
    assert (art / "answers-outcome.md").is_file(), "the outcome was archived before the start record"


def test_8b_a_fence_ends_the_field_it_interrupts(repo):
    """An indented line after a fence is not a continuation of the field before the fence."""
    main, _ = repo
    run_id = _asked(main, ONE.replace("- question: q1?\n", "- question: q1?\n```text\nexample\n```\n  stray\n") + "\n" + TWO)
    r = _list(main, run_id)
    assert "  question: q1?\n" in r.stdout, r.stdout


def test_8b_a_findings_trailing_space_is_not_part_of_it(repo):
    main, _ = repo
    run_id = _asked(main, ONE.replace("## finding one", "## finding one   ") + "\n" + TWO)
    r = _list(main, run_id)
    assert "ENTRY 1: finding one\n" in r.stdout, r.stdout
