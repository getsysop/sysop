"""`/review-close --prepare` / `--resume <run-id>` (`Q-603`, Phase 363) — the skill text's half.

`tests/test_close_run.py` covers the script. This module covers what the skill tells a runner:
the commands it prescribes are run here exactly as written (placeholders substituted) against a
fixture with the script installed where `install.sh` puts it, and each step that asks or stops
carries its `--prepare` arm inside that step, where a runner meets it.
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

REPO = Path(__file__).resolve().parent.parent
CLOSE = REPO / "core/skills/review-close/SKILL.md"
SCRIPT = REPO / "core/companion/scripts/close_run.py"
SETTINGS = REPO / "core/companion/.claude/settings.json"
RULE = "Bash(python3 sysop/scripts/close_run.py:*)"

_ENV = {k: v for k, v in os.environ.items()
        if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
_ENV.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")


def _text() -> str:
    return CLOSE.read_text(encoding="utf-8")


def _span(start: str, end: str) -> str:
    t = _text()
    i = t.index(start)
    return t[i:t.index(end, i + len(start))]


def _section() -> str:
    return _span("## `--prepare` and `--resume <run-id>` (`Q-603`)",
                 "## `--request-review` and `--land <run-id>` (`Q-411`)")


def _commands() -> dict[str, str]:
    found = re.findall(r"^\s*(python3 sysop/scripts/close_run\.py (\w+) .*)$", _section(), re.M)
    by = {}
    for line, sub in found:
        assert sub not in by, f"two `{sub}` commands in the section"
        by[sub] = line.strip()
    assert set(by) == {"begin", "finish", "load", "check", "consume"}, sorted(by)
    return by


def _sh(cwd: Path, cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", "-c", cmd], cwd=cwd, capture_output=True, text=True, env=_ENV)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    for cmd in ("git init -q -b main", "git config user.email t@t", "git config user.name t",
                "printf 'sysop/runtime/\\n.venv\\n' > .gitignore", "git add -A", "git commit -qm base",
                "git branch feat/a", "git branch feat/b"):
        assert _sh(root, cmd).returncode == 0, cmd
    (root / "sysop/scripts").mkdir(parents=True)
    # As a full-mode install lays them out: close_run.py imports the shared pending-doc reader.
    for name in ("close_run.py", "pending_doc_hold.py"):
        shutil.copy2(SCRIPT.parent / name, root / "sysop/scripts" / name)
    # PyYAML is a declared hard dependency, found in the project's venv as a consumer keeps it.
    # A placed worktree has no `.venv`; the venv pytest runs in stands in (CI has none, and its
    # bare python3 carries PyYAML).
    venv = REPO / ".venv" if (REPO / ".venv").is_dir() else (
        Path(sys.prefix) if sys.prefix != sys.base_prefix else None)
    if venv:
        (root / ".venv").symlink_to(venv)
    return root


def test_the_prescribed_commands_run_as_written(repo: Path) -> None:
    """Phase 168 rule 3: run what the change prescribes. Every `close_run.py` line in the
    section, in the order a prepare then a resume runs them."""
    cmds = _commands()
    begin = cmds["begin"].replace('"<default branch>"', '"main"').replace(
        '"<branch>" "<branch>"', '"feat/a" "feat/b"')
    assert "<" not in begin, begin
    r = _sh(repo, begin)
    assert r.returncode == 0, r.stderr
    out = r.stdout.splitlines()
    run_id = out[0].split(": ", 1)[1]
    run_dir = Path(out[1].split(": ", 1)[1])
    for line in out[2:]:
        Path(line.split(": ", 1)[1]).write_text("verdict: approve\n", encoding="utf-8")
    (run_dir / "questions.md").write_text("", encoding="utf-8")

    def sub(cmd: str) -> str:
        return cmd.replace("<run-id>", run_id).replace("<default branch>", "main")

    r = _sh(repo, sub(cmds["finish"]))
    assert r.returncode == 0 and f"RESUME: /review-close --resume {run_id}" in r.stdout, r.stdout + r.stderr
    for name in ("load", "check"):
        r = _sh(repo, sub(cmds[name]))
        assert r.returncode == 0, (name, r.stderr)
    assert r.stdout.strip() == "CURRENT"
    r = _sh(repo, sub(cmds["consume"]))
    assert r.returncode == 0, r.stderr
    assert json.loads((run_dir / "manifest.json").read_text())["consumed"]
    assert _sh(repo, sub(cmds["load"])).returncode == 2


def test_the_section_names_every_line_check_prints() -> None:
    """A `check` line the section does not route is a line a runner improvises on."""
    src = SCRIPT.read_text(encoding="utf-8")
    emitted = set(re.findall(r'f?"(GONE|RERUN ALL|RERUN 2b|RERUN 3|RERUN|NOTE|CURRENT)\b', src))
    assert emitted == {"GONE", "RERUN ALL", "RERUN 2b", "RERUN 3", "RERUN", "NOTE", "CURRENT"}
    sec = _section()
    for token in ("`GONE <branch>: …`", "`RERUN <branch>: …`", "`RERUN ALL: …`", "`RERUN 2b: …`",
                  "`RERUN 3: …`", "`NOTE: …`", "`CURRENT`"):
        assert token in sec, token


# Each arm in FULL, not its opening phrase: round 1's execution lens reversed five arms' bodies
# (Y01-Y05) behind an asserted bold lead.
@pytest.mark.parametrize("step,end,arm", [
    ('### 2a. Feature Branches', '3a. **Gitignored files the branch reads',
     '**Under `--prepare`, ask nothing in step 3a below and do not run its commit-or-copy block:** record each `IGNORED-REF:` line, and the error ask after that block, as a question (*`--prepare` and `--resume <run-id>`* above, item 2), and carry the branch on with its verdict marked `pending Q<n>`.'),
    ('### 2b. Prevention Convention Check', '### 2c.',
     '**Under `--prepare`, a `VERDICT: BLOCKED` in item 4 below stops only its branch, and on the unpushed-main group halts the prepare** (*`--prepare` and `--resume <run-id>`* above, item 3).'),
    ('### 2d. Test-Decision Verification', '### 2e.',
     '**Under `--prepare`, ask nothing in item 3 below:** record each discrepancy as a question (*`--prepare` and `--resume <run-id>`* above, item 2), and carry the branch on with its verdict marked `pending Q<n>`.'),
    ('## Step 3: Run Verification', '## Step 3c:',
     "**Under `--prepare`:** a failing command halts the prepare (*`--prepare` and `--resume <run-id>`* above, item 4). Item 5's ask and a silently denied command leave Step 3 not run, with the reason in the run directory, and the resume runs it (*`--prepare` and `--resume <run-id>`* above, item 2)."),
    ('## Step 3c: Manual Smoke Gate', '**1. Detect signals.**',
     "**Under `--prepare`, run step 1 as written and ask nothing from step 2 on:** record each signal as a question (*`--prepare` and `--resume <run-id>`* above, item 2), record nothing with the recorder, drive nothing, and go to the prepare's `finish` (item 6)."),
    ('## Step 3b: Prepare Worktrees for Merge', '## Step 4:',
     '**Under `--prepare`, do not start this step:** the prepare ends at Step 3c (*`--prepare` and `--resume <run-id>`* above, item 6).'),
])
def test_each_step_that_asks_or_stops_carries_its_prepare_arm(step: str, end: str, arm: str) -> None:
    assert arm in _span(step, end), f"{step}: the `--prepare` arm moved out of its step or was removed"


def test_the_flags_are_declared_and_gated() -> None:
    t = _text()
    assert ('argument-hint: "[--dry-run | --prepare | --resume <run-id> | --request-review '
            '[--agent <name>] | --land <run-id>]"') in t
    sec = _section()
    assert "**Read this section only when `$ARGUMENTS` contains `--prepare` or `--resume`.**" in sec
    # Phase 365 added two flags: the one legal pair is `--resume` with `--request-review`.
    assert ("The flags combine only as `--resume <run-id> --request-review`. Any other pair of "
            "`--dry-run`, `--prepare`, `--resume`, `--request-review` and `--land`: stop and say so."
            ) in sec
    assert RULE.replace("Bash(", "`Bash(").replace(":*)", ":*)`") in sec
    assert RULE in json.loads(SETTINGS.read_text(encoding="utf-8"))["permissions"]["allow"]
    assert "If `$ARGUMENTS` contains `--prepare` or `--resume`, the section" in t


def test_step_4d_prints_the_sha_after_each_push() -> None:
    """Y06: the SHA Step 6 compares against is local <default branch> at the push, in both shapes."""
    pr = _span("#### `pr` policy", "## Step 5:")
    for push in ('git push origin "$INTEGRATION_BRANCH"\n', 'git push origin "<approved branch name>"\n'):
        after = pr[pr.index(push) + len(push):]
        assert after.lstrip().startswith("# 2b. print local <default branch>'s SHA"), push
        assert after.split("\n")[1] == 'git rev-parse "<default branch>"', push


def test_the_prepare_never_reaches_step_3b_and_the_resume_consumes_before_it() -> None:
    sec = _section()
    prep = sec[sec.index("### Under `--prepare`"):sec.index("### Under `--resume <run-id>`")]
    res = sec[sec.index("### Under `--resume <run-id>`"):]
    assert "stops before Step 3b" in prep and "Nothing from Step 3b on runs." in prep
    # Step 1 and the GONE check come before any answer is applied (round 1, semantics lens:
    # applying first defeated "a merged branch is dropped"), and a second check after.
    assert res.index("**Load the run:**") < res.index("**Run Step 1 in full**") \
        < res.index("**Check what moved.**") < res.index("**Ask the recorded questions**") \
        < res.index("**Apply each answer `answers.md` does not mark `applied`**") \
        < res.index("**Check again**") < res.index("Immediately before Step 3b")
    assert "that is a park, never an answer" in res
    # X16: without a fetch, nothing moves origin before `check`, so `RERUN 3: origin/…` never fires
    chk = res[res.index("**Check what moved.**"):res.index("**Ask the recorded questions**")]
    assert chk.index('git fetch origin "<default branch>"') < chk.index("close_run.py check")
    # Round 2 (semantics): a branch the first check marks RERUN must not have its stale recorded
    # questions asked or applied (a smoke driven against changed text).
    assert "- `GONE <branch>: …` — drop the branch:" in chk
    assert "- `RERUN <branch>: …` or `RERUN ALL: …` — set aside that branch's recorded questions" in chk
    assert "- `RERUN 3: …` — set aside the recorded Step 3c questions" in chk
    ask = res[res.index("**Ask the recorded questions**"):res.index("**Apply each answer")]
    assert "not set aside in item 3, except a gone or SKIP branch's" in ask
    assert "**Every answer given live, in this item or item 6, also goes in `answers.md`:**" in res
    again = res[res.index("**Check again**"):res.index("Immediately before Step 3b")]
    assert "When the line names local `<default branch>`, also run Step 2b for the unpushed-main group." in again
    assert "run Steps 2a to 2e for that branch, unless item 3 dropped it." in again
    assert "**On any non-zero exit from `close_run.py`, stop and show its stderr.**" in res
    assert "After applying an answer, append `applied` under it." in res
    assert "takes that answer's outcome: never apply or drive it twice.**" in res
    prep_items = prep[prep.index("3. **A `VERDICT: BLOCKED`"):prep.index("4. **Every other stop")]
    assert "A `VERDICT: BLOCKED` on the unpushed-main group halts the prepare (item 4)." in prep_items
    assert "Step 3c: Manual" not in prep and "Step 1b" not in prep.split("The parks:")[1].split("3. **")[0]


def test_the_claim_task_resume_mentions_name_claim_task() -> None:
    """Spec § 1: two existing `--resume` mentions meant `/claim-task --resume`."""
    t = _text()
    assert t.count("a `/claim-task --resume` after") == 2
    assert not re.search(r"(?<!claim-task )`--resume` after", t)
