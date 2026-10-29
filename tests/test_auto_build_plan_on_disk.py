"""`/auto-build`'s plan handoff, both directions (Phase 344: `Q-571` + `Q-316`).

Two harness facts, measured by one `general-purpose` / `opus` probe spawned the way
Phase 6a and 6e spawn theirs, carry the whole phase:

* **A spawned agent has no `ExitPlanMode`** — absent from its callable and deferred tool
  lists, and `ToolSearch` finds no match. Step 7c item 2 ordered every executor to call
  it, so the revised plan had no destination, and `/plan-review`'s scope argument cited
  the call as happening.
* **Only the report a sub-agent hands back reaches its parent.** Text the probe emitted in an
  earlier turn never arrived, and neither did a text it wrote after handing back. Step 7a told the planner to put
  its plan in its final message, which works only if the planner complies, and a
  summary-only final message silently loses the plan.

So the planner writes `plan.md` into a freshly minted `<CLAIM_DIR>` and the orchestrator
parks on a missing or empty one; the executor writes `revised-plan.md` beside the
orchestrator's `classification.md`. The shell blocks below are EXECUTED from the skill,
not retyped: a copy would pass while the shipped block rotted.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _prose_guard_helpers import _sentences, section, states  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "core" / "skills"
BUILD = SKILLS / "auto-build" / "SKILL.md"
PLAN_REVIEW = SKILLS / "plan-review" / "SKILL.md"
WORKFLOW = REPO_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md"

# git exports these into every hook, and they beat `git -C`; a pre-push pytest run would
# otherwise build these fixtures against the invoking repository.
_GIT_DISCOVERY = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")


def _env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in _GIT_DISCOVERY}


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _fence_containing(text: str, needle: str) -> str:
    """The body of the one fenced block holding `needle`. Fails on zero or two holders."""
    hits = [m.start() for m in re.finditer(re.escape(needle), text)]
    assert len(hits) == 1, f"{needle!r} occurs {len(hits)} times; expected exactly one"
    i = hits[0]
    opener = text.rfind("\n```", 0, i)
    body_start = text.index("\n", opener + 1) + 1
    closer = text.index("\n```", i)
    assert opener != -1 and "```" not in text[body_start:i], "needle is not inside a fence"
    return text[body_start:closer + 1]


# --------------------------------------------------------------------- Q-571: no ExitPlanMode

# Round 2 (lens 4) disqualified the intent screen that stood here, the second shape to fail:
# it read "Do not stop until you call `ExitPlanMode`" as a prohibition, missed "exits plan
# mode", a wrapped line and an order in /claim-task's orchestrator prose, and flagged 10 of
# 15 correct prohibitions. On Wade's answer (2026-09-29) it is an exact INVENTORY instead: no
# guess about what a sentence means, only whether it is one a reader has already judged.
_PLAN_MODE = re.compile(r"\b(?:enter|exit)(?:s|ed|ing)?\s*[_-]?plan\s*[_-]?mode\b", re.I)
_CORE = REPO_ROOT / "core"
# `/plan-review` is a top-level skill that enters and leaves plan mode itself, so it may
# mention the tools freely; every other file that does is inventoried sentence by sentence.
_EXEMPT = {"skills/plan-review/SKILL.md"}
# sha256[:16] of each whitespace-collapsed sentence that mentions plan mode, per file.
# Regenerate with `_print_inventory()` and READ each new sentence before recording it: an
# addition here is a reader's judgement that the sentence does not order a spawned agent to
# use a tool it does not have.
_INVENTORY = {
    "companion/docs/WORKFLOW.md": (
        "0479983e1e1ea5af",  # It does not implement, does not commit, and does not enter plan mode 7
        "2a14cb5279e51c71",  # Internal tracker #220 observed a real review-batch claim run `EnterPla
        "c55a0af0a0135b53",  # **What the shape does and does not fix, stated plainly.** It removes t
    ),
    "companion/docs/WORKFLOW_GUIDE.md": (
        "e7865a379c5ab50a",  # **Any `blocker` halts instead**, per the rubric's halt arm: the plan i
    ),
    "skills/_shared/adversarial-review.md": (
        "9d1314844dae8cad",  # Action: halt — do not call `ExitPlanMode`, do not execute, surface the
    ),
    "skills/auto-build/SKILL.md": (
        "95fc77afab66fbce",  # **There is no `ExitPlanMode` call:** a spawned agent does not have tha
        "1322338c20371218",  # **It does not enter plan mode; nothing in that pipeline does.** The `s
    ),
    "skills/claim-task/SKILL.md": (
        "481ba8541e65f253",  # It never implements.** It does not enter plan mode, does not call `Exi
        "d699fae929c13e2a",  # **Why this is three spawns, a classification and a gate rather than on
        "71950a6b6b7faf29",  # **Drift** — the skill was read hundreds of tool calls ago and plan mod
        "f68aacd1d3044ca1",  # Do NOT implement, do NOT commit, do NOT call `ExitPlanMode` (you are n
        "eae8a6af0b38ba73",  # The tempting recovery from a failed reviewer is *'continue to the exec
    ),
}


def _plan_mode_sentences(text: str) -> list[str]:
    flat = re.sub(r"(?<!\n)\n(?!\n)", " ", text)       # a wrap is not a sentence break
    return [re.sub(r"\s+", " ", s).strip() for s in _sentences(flat) if _PLAN_MODE.search(s)]


def _digest(sentence: str) -> str:
    return hashlib.sha256(sentence.encode("utf-8")).hexdigest()[:16]


def _mentioning_files() -> dict[str, list[str]]:
    out = {}
    for f in sorted(_CORE.rglob("*")):
        if f.is_file() and f.suffix in (".md", ".sh", ".py", ".yml", ".json"):
            rel = str(f.relative_to(_CORE))
            if rel in _EXEMPT:
                continue
            found = _plan_mode_sentences(f.read_text(encoding="utf-8", errors="replace"))
            if found:
                out[rel] = found
    return out


def _print_inventory() -> None:
    for rel, sents in _mentioning_files().items():
        print(f'    "{rel}": (')
        for s in sents:
            print(f'        "{_digest(s)}",  # {s[:70]}')
        print("    ),")


def test_every_plan_mode_sentence_is_one_a_reader_judged() -> None:
    """The population is every shipped file under `core/`; any new file, and any new or
    changed sentence mentioning plan mode in one, fails until a reader records it."""
    got = {rel: tuple(sorted(_digest(s) for s in sents)) for rel, sents in _mentioning_files().items()}
    want = {rel: tuple(sorted(h)) for rel, h in _INVENTORY.items()}
    if got != want:
        new = [f"  {rel}: {s}" for rel, sents in _mentioning_files().items() for s in sents
               if _digest(s) not in _INVENTORY.get(rel, ())]
        raise AssertionError(
            "plan-mode sentences changed; read each, and if none orders an agent to use a "
            "plan-mode tool it does not have, regenerate with _print_inventory():\n"
            + ("\n".join(new) or "  (a recorded sentence was removed)"))


@pytest.mark.parametrize("sentence", [
    "Do not stop until you call `ExitPlanMode`.",                    # round 2 n02
    "Then the agent exits plan mode with the plan.",                 # round 2 n03
    "Then exit plan\nmode with the revised plan.",                   # round 2 n04, a wrap
    "If you are not already in plan mode, call `EnterPlanMode` first.",
])
def test_the_matcher_sees_every_spelling(sentence: str) -> None:
    """Non-vacuity: each shape round 2 walked through the intent screen is a mention the
    inventory counts, so adding it anywhere changes the recorded set."""
    assert _plan_mode_sentences(sentence), sentence


def test_the_inventory_is_not_empty_where_the_phase_worked() -> None:
    assert len(_INVENTORY.get("skills/auto-build/SKILL.md", ())) >= 1
    assert "skills/claim-task/SKILL.md" in _INVENTORY


def test_the_retired_item_2_would_change_the_inventory() -> None:
    text = _read(BUILD) + "\n\n2. **Call `ExitPlanMode`** with the revised plan as the plan content.\n"
    got = {_digest(s) for s in _plan_mode_sentences(text)}
    assert not got <= set(_INVENTORY["skills/auto-build/SKILL.md"])


def _sequence() -> str:
    text = _read(BUILD)
    start = text.index("### Sequence", text.index("**START OF EXECUTION AGENT PROMPT**"))
    return text[start:text.index("### Hard constraints", start)]


def test_item_2_writes_the_revised_plan_to_the_claim_dir() -> None:
    seq = _sequence()
    one, two, three = (seq.index(f"\n{n}. **") for n in (1, 2, 3))
    assert one < two < three, "Sequence items 1, 2, 3 are out of order or missing"
    item2 = seq[two:three]
    assert "**Write the revised plan to `<CLAIM_DIR>/revised-plan.md`**" in item2
    assert "`Write` tool" in item2 and "before you implement" in item2
    assert "## Findings" in item2 and "absorbed" in item2 and "rejected" in item2
    assert "do not `git add` it" in item2, "the main-checkout file could reach the branch"
    # Item 1 must route a rejection to item 2's file, not to prose nobody reads.
    assert "record why in item 2's file" in seq[one:two]


def test_the_executor_is_handed_the_claim_dir() -> None:
    text = _read(BUILD)
    assert "filled with `(task_id, worktree_path, branch_name, claim_dir, plan_text, raw_findings)`" in text
    assert "filled with `(task_id, worktree_path, branch_name, claim_dir)`" in text, (
        "the planner is not handed the directory it must write to")


def test_plan_review_no_longer_cites_the_call() -> None:
    """`/plan-review` 5b's conclusion survives on the premise that holds; the one that
    claimed `/auto-build`'s executor calls `ExitPlanMode` must not come back."""
    text = _read(PLAN_REVIEW)
    assert "executor does call it" not in text
    assert states(text, "`/plan-review` is the only rubric consumer that reaches `ExitPlanMode` at all")
    assert "which do not have the tool" in text


def test_workflow_no_longer_says_the_executor_calls_it() -> None:
    text = _read(WORKFLOW)
    line = next(ln for ln in text.splitlines() if ln.lstrip().startswith("- **Phase 6e**"))
    assert "ExitPlanMode" not in line, line
    assert "revised-plan.md" in line, line


# ------------------------------------------------------------------ Q-316: plan on disk


def test_the_planner_writes_its_plan_to_the_claim_dir() -> None:
    text = _read(BUILD)
    prompt = text[text.index("**START OF PLAN-ONLY AGENT PROMPT**"):
                  text.index("**END OF PLAN-ONLY AGENT PROMPT**")]
    assert "Write the full plan to `<CLAIM_DIR>/plan.md` with the `Write` tool" in prompt
    assert "PLAN_WRITTEN: <CLAIM_DIR>/plan.md" in prompt
    assert "```plan" not in text, (
        "the retired final-message channel (a fenced `plan` block) is back; the orchestrator "
        "never sees a message before the hand-back, so it is a channel that can lose the plan")
    assert "extract the plan text from the fenced" not in text


def test_the_orchestrator_reads_the_file_before_the_reviewer() -> None:
    text = _read(BUILD)
    read_at = text.index("**Then `Read` `<CLAIM_DIR>/plan.md` and store its contents as `PLAN_TEXT[<TASK_ID>]`**")
    check_at = text.index('elif [ ! -s "<claim dir>/plan.md" ]; then')
    spawn_6b = text.index("### Phase 6b:")
    assert check_at < read_at < spawn_6b
    assert "the **contents of `<CLAIM_DIR>/plan.md` verbatim**" in section(text, "### Phase 6b: Adversarial-Reviewer Agents (parallel across tasks)")


def test_the_park_arm_no_longer_writes_the_plan() -> None:
    text = _read(BUILD)
    arm = text[text.index("- **If any finding is `blocker`**"):text.index("- **If all findings are `fixable`")]
    assert "sysop/runtime/auto-build/plan.md" not in arm
    assert "The plan is already on disk at `<CLAIM_DIR>/plan.md`" in arm


# -- the mint block: a fresh directory, or nothing

def _mint(tmp: Path, task: str = "TECH-0007", cycle: str = "20260928T120000Z") -> subprocess.CompletedProcess:
    block = _fence_containing(_read(BUILD), 'CLAIM_DIR="sysop/runtime/claim/<TASK_ID>/<CYCLE_TS>"')
    block = block.replace("<TASK_ID>", task).replace("<CYCLE_TS>", cycle)
    script = tmp / "mint.sh"
    script.write_text("set -u\n" + block)
    return subprocess.run(["bash", str(script)], cwd=str(tmp), capture_output=True, text=True, env=_env())


def test_the_mint_block_creates_and_prints_an_absolute_directory(tmp_path: Path) -> None:
    r = _mint(tmp_path)
    assert r.returncode == 0, r.stderr
    made = tmp_path / "sysop/runtime/claim/TECH-0007/20260928T120000Z"
    assert made.is_dir()
    assert r.stdout.strip() == f"CLAIM_DIR={made.resolve()}", r.stdout


def test_the_mint_block_refuses_a_directory_that_already_exists(tmp_path: Path) -> None:
    """The property the plan check rests on: a `plan.md` from an earlier run cannot sit in
    this run's directory, because minting it again fails."""
    assert _mint(tmp_path).returncode == 0
    stale = tmp_path / "sysop/runtime/claim/TECH-0007/20260928T120000Z/plan.md"
    stale.write_text("an earlier run's plan\n")
    r = _mint(tmp_path)
    assert r.returncode != 0, "a second mint of the same directory succeeded"
    assert "CLAIM_DIR=" not in r.stdout


@pytest.mark.parametrize("task,cycle", [("<TASK_ID>", "20260928T120000Z"), ("TECH-0007", "<CYCLE_TS>")])
def test_the_mint_block_refuses_a_placeholder(tmp_path: Path, task: str, cycle: str) -> None:
    r = _mint(tmp_path, task, cycle)
    assert r.returncode != 0
    assert not (tmp_path / "sysop").exists()


# -- the post-6a block: park on a commit, or on a missing or empty plan

def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True, env=_env()).stdout.strip()


def _worktree(tmp: Path) -> tuple[Path, str]:
    wt = tmp / "wt"
    wt.mkdir()
    _git(wt, "-c", "init.defaultBranch=main", "init", "-q")
    (wt / "f.txt").write_text("x\n")
    _git(wt, "add", "f.txt")
    _git(wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    return wt, _git(wt, "rev-parse", "HEAD")


def _post_6a(tmp: Path, wt: Path, pre: str, claim: str) -> subprocess.CompletedProcess:
    block = _fence_containing(_read(BUILD), 'NEW_HEAD=$(git -C "<worktree path>" rev-parse HEAD)')
    block = (block.replace("<worktree path>", str(wt)).replace("<pre-plan head>", pre)
                  .replace("<claim dir>", claim).replace("<TASK_ID>", "TECH-0007"))
    script = tmp / "post6a.sh"
    script.write_text(block)
    return subprocess.run(["bash", str(script)], cwd=str(tmp), capture_output=True, text=True, env=_env())


def _verdict(wt: Path) -> str | None:
    p = wt / "sysop/runtime/auto-build/review.md"
    return p.read_text() if p.exists() else None


def test_a_written_plan_and_an_unmoved_head_pass_silently(tmp_path: Path) -> None:
    wt, pre = _worktree(tmp_path)
    claim = tmp_path / "claim"
    claim.mkdir()
    (claim / "plan.md").write_text("## Constraints & Risks\n- x\n")
    r = _post_6a(tmp_path, wt, pre, str(claim))
    assert r.returncode == 0, r.stderr
    assert r.stdout == "" and _verdict(wt) is None


@pytest.mark.parametrize("content", [None, ""], ids=["absent", "empty"])
def test_a_missing_or_empty_plan_parks(tmp_path: Path, content: str | None) -> None:
    wt, pre = _worktree(tmp_path)
    claim = tmp_path / "claim"
    claim.mkdir()
    if content is not None:
        (claim / "plan.md").write_text(content)
    r = _post_6a(tmp_path, wt, pre, str(claim))
    assert "PLAN-PHASE-PARK: TECH-0007: PLAN_MISSING" in r.stdout, r.stdout + r.stderr
    assert (_verdict(wt) or "").startswith("PLAN_MISSING:")


def test_a_commit_parks_as_a_violation_even_with_a_plan(tmp_path: Path) -> None:
    wt, pre = _worktree(tmp_path)
    claim = tmp_path / "claim"
    claim.mkdir()
    (claim / "plan.md").write_text("a plan\n")
    (wt / "g.txt").write_text("y\n")
    _git(wt, "add", "g.txt")
    _git(wt, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "planner commit")
    r = _post_6a(tmp_path, wt, pre, str(claim))
    assert "PLAN_PHASE_VIOLATION" in r.stdout
    assert "planner commit" in (_verdict(wt) or "")


def test_an_unsubstituted_claim_dir_parks_rather_than_passes(tmp_path: Path) -> None:
    wt, pre = _worktree(tmp_path)
    block = _fence_containing(_read(BUILD), 'NEW_HEAD=$(git -C "<worktree path>" rev-parse HEAD)')
    block = block.replace("<worktree path>", str(wt)).replace("<pre-plan head>", pre)
    script = tmp_path / "post6a.sh"
    script.write_text(block)
    r = subprocess.run(["bash", str(script)], cwd=str(tmp_path), capture_output=True, text=True, env=_env())
    assert "PLAN_MISSING" in r.stdout, r.stdout + r.stderr


# ------------------------------------------------ round 1: the cycle dir is not a run


def test_sitrep_does_not_offer_resume_for_an_auto_build_park(tmp_path: Path) -> None:
    """Round 1, lens 3 (HIGH): 6a's cycle directory gave every `/auto-build` park a
    `claim/<id>/` directory, and `/sitrep` offered `/claim-task --resume` into it, which
    re-plans and drops the blocker. Only `/claim-task`'s `<stamp>-<8 hex>` runs resume."""
    sys.path.insert(0, str(REPO_ROOT / "core" / "companion" / "scripts"))
    import sitrep_survey as ss
    parked = tmp_path / "sysop/runtime/parked"
    parked.mkdir(parents=True)
    (parked / "FEAT-X__20260928T120500Z.md").write_text("# FEAT-X — PARKED\n")
    cycle = tmp_path / "sysop/runtime/claim/FEAT-X/20260928T120000Z"
    cycle.mkdir(parents=True)
    (cycle / "plan.md").write_text("the reviewed plan\n")
    state, action, _ = ss._claim_stall(tmp_path, "FEAT-X")
    assert state == ss._PARKED_STATE
    assert "--resume" not in action, action
    assert "sysop/runtime/parked/FEAT-X__20260928T120500Z.md" in action
    # Round 2 (lens 4): an OLDER /claim-task run beside the newer cycle is a released
    # claim, not the live one, and must not be paired with the /auto-build park.
    old = tmp_path / "sysop/runtime/claim/FEAT-X/20260927T110000Z-0123abcd"
    old.mkdir()
    (old / "classification.md").write_text('```yaml\n{"verdict": "PROCEED"}\n```\n')
    state, action, _ = ss._claim_stall(tmp_path, "FEAT-X")
    assert state == ss._PARKED_STATE and "--resume" not in action, action
    for m in parked.iterdir():
        m.unlink()
    assert ss._claim_stall(tmp_path, "FEAT-X") == ("", "", []), (
        "a stale /claim-task PROCEED read as 'awaiting approval' under a live /auto-build cycle")
    # A /claim-task run that IS the newest directory still resumes.
    run = tmp_path / "sysop/runtime/claim/FEAT-X/20260928T130000Z-89abcdef"
    run.mkdir()
    (parked / "FEAT-X__20260928T130500Z.md").write_text("# FEAT-X — PARKED\n")
    assert ss._claim_stall(tmp_path, "FEAT-X")[1].endswith("--resume 20260928T130000Z-89abcdef")


# Every surface that described where /auto-build's plan lives. Round 1 (lens 1) reverted
# each of these to the pre-344 wording with every guard green (its rows o4-o8; this
# phase's battery re-runs o4, o6 and o8, and the base-tree control below covers the rest).
_PLAN_LOCATION_SURFACES = (
    "core/skills/auto-build/SKILL.md", "core/companion/docs/WORKFLOW.md",
    "core/companion/docs/WORKFLOW_GUIDE.md", "docs/workflow.html", "install.sh",
    "core/companion/scripts/cleanup_worktrees.sh",
)
_RETIRED_LOCATIONS = (
    "sysop/runtime/auto-build/plan.md",
    "`plan.md` + `review.md` written to `<worktree>",
    "write `plan.md` + `review.md` to `<worktree>",
    "emits a fenced `plan` block",
    "plan + verdict written to `<worktree>/sysop/runtime/auto-build/`",
    "plan + verdict written to `sysop/runtime/auto-build/`",
    "plan.md/review.md",
    "per-worktree plan + review scratch",
)


@pytest.mark.parametrize("rel", _PLAN_LOCATION_SURFACES)
def test_no_surface_puts_the_plan_back_in_worktree_scratch(rel: str) -> None:
    text = _read(REPO_ROOT / rel)
    back = [s for s in _RETIRED_LOCATIONS if s in text]
    assert not back, f"{rel} says the plan lives in the worktree scratch again: {back}"


def test_the_retired_locations_were_real() -> None:
    """Non-vacuity: every retired string occurred in some surface at the base tree, so
    the sweep above is checking wording that existed rather than wording nobody wrote."""
    base = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", "4b69f3e:core/skills/auto-build/SKILL.md"],
        capture_output=True, text=True, env=_env())
    if base.returncode != 0:
        pytest.skip("base commit not in this clone")
    corpus = "".join(
        subprocess.run(["git", "-C", str(REPO_ROOT), "show", f"4b69f3e:{rel}"],
                       capture_output=True, text=True, env=_env()).stdout
        for rel in _PLAN_LOCATION_SURFACES)
    assert all(s in corpus for s in _RETIRED_LOCATIONS), [s for s in _RETIRED_LOCATIONS if s not in corpus]


def test_the_planner_is_told_its_one_write() -> None:
    text = _read(BUILD)
    prompt = text[text.index("**START OF PLAN-ONLY AGENT PROMPT**"):
                  text.index("**END OF PLAN-ONLY AGENT PROMPT**")]
    assert "The one write you make is `<CLAIM_DIR>/plan.md`." in prompt
    assert "no `Edit` / `Write` tool call inside it" in prompt, (
        "the worktree ban reads as a ban on the one Write the planner must make (lens 1)")


def test_the_orchestrator_checks_the_revised_plan_exists() -> None:
    assert "**Then check that `<CLAIM_DIR>/revised-plan.md` exists.**" in _read(BUILD)
