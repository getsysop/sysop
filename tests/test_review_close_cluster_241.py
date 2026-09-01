"""Phase 241 (`Q-326` + `Q-327` + `Q-328` + `Q-329`) — the `/review-close` cluster.

Four § High filings against one skill, four wrong durable states: a merge that
should not happen, a task marked done that isn't, a convention gate that does
not run, and a silent false close.

**What this module tries to do differently.** Phase 240's round measured its own
ten real-subprocess tests at **20%** against an independent lens — execution
coverage is not discrimination when every fixture is the same shape — and filed
four instances of a guard asserting a token that survives next door (`Q-340`).
So the rules here are:

  * **Scope every text assertion to the paragraph or fence it governs**, never to
    the whole file. A substring that survives elsewhere in a 2,700-line document
    proves nothing about the site it was written for.
  * **Assert the property, not the wording, wherever a property exists.** The
    `Q-327` cases below RUN the shipped heredoc against fixtures that differ in
    the one field under test, and read the durable state it wrote.
  * **Assert ORDER where order is the defect.** `Q-326` is a probe that is
    worthless after the merge command; a presence check would pass on a probe
    appended to the end of the block.
"""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

_MISSING = object()  # sentinel: the `user_action` key absent, not present-and-falsy

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "core/skills/review-close/SKILL.md"
SCHEMA = REPO_ROOT / "core/companion/tasks/schema.md"
WORKFLOW = REPO_ROOT / "core/companion/docs/WORKFLOW.md"
SETTINGS = REPO_ROOT / "core/companion/.claude/settings.json"
REVIEW_INDEX = REPO_ROOT / "core/companion/scripts/review_index.py"


def _skill() -> str:
    return SKILL.read_text(encoding="utf-8")


def _paragraph_containing(text: str, needle: str) -> str:
    """The blank-line-delimited paragraph holding `needle`, asserted unique.

    Uniqueness is the point: an anchor that matches twice lets a check bind a
    decoy paragraph and pass while its real subject is gutted.
    """
    assert text.count(needle) == 1, (
        f"anchor {needle!r} occurs {text.count(needle)} times — a paragraph-scoped "
        f"assertion needs exactly one, or it may bind the wrong block"
    )
    for para in text.split("\n\n"):
        if needle in para:
            return para
    raise AssertionError(f"no paragraph holds {needle!r}")


def _fence_containing(text: str, needle: str) -> str:
    """The ```-delimited fence body holding `needle`, asserted unique."""
    fences = re.findall(r"^\s*```[^\n]*\n(.*?)^\s*```", text, re.M | re.S)
    hits = [f for f in fences if needle in f]
    assert len(hits) == 1, (
        f"expected exactly one fence containing {needle!r}, found {len(hits)}"
    )
    return hits[0]


def _required_rule_bullet(rule: str) -> bool:
    """True when `rule` is a REQUIRED allow-rule bullet, not merely mentioned.

    The preamble runs from "confirm `permissions.allow` satisfies every rule below"
    to the "Deliberate non-entries" paragraph, plus the `pr`-only block. A check
    that searches the whole file passes on a bullet reworded `(NOT required)`, and
    on the rule name appearing in any prose anywhere — both measured by the round.
    """
    text = _skill()
    head = text.index("confirm `permissions.allow` satisfies every rule below")
    tail = text.index("Every rule named above ships in the installer's seeded allow-list")
    for line in text[head:tail].splitlines():
        st = line.strip()
        if not st.startswith("- `" + rule):
            continue
        if re.search(r"\bnot required\b|\boptional\b|\bno longer\b", st, re.I):
            return False
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Q-329 — the batch-set reader that could not run
# ─────────────────────────────────────────────────────────────────────────────


def test_the_batch_set_reader_is_invoked_with_python_not_bash():
    """The command word, pinned at its own site.

    The pre-fix guard (`test_review_close_zero_batch_arm.py`) asserted only that
    the substring `review_index.py --list` appeared in the paragraph — which is
    true of the broken spelling too. That is the assert-the-mention-not-the-
    behaviour shape, and it is why this defect shipped with a guard over it.
    """
    para = _paragraph_containing(_skill(), "the source is `review_tasks.md`")
    # The backtick is load-bearing: it anchors the COMMAND WORD. Without it this
    # assertion is a substring check that `.venv/bin/python3 sysop/scripts/
    # review_index.py --list` satisfies — a spelling that binds no allow-rule
    # (Phase 126/183 class) and is silently denied under `dontAsk`. That survivor
    # was found by this phase's own battery (row X02).
    assert "`python3 sysop/scripts/review_index.py --list`" in para, (
        "Step 4b's batch-set derivation no longer names bare `python3` as the "
        "command word for review_index.py — a PATH-prefixed spelling binds no rule"
    )
    assert ".venv/bin/python3 sysop/scripts/review_index.py" not in para, (
        "the step prescribes a venv-prefixed interpreter, which matches no seeded "
        "allow-rule"
    )
    assert "bash sysop/scripts/review_index.py" not in para, (
        "Step 4b prescribes `bash` on a Python module again — it exits 2 with an "
        "empty stdout, which is byte-for-byte a batch-free cycle"
    )


# Shipped roots a prescribed command can live in. `install.sh` and `scripts/` are
# NOT under core/ or packs/, and the first cut of this guard omitted both — the
# exact hole `_shared/adversarial-review.md` rule 1 names ("one such guard excluded
# the installer"). The git-hooks are extensionless shell and were invisible to a
# suffix filter.
_SWEEP_ROOTS = ("core", "packs", "scripts")
_SWEEP_FILES = ("install.sh",)
_TEXTY = {".md", ".sh", ".json", ".yml", ".yaml", ".py", ".fragment", ".example",
          ".ts", ".tsx", ".txt", ""}
_BASH_PY = re.compile(r"(?:^|[|;&(]|\s)\s*(?:/[\w/]*/)?bash\s+\S*\.py\b")


def _fenced_shell_regions(text: str) -> list[str]:
    r"""Correctly-paired fences, keeping only the shell-ish ones.

    The first cut used `^\s*```(?:bash|sh|shell)?\s*\n(.*?)^\s*```` — an opener
    that matches ONLY an empty or shell info string. Every ```yaml / ```json /
    ```python fence in between then desynchronises the pairing, so the scanner
    reads the PROSE BETWEEN fences as if it were code while real shell fences fall
    outside its window. Measured on review-close/SKILL.md: 46 regions and 118,448
    chars against a correct pairing's 47 and 94,095 — 25% more text, and the
    command this phase added was NOT in it. Pair on ANY info string, then filter.
    """
    out = []
    fence, info, buf = False, "", []
    for line in text.splitlines():
        m = re.match(r"^\s*```(\S*)", line)
        if m:
            if fence:
                if info.lower() in ("", "bash", "sh", "shell", "console"):
                    out.append("\n".join(buf))
                fence, info, buf = False, "", []
            else:
                fence, info, buf = True, m.group(1), []
            continue
        if fence:
            buf.append(line)
    return out


def _sweep_paths():
    seen = []
    for root in _SWEEP_ROOTS:
        d = REPO_ROOT / root
        if d.is_dir():
            seen += [p for p in d.rglob("*") if p.is_file()]
    seen += [REPO_ROOT / f for f in _SWEEP_FILES]
    return [p for p in seen if p.suffix in _TEXTY and p.exists()]


def test_no_shipped_file_invokes_a_python_module_with_bash():
    """The class, not the instance. `Q-329`'s site was the only one; keep it so.

    Rewritten after the round's guards lens killed **0 of 7** mutations against the
    first cut — including an unindented positive control in a plain ```bash fence.
    Three independent causes, all now closed: fence mis-pairing (above), a `^`
    anchor that one leading space defeated (47% of lines were unreachable), and a
    population that skipped `install.sh`, `scripts/`, the extensionless git-hooks,
    and every `.py`/`.yaml`.
    """
    paths = _sweep_paths()
    # Floor derived from the tree (153 at Phase 241), not guessed. It exists because
    # a sweep whose population silently narrows reports clean while testing nothing —
    # and the first cut of this guard did exactly that.
    assert len(paths) >= 140, (
        f"population collapsed to {len(paths)} files — a sweep that reads nothing "
        "passes, which is how the first cut of this guard scored 0 of 7"
    )
    offenders = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        # Prose naming the anti-pattern in order to forbid it is not a defect, so
        # `.md` is read through its fenced shell regions. Everything else is code.
        regions = _fenced_shell_regions(text) if path.suffix == ".md" else [text]
        for region in regions:
            for line in region.splitlines():
                if line.lstrip().startswith("#"):
                    continue
                if _BASH_PY.search(line):
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {line.strip()[:80]}")
    assert not offenders, (
        "a shipped file invokes a Python module with bash — bash lexes the module "
        f"docstring as one quoted word and exits 2 with empty stdout: {offenders}"
    )


def test_the_class_sweep_actually_sees_the_sites_it_claims_to_cover():
    """Vacuity control. A sweep is only a class guard if its window holds the class.

    Positive controls at the five sites the lens used, including the one this
    phase itself added. Without this, the sweep can silently narrow again and
    still read as coverage — which is what it did.
    """
    skill = SKILL.read_text(encoding="utf-8")
    regions = _fenced_shell_regions(skill)
    for probe, why in (
        ('gh pr view "<PR>" --json statusCheckRollup', "the command THIS PHASE added"),
        ('git push origin "$INTEGRATION_BRANCH"', "Step 4d's push"),
        ("gh pr create --base main", "Step 4d's PR creation"),
        ("python3 sysop/scripts/validate_tasks.py", "Step 4c's validator"),
    ):
        assert any(probe in r for r in regions), (
            f"the sweep's window does not contain {why} — a `bash <x>.py` planted "
            f"there would pass unseen, which is how the first cut scored 0 of 7"
        )
    # Indented lines must be reachable: SKILL.md's fences are mostly indented.
    assert _BASH_PY.search("   bash sysop/scripts/review_index.py --list"), (
        "the anchor is defeated by leading whitespace again"
    )
    assert _BASH_PY.search("/bin/bash sysop/scripts/review_index.py --list"), (
        "an absolute interpreter path walks the anchor"
    )
    assert not _BASH_PY.search("bash close_batch.sh 1 2 3"), "false positive on a real bash script"
    # Population must reach the files the first cut missed.
    names = {p.name for p in _sweep_paths()}
    for f in ("install.sh", "pre-commit", "checks.yml.fragment"):
        assert f in names, f"the sweep no longer reads {f}"


def test_bash_on_review_index_really_does_produce_a_silent_empty_result(tmp_path):
    """Run the broken spelling. This is the premise the fix rests on.

    Not `bash -n` — the run itself is the evidence. Exit non-zero with **zero
    bytes on stdout** is what makes a failed measurement indistinguishable from a
    measured-empty batch set.
    """
    copy = tmp_path / "review_index.py"
    copy.write_bytes(REVIEW_INDEX.read_bytes())
    r = subprocess.run(["bash", str(copy), "--list"], capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode != 0, "premise gone: bash no longer fails on this module"
    assert r.stdout == "", (
        "premise gone: bash now writes to stdout, so a failed run would no longer "
        f"mimic an empty batch set (got {r.stdout!r})"
    )


def test_the_empty_arm_distinguishes_could_not_measure_from_measured_empty():
    """The second half of the fix: a non-zero exit is not an empty set."""
    para = _paragraph_containing(_skill(), "And it does not mean the reader failed to run")
    # Verified by execution (see the module docstring's sibling test): `--list`
    # exits 0 on a genuinely empty tracker and 1 when the tracker is absent. Assert
    # THAT claim, not the token `0` — the first cut of this check matched an
    # incidental "exit `0`" three sentences later and passed while the sentence
    # establishing the discriminator had been deleted (battery row X04).
    assert "exits **0** whether it names" in para, (
        "the empty arm no longer states that `--list` exits 0 whether it names "
        "batches or none — without that claim the exit code is not a discriminator "
        "and the arm is back to reading stdout alone"
    )
    assert "discriminator" in para
    assert "non-zero" in para and "STOP" in para, (
        "the empty arm no longer routes a non-zero exit to a stop — a batch the "
        "reader could not name is then left Pending under a successful close"
    )


def test_the_review_index_rule_is_seeded_and_the_skill_asserts_it():
    """A prescribed command with no rule is a silent deny waiting to happen."""
    rule = "Bash(python3 sysop/scripts/review_index.py:*)"
    assert rule in SETTINGS.read_text(encoding="utf-8"), f"{rule} no longer seeded"
    assert _required_rule_bullet(rule), (
        "/review-close prescribes review_index.py but its allow-rule is no longer a "
        "REQUIRED bullet in the preamble — the round's lens turned these into "
        "`(NOT required) …` and both assertions stayed green, because they searched "
        "the whole 2,700-line file for the rule text"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Q-326 — the merge that runs on an unmeasured check surface
# ─────────────────────────────────────────────────────────────────────────────


def test_the_check_run_probe_exists_and_precedes_the_merge():
    """Order is the property. A probe after `gh pr merge` measures nothing.

    Presence alone would pass on a probe appended below the merge, which is the
    exact defect (`4d-1` already 'handled' the zero-checks case — post-merge).
    """
    fence = _fence_containing(_skill(), "statusCheckRollup")
    assert "--jq '.statusCheckRollup | length'" in fence, (
        "the probe no longer counts the rollup"
    )
    # Index on the COMMAND, not the word: `statusCheckRollup` also appears in the
    # `# 4b.` comment above it, and that comment stays put when the command moves
    # below the merge — battery row O02 walked through the bare-word version.
    probe_at = fence.index("--json statusCheckRollup --jq")
    merge_at = fence.index("gh pr merge")
    assert probe_at < merge_at, (
        "the check probe no longer runs BEFORE `gh pr merge` — a count read after "
        "the squash cannot prevent it"
    )
    # The COMMAND, not the phrase. `gh pr checks` is also named in the 4b comment
    # explaining which data set the probe matches, and that comment survives the
    # command's deletion — battery row O03 walked through the bare-phrase version.
    # Eighth instance of this class in one phase, and every one had the same cause:
    # a rationale comment beside a command supplies the token the guard checks for.
    checks_at = fence.index('gh pr checks "<PR>" --watch --fail-fast')
    assert checks_at < probe_at, (
        "the probe no longer runs after command 4's wait, so a count of 0 cannot be "
        "read as could-not-measure — checks may simply not have finished"
    )
    # The data set is the finding, not a detail. `commits/<sha>/check-runs` counts
    # ONLY the Checks API, so a consumer whose required checks arrive through the
    # Status API (Jenkins, Buildkite, CircleCI classic) reads 0 on a fully green PR
    # and is blocked on every run, with both stated remedies pointing the wrong way.
    # Measured on PR #518's head: check-runs 1, commits/<sha>/status 0, rollup 1.
    assert "/check-runs" not in fence, (
        "the probe is back on the REST check-runs endpoint, which cannot see commit "
        "statuses — a Status-API consumer gets a permanent false STOP on a green PR"
    )


def test_the_probe_reads_the_same_data_set_as_the_command_it_reinforces():
    para = _paragraph_containing(_skill(), "Why this reads `statusCheckRollup`")
    assert "Status API" in para and "CheckRun | StatusContext" in para, (
        "the rationale no longer names the union — the next reader 'simplifies' back "
        "to check-runs and re-blocks every Status-API consumer"
    )
    assert "A gate that cannot be satisfied is worse than the hole it closes" in para


def test_the_batch_reader_arm_enumerates_only_reachable_exit_codes():
    """`--list` refuses nothing; 3/5/6 sit behind other flags."""
    text = _skill()
    para = _paragraph_containing(text, "Exactly two exit codes are reachable")
    assert "`--list` itself refuses\nnothing" in para or "`--list` itself refuses nothing" in " ".join(para.split()), (
        "the arm no longer says --list refuses nothing, and the unreachable exit "
        "codes 3/5/6 read as live arms again"
    )
    assert "--check-fences" in para


def test_an_exit_zero_that_dropped_a_batch_is_a_could_not_measure():
    """Measured: a duplicate batch number drops the REAL batch at exit 0.

    The only signal is a WARNING on stderr, which a caller reading stdout for
    tab-separated rows never sees. Exit 0 means the reader RAN, not that its
    answer is complete.
    """
    para = _paragraph_containing(_skill(), "third state")
    assert "capture stderr as well" in para and "WARNING:" in para, (
        "the arm no longer tells the caller to read stderr, so a silently truncated "
        "batch list is indistinguishable from a complete one at exit 0"
    )
    assert "only the last" in para


def test_the_two_user_action_gates_use_the_same_predicate():
    """1c said `== true` while the round-trip uses truthiness — they diverge on
    exactly the malformed values the truthiness bias was chosen for."""
    text = _skill()
    step1c = text[text.index("1c. **Hold back any pending-doc"):
                  text.index("2. **If none found**")]
    assert "truthy, **not** `== true`" in step1c, (
        "Step 1c states an equality test again; on a non-bool value it routes the "
        "doc and the round-trip then holds the task, which is the stranding path"
    )
    # The directive, not the word — `task_ids` also appears in the sentence that
    # explains why the shim matters, and that sentence survives the shim's removal
    # (battery row W06).
    assert "**Read `roadmap_ids`, falling back to `task_ids`**" in step1c, (
        "Step 1c no longer applies the Phase-23a compat shim, so a legacy doc keyed "
        "on task_ids passes this gate unheld and is routed — the stranding path, "
        "reached through the gate that exists to close it"
    )


def test_zero_checks_is_routed_to_a_stop_not_to_the_merge():
    para = _paragraph_containing(_skill(), "Command 4b is a gate")
    # Punctuation-agnostic: `STOP — do not run command 5` is the same instruction
    # (false kill N07). The polarity is what matters, not the sentence break.
    assert "STOP" in para and re.search(r"[Dd]o not run command 5", para), (
        "a `total_count` of 0 no longer stops the close — it falls through to the "
        "unconditional merge, which is the filed defect"
    )
    assert "could not measure" in para, (
        "the third state is no longer named as could-not-measure; green and red "
        "alone is the shape this gate exists to break"
    )


def test_the_held_back_row_does_not_force_1c_into_1bs_fields():
    fence = _fence_containing(_skill(), "Held-back docs: <N>")
    assert "Two reasons, and they need different evidence" in fence, (
        "the Held-back row collapses the two hold reasons again — a 1c hold has "
        "rev-list 0, which reads as 'merged fine' beside 'held'"
    )
    assert "branch retained by Step 6" in fence


def test_step_4d1_names_the_zero_check_verdict_as_out_of_its_scope():
    para = _paragraph_containing(_skill(), "A third cause is not a stuck PR at all")
    assert "command 4b" in para, "4d-1 no longer points the third verdict at its owner"
    assert re.search(r"re-runn?ing `/review-close` inherits the condition", para), (
        "4d-1 no longer says re-running does not help — a fresh integration PR "
        "inherits the same registration condition"
    )


def test_the_gh_api_rule_is_seeded_and_asserted():
    rule = "Bash(gh api:*)"
    assert rule in SETTINGS.read_text(encoding="utf-8"), f"{rule} no longer seeded"
    assert _required_rule_bullet(rule), (
        "the skill runs `gh api` but its rule is no longer a REQUIRED bullet"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Q-327 — a task marked done whose human step never happened
# ─────────────────────────────────────────────────────────────────────────────


def _round_trip_body() -> str:
    """The shipped Step 4c `tasks/index.yml` heredoc, verbatim and dedented."""
    text = _skill()
    fence = _fence_containing(text, "closed.append(t['id'])")
    m = re.search(r"python3 - <<'PY'\n(.*?)\n\s*PY\b", fence, re.S)
    assert m, "the Step 4c round-trip is no longer a `python3 - <<'PY'` heredoc"
    return textwrap.dedent(m.group(1))


def _run_round_trip(tmp_path: Path, tasks: list[dict], ids: list[str]) -> tuple[subprocess.CompletedProcess, dict]:
    """Execute the SHIPPED heredoc against a real git repo. Verbatim, not retyped."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    # Exercise the heredoc's OWN PyYAML bootstrap rather than routing around it:
    # it globs `<repo>/.venv/lib/python*/site-packages`, so give the fixture one
    # pointing at this checkout's. Running the block under a venv interpreter
    # instead would test a shape no consumer is told to use.
    _sp = Path(yaml.__file__).resolve().parent.parent
    _link = tmp_path / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    _link.mkdir(parents=True)
    (_link / "site-packages").symlink_to(_sp)
    for k, v in (("user.email", "t@example.com"), ("user.name", "T")):
        subprocess.run(["git", "-C", str(tmp_path), "config", k, v], check=True)
    (tmp_path / "tasks" / "open").mkdir(parents=True)
    (tmp_path / "tasks" / "archive").mkdir(parents=True)
    for t in tasks:
        (tmp_path / "tasks" / "open" / f"{t['id']}.md").write_text("# body\n", encoding="utf-8")
    # The runtime artifacts the hold is SUPPOSED to preserve. Without these the
    # executed column cannot see `for tid in closed:` widened to `closed + held`,
    # which drops a held task's lock, its parked marker (plan + verdict, NEVER
    # committed, unrecreatable) and its claim artifacts — the three things the
    # heredoc's own comment says are withheld. The round's guards lens planted
    # exactly that mutation and this fixture was blind to it.
    for t in tasks:
        (tmp_path / "sysop" / "runtime" / "locks").mkdir(parents=True, exist_ok=True)
        (tmp_path / "sysop" / "runtime" / "locks" / f"{t['id']}.lock").write_text(
            f"task_id: {t['id']}\nbranch: feat/{t['id']}\n", encoding="utf-8")
        (tmp_path / "sysop" / "runtime" / "parked").mkdir(parents=True, exist_ok=True)
        (tmp_path / "sysop" / "runtime" / "parked" / f"{t['id']}__20260829.md").write_text(
            "plan + verdict\n", encoding="utf-8")
        cd = tmp_path / "sysop" / "runtime" / "claim" / t["id"] / "run1"
        cd.mkdir(parents=True, exist_ok=True)
        (cd / "plan.md").write_text("plan\n", encoding="utf-8")
    index = tmp_path / "tasks" / "index.yml"
    index.write_text(yaml.safe_dump({"tasks": tasks}, sort_keys=False), encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "seed"], check=True)

    body = _round_trip_body()
    id_literal = ", ".join(f'"{i}"' for i in ids)
    body = re.sub(r'ids = \[[^\]]*\]', f"ids = [{id_literal}]", body, count=1)
    assert "<ROADMAP_ID" not in body, "placeholder substitution failed"
    script = f"python3 - <<'PY'\n{body}\nPY\n"
    r = subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True)
    written = yaml.safe_load(index.read_text(encoding="utf-8"))
    return r, written


def _task(tid: str, user_action: bool) -> dict:
    return {
        "id": tid, "title": f"t {tid}", "status": "in_progress", "phase": 1,
        "user_action": user_action, "body": f"open/{tid}.md",
    }


def test_a_user_action_task_is_held_rather_than_closed(tmp_path):
    """The behaviour, executed. This is the filing's whole subject."""
    r, written = _run_round_trip(tmp_path, [_task("T-1", True)], ["T-1"])
    assert r.returncode == 0, f"heredoc failed: {r.stderr}"
    entry = written["tasks"][0]
    assert entry["status"] == "in_progress", (
        "a `user_action: true` task was flipped to done on the strength of a merged "
        "diff — the human step never happened and every downstream gate now reports "
        "success"
    )
    assert "completed_date" not in entry, "a held task was stamped with a completion date"
    assert entry["body"] == "open/T-1.md", "a held task's body was archived"
    assert (tmp_path / "tasks" / "open" / "T-1.md").exists(), "held task's body was moved"
    assert "HELD_USER_ACTION: T-1" in r.stdout, "the hold was not reported"


def test_a_held_tasks_runtime_artifacts_survive(tmp_path):
    """The three things the hold says it withholds — checked on disk.

    Found by the round's guards lens: `for tid in closed:` widened to
    `closed + held` drops a held task's lock, its parked marker and its claim
    artifacts, and the previous fixture created none of them, so the executed
    column — the column this phase rated strongest — could not see it. The parked
    marker is the sharp one: it holds a plan and a verdict that are never
    committed, so its removal is unrecoverable.
    """
    r, _ = _run_round_trip(tmp_path, [_task("T-6", True)], ["T-6"])
    assert r.returncode == 0, f"heredoc failed: {r.stderr}"
    rt = tmp_path / "sysop" / "runtime"
    assert (rt / "locks" / "T-6.lock").exists(), (
        "a HELD task lost its lock — the close released work the human has not "
        "finished, and the 'is anyone working on this?' signal now says no"
    )
    assert (rt / "parked" / "T-6__20260829.md").exists(), (
        "a HELD task lost its parked marker — plan + verdict, never committed, "
        "so this is unrecoverable"
    )
    assert (rt / "claim" / "T-6" / "run1" / "plan.md").exists(), (
        "a HELD task lost its claim artifacts"
    )
    assert "LOCKS_REMOVED: (none)" in r.stdout


def test_a_closed_tasks_runtime_artifacts_are_cleaned(tmp_path):
    """The negative control for the above. A hold that preserves everything for
    everyone is not a hold — it is a disabled cleanup."""
    r, _ = _run_round_trip(tmp_path, [_task("T-7", False)], ["T-7"])
    assert r.returncode == 0, f"heredoc failed: {r.stderr}"
    rt = tmp_path / "sysop" / "runtime"
    assert not (rt / "locks" / "T-7.lock").exists(), "an ordinary close no longer drops its lock"
    assert not list((rt / "parked").glob("T-7__*.md")), "an ordinary close no longer clears its parked marker"
    assert "LOCKS_REMOVED: T-7" in r.stdout


def test_a_normal_task_still_closes(tmp_path):
    """The negative control. A hold that holds everything is not a fix.

    Without this, deleting the `if t.get('user_action')` guard's *condition* —
    holding every task — would pass every other case in this file.
    """
    r, written = _run_round_trip(tmp_path, [_task("T-2", False)], ["T-2"])
    assert r.returncode == 0, f"heredoc failed: {r.stderr}"
    entry = written["tasks"][0]
    assert entry["status"] == "done", "an ordinary task no longer closes"
    assert entry["completed_date"], "an ordinary task closed with no completed_date"
    assert entry["body"] == "archive/T-2.md", "an ordinary task's body was not archived"
    assert "CLOSED_IDS: T-2" in r.stdout


def test_held_and_closed_tasks_are_reported_separately_in_one_run(tmp_path):
    """Mixed run: the discriminating fixture. Same command, two outcomes."""
    r, written = _run_round_trip(
        tmp_path, [_task("T-3", True), _task("T-4", False)], ["T-3", "T-4"]
    )
    assert r.returncode == 0, f"heredoc failed: {r.stderr}"
    by_id = {t["id"]: t for t in written["tasks"]}
    assert by_id["T-3"]["status"] == "in_progress"
    assert by_id["T-4"]["status"] == "done"
    assert "HELD_USER_ACTION: T-3" in r.stdout
    assert "CLOSED_IDS: T-4" in r.stdout


@pytest.mark.parametrize(
    "value, expect_held",
    [
        (True, True),          # the ordinary hold
        (False, False),        # the ordinary close
        (None, False),         # explicit null — a task predating the field
        ("false", True),       # MALFORMED, and it must hold. See below.
        ("true", True),        # malformed the other way; same answer, same reason
        (1, True),
        (0, False),
        (_MISSING, False),     # the key absent entirely — a task predating the field
    ],
)
def test_a_malformed_user_action_resolves_toward_holding(tmp_path, value, expect_held):
    """The hostile-input corpus, built before the rationale was written.

    `validate_tasks.py` requires a bool, but it runs at the END of Step 4c — so a
    malformed index reaches the round-trip first. The predicate is truthiness-based
    on purpose: holding a task that should have closed costs one
    `clear_user_action.py`; closing one that should have held is the defect the
    hold exists to remove.

    **This test exists to stop the obvious tightening.** `is True` looks stricter
    and is more dangerous: the string `"true"` would then CLOSE a task whose human
    step is outstanding — inverting the bias on exactly the input the strictness
    was supposed to protect against.
    """
    t = _task("T-9", False)
    if value is _MISSING:
        del t["user_action"]
    else:
        t["user_action"] = value
    r, written = _run_round_trip(tmp_path, [t], ["T-9"])
    assert r.returncode == 0, f"heredoc failed: {r.stderr}"
    held = "T-9" in re.search(r"^HELD_USER_ACTION: (.*)$", r.stdout, re.M).group(1)
    assert held is expect_held, (
        f"user_action={value!r} resolved to held={held}; expected {expect_held}"
    )
    assert (written["tasks"][0]["status"] == "in_progress") is expect_held


def test_a_held_task_is_not_misreported_as_missing_from_the_index(tmp_path):
    """The partition property, and a defect this phase nearly introduced.

    `NOT_IN_INDEX` was `ids - closed`. A held task is in `ids` and not in
    `closed`, so the first cut of this fix reported a task that exists as one
    that does not — sending the operator to look for a missing entry instead of
    an outstanding human step.
    """
    r, _ = _run_round_trip(tmp_path, [_task("T-5", True)], ["T-5", "T-NOPE"])
    assert r.returncode == 0, f"heredoc failed: {r.stderr}"
    m = re.search(r"^NOT_IN_INDEX: (.*)$", r.stdout, re.M)
    assert m, f"the round-trip printed no NOT_IN_INDEX row: {r.stdout!r}"
    not_in_index = m.group(1)
    assert "T-5" not in not_in_index, (
        "a HELD task is reported as absent from the index it was read from"
    )
    assert "T-NOPE" in not_in_index, (
        "a genuinely absent id is no longer reported — the row lost its job while "
        "being taught about holds"
    )


def test_a_held_task_keeps_its_pending_doc_so_a_later_run_can_close_it():
    """The stranding path — found by author-side rule 2, in this phase's own fix.

    The first cut did what the filing prescribed: route the doc entries as normal
    and hold only the three completion mutations. That strands the task. Step 6
    deletes the pending-docs this step consolidated; a routed doc is consolidated;
    and the pending-doc is the ONLY carrier of `roadmap_ids` into the round-trip.
    So the doc would be gone, the task would sit `in_progress` with its lock held,
    and nothing could ever close it — `clear_user_action.py` flips the flag and
    prints that an `in_progress` task stays off the frontier.

    A silent permanent stall, arriving from a fix for a silent false close.
    """
    text = _skill()
    step1c = text[text.index("1c. **Hold back any pending-doc"):
                  text.index("2. **If none found**")]
    assert "do not route this doc at all this run" in step1c, (
        "Step 1c no longer holds the whole doc — routing it and holding only the "
        "flip consumes the carrier and strands the task"
    )
    assert "user_action outstanding" in step1c, (
        "Step 1c no longer names the Held-back reason, so the hold is invisible in "
        "the one report row that would show it"
    )
    # The failure mode must stay written down. A future reader who only sees the
    # narrower remedy in `Q-327` will re-derive the stranding unless the file says
    # why the wider one was taken.
    assert "clear_user_action.py" in step1c
    # Pin the SENTENCE, not the word. `stranded` also occurs in the paragraph above
    # this one, so a word-level check passed while the sentence naming the failure
    # class was deleted (battery row S04) — the Q-340 shape yet again.
    assert (
        "**A silent permanent stall, arriving from a fix for a silent false close.**"
        in step1c
    ), (
        "Step 1c no longer names the failure class it exists to prevent — the next "
        "reader sees only the narrow remedy in Q-327 and re-introduces the stall"
    )


def test_step_8_cross_checks_the_hold_against_the_held_back_docs_row():
    """Two rows must agree; a hold in one and not the other IS the stranding."""
    fence = _fence_containing(_skill(), "Documentation written:")
    remaining = fence[fence.index("Remaining:"):]
    # Polarity: `Held-back docs:` survives an edit that tells the reader to IGNORE
    # it (battery row S05). Pin the instruction, not the referent.
    assert "The invariant to check is the ordinary arm's:" in remaining, (
        "the Remaining row no longer INSTRUCTS the cross-check — naming the rows "
        "while telling the reader to skip them is the reversal, and that check is "
        "the only place a stranded task becomes visible"
    )
    assert "`Held-back docs:` row AND a retained branch" in remaining, (
        "the invariant no longer names BOTH halves of the carrier — a held doc "
        "whose branch Step 6 deleted halts the next close instead of resuming it"
    )
    assert "stranded task" in remaining
    # The two arms are different events and the report must not merge them: the
    # ordinary hold prints HELD_USER_ACTION `(none)`, because Step 1c stops the ids
    # ever reaching the heredoc. A row demanding both is false by construction —
    # which is what the first cut of this bullet asserted.
    assert "ORDINARY (Step 1c)" in remaining and "ANOMALOUS" in remaining, (
        "Step 8 no longer distinguishes the Step-1c hold from the heredoc hold; "
        "they are different events with opposite evidence"
    )
    assert "RETAINED by Step 6" in remaining, (
        "Step 8 no longer reports branches retained for a held doc — an operator "
        "reads them as leaked and deletes the other half of the carrier"
    )


def test_the_heredoc_hold_is_declared_defence_in_depth_not_the_primary_gate():
    """Both arms must exist, and the record must say which is which.

    The heredoc arm alone routes the doc first, so on its own it is the stranding
    bug. Step 1c alone is skippable — the id list is a hand-substituted literal.
    """
    fence = _fence_containing(_skill(), "THIS IS DEFENCE IN DEPTH")
    para = fence[fence.index("THIS IS DEFENCE IN DEPTH"):fence.index("if t.get('user_action')")]
    # The comment is line-wrapped inside a `#`-prefixed block, so compare on the
    # normalised text rather than the raw slice — otherwise this check is really a
    # check about where the author broke the line.
    flat = " ".join(para.replace("#", " ").split())
    assert "Step 1c above holds the whole pending-doc back" in flat
    assert re.search(r"\bby hand\b", flat, re.I) and "literal" in flat, (
        "the arm no longer says why a second gate is needed — without the reason "
        "it reads as redundant and gets deleted"
    )


def test_step_6_retains_the_branch_of_a_held_back_doc():
    """The other half of the carrier — found by the round's claims lens.

    Step 1c holds the doc; Step 6 deleted the branch under BOTH policies. The
    doc's `branch:` is what step 1b resolves, so on the next close the ref no
    longer resolves and step 1b's stop-and-ask fires: a deliberate hold became a
    hard stop on every subsequent close. The file already documented this exact
    self-inflicted stop for the cherry-pick case, three paragraphs above Step 1c.
    """
    text = _skill()
    start = text.index("**HARD RULE — do not delete a branch whose pending-doc")
    rule = text[start:text.index("**`direct` policy — per-branch cleanup.**", start)]
    assert "both** policies" in rule, (
        "Step 6's retention rule no longer covers both merge policies — `direct`'s "
        "safe `git branch -d` succeeds on a genuinely merged branch too"
    )
    assert "stop and ask" in rule, (
        "the rule no longer names the failure it prevents, so it reads as tidiness "
        "and gets dropped"
    )
    assert "sysop/runtime/pending-docs/" in rule, (
        "the rule no longer says how to derive the retained set"
    )
    # Ordering: the rule must precede BOTH cleanup lists, or it is advice after
    # the deletion it is meant to prevent — the same defect Q-326 is about.
    assert text.index("HARD RULE — do not delete a branch") < text.index(
        "**`direct` policy — per-branch cleanup.**"
    ) < text.index("**`pr` policy — per-branch cleanup**")


def test_step_1c_says_the_doc_is_only_half_the_carrier():
    text = _skill()
    step1c = text[text.index("1c. **Hold back any pending-doc"):
                  text.index("2. **If none found**")]
    assert "The doc is only half the carrier, and the other half is the branch" in step1c, (
        "Step 1c claims the doc alone resumes the close — it does not; Step 6 "
        "deletes the branch step 1b needs to resolve"
    )
    assert "neither works alone" in step1c


def test_the_schema_concession_and_the_remedy_do_not_diverge():
    """`schema.md` conceded the gap in prose; the fix must be recorded there too."""
    schema = SCHEMA.read_text(encoding="utf-8")
    assert "Nothing verifies the steps were performed" in schema, (
        "the § User ops concession was deleted rather than scoped — the honest "
        "statement of what the flag does NOT do is load-bearing"
    )
    para = _paragraph_containing(schema, "It can no longer be *closed* that way")
    assert "clear_user_action.py" in para, (
        "§ User ops no longer names how a held task is released"
    )
    assert "held back in `sysop/runtime/pending-docs/`" in para, (
        "schema.md describes the ROUTED-doc design — the one this phase built, "
        "found stranding, and replaced. It shipped that way for three commits with "
        "this guard pinning it, which is a guard certifying the wrong contract."
    )
    # normalise: the sentence is line-wrapped in the shipped file
    assert "not routed at all this run" in " ".join(para.split())
    assert "retained by a" in para and "Step 6" in para, (
        "schema.md no longer states that the branch is retained too — a reader "
        "implementing from this section alone rebuilds the halt"
    )


def test_the_round_trip_no_longer_claims_to_be_unconditional():
    para = _paragraph_containing(_skill(), "The Roadmap column is **informational only**")
    assert "user_action" in para, (
        "the paragraph still describes the round-trip as driven by data presence "
        "alone — the sentence the filing quoted, and it is now false"
    )


def test_step_8_reports_held_tasks_under_remaining():
    """Scoped to the `Remaining:` block, not to the whole report fence.

    `HELD_USER_ACTION` appears twice in that fence — once in the
    `Documentation written` row and once here — so a fence-wide check passed while
    this bullet was gutted (battery row P08). The row and the bullet do different
    jobs: one accounts for the ids, this one tells the operator what to do.
    """
    fence = _fence_containing(_skill(), "Documentation written:")
    remaining = fence[fence.index("Remaining:"):]
    assert "HELD on `user_action`" in remaining, (
        "Step 8's Remaining block no longer names held tasks — the hold happens and "
        "the operator is never told which task is waiting on them"
    )
    assert "clear_user_action.py" in remaining, (
        "the Remaining block no longer tells the operator how to release a held task"
    )
    assert "HELD_USER_ACTION" in fence[:fence.index("Remaining:")], (
        "the `Documentation written` accounting row lost its held-ids column"
    )


# ─────────────────────────────────────────────────────────────────────────────
# The polarity pins below are verbatim, and the record says plainly what that
# buys: the INSTANCE, not the class. The round's guards lens inverted eight more
# directives while keeping every required token — a fourth independent
# measurement of the class (78% survival) after Q-318 (76-81%), Phase 179 (0 of
# 21) and Q-325 (56.5%). These are pinned because each flips a gate into
# producing a wrong DURABLE state; the residual is filed, not fought. See Q-343.

def test_the_gates_that_flip_durable_state_keep_their_polarity():
    text = _skill()
    step1c = " ".join(text[text.index("1c. **Hold back any pending-doc"):
                           text.index("2. **If none found**")].split())
    assert ("**If any of those ids has a truthy `user_action`, do not route this doc "
            "at all this run**") in step1c, (
        "Step 1c's condition lost its polarity. Inverting `any` to `all` narrows the "
        "hold to docs where EVERY task is held; inverting the value fires it on every "
        "task that needs no human step. Both were walked by the round."
    )

    empty = _paragraph_containing(text, "And it does not mean the reader failed to run")
    assert "**STOP** — do not take the empty arm below" in " ".join(empty.split()), (
        "the batch-set arm's stop is inverted or softened — a could-not-measure then "
        "takes the empty arm and the close reports success over a Pending batch"
    )

    gate = " ".join(_paragraph_containing(text, "Command 4b is a gate").split())
    assert "resolves against merging" in gate, (
        "the unmeasured state no longer resolves AGAINST merging — reversing this "
        "one clause turns the whole gate into a rubber stamp"
    )
    assert "Read its number before running command 5" in gate, (
        "the gate no longer runs before command 5; a count read after the squash "
        "cannot prevent it"
    )

    d1 = " ".join(_paragraph_containing(text, "A third cause is not a stuck PR at all").split())
    assert "Stop at command 4b and follow its note." in d1, (
        "4d-1 no longer routes the zero-check case back to its owner, so it falls "
        "into stuck-PR recovery that cannot apply"
    )


def test_step_1c_names_the_right_namespace_index_and_directory():
    """Re-pointing 1c at a plausible-but-wrong artifact is silent and total.

    The round pointed it at `review_task_ids` (the namespace this same skill
    spends a paragraph forbidding), at `sysop/runtime/index.yml`, and at a
    `held-docs/` directory that does not exist. All three passed.
    """
    text = _skill()
    step1c = " ".join(text[text.index("1c. **Hold back any pending-doc"):
                           text.index("2. **If none found**")].split())
    assert "`roadmap_ids`, falling back to `task_ids`" in step1c
    assert "review_task_ids" not in step1c, (
        "Step 1c reads the documentary namespace — the one Step 4c's own routing "
        "note says is never consulted for task state"
    )
    assert "`tasks/index.yml`" in step1c, "1c no longer names the index it looks tasks up in"
    assert "`sysop/runtime/pending-docs/`" in step1c, (
        "1c no longer names the directory the doc is left in"
    )
    assert "sysop/runtime/index.yml" not in step1c


def test_step_1c_runs_before_routing_not_after():
    """Ordering is the mechanism: 1c after routing is the stranding bug."""
    text = _skill()
    assert text.index("1c. **Hold back any pending-doc") < text.index(
        "For each entry, generate the doc content from"
    ), "Step 1c no longer precedes doc generation — held docs are routed first"


def test_the_step_8_rows_the_hold_depends_on_still_exist():
    """The cross-check asserted the REFERENCE; the round deleted the referent."""
    fence = _fence_containing(_skill(), "Documentation written:")
    assert re.search(r"^Held-back docs: <N>", fence, re.M), (
        "Step 8's `Held-back docs:` row is gone — the row the user_action hold's "
        "own cross-check points at, and the only evidence an ordinary hold produces"
    )
    remaining = fence[fence.index("Remaining:"):]
    assert "python3 sysop/scripts/clear_user_action.py <TASK_ID>" in remaining, (
        "Step 8 no longer gives the operator the command that releases a held task"
    )


# Q-328 — the convention gate that reads one section of three
# ─────────────────────────────────────────────────────────────────────────────


def test_the_doc_only_skip_predicate_reads_all_three_convention_sources():
    text = _skill()
    start = text.index("**0. Per-target doc-only skip")
    # End at the ENUMERATION's close, not at the step's. The wider slice swept in
    # the `Check the second condition` note that follows, which also names
    # `## Testing Patterns` — so dropping the sibling-section source from the list
    # left the token alive next door and this check passed (battery row P03, the
    # third instance of the Q-340 class in this phase alone). The predicate's
    # three sources are the three numbered items; assert them there.
    close = text.index("If any of the three yields a rule", start)
    # Two scopes, deliberately. `enumeration` is where the three sources must live;
    # `predicate` extends just far enough to hold the concluding directive, and no
    # further — the note after it names the same tokens for a different purpose.
    enumeration = text[start:close]
    predicate = text[start:text.index("Docs-only cycles are not an edge case", close)]
    assert (
        "If any of the three yields a rule that could govern the touched types, "
        "spawn the agent and let it route."
    ) in " ".join(predicate.split()), (
        "the predicate's concluding directive is gone — battery row P04 replaced it "
        "with a sentence reinstating the narrow reading while keeping all three "
        "source names, so a names-only check passed over a reversal. Pinned "
        "verbatim; this closes the instance, not the class (see Q-325)."
    )
    # Each source must be its OWN numbered item. A bare `in enumeration` check
    # passed when item 1 was deleted, because the lead-in sentence three lines
    # above still names `## Prevention Conventions` — the token-next-door class
    # again, inside the very slice re-pointed to close two earlier instances.
    items = re.findall(r"^\s+(\d)\. (.*(?:\n(?!\s+\d\. ).*)*)", enumeration, re.M)
    assert [n for n, _ in items] == ["1", "2", "3"], (
        f"Step 2b's predicate no longer enumerates three sources; found {[n for n, _ in items]}"
    )
    bodies = {n: b for n, b in items}
    for n, source, why in (
        ("1", "Prevention Conventions", "the original single source"),
        ("2", "Testing Patterns", "the sibling top-level section the template ships"),
        ("3", "convention_map.project.md", "the consumer overlay that routes globs"),
    ):
        assert source in bodies[n], (
            f"predicate source {n} is no longer {source} ({why}) — a target governed "
            f"only by it is skipped while the run reports a clean gate"
        )
        # A source listed and then waived is worse than one omitted: it reads as
        # coverage. The round rewrote items 2 and 3 into "out of scope here … do
        # not read it" while keeping every token.
        assert not re.search(r"\bskip (?:them|it)\b|\bdo not read\b|\bout of scope\b|"
                             r"\bnot part of this predicate\b|\bmay be skipped\b",
                             bodies[n], re.I), (
            f"predicate source {n} is listed and then waived — that is a reversal "
            f"wearing the shape of coverage"
        )


def test_the_skip_escape_is_not_sealed_inside_one_section():
    para = _paragraph_containing(_skill(), "Check the second condition; do not assume it")
    # Emphasis-agnostic: `__do not skip__` is the same instruction, and the round's
    # controls reddened on it (false kill N05). Pin the DIRECTIVE, not the markup.
    assert re.search(r"(\*\*|__)do not skip(\*\*|__)", para), (
        "the escape's directive is no longer `do not skip` — battery row P05 "
        "inverted it to `skip anyway` while keeping every other required token, "
        "which is the polarity class Q-318/Q-325 measure at 56-81% survivable. "
        "Pinning the directive verbatim closes the INSTANCE, not the class."
    )
    assert "any of the three" in para, (
        "the do-not-skip escape is scoped to subsections again — it then misses the "
        "same rules the predicate misses, from the same blind spot"
    )


def test_the_skill_no_longer_contradicts_the_shipped_template():
    """`Testing Patterns` is a top-level section; the skill said it was a subsection."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert re.search(r"^\| `## Testing Patterns` \|", workflow, re.M), (
        "premise gone: WORKFLOW § 6.1 no longer lists `## Testing Patterns` as its "
        "own required section — re-derive Q-328 before trusting this module"
    )
    # `Q-342` REMOVED the parenthetical this test used to scan. That change makes
    # the guarded property unreachable by the old route and TRUE by a stronger one:
    # step 1 no longer offers a subsection list at all, because it now pastes
    # `## Testing Patterns` as the sibling top-level section § 6.1 says it is.
    # Re-pointed rather than deleted -- a removed guard leaves a roster that reads
    # as coverage (Phase 204).
    skill = _skill()
    assert "The set is `## Prevention Conventions` + `## Testing Patterns`" in skill, (
        "step 1 no longer names Testing Patterns as a member of the pasted set -- "
        "Q-328's contradiction is reopened from the other side"
    )
    # Scope to the EXAMPLES sentence only. `Q-342` made the surrounding paragraph
    # name `## Testing Patterns` legitimately -- as the sibling top-level section
    # it is -- so a whole-paragraph scan now reports the fix as the defect. What
    # must stay true is narrower and is the actual Q-328 property: it is never
    # offered as one of the SUBSECTION examples.
    #
    # ⚠ The FIRST re-point of this test used a fixed two-anchor window
    # (`Subsection names…` .. `**The set is`) and that was a NET WEAKENING, caught
    # by Phase 247's round. The scan it replaced was balanced-delimiter for a
    # reason an earlier round had already established -- "an earlier `).` truncates
    # the slice and lets the example be re-added outside it" -- and a fixed window
    # has the identical hole one clause further out: the round re-added the example
    # immediately after the bolded set sentence and walked straight through. The
    # span therefore covers the examples sentence AND the set sentence that follows.
    para = _paragraph_containing(skill, "Subsection names vary by project")
    start = para.index("Subsection names vary by project")
    set_at = para.index("**The set is", start)
    close = para.index("**", set_at + len("**The set is"))
    tail = para[close:]
    end = close + (tail.index(". ") + 2 if ". " in tail else len(tail))
    span = para[start:end]
    # Not "the string is absent" -- `Q-342` makes the widened span name it
    # legitimately, as `## Testing Patterns`, the sibling top-level section § 6.1
    # says it is. The Q-328 property is that it never appears as a BARE subsection
    # name: every occurrence in this span must carry its `## ` heading marker.
    bare = [
        i for i in range(len(span))
        if span.startswith("Testing Patterns", i) and not span[:i].endswith("## ")
    ]
    assert not bare, (
        "`Testing Patterns` is offered as a subsection of Prevention Conventions "
        "again, contradicting WORKFLOW § 6.1's required-sections table"
    )
