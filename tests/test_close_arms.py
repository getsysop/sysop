"""The arm receipt behind `/review-close`'s step files — Phase 388, `Q-409` P2.

`tools/RUNNER_CORE_SPLIT_SPEC.md` § 5 moves runner text out of `SKILL.md` into step files
the runner reads only when an arm's trigger fires. A `Read` leaves nothing a later step can
check, so `core/companion/scripts/close_arms.py` keeps a receipt: a command decides each
trigger and records the arm as due, the arm's first command records that it loaded with the
digest its file carries, checked against that file, and Step 8's `check` names any arm due and
never loaded.
The first arm is Step 4d's `direct` policy (`steps/4d-direct.md`). Phase 390 (P4) moved
Step 4a's shared-append conflict recipe (`steps/4a-append.md`, made due by `conflicts`) and
4a-fix's body (`steps/4a-fix.md`, made due by `notes`). Phase 393 (P4b) moved the two flag
sections (`steps/prepare-resume.md`, `steps/request-review-land.md`, made due by `begin` from the
flags written out) and Step 4d's `pr` arm (`steps/4d-pr.md`, made due by `arm`, or by `begin`
under `--land`), and `begin` moved ahead of the flag sections.

This module pins:

* the receipt's behaviour, by running the script in scratch repositories;
* the digest: each step file's `loaded` line carries the digest of its own text, and the
  shipped script neither carries nor prints one;
* the one-to-one map between `<!-- sysop:arm=… -->` markers and step files in every skill
  (`skill_text` appends a step file no marker names; here that is a defect);
* that each step file's first command is its `loaded` line, and each stub names its trigger;
* the core budget (spec § 4), which replaced `EDITOR_MIXED_CEILING` in this phase;
* the merge-policy read on `POLICY_CASES`, and that `close_batch.sh` reads through it.
"""
from __future__ import annotations

import os
import shutil
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _prose_guard_helpers import _fence_state  # noqa: E402
from skill_runner_text import step_files, text_of  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "core" / "companion" / "scripts" / "close_arms.py"
SKILLS = REPO / "core" / "skills"
CLOSE_DIR = SKILLS / "review-close"
CLOSE_CORE = CLOSE_DIR / "SKILL.md"
CLOSE_BATCH = REPO / "core" / "companion" / "scripts" / "close_batch.sh"

sys.path.insert(0, str(SCRIPT.parent))
import close_arms  # noqa: E402

MARKER = re.compile(r"^<!-- sysop:arm=(\S+) -->[ \t]*$")

#: `wc -c core/skills/review-close/SKILL.md` may not exceed this (spec § 4). It bounds from
#: above only (Wade, 2026-10-19, at Phase 388's second round): a phase that moves text out of
#: the core lowers it to the new size on purpose and says so in its record, and an ordinary
#: edit under it changes no constant. Raising it is a one-line diff the phase record has to
#: justify. Phase 388 set it at the size it left the core in; the core was 443,993 bytes at
#: `44049727`. Phase 390 (P4) lowered it from 444,060 to 428,645, the core after `4a-append` and
#: `4a-fix` moved out. Phase 393 (P4b) lowered it to 384,477, the core after the two flag
#: sections and Step 4d's `pr` arm moved out. Phase 394 (`Q-667`) raised it to 386_995: Step 2b's
#: verdict lookup and record, on Wade's 2026-10-20 answers, with their rationale in `REFERENCE.md`.
#: Phase 395 (`Q-666`) lowered it to 386_847: step 3b's by-hand security gate and write-once
#: paragraph became one command and its exits. Phase 397 (P5, Step 3b) lowered it to 367_141: the
#: collect's non-zero exits and the refused remove's rollback moved to two step files, and its
#: round put the no-exit-code rule back in the collect's stub and named `exited` where the core
#: lists the receipt's commands. Phase 398 (`Q-676`) raised it by 1, to 367_142: Step 2d's
#: citation of `onboard/SKILL.md` moved from line 95 to 103 when `/onboard` gained its Step 0
#: model table. Phase 403 (P5, Step 4c) lowered it to 364_053: 1b's non-zero-count fallback and
#: item 5's `close_check.py` exit table moved to two step files (363,888), and its round put the
#: no-`RESULT:`-line stop in the check's stub. Phase 406 (P5, Step 2b) lowered it to 355_791: four
#: arms moved to step files. Phase 409 (opened as 407, `Q-686`) raised it to 356_398: the core's revision operands
#: that name a local branch gained `refs/heads/`, its HEAD-name reads became `--show-current`, and
#: 4c 1b's stop names the bare-name retry it forbids; none is an arm. Phase 411 (P5, Step 3c)
#: lowered it to 350_157: the signal arm, from the `READ:`-label paragraph through the recorder,
#: moved to a step file (350,109), and its round's lens A made the `--prepare` line load it.
#: Phase 415 (P5, Step 4-pre) lowered it to 335_141: the two `pr` shapes, the PR-reuse probe
#: through the integration branch's base merge, moved to a step file that `policy` makes due
#: (335,141), and its round's lens A shortened Step 6's stale citation of condition 3 (335,070).
#: Phase 416 (P5, Step 6) lowered it to 323_119: the `pr` re-sync and both per-branch cleanups
#: moved to three step files that Step 6's own `arm` makes due; its round raised it to 323,138,
#: adding Step 6 to the allow-rule inventory and to the steps that write the close id.
#: Phase 418 (P5, Step 4b) lowered it to 314_684: the non-empty batch set, from `close_batch.sh`
#: through the close-batch commit's recovery paths, moved to a step file that Step 4b's `exited`
#: makes due when `review_index.py --list --merged` prints a row (314,629 after the move, the
#: core's reading of the new flag included); naming the reader's full command and giving 3b its
#: own `exited` clause in the allow rule took it to 314,684. Its round raised it to 314,859: the
#: reader's no-operand run and the PR-reuse operand (lens A), exact spelling (lens A, lens B), and
#: Step 4b in the close-id list (lens B). Its round 2 (lens C) raised it to 314,996: the empty
#: arm checks the verdict line's branch count against the branches Step 4a merged.
#: Phase 419 (P5, Step 4a-post) lowered it to 309_427: item 4's failure arms (the fix-commit
#: test, the inherited-failure arm, the pre-existing ask) moved to a step file that 4a-post's
#: `exited` makes due when a gate command answers with a failure; the lead and the stop stay.
#: Its round (lens A) raised it to 309,461: a `TIMEOUT` and a failing `!` run load the arm too,
#: as the fix-commit test reached a `TIMEOUT` before the move. Lens B's dimension-10 finding
#: dropped the stub's literal-`1` rationale, which no sibling stub carries (309,401).
#: Phase 421 (`Q-665`, the prepare under `dontAsk`) lowered it to 297_507: Step 1's three loops
#: became `close_state.py` calls, Step 2b's pin and assertion shell became `review_pins.py`, and
#: Step 3c's per-branch list became `smoke_detect.py --branches`; the `--headless` paragraph and
#: the four new pre-flight rules are inside it. Its round lowered it to 296_948: lens A's fixes
#: added Step 2b's `MOVED:` line and Step 3c's operand exit, and lens B's dimension-10 finding
#: moved the baseline and placement rationale to REFERENCE.md. Then Wade's answer on `Q-712` raised
#: it to 297_552: Step 2b checks that the reviewers' fork has `git_ro.py` before it spawns them.
#: Phase 422 (`Q-665`, the resume under `dontAsk`) lowered it to 293_654: Step 3b's symlink loop
#: became `close_state.py strip-links`, Step 4a's published test `git_check.py published`, Step
#: 4c's validator tail and cleanup two calls, the pre-flight's stale loop paragraph went, and the
#: AWAITING/STOPPED look became a `find`. (The budget was first set to 293_806, 152 bytes above the
#: file, which its round's lens B caught.) Its round lowered it to 293_478: rationale moved to
#: REFERENCE.md and stale integration-branch prose went.
#: Phase 423 (`Q-665`, the unattended land under `dontAsk`) lowered it to 293_296: Step 6's HARD
#: RULE rationale moved to REFERENCE.md, which paid for its prescribed `find`, the pre-flight's
#: scripts `find` and the argument-hint's `[--headless]` on the unattended land. Its round
#: (lens A) lowered it to 293_280: the HARD RULE's `find` gained `-type f` and its no-directory
#: outcome, paid for by two clauses of the same paragraph.
#: Phase 426 (`Q-713`) lowered it to 293_216: the reviewer prompt's run-each-line-alone rule and
#: its one-call-per-entry clause, paid for by Step 2b's isolation-incident parenthetical, which
#: moved to REFERENCE.md. Its round set it to 293_232, still below the phase's base of 293_244:
#: the same prompt's "you will write a loop" sentence became one call per file (both lenses), and
#: the rule names `||` and `$(…)` (lens B).
#: Phase 429 (P5, Step 4a) lowered it to 289_751: item 2's published arm and item 3 moved to a
#: step file that Step 4a's `exited` makes due when `git_check.py published` exits 0; item 2's
#: lead, the local-only arm, a one-line item 3 and item 4 stay. Its round (lens A) raised it to
#: 289,803: the stub names `git_check.py published` (item 1 runs two commands that exit 0), and
#: item 1's stale-ref sentence names the published arm's cost as a merge commit, not the
#: throwaway ref Phase 219 withdrew. Lens B lowered it to 289_775: the stub's "follow it in full
#: before you merge the branch" became "follow it in full", since the arm holds the merge.
#: Phase 430 (P5, the last two command-triggered rows): 287,097 after the move, which put Step
#: 2a step 3a's answers in `steps/2a-ignored-refs.md` (made due by the check's non-zero exit)
#: and 4a-post 3a's non-zero, could-not-run and absent-script outcomes in
#: `steps/4a-post-prescan.md`; +51 for the two arms in `begin`'s list, 2a in the close-id list
#: and 2a's `exited` in the allow-rule inventory. Its round (lens A) lowered it to 287,120: the
#: pre-scan stub's lead names only what loads its arm ("A non-zero exit, or no script to run",
#: not "Any other outcome", which a killed run could be read as).
#: Phase 438 (`Q-409` closes at P5, Wade's ruling of 2026-10-29) lowered it to 286_503, the core's
#: `wc -c` at `5a22f775`: Phase 433's citation scrub shrank the core by 617 bytes and left this
#: constant where Phase 430 set it, against Wade's 2026-10-14 answer 2 (lower it to each phase's
#: new size). The campaign stops here; the budget stays as a growth guard on the core.
#: Phase 445 (`Q-547`, Wade's ruling of 2026-10-30) raised it to 287_130 (+627): Step 4a item 1's
#: `CLOSED TASK EDITED:` bullet, "under either policy" on the check that prints it, and Step 8's
#: `Closed-task edits:` row. The bullet routes before the merge it governs, so it cannot sit in an
#: arm the merge loads. Phase 446 (`Q-547`, Wade 2026-10-30) raised it to 287_190 (+60): the
#: `Closed-task edits:` row names Rule B's push-time check too.
CORE_BUDGET_BYTES = 287_190

GIT_ENV = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}


def run(*args, cwd):
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=cwd, capture_output=True,
                          text=True, env=GIT_ENV)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True, env=GIT_ENV)
    subprocess.run(["git", "-C", str(r), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True, env=GIT_ENV)
    return r


ARM_FILE = CLOSE_DIR / "steps" / "4d-direct.md"
DIGEST = close_arms.digest_of(ARM_FILE.read_text(encoding="utf-8"))


def load(cid, cwd, digest=DIGEST, arm="4d-direct", skill=CLOSE_DIR):
    return run("loaded", cid, arm, digest, str(skill), cwd=cwd)


def begin(cwd, flags="") -> str:
    p = run("begin", flags, *sorted(close_arms.ARMS), cwd=cwd)
    assert p.returncode == 0, p.stderr
    m = re.fullmatch(r"CLOSE: (\S+)\n(ARM: \S+\n)+", p.stdout)
    assert m, p.stdout
    return m.group(1)


def receipt(root: Path, cid: str) -> Path:
    return root / "sysop" / "runtime" / "close-arms" / f"{cid}.tsv"


# ── the receipt ─────────────────────────────────────────────────────────────────────────

def test_a_direct_close_that_never_loads_its_arm_is_named_and_kept(repo):
    cid = begin(repo)
    assert run("policy", cid, cwd=repo).stdout.splitlines()[0] == "POLICY: direct"
    assert run("arm", cid, "4d", cwd=repo).stdout == "ARM: 4d-direct\n"
    p = run("check", cid, cwd=repo)
    assert p.returncode == 1
    assert "ARM NOT LOADED: 4d-direct" in p.stdout.splitlines()
    assert "ARMS: required 1, loaded 0" in p.stdout.splitlines()
    recs = receipt(repo, cid).read_text().splitlines()
    assert recs[-1].split("\t")[0] == "checked" and recs[-1].endswith("missing 1")


def test_a_loaded_arm_checks_clean_and_the_receipt_is_removed(repo):
    cid = begin(repo)
    run("policy", cid, cwd=repo)
    run("arm", cid, "4d", cwd=repo)
    p = load(cid, repo)
    assert p.returncode == 0 and p.stdout == "LOADED: 4d-direct\n", p.stderr
    p = run("check", cid, str(CLOSE_DIR), cwd=repo)
    assert p.returncode == 0, p.stdout
    lines = p.stdout.splitlines()
    assert lines[0] == "ARMS: required 1, loaded 1"
    assert not [ln for ln in lines if ln.startswith("ARM NOT LOADED")]
    assert f"CORE: {CLOSE_CORE.stat().st_size}" in lines
    assert f"LOADED: 4d-direct {(CLOSE_DIR / 'steps' / '4d-direct.md').stat().st_size}" in lines
    assert f"SHARED: _shared/main-push-guard.md {(SKILLS / '_shared' / 'main-push-guard.md').stat().st_size}" in lines
    assert not receipt(repo, cid).exists()


def test_a_load_nothing_required_is_not_counted_as_a_required_load(repo):
    """Under `pr` the `direct` arm is not due. A runner that loads it anyway leaves a
    `loaded` record the count must not read as a required arm met, and `4d-pr` stays missing."""
    (repo / "CLAUDE.md").write_text("## Merge policy\n\npr\n")
    cid = begin(repo)
    run("policy", cid, cwd=repo)
    run("arm", cid, "4d", cwd=repo)
    load(cid, repo)
    p = run("check", cid, cwd=repo)
    assert p.returncode == 1
    assert p.stdout == ("ARMS: required 2, loaded 0\nARM NOT LOADED: 4-pre-pr\n"
                        "ARM NOT LOADED: 4d-pr\n")


def test_a_digest_the_step_file_does_not_print_is_refused_and_records_nothing(repo):
    cid = begin(repo)
    run("policy", cid, cwd=repo)
    run("arm", cid, "4d", cwd=repo)
    before = receipt(repo, cid).read_text()
    p = load(cid, repo, digest="0" * 16)
    assert p.returncode == 2 and "DIGEST MISMATCH" in p.stderr
    assert DIGEST not in p.stderr, "the refusal must not print the digest it wanted"
    assert receipt(repo, cid).read_text() == before
    p = load(cid, repo, arm="no-such-arm")
    assert p.returncode == 2 and "unknown arm" in p.stderr
    p = load(cid, repo, skill=repo)
    assert p.returncode == 2 and "could not be read" in p.stderr
    p = load(cid, repo, skill="")
    assert p.returncode == 2, "an unsubstituted skill directory must not record a load"
    assert receipt(repo, cid).read_text() == before
    assert run("check", cid, cwd=repo).returncode == 1


def test_the_digest_is_checked_against_the_file_the_runner_was_handed(repo, tmp_path):
    """Phase 388's round (lens A): a plugin skill newer than the installed script carries a
    new digest, so the check reads the arm file the skill directory holds, not a table."""
    skill = tmp_path / "skill"
    (skill / "steps").mkdir(parents=True)
    edited = ARM_FILE.read_text(encoding="utf-8") + "\nOne more line.\n"
    (skill / "steps" / "4d-direct.md").write_text(edited, encoding="utf-8")
    cid = begin(repo)
    assert load(cid, repo, skill=skill).returncode == 2, "the old digest passed an edited file"
    p = load(cid, repo, digest=close_arms.digest_of(edited), skill=skill)
    assert p.returncode == 0, p.stderr


def test_the_shipped_script_cannot_print_a_digest():
    """The seeded rule covers every `close_arms.py` subcommand, so a `digest` one would let a
    runner compute the value without reading the file (Phase 388's round, lens B)."""
    assert "digest" not in close_arms.COMMANDS
    assert DIGEST not in SCRIPT.read_text(encoding="utf-8")


def test_begin_refuses_a_skill_and_script_from_different_versions(repo):
    arms = sorted(close_arms.ARMS)
    for args in ([""], ["", "4d-direct", "4d-pr"], ["", "4d-pr"], ["", *arms, "4d-pr"],
                 ["", *arms[1:], arms[1]], ["", *arms, "4a-skip"],
                 ["4a-append", "4a-fix", "4d-direct"],          # Phase 392's core, no flags
                 arms):
        p = run("begin", *args, cwd=repo)
        assert p.returncode == 2 and "different versions" in p.stderr, args
        assert p.stdout == "", args
    assert run("begin", cwd=repo).returncode == 2
    assert not (repo / "sysop").exists()


def test_the_core_names_every_arm_it_marks_to_begin():
    text = CLOSE_CORE.read_text(encoding="utf-8")
    line = next(ln for ln in text.split("\n") if ln.startswith("python3 sysop/scripts/close_arms.py begin"))
    assert line.split()[3] == '"<flags>"', line
    assert line.split()[4:] == sorted(_markers(CLOSE_DIR)) == sorted(close_arms.ARMS)


@pytest.mark.parametrize("step", ["4D", "4d ", "4e", ""])
def test_arm_refuses_a_step_with_no_arms(repo, step):
    """Round 2 (lens C): a mistyped step printed `ARM: none` and read like `pr`."""
    cid = begin(repo)
    run("policy", cid, cwd=repo)
    p = run("arm", cid, step, cwd=repo)
    assert p.returncode == 2 and "unknown step" in p.stderr, (step, p.stdout)


def test_the_latest_policy_record_decides_the_arm(repo):
    cid = begin(repo)
    run("policy", cid, cwd=repo)                                   # direct
    (repo / "CLAUDE.md").write_text("## Merge policy\n\npr\n")
    run("policy", cid, cwd=repo)                                   # pr, a rerun of 4-pre
    assert run("arm", cid, "4d", cwd=repo).stdout == "ARM: 4d-pr\n"


def test_a_receipt_line_of_the_wrong_shape_makes_it_unreadable(repo):
    """Phase 388's round (lens A): a truncated or space-separated `required` line read as no
    arm due, so `check` exited 0 and deleted the receipt."""
    for bad in ("requir", "required 4d-direct x", "required\t\tx", "", "loaded\t4d-direct\tx"):
        cid = begin(repo)
        with open(receipt(repo, cid), "a") as f:
            f.write(bad + "\n")
        p = run("check", cid, cwd=repo)
        assert p.returncode == 2 and "damaged" in p.stderr, bad
        assert receipt(repo, cid).exists()


def test_check_says_when_it_cannot_measure_the_core(repo, tmp_path):
    cid = begin(repo)
    assert run("check", cid, str(tmp_path), cwd=repo).stdout.splitlines()[-1].startswith(
        "CORE: unknown (no SKILL.md in")


def test_a_pr_close_requires_the_pr_arm(repo):
    """Phase 393: Step 4d's `pr` policy is an arm (`steps/4d-pr.md`), made due by `arm`."""
    (repo / "CLAUDE.md").write_text("# p\n\n## Merge policy\n\npr\n")
    cid = begin(repo)
    out = run("policy", cid, cwd=repo).stdout.splitlines()
    assert out == ["POLICY: pr", "SOURCE: declared in CLAUDE.md ## Merge policy", "ARM: 4-pre-pr"]
    assert run("arm", cid, "4d", cwd=repo).stdout == "ARM: 4d-pr\n"
    p = run("check", cid, cwd=repo)
    assert p.returncode == 1 and p.stdout == ("ARMS: required 2, loaded 0\n"
                                              "ARM NOT LOADED: 4-pre-pr\nARM NOT LOADED: 4d-pr\n")
    cid = begin(repo)
    run("policy", cid, cwd=repo)
    run("arm", cid, "4d", cwd=repo)
    for arm in ("4-pre-pr", "4d-pr"):
        text = (CLOSE_DIR / "steps" / f"{arm}.md").read_text(encoding="utf-8")
        assert load(cid, repo, close_arms.digest_of(text), arm=arm).returncode == 0, arm
    assert run("check", cid, cwd=repo).returncode == 0


def test_policy_makes_step_4_pres_pr_arm_due_under_pr_only(repo):
    """Phase 415 (P5, Step 4-pre): `policy` records `4-pre-pr` and prints it under `pr`, and
    under `direct` prints `ARM: none` and records no arm. Step 4d's `arm` refuses a close whose
    policy was never recorded, so a close that lands cannot skip this trigger (Wade, 2026-10-23)."""
    cid = begin(repo)
    assert run("policy", cid, cwd=repo).stdout.splitlines() == [
        "POLICY: direct", "SOURCE: no readable CLAUDE.md", "ARM: none"]
    assert not [r for r in receipt(repo, cid).read_text().splitlines()
                if r.startswith("required\t")]
    (repo / "CLAUDE.md").write_text("## Merge policy\n\npr\n")
    cid = begin(repo)
    assert run("policy", cid, cwd=repo).stdout.splitlines()[-1] == "ARM: 4-pre-pr"
    assert [r.split("\t")[1] for r in receipt(repo, cid).read_text().splitlines()
            if r.startswith("required\t")] == ["4-pre-pr"]
    p = run("check", cid, cwd=repo)
    assert p.returncode == 1 and "ARM NOT LOADED: 4-pre-pr" in p.stdout.splitlines()


def _digest(arm: str) -> str:
    return close_arms.digest_of((CLOSE_DIR / "steps" / f"{arm}.md").read_text(encoding="utf-8"))


def _required(repo, cid) -> list:
    return [r.split("\t")[1] for r in receipt(repo, cid).read_text().splitlines()
            if r.startswith("required\t")]


def test_step_6s_arm_makes_its_policy_runs_due(repo):
    """Phase 416 (P5, Step 6): Step 6's own `arm` records `6-direct` under `direct`, and
    `6-pr-gate` then `6-pr-cleanup` under `pr`, each printed; `check` names each until it loads."""
    cid = begin(repo)
    run("policy", cid, cwd=repo)
    assert run("arm", cid, "6", cwd=repo).stdout == "ARM: 6-direct\n"
    assert _required(repo, cid) == ["6-direct"]
    p = run("check", cid, cwd=repo)
    assert p.returncode == 1 and p.stdout.splitlines()[1:] == ["ARM NOT LOADED: 6-direct"]
    (repo / "CLAUDE.md").write_text("## Merge policy\n\npr\n")
    cid = begin(repo)
    run("policy", cid, cwd=repo)
    assert run("arm", cid, "6", cwd=repo).stdout == "ARM: 6-pr-gate\nARM: 6-pr-cleanup\n"
    assert _required(repo, cid) == ["4-pre-pr", "6-pr-gate", "6-pr-cleanup"]
    for arm in ("4-pre-pr", "6-pr-gate"):
        assert load(cid, repo, _digest(arm), arm).returncode == 0
    p = run("check", cid, cwd=repo)
    assert p.returncode == 1 and p.stdout.splitlines()[1:] == ["ARM NOT LOADED: 6-pr-cleanup"]
    assert load(cid, repo, _digest("6-pr-cleanup"), "6-pr-cleanup").returncode == 0
    assert run("check", cid, cwd=repo).returncode == 0


def test_a_close_that_skips_step_6_on_purpose_requires_none_of_its_arms(repo):
    """Phase 416: half A of `--request-review`, a stuck PR and a broken staging deploy each run
    Step 4d's `arm` and then skip Step 6. Recording Step 6's arms at Step 4d would report them
    not loaded on all three (Wade, 2026-10-23), so 4d's `arm` records 4d's alone."""
    (repo / "CLAUDE.md").write_text("## Merge policy\n\npr\n")
    cid = begin(repo, "--request-review")
    run("policy", cid, cwd=repo)
    assert run("arm", cid, "4d", cwd=repo).stdout == "ARM: 4d-pr\n"
    assert _required(repo, cid) == ["request-review-land", "4-pre-pr", "4d-pr"]
    for arm in ("request-review-land", "4-pre-pr", "4d-pr"):
        assert load(cid, repo, _digest(arm), arm).returncode == 0
    assert run("check", cid, cwd=repo).returncode == 0


def _flags(flag_set) -> str:
    """A `FLAG_SETS` entry written out, each flag that takes one given a value `VALUE` accepts."""
    values = {"--resume": "20261023T120000Z-ab12", "--land": "20261023T120000Z-ab12",
              "--agent": "codex"}
    return " ".join(f"{f} {values[f]}" if f in values else f for f in sorted(flag_set))


def test_a_land_records_its_policy_so_step_6s_arm_runs(repo):
    """Phase 416: `--land` runs no Step 4-pre and reaches Step 6, so `begin` records the `pr`
    policy it has checked; without it Step 6's `arm` would refuse every land. No other flag set
    records a policy at `begin`, so Step 4d's `arm` still proves Step 4-pre ran. Its round (lens B)
    found the unattended land and `--agent`/`--prepare` unseen: every entry of `FLAG_SETS` runs."""
    (repo / "CLAUDE.md").write_text("## Merge policy\n\npr\n")
    lands = [s for s in close_arms.FLAG_SETS if "--land" in s]
    assert len(lands) == 2
    for flag_set in lands:
        cid = begin(repo, _flags(flag_set))
        recs = receipt(repo, cid).read_text().splitlines()
        assert [r.split("\t")[:2] for r in recs if r.startswith("policy\t")] == [["policy", "pr"]]
        assert run("arm", cid, "6", cwd=repo).stdout == "ARM: 6-pr-gate\nARM: 6-pr-cleanup\n"
        assert _required(repo, cid) == ["request-review-land", "4d-pr", "6-pr-gate", "6-pr-cleanup"]
    others = [s for s in close_arms.FLAG_SETS if "--land" not in s]
    assert len(others) == len(close_arms.FLAG_SETS) - 2
    for flag_set in others:
        flags = _flags(flag_set)
        cid = begin(repo, flags)
        assert not [r for r in receipt(repo, cid).read_text().splitlines()
                    if r.startswith("policy\t")], flags
        for step in ("4d", "6"):
            p = run("arm", cid, step, cwd=repo)
            assert p.returncode == 2 and "no policy recorded" in p.stderr, (flags, step)


def test_a_close_that_stops_before_4d_requires_nothing(repo):
    """A dry run and a plain close that stops before Step 4 open a receipt with no arm due, so
    `check` passes and `unchecked` reports nothing even when it ages."""
    cid = begin(repo, "--dry-run")
    os.utime(receipt(repo, cid), (time.time() - 90000, time.time() - 90000))
    assert run("unchecked", cwd=repo).stdout == ""
    assert run("check", cid, cwd=repo).returncode == 0


def test_an_unrecognised_policy_word_stops_the_close_at_step_1(repo):
    (repo / "CLAUDE.md").write_text("## Merge policy\n\npull-request\n")
    p = run("begin", "", *sorted(close_arms.ARMS), cwd=repo)
    assert p.returncode == 2 and "'pull-request'" in p.stderr and p.stdout == ""
    assert not (repo / "sysop").exists(), "a refused begin created a receipt"


def test_a_word_changed_after_step_1_is_refused_at_4_pre(repo):
    cid = begin(repo)
    (repo / "CLAUDE.md").write_text("## Merge policy\n\npull-request\n")
    p = run("policy", cid, cwd=repo)
    assert p.returncode == 2 and "'pull-request'" in p.stderr
    p = run("arm", cid, "4d", cwd=repo)
    assert p.returncode == 2 and "no policy recorded" in p.stderr


@pytest.mark.parametrize("bad", ["../x", "", "20261019T133542Z-f0f4/../../y", "x" * 21])
def test_a_close_id_that_is_not_one_is_refused(repo, bad):
    p = run("check", bad, cwd=repo)
    assert p.returncode == 2 and "is not a close id" in p.stderr


def test_a_missing_receipt_is_refused(repo):
    p = run("arm", "20261019T133542Z-f0f4", "4d", cwd=repo)
    assert p.returncode == 2 and "no receipt" in p.stderr


def test_a_linked_worktree_writes_the_main_checkouts_receipt(repo, tmp_path):
    wt = tmp_path / "wt"
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(wt)],
                   check=True, env=GIT_ENV)
    cid = begin(wt)
    assert receipt(repo, cid).is_file()
    assert not (wt / "sysop").exists()


def test_a_separate_git_dir_reads_the_checkouts_own_policy(tmp_path):
    """Phase 388's round (lens A, HIGH): the common directory's parent is not the repository
    under `--separate-git-dir`, and the policy read from there was `direct` over a `pr`."""
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "main", f"--separate-git-dir={tmp_path / 'gd'}",
                    str(work)], check=True, env=GIT_ENV)
    (work / "CLAUDE.md").write_text("## Merge policy\n\npr\n")
    p = run("begin", "", *sorted(close_arms.ARMS), cwd=work)
    assert p.returncode == 0, p.stderr
    cid = p.stdout.split()[1]
    assert run("policy", cid, cwd=work).stdout.splitlines()[0] == "POLICY: pr"
    assert run("arm", cid, "4d", cwd=work).stdout == "ARM: 4d-pr\n"
    (work / "CLAUDE.md").write_text("## Merge policy: pr\n")
    p = run("begin", "", *sorted(close_arms.ARMS), cwd=work)
    assert p.returncode == 2, "begin read the policy somewhere other than the work tree"


def test_an_inherited_git_dir_does_not_redirect_the_receipt(repo, tmp_path):
    other = tmp_path / "other"
    subprocess.run(["git", "init", "-q", str(other)], check=True, env=GIT_ENV)
    p = subprocess.run([sys.executable, str(SCRIPT), "begin", "", *sorted(close_arms.ARMS)],
                       cwd=repo, capture_output=True, text=True,
                       env={**GIT_ENV, "GIT_DIR": str(other / ".git")})
    assert p.returncode == 0, p.stderr
    assert receipt(repo, p.stdout.split()[1]).is_file()


def test_unchecked_names_an_aged_receipt_with_an_unloaded_arm_and_only_that(repo):
    cid = begin(repo)
    run("policy", cid, cwd=repo)
    run("arm", cid, "4d", cwd=repo)
    assert run("unchecked", cwd=repo).stdout == "", "a fresh receipt is a live close"
    three = time.time() - 3 * 3600
    os.utime(receipt(repo, cid), (three, three))
    assert run("unchecked", cwd=repo).stdout == "", "the default is a day, not hours"
    old = time.time() - 25 * 3600
    os.utime(receipt(repo, cid), (old, old))
    assert run("unchecked", cwd=repo).stdout == f"UNCHECKED: {cid} 4d-direct\n"
    assert run("unchecked", "--hours", "30", cwd=repo).stdout == ""
    run("arm", cid, "4d", cwd=repo)                  # the same arm due twice: one line
    os.utime(receipt(repo, cid), (old, old))
    assert run("unchecked", cwd=repo).stdout == f"UNCHECKED: {cid} 4d-direct\n"
    run("check", cid, cwd=repo)                      # checked, missing 1
    os.utime(receipt(repo, cid), (old, old))
    assert run("unchecked", cwd=repo).stdout == "", "Step 8 already reported it"


def test_unchecked_names_a_receipt_it_cannot_read(repo):
    cid = begin(repo)
    receipt(repo, cid).write_bytes(b"begin\t\xff\n")
    os.utime(receipt(repo, cid), (time.time() - 25 * 3600,) * 2)
    out = run("unchecked", cwd=repo).stdout
    assert out.startswith(f"UNREADABLE: {cid}.tsv"), out


def test_begin_prunes_only_receipts_with_nothing_left_to_report(repo):
    stale = time.time() - 31 * 86400
    keep = begin(repo)                               # unchecked, an arm due: kept
    run("policy", keep, cwd=repo)
    run("arm", keep, "4d", cwd=repo)
    empty = begin(repo)                              # nothing due: pruned
    reported = begin(repo)                           # checked with a miss: pruned
    run("policy", reported, cwd=repo)
    run("arm", reported, "4d", cwd=repo)
    run("check", reported, cwd=repo)
    young = begin(repo)                              # nothing due, but young: kept
    week = begin(repo)                               # nothing due, three days old: kept
    broken = begin(repo)                             # unreadable and stale: kept, and no refusal
    receipt(repo, broken).write_bytes(b"\xff\xfe\n")
    for c in (keep, empty, reported, broken):
        os.utime(receipt(repo, c), (stale, stale))
    os.utime(receipt(repo, week), (time.time() - 3 * 86400,) * 2)
    begin(repo)
    assert receipt(repo, week).exists()
    assert receipt(repo, broken).exists()
    assert receipt(repo, keep).exists()
    assert not receipt(repo, empty).exists()
    assert not receipt(repo, reported).exists()
    assert receipt(repo, young).exists()


# ── the flags: `begin` before the flag sections (Phase 393, P4b) ─────────────────────────

RUN = "20261019T010203Z-abcd"
# `--skip-permission-guard` goes with any combination, and `--headless` (Phase 421, `Q-665`)
# with any that holds `--prepare` or `--resume`; neither is part of a combination.
NON_SKIP = sorted(close_arms.FLAGS - {"--skip-permission-guard", "--headless"})


def _flag_words(flags) -> str:
    return " ".join(f"{f} {'agent-1' if f == '--agent' else RUN}" if f in close_arms.VALUE_FLAGS
                    else f for f in flags)


def _expand(hint: str) -> set:
    """Every flag set the argument hint spells: `a | b` alternates, `[x]` is optional."""
    def alts(s):
        out, depth, cur = [], 0, ""
        for ch in s:
            depth += ch == "["
            depth -= ch == "]"
            if ch == "|" and depth == 0:
                out.append(cur); cur = ""
            else:
                cur += ch
        return out + [cur]

    def seq(s):
        sets = [frozenset()]
        i = 0
        while i < len(s):
            if s[i] == "[":
                depth, j = 1, i + 1
                while depth:
                    depth += {"[": 1, "]": -1}.get(s[j], 0); j += 1
                inner = set().union(*(seq(a) for a in alts(s[i + 1:j - 1])))
                sets = [a | b for a in sets for b in inner | {frozenset()}]
                i = j
            else:
                j = i
                while j < len(s) and s[j] != "[":
                    j += 1
                words = {w for w in s[i:j].split() if w.startswith("--")}
                sets = [a | words for a in sets]
                i = j
        return set(sets)
    return set().union(*(seq(a) for a in alts(hint)))


def test_the_flag_sets_begin_accepts_are_the_argument_hints():
    """One grammar: the frontmatter's `argument-hint`, which the harness shows the user, and the
    combinations `begin` accepts, which replaced the two sections' combination sentences."""
    hint = re.search(r'^argument-hint: "(.*)"$', CLOSE_CORE.read_text(encoding="utf-8"), re.M).group(1)
    sets = _expand(hint)
    base = {s - {"--headless"} for s in sets}
    assert base == close_arms.FLAG_SETS, base ^ close_arms.FLAG_SETS
    assert len(close_arms.FLAG_SETS) == 12
    # The hint offers `--headless` exactly where `begin` accepts it: beside `--prepare` or
    # `--resume`, in every combination either one opens, and the unattended land (Phase 423).
    headless = {s - {"--headless"} for s in sets if "--headless" in s}
    assert headless == {s for s in close_arms.FLAG_SETS if {"--prepare", "--resume"} & s
                        or {"--land", "--unattended"} <= s}, headless


def test_the_hint_expander_is_not_vacuous():
    assert _expand("[--a | --b [--c]]") == {frozenset(), frozenset({"--a"}), frozenset({"--b"}),
                                            frozenset({"--b", "--c"})}


def test_begin_refuses_every_combination_the_skill_does_not_run():
    import itertools
    refused = 0
    for n in range(len(NON_SKIP) + 1):
        for combo in itertools.combinations(NON_SKIP, n):
            for skip in ((), ("--skip-permission-guard",)):
                words = _flag_words(combo + skip)
                if frozenset(combo) in close_arms.FLAG_SETS:
                    assert set(close_arms.parse_flags(words)) == set(combo + skip), words
                else:
                    with pytest.raises(close_arms.Refuse, match="does not run with the flags"):
                        close_arms.parse_flags(words)
                    refused += 1
    assert refused == 2 * (2 ** len(NON_SKIP) - len(close_arms.FLAG_SETS))


def test_headless_goes_with_prepare_resume_or_the_unattended_land_and_nothing_else():
    """Phase 421 (`Q-665`): the launcher passes `--headless` to both nights' sessions; Phase 423
    adds the third, `--land … --unattended`. The attended land is refused: a human runs it."""
    admitted = 0
    for combo in close_arms.FLAG_SETS:
        words = _flag_words(tuple(sorted(combo)) + ("--headless",))
        if {"--prepare", "--resume"} & combo or {"--land", "--unattended"} <= combo:
            assert "--headless" in close_arms.parse_flags(words), words
            admitted += 1
        else:
            with pytest.raises(close_arms.Refuse,
                               match="--headless goes with --prepare, --resume or --land --unattended"):
                close_arms.parse_flags(words)
    assert admitted == 7, admitted  # 2 prepare + 4 resume + the unattended land
    with pytest.raises(close_arms.Refuse, match="--headless goes with"):
        close_arms.parse_flags(_flag_words(("--land", "--headless")))
    # The refusal of an unknown combination names where `--headless` goes, too (lens B's B02).
    with pytest.raises(close_arms.Refuse,
                       match="and --headless with --prepare, --resume or --land --unattended"):
        close_arms.parse_flags(_flag_words(("--prepare", "--land")))


def test_begin_under_the_headless_unattended_land_prints_its_two_arms(repo):
    """Run as the night runs it (Phase 423): `begin` admits the flags and prints both arms."""
    (repo / "CLAUDE.md").write_text("# p\n\n## Merge policy\n\npr\n", encoding="utf-8")
    p = run("begin", f"--land {RUN} --agent bot --unattended --headless", *sorted(close_arms.ARMS),
            cwd=repo)
    assert p.returncode == 0, p.stderr
    assert "ARM: request-review-land" in p.stdout and "ARM: 4d-pr" in p.stdout, p.stdout


@pytest.mark.parametrize("words,why", [
    ("--dryrun", "not a /review-close flag"), ("--land", "takes a value"),
    ("--land --unattended --agent a", "takes a value"), (f"--resume {RUN[:-1]}", "takes a value"),
    ("--prepare --agent --unattended", "takes a value"), (f"--resume {RUN} --resume {RUN}", "twice"),
    ("--dry-run --dry-run", "twice"), ("dry-run", "not a /review-close flag"),
    (f"--land {RUN} extra", "not a /review-close flag"), ('--request-review --agent "x"', "is not one: an agent name"),
    # Phase 393's round (lens B): each shape is a whole match, in ASCII digits, as close_run.py's.
    (f"--land {RUN}x", "takes a value"), ("--land not-a-run-id", "takes a value"),
    (f"--resume {'x' * 21}", "takes a value"), ("--resume ٢٠٢٦١٠١٩T٠١٠٢٠٣Z-abcd", "takes a value"),
    ("--request-review --agent " + "a" * 65, "is not one: an agent name"),
])
def test_begin_refuses_flags_it_cannot_read_and_creates_nothing(repo, words, why):
    p = run("begin", words, *sorted(close_arms.ARMS), cwd=repo)
    assert p.returncode == 2 and why in p.stderr and p.stdout == "", (words, p.stderr)
    assert not (repo / "sysop").exists()


@pytest.mark.parametrize("flags", sorted(close_arms.FLAG_SETS, key=sorted), ids=lambda f: " ".join(sorted(f)) or "plain")
def test_begin_makes_the_flag_arms_due_and_prints_them(repo, flags):
    (repo / "CLAUDE.md").write_text("## Merge policy\n\npr\n")
    p = run("begin", _flag_words(sorted(flags)), *sorted(close_arms.ARMS), cwd=repo)
    assert p.returncode == 0, p.stderr
    lines = p.stdout.splitlines()
    want = list(dict.fromkeys(a for f, a in close_arms.FLAG_ARMS if f in flags))
    assert lines[1:] == [f"ARM: {a}" for a in want or ["none"]], lines
    recs = receipt(repo, lines[0].split()[1]).read_text().splitlines()
    assert [r.split("\t")[1] for r in recs if r.startswith("required")] == want


def test_the_flag_arms_by_flag():
    """Spelled out once, so a row cannot move in `FLAG_ARMS` unseen."""
    assert close_arms.FLAG_ARMS == (
        ("--prepare", "prepare-resume"), ("--resume", "prepare-resume"),
        ("--request-review", "request-review-land"), ("--land", "request-review-land"),
        ("--land", "4d-pr"))


@pytest.mark.parametrize("words", ["--request-review", f"--land {RUN}",
                                   f"--resume {RUN} --request-review", "--request-review --agent a",
                                   "--prepare --agent a"])
def test_request_review_land_and_agent_need_the_pr_policy(repo, words):
    """Round 1 (lens A): `--prepare --agent`'s own `pr` check was left in the arm, after `loaded`."""
    p = run("begin", words, *sorted(close_arms.ARMS), cwd=repo)
    assert p.returncode == 2 and "need `## Merge policy` `pr`" in p.stderr, p.stderr
    (repo / "CLAUDE.md").write_text("## Merge policy\n\ndirect\n")
    p = run("begin", words, *sorted(close_arms.ARMS), cwd=repo)
    assert p.returncode == 2 and "it reads direct" in p.stderr
    assert not (repo / "sysop").exists()
    (repo / "CLAUDE.md").write_text("## Merge policy\n\npr\n")
    assert run("begin", words, *sorted(close_arms.ARMS), cwd=repo).returncode == 0


def test_a_land_that_loads_neither_arm_is_named_twice(repo):
    (repo / "CLAUDE.md").write_text("## Merge policy\n\npr\n")
    cid = begin(repo, f"--land {RUN}")
    p = run("check", cid, cwd=repo)
    assert p.returncode == 1
    assert p.stdout.splitlines() == ["ARMS: required 2, loaded 0",
                                     "ARM NOT LOADED: request-review-land", "ARM NOT LOADED: 4d-pr"]
    cid = begin(repo, f"--land {RUN}")
    for arm in ("request-review-land", "4d-pr"):
        text = (CLOSE_DIR / "steps" / f"{arm}.md").read_text(encoding="utf-8")
        assert load(cid, repo, close_arms.digest_of(text), arm=arm).returncode == 0
    assert run("check", cid, cwd=repo).returncode == 0


@pytest.mark.parametrize("step", sorted((CLOSE_DIR / "steps").glob("*.md")), ids=lambda p: p.stem)
def test_no_step_file_reads_the_arguments(step):
    """Spec § 9 item 11: Claude Code substitutes `$ARGUMENTS` into `SKILL.md` only, so a step
    file that tests it tests the literal word. A flag arm reads the flags `begin` was given."""
    assert "ARGUMENTS" not in step.read_text(encoding="utf-8")


def test_the_flag_sections_are_stubs_behind_begin():
    """`begin` sits after the second-reader check, so a stop there leaves no receipt naming a
    flag arm, and before both flag sections, which hold only their stubs."""
    core = CLOSE_CORE.read_text(encoding="utf-8")
    waiting = core.index("## A close waiting for its second reader")
    opens = core.index("## Open the close's arm receipt")
    pr = core.index("## `--prepare` and `--resume <run-id>`")
    rl = core.index("## `--request-review` and `--land <run-id>`")
    s1 = core.index("## Step 1: Gather State")
    assert waiting < opens < pr < rl < s1
    assert core[opens:pr].count("close_arms.py begin ") == 1
    # Round 1 (lens A): a combined mode is split across two arms, and each opens with a stop,
    # so every printed arm is loaded before any is followed; `--land`'s `4d-pr` with them.
    assert "**Load every arm it printed before you act on any of them:**" in core[opens:pr]
    assert "load `${CLAUDE_SKILL_DIR}/steps/4d-pr.md` with the arm below" in core[rl:s1]
    for a, b in ((pr, rl), (rl, s1)):
        assert "### " not in core[a:b] and core[a:b].count("```") == 0, core[a:b][:200]
    assert "`ARM: 4d-pr`" in core[rl:s1] and "${CLAUDE_SKILL_DIR}/steps/4d-pr.md" in core[rl:s1]


# ── the merge-policy read ───────────────────────────────────────────────────────────────

#: `(CLAUDE.md, what the one reader returns)`: `""` is a refusal. Since Phase 388's round 2 this is
#: the only reader (`close_batch.sh` calls `close_arms.py read-policy`); two rounds had found its
#: `awk` twin disagreeing on inputs no list held.
POLICY_CASES = [
    (None, "direct"),
    ("# x\n", "direct"),
    ("## Merge policy\n\npr\n", "pr"),
    ("## Merge policy\n\nPR\n", "pr"),
    ("## Merge policy   \n\n   direct   trailing\n", "direct"),
    ("## Merge policy\r\n\r\npr\r\n", "pr"),
    ("## Merge policy\r\rpr\r", "pr"),
    ("```markdown\n## Merge policy\n\npr\n```\n", "direct"),
    ("~~~\n## Merge policy\n\npr\n~~~\n\n## Merge policy\n\ndirect\n", "direct"),
    ("## Merge policy\n\n```\npr\n```\n\ndirect\n", "direct"),
    ("## Merge policy\n", "direct"),
    ("## Merge policy\n\n## Next\n", "direct"),
    ("  ```\n## Merge policy\n\npr\n  ```\n", "direct"),
    ("\t~~~\n## Merge policy\n\npr\n\t~~~\n## Merge policy\n\ndirect\n", "direct"),
    # A consumer's real section (Phase 388): the word in backticks, then prose.
    ("## Merge policy\n\n`pr`\n\nThis project merges through squash PRs.\n", "pr"),
    ("## Merge policy\n\n**direct**\n", "direct"),
    ("## Merge policy\n\n`PR`\n", "pr"),
    ("## Merge policy\n\n__pr__\n", "pr"),
    ("# Notes\nCaf\xe9 r\xe9sum\xe9\n\n## Merge policy\n\npr\n", "pr"),
    # Round 2 (lens D) found an unrelated heading refused; the narrowing that accepted it let
    # round 3 (lens E) find `## Merge policy — pr` read as no section, so `direct`. Every
    # heading that starts with the words is refused, and the message says to rename one.
    ("### Merge policy history\n\nold\n\n## Merge policy\n\npr\n", ""),
    ("# Merge policy and branching\n\n## Merge policy\n\npr\n", ""),
    ("## Merge policy notes\n\npr\n", ""),
    ("## Merge policy — pr\n\npr\n", ""),
    ("## Merge policy - pr\n\npr\n", ""),
    ("## Merge policy pr\n\npr\n", ""),
    ("## Merge policy = pr\n\npr\n", ""),
    ("## Merge policy `pr`\n\npr\n", ""),
    ("## Merge policy [pr]\n\npr\n", ""),
    # Refused: a word that is not one of the two, and the heading written another way.
    ("## Merge policy\n\nsquash\n", ""),
    ("## Merge policy\n\npr.\n", ""),
    ("## Merge policy\n\n<!-- pr -->\npr\n", ""),
    ("## Merge policy: pr\n", ""),
    ("## Merge Policy\n\npr\n", ""),
    ("### Merge policy\n\npr\n", ""),
    ("## Merge policy (pr)\n\npr\n", ""),
    ("## Merge policy ##\n\npr\n", ""),
    ("## Merge policy\n\n\u00a0pr\n", ""),
    ("## Merge policy\n\npr\u00a0\n", ""),
    ("## Merge policy\n\f\npr\n", ""),
    ("## Merge policy\n\npr\x00x\n", ""),
]


def test_the_policy_cases_cannot_lose_a_row_unseen():
    """Round 2 (lens D): a row deleted from the list left the module green."""
    import hashlib
    got = hashlib.sha256(repr(POLICY_CASES).encode()).hexdigest()[:16]
    assert got == "eb608e9078fc6fc0", f"POLICY_CASES changed: re-pin {got} on purpose"


@pytest.mark.parametrize("text,want", POLICY_CASES)
def test_the_policy_read(tmp_path, text, want):
    if text is not None:
        (tmp_path / "CLAUDE.md").write_bytes(text.encode("latin-1") if "\xe9" in text else text.encode())
    policy, why = close_arms.read_policy(tmp_path)
    assert policy == want, (text, why)
    p = run("read-policy", str(tmp_path), cwd=tmp_path)
    assert (p.returncode, p.stdout.strip()) == ((0, want) if want else (2, "")), (text, p.stderr)


def test_the_refusal_says_to_rename_an_unrelated_heading(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("### Merge policy history\n\nold\n")
    _, why = close_arms.read_policy(tmp_path)
    assert "### Merge policy history" in why and "rename" in why and "exactly `## Merge policy`" in why


def test_a_receipt_removed_mid_read_is_skipped_by_both_readers(repo, monkeypatch):
    """Round 3 (lens E): a Step 8 `check` or a prune can unlink a receipt between the age
    check and the read; it is gone, not unreadable."""
    import sitrep_survey
    d = repo / "sysop" / "runtime" / "close-arms"
    d.mkdir(parents=True)
    f = d / "20261001T000000Z-eeee.tsv"
    f.write_text("begin\tx\nchecked\tx\tok\n")
    os.utime(f, (time.time() - 25 * 3600,) * 2)
    real = Path.read_text

    def vanish(self, *a, **k):
        if self.suffix == ".tsv":
            self.unlink(missing_ok=True)
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", vanish)
    kinds = [x.kind for x in sitrep_survey._find_discrepancies([], [], {}, repo)]
    assert "review-close arm receipt unreadable" not in kinds
    f.write_text("begin\tx\n")
    os.utime(f, (time.time() - 25 * 3600,) * 2)
    monkeypatch.chdir(repo)
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert close_arms.cmd_unchecked([]) == 0
    assert buf.getvalue() == ""


def test_close_batch_reads_the_policy_through_close_arms():
    """One reader: `close_batch.sh` holds no copy of the read (Phase 388, round 2)."""
    src = CLOSE_BATCH.read_text()
    m = re.search(r"^_read_merge_policy\(\) \{\n.*?^\}\n", src, re.M | re.S)
    assert m, "close_batch.sh no longer defines _read_merge_policy"
    assert 'python3 "$here/close_arms.py" read-policy "$REPO_ROOT"' in m.group(0)
    assert "awk " not in m.group(0) and "awk '" not in m.group(0), "a second reader is back"


# ── the step files ──────────────────────────────────────────────────────────────────────

def _markers(skill_dir: Path) -> list[str]:
    lines = (skill_dir / "SKILL.md").read_text(encoding="utf-8").split("\n")
    return [m.group(1) for i, fenced in _fence_state(lines)
            if not fenced and (m := MARKER.match(lines[i]))]


SKILL_DIRS = sorted(p.parent for p in SKILLS.glob("*/SKILL.md"))


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda d: d.name)
def test_markers_and_step_files_match_one_to_one(skill_dir):
    marks = _markers(skill_dir)
    assert len(marks) == len(set(marks)), f"{skill_dir.name}: an arm is marked twice: {marks}"
    files = {p.relative_to(skill_dir / "steps").with_suffix("").as_posix()
             for p in step_files(skill_dir) if (skill_dir / "steps") in p.parents}
    others = [p for p in step_files(skill_dir) if (skill_dir / "steps") not in p.parents]
    assert not others, f"{skill_dir.name}: runner text outside steps/: {others}"
    assert set(marks) == files, (
        f"{skill_dir.name}: markers {sorted(marks)} and step files {sorted(files)} differ. A "
        "step file no marker names is text the runner cannot reach")


def test_the_marker_resolve_check_is_not_vacuous(tmp_path):
    d = tmp_path / "s"
    (d / "steps").mkdir(parents=True)
    (d / "SKILL.md").write_text("# s\n\n<!-- sysop:arm=a -->\n\n```\n<!-- sysop:arm=b -->\n```\n")
    (d / "steps" / "a.md").write_text("A\n")
    assert _markers(d) == ["a"], "a fenced marker is an example, not an arm"
    (d / "steps" / "c.md").write_text("C\n")
    with pytest.raises(AssertionError, match="differ"):
        test_markers_and_step_files_match_one_to_one(d)


def _arm_files():
    return [p for d in SKILL_DIRS for p in step_files(d) if (d / "steps") in p.parents]


#: Every arm a command can make due: `arm`'s table, the arms `conflicts` and `notes` record,
#: the flag arms `begin` records, and the arms `exited` records.
REQUIRABLE = ({a for arms in close_arms.ARM_FOR.values() for a in arms} | {close_arms.CONFLICT_ARM, close_arms.NOTES_ARM,
                                                   close_arms.POLICY_ARM}
              | {arm for _, arm in close_arms.FLAG_ARMS} | close_arms.EXIT_ARMS)


def test_review_close_has_its_arms():
    assert [p.name for p in _arm_files()] == [
        "2a-ignored-refs.md", "2b-large-diff.md", "2b-leak.md", "2b-no-conventions.md",
        "2b-twin-spawn.md", "3b-collect-exit.md", "3b-rollback.md", "3c-signals.md", "4-pre-pr.md",
        "4a-append.md", "4a-fix.md", "4a-post-failure.md", "4a-post-prescan.md",
        "4a-published.md", "4b-batches.md",
        "4c-check-exit.md", "4c-unmerged.md", "4d-direct.md", "4d-pr.md", "6-direct.md",
        "6-pr-cleanup.md", "6-pr-gate.md", "prepare-resume.md", "request-review-land.md"]
    assert set(close_arms.ARMS) == {"2a-ignored-refs", "2b-large-diff", "2b-leak", "2b-no-conventions", "2b-twin-spawn",
                                    "3b-collect-exit", "3b-rollback", "3c-signals", "4-pre-pr",
                                    "4a-append",
                                    "4a-fix", "4a-post-failure", "4a-post-prescan",
                                    "4a-published", "4b-batches",
                                    "4c-check-exit",
                                    "4c-unmerged",
                                    "4d-direct", "4d-pr",
                                    "6-direct", "6-pr-cleanup", "6-pr-gate",
                                    "prepare-resume", "request-review-land"}


@pytest.mark.parametrize("step", _arm_files(), ids=lambda p: p.stem)
def test_a_step_files_first_command_is_its_loaded_line_with_its_own_digest(step):
    text = step.read_text(encoding="utf-8")
    lines = text.split("\n")
    at = next(i for i, ln in enumerate(lines) if re.match(r"[ \t]*(```|~~~)", ln))  # any tag
    # An arm cut from inside a list item keeps its indentation (Phase 397), so its loaded
    # block carries the same: the line is the fence's indentation and the command, exactly.
    indent = lines[at][:len(lines[at]) - len(lines[at].lstrip(" \t"))]
    first = lines[at + 1]
    want = (f'{indent}python3 sysop/scripts/close_arms.py loaded "<close-id>" {step.stem} '
            f'{close_arms.digest_of(text)} "<skill directory>"')
    assert first == want, (
        f"{step.name}'s first command is {first!r}, not {want!r}. After an edit, the digest "
        f"is `python3 tools/runner_core_split/arm_digest.py {step.relative_to(REPO)}`")
    assert step.stem in close_arms.ARMS
    assert sum(1 for ln in lines if close_arms.LOADED_LINE.search(ln)) == 1


@pytest.mark.parametrize("step", _arm_files(), ids=lambda p: p.stem)
def test_no_step_file_names_the_skill_directory_variable(step):
    """Phase 388's round 2 (lens C, HIGH): Claude Code substitutes `${CLAUDE_SKILL_DIR}` into
    `SKILL.md` only, not into a file the runner opens with Read (measured with `claude -p`), so
    in a step file it reaches the shell unset and the `loaded` line ran with an empty path.
    `ENV_PROVIDED` exempts the name tree-wide, which is why no other guard saw it."""
    assert "CLAUDE_SKILL_DIR" not in step.read_text(encoding="utf-8")


def test_the_digest_sees_an_edit_anywhere_but_the_loaded_line():
    text = (CLOSE_DIR / "steps" / "4d-direct.md").read_text(encoding="utf-8")
    d = close_arms.digest_of(text)
    assert close_arms.digest_of(text.replace("never `--force`", "never --force")) != d
    assert close_arms.digest_of(text.replace(d, "f" * 16)) == d


@pytest.mark.parametrize("step", _arm_files(), ids=lambda p: p.stem)
def test_each_stub_names_its_trigger_and_a_command_records_it(step):
    """§ 5.3: a stub names its trigger, and only an arm a command makes due may move."""
    core = CLOSE_CORE.read_text(encoding="utf-8").split("\n")
    at = core.index(f"<!-- sysop:arm={step.stem} -->")
    assert core[at - 1] == "", "the stub is the paragraph just above the marker"
    # The whole paragraph, whitespace-normalized: a re-wrap is an ordinary edit (Phase 397's
    # battery, C02, false-killed the line-keyed read).
    start = at - 2
    while start > 0 and core[start - 1].strip():
        start -= 1
    stub = " ".join(" ".join(core[start:at - 1]).split())
    assert stub, "no stub paragraph above the marker"
    assert f"`ARM: {step.stem}`" in stub, stub
    assert f"${{CLAUDE_SKILL_DIR}}/steps/{step.name}" in stub, stub
    assert "says `<skill directory>`, write `${CLAUDE_SKILL_DIR}`" in stub, stub
    assert step.stem in REQUIRABLE


def test_every_arm_the_script_can_require_has_a_step_file():
    assert REQUIRABLE == set(close_arms.ARMS)
    assert {p.stem for p in _arm_files()} == set(close_arms.ARMS)


def test_step_4c_unmerged_stub_loads_on_no_count_too():
    """Phase 403's battery (S07): `rev-list` prints nothing for a ref that does not resolve, and
    a stub that names only a non-zero count reads that as merged and routes the doc."""
    text = text_of(CLOSE_CORE)
    stub = text[:text.index('exited "<close-id>" 4c-unmerged 1\n')]
    end = stub.rindex("\n\n", 0, stub.rindex("```bash"))
    stub = " ".join(stub[stub.rindex("\n\n", 0, end):end].split())
    # The stub's own paragraph: anywhere else (the arm it loads, say) is read only after the
    # stub has sent the doc there (its round, lens B).
    assert stub.startswith("**On a count other than `0`, or no count at all** (a ref that does not "
                           "resolve prints none), the doc goes to the arm below"), stub


def test_the_allow_rule_names_every_step_that_runs_exited():
    """Phase 403's battery (S09): the rule's command list could drop a step unseen."""
    rule = next(ln for ln in text_of(CLOSE_CORE).split("\n")
                if ln.startswith("- `Bash(python3 sysop/scripts/close_arms.py:*)`"))
    # Each step in a clause that ends at `exited`, however the list is worded (its round, lens B).
    clauses = " ".join(re.findall(r"([^,;]*)`exited`", rule))
    # Phase 419: `4a-post-failure` is Step 4a-post's, not Step 4a's (Phase 429's
    # `4a-published` is Step 4a's).
    for step in sorted({"4a-post" if arm.startswith("4a-post-") else arm.split("-")[0]
                        for arm in close_arms.EXIT_ARMS}):
        assert f"{step}'s" in clauses, (step, rule)


def test_every_step_file_names_its_own_loaded_line_and_its_stop():
    """The header's `LOADED:` line and its Exit 2 stop were unchecked text in every arm (Phase
    403's round, lens B): a header naming another arm, or without the stop, walked every guard."""
    for step in _arm_files():
        text = step.read_text(encoding="utf-8")
        line = next(ln for ln in text.split("\n") if "It prints `LOADED:" in ln)
        assert line.strip() == f"It prints `LOADED: {step.stem}`. **Exit 2**: stop and show its stderr.", (step.name, line)
        assert text.index(line) == text.index("\n\n", text.index(f'loaded "<close-id>" {step.stem} ')) + 2, step.name


def test_the_close_runs_each_receipt_command():
    text = text_of(CLOSE_CORE)
    for cmd in ('python3 sysop/scripts/close_arms.py begin "<flags>" 2a-ignored-refs 2b-large-diff '
                '2b-leak 2b-no-conventions 2b-twin-spawn 3b-collect-exit 3b-rollback 3c-signals '
                '4-pre-pr 4a-append 4a-fix 4a-post-failure 4a-post-prescan 4a-published 4b-batches '
                '4c-check-exit '
                '4c-unmerged 4d-direct '
                '4d-pr 6-direct '
                '6-pr-cleanup 6-pr-gate prepare-resume request-review-land\n',
                'python3 sysop/scripts/close_arms.py policy "<close-id>"\n',
                'python3 sysop/scripts/close_arms.py conflicts "<close-id>"\n',
                'python3 sysop/scripts/close_arms.py notes "<close-id>" <count>\n',
                # Phase 430 (P5): Step 2a step 3a's check, with its exit code.
                'python3 sysop/scripts/close_arms.py exited "<close-id>" 2a-ignored-refs <code>\n',
                # Phase 406: Step 2b's four, each a printed value passed on as a literal `1`.
                'python3 sysop/scripts/close_arms.py exited "<close-id>" 2b-no-conventions 1\n',
                'python3 sysop/scripts/close_arms.py exited "<close-id>" 2b-large-diff 1\n',
                'python3 sysop/scripts/close_arms.py exited "<close-id>" 2b-twin-spawn 1\n',
                'python3 sysop/scripts/close_arms.py exited "<close-id>" 2b-leak 1\n',
                'python3 sysop/scripts/close_arms.py exited "<close-id>" 3b-collect-exit <code>\n',
                'python3 sysop/scripts/close_arms.py exited "<close-id>" 3b-rollback <code>\n',
                # Phase 419 (P5): a gate command's failure, passed on as a literal `1`.
                'python3 sysop/scripts/close_arms.py exited "<close-id>" 4a-post-failure 1\n',
                # Phase 430 (P5): the pre-scan's non-zero exit or absent script, as a literal `1`.
                'python3 sysop/scripts/close_arms.py exited "<close-id>" 4a-post-prescan 1\n',
                # Phase 429 (P5): item 1's `published` exiting 0, passed on as a literal `1`.
                'python3 sysop/scripts/close_arms.py exited "<close-id>" 4a-published 1\n',
                # Phase 418 (P5): `--merged` printing a row, passed on as a literal `1`.
                'python3 sysop/scripts/close_arms.py exited "<close-id>" 4b-batches 1\n',
                # Phase 403: a literal `1`, so the runner never writes the count itself.
                'python3 sysop/scripts/close_arms.py exited "<close-id>" 4c-unmerged 1\n',
                'python3 sysop/scripts/close_arms.py exited "<close-id>" 4c-check-exit <code>\n',
                'python3 sysop/scripts/close_arms.py arm "<close-id>" 4d\n',
                # Phase 416 (P5): Step 6's own `arm`, run only when Step 6 runs.
                'python3 sysop/scripts/close_arms.py arm "<close-id>" 6\n',
                'python3 sysop/scripts/close_arms.py check "<close-id>" "${CLAUDE_SKILL_DIR}"\n'):
        assert text.count(cmd) == 1, cmd
    # Phase 411 (P5): Step 3c's signal arm, made due by the core's stub on `SMOKE_REQUIRED` and
    # by the resume before it applies a Step 3c answer (Wade, 2026-10-22): one each.
    cmd = 'python3 sysop/scripts/close_arms.py exited "<close-id>" 3c-signals 1\n'
    assert text.count(cmd) == 2, text.count(cmd)
    resume = (CLOSE_CORE.parent / "steps" / "prepare-resume.md").read_text(encoding="utf-8")
    assert resume.count("   " + cmd) == 1
    assert text.index("5. **Apply each answer `answers.md` does not mark `applied`**") \
        < text.index("   " + cmd) < text.index("   **Every answer given live, in this item or item 6")
    # Phase 430 (P5): Step 2a step 3a's arm, made due the same way by the resume before it
    # applies a recorded Step 2a step 3a answer; the core's own trigger passes the exit code.
    cmd2a = 'python3 sysop/scripts/close_arms.py exited "<close-id>" 2a-ignored-refs 1\n'
    assert text.count(cmd2a) == 1 and resume.count("   " + cmd2a) == 1
    assert text.index("5. **Apply each answer `answers.md` does not mark `applied`**") \
        < text.index("   " + cmd2a) < text.index("   " + cmd)
    order = [text.index(s) for s in (
        "## A close waiting for its second reader", "## Open the close's arm receipt",
        'close_arms.py begin "<flags>" ', "## `--prepare` and `--resume <run-id>`",
        'close_arms.py loaded "<close-id>" prepare-resume ', "## `--request-review` and `--land",
        'close_arms.py loaded "<close-id>" request-review-land ', "## Step 1: Gather State",
        "### 1-pre.",
        # Phase 430 (P5): Step 2a step 3a's check, its stub's trigger, the arm, then step 4.
        "3a. **Gitignored files the branch reads", "python3 sysop/scripts/ignored_refs.py ",
        'close_arms.py exited "<close-id>" 2a-ignored-refs <code>\n',
        'close_arms.py loaded "<close-id>" 2a-ignored-refs ', "**Exit 1**: ask about each `IGNORED-REF:` line",
        "**Exit 3, or any other exit**, from the check", "4. Verdict: **approve**",
        "### 2b. Prevention Convention Check",
        'close_arms.py exited "<close-id>" 2b-no-conventions 1\n',
        'close_arms.py loaded "<close-id>" 2b-no-conventions ', "   **At or below 10,000, paste it",
        'close_arms.py exited "<close-id>" 2b-large-diff 1\n',
        'close_arms.py loaded "<close-id>" 2b-large-diff ', "   > **Why a threshold and not a rule",
        "2. **Capture the primary-tree baseline", "**Gate and copy",
        'close_arms.py exited "<close-id>" 2b-twin-spawn 1\n',
        'close_arms.py loaded "<close-id>" 2b-twin-spawn ', "Spawn one Agent per surviving target",
        "   **Under `--prepare`, a `VERDICT: BLOCKED` in item 4", "> **HARD RULE",
        'close_arms.py exited "<close-id>" 2b-leak 1\n',
        'close_arms.py loaded "<close-id>" 2b-leak ', "> **If your harness offers no `isolation`",
        # A line start: the HARD RULE above names this heading in its own text (Phase 406).
        "### 2c. Unpushed Main Commits",
        # Phase 411 (P5): the core's own line, at column 0; the resume's copy is indented and
        # sits earlier, in the flag section.
        "## Step 3c: Manual Smoke Gate", "**Which task bodies are read, and which indexes.**",
        '\npython3 sysop/scripts/close_arms.py exited "<close-id>" 3c-signals 1\n',
        'close_arms.py loaded "<close-id>" 3c-signals ', "**2. For each signal, call `AskUserQuestion`.**",
        "> **For new projects:** declare `manual_smoke: true`", "\n## Step 3b: Prepare Worktrees for Merge",
        'close_arms.py exited "<close-id>" 3b-collect-exit <code>\n',
        'close_arms.py loaded "<close-id>" 3b-collect-exit ', " - b. **ONLY WHEN `SHAPE=worktree`**",
        'close_arms.py exited "<close-id>" 3b-rollback <code>\n',
        'close_arms.py loaded "<close-id>" 3b-rollback ', "**2. Remove the workspace",
        "### 4-pre.",
        # Phase 415 (P5): the `pr` shapes load after `policy`, and the branch guard after them.
        'close_arms.py policy "<close-id>"\n', 'close_arms.py loaded "<close-id>" 4-pre-pr ',
        "**PR-reuse probe (run first).**", "> **HARD RULE — branch guard.**", "### 4a.",
        # Phase 429 (P5): the published stub's trigger, the arm (its merge, then item 3), the
        # core's one-line item 3, then item 4's conflict routing.
        "**Local-only**", 'close_arms.py exited "<close-id>" 4a-published 1\n',
        'close_arms.py loaded "<close-id>" 4a-published ', "**Published** — **do not rebase it at all.**",
        "3. **Under the `pr` policy, a published branch's own PR", "3. **A published branch's own PR** is",
        'close_arms.py conflicts "<close-id>"\n',
        'close_arms.py loaded "<close-id>" 4a-append ', "### 4a-fix.",
        'close_arms.py notes "<close-id>" <count>\n', 'close_arms.py loaded "<close-id>" 4a-fix ',
        # Phase 419 (P5): item 4's lead, the stub's trigger, the arm, then the stop that stays.
        "### 4a-post. Verify the Merged Tree",
        # Phase 430 (P5): 3a's Exit 0 arm stays; the stub, then the arm, then de-duplication.
        "**Exit 0** — **not automatically clean", 'close_arms.py exited "<close-id>" 4a-post-prescan 1\n',
        'close_arms.py loaded "<close-id>" 4a-post-prescan ', "**Non-zero** — read the accounting header",
        "**The script is absent**", "**De-duplication — does any resolved command REACH",
        "4. **On failure, stop",
        'close_arms.py exited "<close-id>" 4a-post-failure 1\n',
        'close_arms.py loaded "<close-id>" 4a-post-failure ',
        "   **If `4a-fix` kept a fix commit, test it before anything below**",
        '   **On "Proceed"**, report `PRE-EXISTING:', "   **On every other failure, stop.**",
        "5. **Confirm the gate left the tree clean**",
        # Phase 418 (P5): the set's reader, the empty arm, then the arm the stub makes due,
        # and the rule after it that stays in the core.
        "### 4b. Close Merged Batches", "python3 sysop/scripts/review_index.py --list --merged ",
        "4b: no review batches this cycle", 'close_arms.py exited "<close-id>" 4b-batches 1\n',
        'close_arms.py loaded "<close-id>" 4b-batches ', "\nWith a non-empty set:\n",
        "**Do NOT remove completed batches**",
        "### 4c. Consolidate Pending Documentation", "1b. **Drop any pending-doc",
        'close_arms.py exited "<close-id>" 4c-unmerged 1\n',
        'close_arms.py loaded "<close-id>" 4c-unmerged ', "   > **Quote the `^` operand.",
        "1c. **Hold back any pending-doc", "5. **Check what the writes above did",
        'close_arms.py exited "<close-id>" 4c-check-exit <code>\n',
        'close_arms.py loaded "<close-id>" 4c-check-exit ', "6. **Clean up pending-docs**",
        "### 4d.", 'close_arms.py arm "<close-id>" 4d\n', 'close_arms.py loaded "<close-id>" 4d-direct ',
        "#### `pr` policy", 'close_arms.py loaded "<close-id>" 4d-pr ',
        "## Step 5: Verify Staging Deployment",
        # Phase 416 (P5): Step 6's `arm` after the policy gate, then its three arms in place,
        # the HARD RULE before both cleanup lists.
        "## Step 6: Clean Up", "**Merge-policy gate (Step 4-pre).**",
        'close_arms.py arm "<close-id>" 6\n', 'close_arms.py loaded "<close-id>" 6-pr-gate ',
        "  **Then check for commits made after Step 4d's push**", "> **Lock-as-real-time-signal",
        "**HARD RULE — do not delete a branch whose pending-doc",
        'close_arms.py loaded "<close-id>" 6-direct ', "**Why this order matters (BeanRider ISSUE-0021).**",
        'close_arms.py loaded "<close-id>" 6-pr-cleanup ', "**Under the PR-reuse shape both of the above",
        "For each **SKIP'd** branch", "## Step 7: Friction Capture",
        "## Step 8: Report", 'close_arms.py check "<close-id>"')]
    assert order == sorted(order), "the receipt commands are out of step order"


# ── Step 4a's arms: `conflicts` and `notes` (Phase 390) ────────────────────────────────

def _git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                           *args], capture_output=True, text=True, env=GIT_ENV, check=check)


def _conflict(repo, path, how="merge"):
    """Two branches change `path` differently; merge (or rebase) one onto the other."""
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    f.write_text("feature\n")
    _git(repo, "commit", "-q", "-am", "feature")
    _git(repo, "checkout", "-q", "main")
    f.write_text("main\n")
    _git(repo, "commit", "-q", "-am", "main")
    if how == "merge":
        assert _git(repo, "merge", "--no-ff", "-m", "m", "feature", check=False).returncode != 0
    else:
        _git(repo, "checkout", "-q", "feature")
        assert _git(repo, "rebase", "main", check=False).returncode != 0


# `tasks/open/é "q".md` is a name git quotes without `-z` (lens B, Phase 390).
@pytest.mark.parametrize("path", ["tasks/index.yml", "review_tasks.md", "tasks/notes.md",
                                  "tasks/open/T-1 a.md", 'tasks/open/é "q".md'])
@pytest.mark.parametrize("how", ["merge", "rebase"])
def test_a_shared_append_conflict_makes_4a_append_due(repo, path, how):
    cid = begin(repo)
    _conflict(repo, path, how)
    p = run("conflicts", cid, cwd=repo)
    assert p.returncode == 0, p.stderr
    assert p.stdout == f"CONFLICTED: {path}\nARM: 4a-append\n"
    assert run("check", cid, cwd=repo).stdout.splitlines()[1] == "ARM NOT LOADED: 4a-append"


def test_a_code_conflict_beside_a_shared_one_makes_the_arm_due(repo):
    """Lens B (Phase 390): every conflict test had one path, so `any` -> `all` and
    first-path-only both passed the suite. `src/a.py` sorts first."""
    cid = begin(repo)
    for f in ("src/a.py", "tasks/index.yml"):
        (repo / f).parent.mkdir(parents=True, exist_ok=True)
        (repo / f).write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    for f in ("src/a.py", "tasks/index.yml"):
        (repo / f).write_text("feature\n")
    _git(repo, "commit", "-q", "-am", "feature")
    _git(repo, "checkout", "-q", "main")
    for f in ("src/a.py", "tasks/index.yml"):
        (repo / f).write_text("main\n")
    _git(repo, "commit", "-q", "-am", "main")
    assert _git(repo, "merge", "--no-ff", "-m", "m", "feature", check=False).returncode != 0
    p = run("conflicts", cid, cwd=repo)
    assert p.stdout == "CONFLICTED: src/a.py\nCONFLICTED: tasks/index.yml\nARM: 4a-append\n", p


def test_a_code_conflict_makes_no_arm_due(repo):
    cid = begin(repo)
    _conflict(repo, "src/a.py")
    p = run("conflicts", cid, cwd=repo)
    assert p.returncode == 0 and p.stdout == "CONFLICTED: src/a.py\nARM: none\n", p.stderr
    assert run("check", cid, cwd=repo).stdout == "ARMS: required 0, loaded 0\n"


def test_a_dirty_file_that_did_not_conflict_is_not_a_conflict(repo):
    """A modified task body beside a code conflict is not unmerged, so it makes no arm due:
    the read is git's unmerged set, not every path that differs."""
    body = repo / "tasks" / "open" / "T-2.md"
    body.parent.mkdir(parents=True)
    body.write_text("one\n")
    cid = begin(repo)
    _conflict(repo, "src/a.py")
    body.write_text("two\n")
    p = run("conflicts", cid, cwd=repo)
    assert p.returncode == 0 and p.stdout == "CONFLICTED: src/a.py\nARM: none\n", p.stdout


def test_a_path_that_is_not_utf8_is_reported_and_still_decides(repo):
    """Lens A (Phase 390): printing a surrogate-escaped name crashed the report with exit 1
    before the decision. Unmerged index entries for a non-UTF-8 task body and a code file."""
    cid = begin(repo)
    blob = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"], input=b"x\n",
                          capture_output=True, env=GIT_ENV, check=True).stdout.strip()
    info = b"".join(b"100644 " + blob + b" %d\t" % s + path + b"\n"
                    for path in (b"tasks/\xff.md", b"src/x.py") for s in (1, 2, 3))
    subprocess.run(["git", "-C", str(repo), "update-index", "--index-info"], input=info,
                   env=GIT_ENV, check=True)
    p = subprocess.run([sys.executable, str(SCRIPT), "conflicts", cid], cwd=repo,
                       capture_output=True, env=GIT_ENV)
    assert p.returncode == 0, p.stderr
    assert p.stdout == b"CONFLICTED: src/x.py\nCONFLICTED: tasks/\xff.md\nARM: 4a-append\n"
    assert "required\t4a-append" in receipt(repo, cid).read_text()


def test_diff_relative_does_not_hide_a_shared_conflict(repo):
    cid = begin(repo)
    (repo / "src").mkdir()
    (repo / "src" / "keep.py").write_text("k\n")
    _conflict(repo, "tasks/index.yml")
    _git(repo, "config", "diff.relative", "true")
    p = run("conflicts", cid, cwd=repo / "src")
    assert p.returncode == 0 and p.stdout == "CONFLICTED: tasks/index.yml\nARM: 4a-append\n", p.stdout


def test_conflicts_refuses_when_git_cannot_list_and_records_nothing(repo):
    cid = begin(repo)
    before = receipt(repo, cid).read_text()
    (repo / ".git" / "index").write_bytes(b"not an index")
    p = run("conflicts", cid, cwd=repo)
    assert p.returncode == 2 and "could not list the unmerged paths" in p.stderr, p
    assert p.stdout == "" and receipt(repo, cid).read_text() == before


def test_conflicts_with_nothing_unmerged_says_so(repo):
    cid = begin(repo)
    p = run("conflicts", cid, cwd=repo)
    assert p.returncode == 0 and p.stdout == "CONFLICTED: none\nARM: none\n", p.stderr


def test_a_loaded_append_arm_checks_clean(repo):
    cid = begin(repo)
    _conflict(repo, "tasks/index.yml")
    run("conflicts", cid, cwd=repo)
    arm = CLOSE_DIR / "steps" / "4a-append.md"
    p = load(cid, repo, close_arms.digest_of(arm.read_text(encoding="utf-8")), arm="4a-append")
    assert p.returncode == 0 and p.stdout == "LOADED: 4a-append\n", p.stderr
    assert run("check", cid, cwd=repo).returncode == 0


def test_the_filing_step_4d_runs_on_every_landing_close_stays_in_the_core():
    """Lens A (Phase 390): Step 4d files Step 3c's smoke tasks "by the same route" as 4a-fix's
    item 6, on every landing close, and `steps/4a-fix.md` loads only when there are notes. So
    items 6 and 7 stay in the core, below the marker; the splice still reads 1 to 7 in order."""
    core = CLOSE_CORE.read_text(encoding="utf-8")
    arm = (CLOSE_DIR / "steps" / "4a-fix.md").read_text(encoding="utf-8")
    item6 = "6. **File the notes routed to a task at the start of Step 4d, in one further commit.**"
    assert item6 in core and item6 not in arm
    assert core.index("<!-- sysop:arm=4a-fix -->") < core.index(item6) < core.index("### 4a-post.")
    assert "5. **Act on the verdict.**" in arm and "5. **Act on the verdict.**" not in core
    assert "with its item 6" in core


@pytest.mark.parametrize("path,want", [
    ("tasks/index.yml", True), ("review_tasks.md", True), ("tasks/notes.md", True),
    ("tasks/open/FEAT-0001.md", True), ("tasks/archive/x.md", True), ("tasks/a.md", True),
    ("tasks/index.yaml", False), ("docs/review_tasks.md", False), ("src/tasks/x.md", False),
    ("tasks/open/x.txt", False), ("README.md", False)])
def test_which_paths_are_shared_append_files(path, want):
    assert close_arms.shared_append(path) is want


@pytest.mark.parametrize("count,arm", [("0", None), ("1", "4a-fix"), ("12", "4a-fix")])
def test_notes_makes_4a_fix_due_only_on_a_count_above_zero(repo, count, arm):
    cid = begin(repo)
    p = run("notes", cid, count, cwd=repo)
    assert p.returncode == 0 and p.stdout == f"ARM: {arm or 'none'}\n", p.stderr
    c = run("check", cid, cwd=repo)
    assert ("ARM NOT LOADED: 4a-fix" in c.stdout) is (arm is not None)


@pytest.mark.parametrize("bad", ["<count>", "-1", "two", "", "1.0"])
def test_notes_refuses_what_is_not_a_count_and_records_nothing(repo, bad):
    cid = begin(repo)
    before = receipt(repo, cid).read_text()
    p = run("notes", cid, bad, cwd=repo)
    assert p.returncode == 2 and "is not a count" in p.stderr
    assert receipt(repo, cid).read_text() == before


# ── Step 3b's arms: `exited` (Phase 397, P5) ────────────────────────────────────────────

@pytest.mark.parametrize("arm", sorted(close_arms.EXIT_ARMS))
@pytest.mark.parametrize("code,due", [("0", False), ("1", True), ("2", True), ("8", True), ("255", True)])
def test_exited_makes_the_arm_due_only_on_a_code_other_than_zero(repo, arm, code, due):
    cid = begin(repo)
    p = run("exited", cid, arm, code, cwd=repo)
    assert p.returncode == 0 and p.stdout == f"ARM: {arm if due else 'none'}\n", p.stderr
    c = run("check", cid, cwd=repo)
    assert (f"ARM NOT LOADED: {arm}" in c.stdout) is due
    assert c.returncode == (1 if due else 0)


@pytest.mark.parametrize("arm", sorted(close_arms.EXIT_ARMS))
def test_a_loaded_exit_arm_checks_clean(repo, arm):
    cid = begin(repo)
    assert run("exited", cid, arm, "3", cwd=repo).stdout == f"ARM: {arm}\n"
    assert run("exited", cid, arm, "6", cwd=repo).stdout == f"ARM: {arm}\n"   # a second branch
    digest = close_arms.digest_of((CLOSE_DIR / "steps" / f"{arm}.md").read_text(encoding="utf-8"))
    assert load(cid, repo, digest=digest, arm=arm).stdout == f"LOADED: {arm}\n"
    c = run("check", cid, cwd=repo)
    assert c.returncode == 0 and "ARMS: required 1, loaded 1" in c.stdout, c.stdout


@pytest.mark.parametrize("arm,code,why", [
    ("3b-collect-exit", "<code>", "is not an exit code"),
    ("3b-collect-exit", "-1", "is not an exit code"),
    ("3b-collect-exit", "256", "is not an exit code"),
    ("3b-collect-exit", "1.0", "is not an exit code"),
    ("3b-collect-exit", "", "is not an exit code"),
    ("3b-collect-exit", "0x1", "is not an exit code"),
    ("3b-collect-exit", "\u0661", "is not an exit code"),   # Arabic-Indic 1: `int()` takes it
    ("3b-collect-exit", "\uff11", "is not an exit code"),   # fullwidth 1 (round 1, lens A)
    ("4a-fix", "1", "unknown arm"),
    ("4d-direct", "1", "unknown arm"),
    ("<arm-id>", "1", "unknown arm"),
    # Round 1, lens B: the arm is checked whatever the code, `4a-append` is not an exit arm,
    # and a sign is not a digit.
    ("4a-fix", "0", "unknown arm"),
    ("4a-append", "1", "unknown arm"),
    ("3b-rollback", "+1", "is not an exit code"),
])
def test_exited_refuses_what_it_cannot_read_and_records_nothing(repo, arm, code, why):
    cid = begin(repo)
    before = receipt(repo, cid).read_text()
    p = run("exited", cid, arm, code, cwd=repo)
    assert p.returncode == 2 and why in p.stderr, p.stderr
    assert receipt(repo, cid).read_text() == before


def test_exited_refuses_a_fourth_argument_and_records_nothing(repo):
    cid = begin(repo)
    before = receipt(repo, cid).read_text()
    p = run("exited", cid, "3b-rollback", "1", "extra", cwd=repo)
    assert p.returncode == 2 and "usage: exited" in p.stderr, p.stderr
    assert receipt(repo, cid).read_text() == before


@pytest.mark.parametrize("code", ["0", "1"])
def test_exited_refuses_a_missing_receipt(repo, code):
    """Code 0 too: an unsubstituted or mistyped close id must not read as `ARM: none`."""
    p = run("exited", "20261020T000000Z-abcd", "3b-rollback", code, cwd=repo)
    assert p.returncode == 2 and p.stdout == ""


def test_the_digest_leaves_out_a_role_marked_line_and_nothing_else():
    text = (CLOSE_DIR / "steps" / "4a-fix.md").read_text(encoding="utf-8")
    d = close_arms.digest_of(text)
    role = next(ln for ln in text.split("\n") if close_arms.ROLE_LINE.search(ln))
    assert close_arms.digest_of(text.replace(role, role.replace('"sonnet"', '"opus"'))) == d
    assert close_arms.digest_of(text.replace("Spawn no security twin", "Spawn a twin")) != d
    # Only the role marker is left out: any other comment line still counts.
    other = "x\n<!-- sysop:arm=a -->\n<!-- a note -->\n"
    assert close_arms.digest_of(other) != close_arms.digest_of(other.replace("a note", "b note"))
    assert close_arms.digest_of(other) != close_arms.digest_of(other.replace("arm=a", "arm=b"))


def test_a_role_override_leaves_every_step_files_digest_valid(tmp_path):
    """The install-time resolver rewrites a role-marked pin to the consumer's mapping. A
    digest over that line would refuse every load after an override (Phase 390)."""
    skills = tmp_path / "skills"
    shutil.copytree(SKILLS, skills, ignore=shutil.ignore_patterns("__pycache__"))
    cfg = REPO / "core" / "companion" / ".claude" / "served_models.yml"
    local = tmp_path / "served_models.local.yml"
    local.write_text("roles:\n  convention-gate: opus\nefforts:\n  convention-gate: low\n")
    r = subprocess.run([sys.executable, str(SCRIPT.parent / "resolve_skill_models.py"),
                        "--root", str(skills), "--config", str(cfg), "--local", str(local),
                        "--apply", "--quiet"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    resolved = (skills / "review-close" / "steps" / "4a-fix.md").read_text(encoding="utf-8")
    assert resolved != (CLOSE_DIR / "steps" / "4a-fix.md").read_text(encoding="utf-8"), \
        "the override rewrote nothing, so this test proves nothing"
    for step in (skills / "review-close" / "steps").glob("*.md"):
        text = step.read_text(encoding="utf-8")
        line = next(ln for ln in text.split("\n") if close_arms.LOADED_LINE.search(ln))
        assert line.split()[5] == close_arms.digest_of(text), step.name


# ── the core budget ─────────────────────────────────────────────────────────────────────

def budget_problems(core: int, budget: int = CORE_BUDGET_BYTES) -> list[str]:
    if core > budget:
        arms = sum(p.stat().st_size for p in _arm_files())
        shared = (SKILLS / "_shared" / "main-push-guard.md").stat().st_size
        return [f"review-close/SKILL.md is {core:,} bytes, {core - budget:,} over its budget "
                f"of {budget:,}. Arms: {arms:,} bytes in {len(_arm_files())} step file(s). "
                f"Shared, read on every landing close: _shared/main-push-guard.md {shared:,}. "
                "Move text into an arm (spec § 5) or raise CORE_BUDGET_BYTES with the reason "
                "in the phase record."]
    return []


def test_the_core_stays_within_its_budget():
    core = CLOSE_CORE.stat().st_size
    assert not budget_problems(core), budget_problems(core)[0]


@pytest.mark.parametrize("core,budget,expect", [(10, 10, False), (11, 10, True), (9, 10, False)])
def test_the_budget_check_is_not_vacuous(core, budget, expect):
    assert bool(budget_problems(core, budget)) is expect


# ── the readers: `self_check.sh` and `/sitrep` ──────────────────────────────────────────

def _aged_receipt(root: Path, *, loaded=False, checked=False, hours=25.0) -> str:
    cid = "20261001T000000Z-abcd"
    d = root / "sysop" / "runtime" / "close-arms"
    d.mkdir(parents=True, exist_ok=True)
    recs = ["begin\t20261001T000000Z", "policy\tdirect\tx", "required\t4d-direct\t20261001T000000Z"]
    if loaded:
        recs.append(f"loaded\t4d-direct\t{DIGEST}\t20261001T000000Z")
    if checked:
        recs.append("checked\t20261001T000000Z\tmissing 1")
    p = d / f"{cid}.tsv"
    p.write_text("\n".join(recs) + "\n")
    os.utime(p, (time.time() - hours * 3600,) * 2)
    return cid


@pytest.fixture(scope="module")
def installed(tmp_path_factory):
    import test_self_check_sh as SC
    root = SC._consumer(tmp_path_factory.mktemp("arms") / "c")
    assert SC._install(root, "--packs", "").returncode == 0
    return root


def _self_check(root):
    import test_self_check_sh as SC
    return SC._self_check(root)


def test_self_check_fails_on_an_unchecked_receipt_with_an_unloaded_arm(installed):
    cid = _aged_receipt(installed)
    try:
        r = _self_check(installed)
        assert r.returncode == 1, r.stdout + r.stderr
        assert "left an arm due and never loaded" in r.stdout
        assert f"UNCHECKED: {cid} 4d-direct" in r.stdout
    finally:
        shutil.rmtree(installed / "sysop" / "runtime" / "close-arms")


@pytest.mark.parametrize("kw", [{"loaded": True}, {"checked": True}, {"hours": 1.0}],
                         ids=["loaded", "checked", "young"])
def test_self_check_passes_a_receipt_with_nothing_to_report(installed, kw):
    _aged_receipt(installed, **kw)
    try:
        r = _self_check(installed)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "no /review-close left an arm due and unloaded" in r.stdout
    finally:
        shutil.rmtree(installed / "sysop" / "runtime" / "close-arms")


def test_self_check_is_silent_with_no_receipt_directory(installed):
    r = _self_check(installed)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "arm due" not in r.stdout


def test_a_loop_install_ships_neither_the_script_nor_the_probe_line(tmp_path):
    import test_self_check_sh as SC
    root = SC._consumer(tmp_path / "c")
    assert SC._install(root, "--mode", "loop", "--packs", "").returncode == 0
    assert not (root / "sysop" / "scripts" / "close_arms.py").exists()
    _aged_receipt(root)
    r = _self_check(root)
    assert "arm due" not in r.stdout, "loop mode installs no close_arms.py to read with"


def _kinds(root: Path) -> list:
    import sitrep_survey
    return [d for d in sitrep_survey._find_discrepancies([], [], {}, root)
            if d.kind == "review-close arm never loaded"]


def test_sitrep_reports_an_unchecked_receipt_with_an_unloaded_arm(repo):
    cid = _aged_receipt(repo)
    found = _kinds(repo)
    assert len(found) == 1 and f"{cid}.tsv" in found[0].detail and "4d-direct" in found[0].detail


@pytest.mark.parametrize("kw", [{"loaded": True}, {"checked": True}, {"hours": 1.0}],
                         ids=["loaded", "checked", "young"])
def test_sitrep_is_quiet_on_a_receipt_with_nothing_to_report(repo, kw):
    _aged_receipt(repo, **kw)
    assert _kinds(repo) == []


def test_a_full_install_delivers_the_arm_and_the_script(installed):
    """The installer recurses into skill subdirectories since Phase 383 (P0); this is the
    first shipped file that needs it."""
    step = installed / ".claude" / "skills" / "review-close" / "steps" / "4d-direct.md"
    assert step.read_text(encoding="utf-8") == (CLOSE_DIR / "steps" / "4d-direct.md").read_text(encoding="utf-8")
    assert (installed / "sysop" / "scripts" / "close_arms.py").is_file()


def test_step_8s_template_carries_the_arms_row():
    """Phase 388's round (lens B): a length-preserving rename of the row survived every module."""
    text = text_of(CLOSE_CORE)
    step8 = text[text.index("## Step 8: Report"):]
    a = step8.index("```\n"); b = step8.index("\n```\n", a + 4)
    lines = step8[a:b].split("\n")
    at = [i for i, ln in enumerate(lines) if ln.startswith("Arms:")]
    assert len(at) == 1, at
    assert lines[at[0]:at[0] + 2] == [
        "Arms:          <close_arms.py check's lines: ARMS:, each ARM NOT LOADED:, CORE:, LOADED:",
        "               and SHARED:>"], lines[at[0]:at[0] + 2]


def test_exiteds_help_names_each_2b_trigger():
    """Phase 406's round (lens B, P01): the help's thresholds survived every module."""
    doc = " ".join(close_arms.__doc__.split())
    for clause in ("(`2b-no-conventions`, on a `TOTAL` of `0`)", "(`2b-large-diff`, above 1,000 lines)",
                   "(`2b-twin-spawn`, on `SPAWN`)",
                   "(`2b-leak`, any of the five commands printing other than its clean line)",
                   # Phase 411 (P5): Step 3c's, and the resume's second trigger for it; and the
                   # literal and the count its round's lens B (H01, H02) left unread.
                   "(`3c-signals`, on `SMOKE_REQUIRED`, and the resume when a Step 3c question is "
                   "recorded), run with a literal `1`;",
                   # Phase 418 (P5): Step 4b's.
                   "Step 4b's batch set (`4b-batches`, when `review_index.py --list --merged` "
                   "printed a row), run with a literal `1`;",
                   # Phase 419 (P5): Step 4a-post's.
                   "Step 4a-post's failure arms (`4a-post-failure`, when a gate command failed or "
                   "timed out), run with a literal `1`;",
                   # Phase 429 (P5): Step 4a's.
                   "Step 4a's published arm (`4a-published`, when `git_check.py published` exited "
                   "0), run with a literal `1`;",
                   # Phase 430 (P5): Step 2a's, with the resume's second trigger, and 4a-post's
                   # pre-scan.
                   "Step 2a's ignored-file check (`2a-ignored-refs`, on any non-zero exit, and the "
                   "resume, with a literal `1`, when a Step 2a step 3a question is recorded);",
                   "its pre-scan (`4a-post-prescan`, when `run_checks.sh` exited non-zero or is "
                   "absent), run with a literal `1`;",
                   "Today eight steps' fourteen arms (`EXIT_ARMS`)"):
        assert clause in doc, clause


def test_policys_help_names_the_arm_it_makes_due():
    """Phase 415's battery (H01): the help's `policy` entry could lose its arm unseen; its round's
    lens B (B23) then rewrote the third sentence to call the trigger optional."""
    doc = " ".join(close_arms.__doc__.split())
    assert ("Under `pr` it then records `required 4-pre-pr` and prints `ARM: 4-pre-pr`, Step "
            "4-pre's two `pr` shapes; under `direct`, `ARM: none`. Step 4d's `arm` refuses a close "
            "whose policy was never recorded, so this trigger runs on every close that runs Step 4d's "
            "`arm`.") in doc


def test_arms_and_begins_help_name_step_6s_trigger():
    """Phase 416's battery (H01, H02): the help's `arm` entry could lose Step 6, and `begin`'s the
    land's policy record, unseen."""
    doc = " ".join(close_arms.__doc__.split())
    for clause in ("Step `6`, run when Step 6 runs (so a close that stops before Step 6 records "
                   "nothing): under `direct`, `6-direct`; under `pr`, `6-pr-gate` then `6-pr-cleanup`, "
                   "each recorded and printed.",
                   "Under `--land` it also records the `pr` policy it has just read, since a land runs "
                   "no Step 4-pre and its Step 6 runs `arm`."):
        assert clause in doc, clause


def test_workflow_names_begins_arm_list():
    text = (REPO / "core" / "companion" / "docs" / "WORKFLOW.md").read_text(encoding="utf-8")
    assert "| `close_arms.py begin <flags> <arm-id>...` · `policy <close-id>` · `read-policy <dir>` · `arm <close-id> <step>` · " \
           "`conflicts <close-id>` · `notes <close-id> <count>` · " \
           "`exited <close-id> <arm-id> <code>` · " \
           "`loaded <close-id> <arm-id> <digest> <skill-dir>` · " in text
    # Phase 397 (P5): Step 3b's two exit arms and the command that makes them due.
    assert "Step 3b's `exited` when the collect exits non-zero, `steps/3b-collect-exit.md`, or " \
           "`git worktree remove` refuses, `steps/3b-rollback.md`;" in text
    # Phase 406 (P5): Step 2b's four (its battery's W01 deleted the clause unseen).
    assert "Step 2b's `exited` when the conventions measure prints a `TOTAL` of `0`, " \
           "`steps/2b-no-conventions.md`, a target's diff is above 1,000 lines, " \
           "`steps/2b-large-diff.md`, the security gate prints `SPAWN`, `steps/2b-twin-spawn.md`, " \
           "or one of the leak assertion's five commands prints other than its clean line, " \
           "`steps/2b-leak.md`;" in text
    # Phase 411 (P5): Step 3c's signal arm and both of its triggers.
    assert "Step 3c's `exited` when the smoke detection prints `SMOKE_REQUIRED`, and the resume's " \
           "when a Step 3c question is recorded, `steps/3c-signals.md`;" in text
    # Phase 415 (P5): Step 4-pre's `pr` shapes, made due by `policy` (its battery's W01).
    assert "Step 4-pre's `policy` records the merge policy and, under `pr`, " \
           "`steps/4-pre-pr.md`," in text
    # Phase 429 (P5): Step 4a's.
    assert "Step 4a's `exited` when `git_check.py published` answers published, " \
           "`steps/4a-published.md`;" in text
    # Phase 419 (P5): Step 4a-post's, and Phase 430's pre-scan.
    assert "Step 4a-post's `exited` when a gate command fails or times out, " \
           "`steps/4a-post-failure.md`, or the pre-scan exits non-zero or is absent, " \
           "`steps/4a-post-prescan.md`;" in text
    # Phase 430 (P5): Step 2a's, and the resume's second trigger for it.
    assert "Step 2a's `exited` when the ignored-file check exits non-zero, and the resume's when a " \
           "Step 2a step 3a question is recorded, `steps/2a-ignored-refs.md`;" in text
    # Phase 418 (P5): Step 4b's.
    assert "Step 4b's `exited` when `review_index.py --list --merged` prints a row, " \
           "`steps/4b-batches.md`;" in text
    # Phase 403 (P5): Step 4c's two.
    assert "Step 4c's `exited` when `close_check.py` exits non-zero, `steps/4c-check-exit.md`, or " \
           "1b's merge count is anything but `0`, `steps/4c-unmerged.md`;" in text
    # Lens B (Phase 390): the row's trigger and digest clauses could be deleted unseen.
    assert "Step 4a's `conflicts` when a shared append file conflicted, `steps/4a-append.md`; " \
           "Step 4a-fix's `notes` when Step 2b collected notes, `steps/4a-fix.md`;" in text
    assert "(lines the model-role resolver rewrites are left out of it)" in text
    # Phase 393's round (lens B): the clauses the phase added could be deleted unseen.
    assert "`begin` opens it before the flag sections, recording the flag arms the invocation's flags " \
           "make due (`steps/prepare-resume.md` for `--prepare` or `--resume`, " \
           "`steps/request-review-land.md` for `--request-review` or `--land`, and `steps/4d-pr.md` " \
           "too for `--land`, whose merge policy it records too, since a land runs no Step 4-pre)" in text
    # Phase 416 (P5): Step 6's own `arm`, after Step 4d's (its battery's W01, W02).
    assert "Step 4d's `arm`, `steps/4d-direct.md` under `direct` and `steps/4d-pr.md` under `pr`; " \
           "Step 6's `arm`, run only when Step 6 runs, `steps/6-direct.md` under `direct` and " \
           "`steps/6-pr-gate.md` and `steps/6-pr-cleanup.md` under `pr`)" in text
    assert "`begin` refuses a flag combination the skill does not run, `--request-review`, `--land` or " \
           "`--agent` under a policy other than `pr`, and a skill and script from different versions;" in text


def test_the_pre_flight_names_every_receipt_command():
    line = next(ln for ln in CLOSE_CORE.read_text(encoding="utf-8").split("\n")
                if ln.startswith("- `Bash(python3 sysop/scripts/close_arms.py:*)`"))
    for cmd in ("`begin`", "`policy`", "`conflicts`", "`notes`", "`arm`", "`loaded`", "`check`"):
        assert cmd in line, cmd
    assert "the arm receipt: `begin` before the flag sections," in line, "Phase 393's round (lens B)"
    # Phase 416's battery (RL2): each step that runs `arm` is named, read off `ARM_FOR`.
    for step in sorted({step for step, _ in close_arms.ARM_FOR}):
        assert f"{step}'s `arm`" in line, step


def test_sitreps_receipt_shapes_are_close_arms_own():
    """Round 2 (lens D): `sitrep_survey.py` carries its own copy of the record shapes."""
    import ast
    src = (SCRIPT.parent / "sitrep_survey.py").read_text(encoding="utf-8")
    found = [ast.literal_eval(n.value) for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "shapes" for t in n.targets)]
    assert found == [close_arms.SHAPES], found


def test_sitrep_reports_a_receipt_it_cannot_open(repo):
    import sitrep_survey
    if os.geteuid() == 0:
        pytest.skip("root reads a mode-000 file")
    d = repo / "sysop" / "runtime" / "close-arms"
    d.mkdir(parents=True)
    f = d / "20261001T000000Z-dddd.tsv"
    f.write_text("begin\tx\n")
    os.utime(f, (time.time() - 25 * 3600,) * 2)
    f.chmod(0)
    try:
        kinds = [x.kind for x in sitrep_survey._find_discrepancies([], [], {}, repo)]
        assert "review-close arm receipt unreadable" in kinds
    finally:
        f.chmod(0o600)


def test_sitrep_reports_a_receipt_it_cannot_read(repo):
    import sitrep_survey
    d = repo / "sysop" / "runtime" / "close-arms"
    d.mkdir(parents=True)
    for name, body in (("20261001T000000Z-aaaa", b"begin\t\xff\n"),
                       ("20261001T000000Z-bbbb", b"begin\tx\nrequir\n")):
        (d / f"{name}.tsv").write_bytes(body)
        os.utime(d / f"{name}.tsv", (time.time() - 25 * 3600,) * 2)
    found = [x for x in sitrep_survey._find_discrepancies([], [], {}, repo)
             if x.kind == "review-close arm receipt unreadable"]
    assert sorted(x.detail.split(":")[0] for x in found) == [
        "sysop/runtime/close-arms/20261001T000000Z-aaaa.tsv",
        "sysop/runtime/close-arms/20261001T000000Z-bbbb.tsv"]


def test_self_check_names_an_unreadable_receipt_as_unreadable(installed):
    d = installed / "sysop" / "runtime" / "close-arms"
    d.mkdir(parents=True, exist_ok=True)
    (d / "20261001T000000Z-cccc.tsv").write_bytes(b"begin\t\xff\n")
    os.utime(d / "20261001T000000Z-cccc.tsv", (time.time() - 25 * 3600,) * 2)
    try:
        r = _self_check(installed)
        assert r.returncode == 1
        assert "cannot be read" in r.stdout and "left an arm due" not in r.stdout, r.stdout
    finally:
        shutil.rmtree(d)


def test_self_check_fails_when_the_reader_itself_fails(installed):
    script = installed / "sysop" / "scripts" / "close_arms.py"
    saved = script.read_bytes()
    d = installed / "sysop" / "runtime" / "close-arms"
    d.mkdir(parents=True, exist_ok=True)
    script.write_text("import sys\nsys.exit(3)\n")
    try:
        r = _self_check(installed)
        assert r.returncode == 1 and "close_arms.py unchecked failed" in r.stdout, r.stdout
    finally:
        script.write_bytes(saved)
        shutil.rmtree(d)


def test_sitrep_waits_a_day(repo):
    _aged_receipt(repo, hours=3.0)
    assert _kinds(repo) == []
