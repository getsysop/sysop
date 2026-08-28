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
    for needle in ("MOVED_PRIOR_ENVELOPES", "classified_by", '"parked"',
                   "planner-integrity", "RESUME_OK", "executor_status",
                   "strip_sections", "plan-only.md"):
        matches = [(a, b) for a, b in found if needle in b]
        assert len(matches) == 1, (
            f"expected exactly one prescribed block containing {needle!r}, found "
            f"{len(matches)} — a duplicate would let a check bind the wrong one"
        )
        out[needle] = matches[0]
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
    subs = {**IDS, "<RUN_ID>": run_id, "<WORKTREE_PATH>": str(wt), "<PRE_PLAN_HEAD>": pre}
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
                               "<PRE_PLAN_HEAD>": "deadbeef"}),
    ):
        r = run_block(needle, subs, main)
        assert r.returncode == 3, f"{needle} minted a run it should have refused: {r.stdout}"
    assert not (main / "sysop/runtime/claim/TECH-0007" / ghost).exists()

    bad = run_block("RESUME_OK", {**IDS, "<RUN_ID>": ghost}, main)
    assert bad.returncode == 3 and "available runs" in bad.stderr


def test_an_unsubstituted_placeholder_is_refused_not_materialised(repo):
    """Quoting alone does not make one loud in a block that CREATES its path — it
    would quietly become a directory of that literal name."""
    main, _ = repo
    for needle in ("MOVED_PRIOR_ENVELOPES", "classified_by", '"parked"'):
        arg_spec, body = heredocs()[needle]
        r = subprocess.run(["bash", "-c", f"python3 - <<'PY' {arg_spec}\n{body}\nPY\n"],
                           cwd=main, capture_output=True, text=True)
        assert r.returncode == 2, f"{needle} accepted an unsubstituted placeholder"
    assert not (main / "sysop/runtime/claim/<CLAIM_ID>").exists()


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
