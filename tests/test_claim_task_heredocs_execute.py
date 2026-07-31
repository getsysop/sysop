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
                   "planner-integrity", "RESUME_OK", "executor_status"):
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
    assert len(blocks) == 6
    for needle, (_args, body) in blocks.items():
        assert body.strip(), f"{needle} extracted an empty body"
        assert "sys.argv" in body, f"{needle} takes no substituted arguments"
