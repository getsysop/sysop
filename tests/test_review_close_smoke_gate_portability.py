"""Phase 218 — Step 3c's bash preamble must PARSE on the oldest shell Sysop supports.

Found by executing it, not by reading it. `bash 3.2` — what stock macOS ships as
`/bin/bash`, and the floor Sysop's *companion scripts* are held to — cannot parse a
`case` nested inside a `while` inside command substitution:

    syntax error near unexpected token `;;'

That is a **parse**-time failure, so the entire Step 3c block dies before the gate runs.

**The coverage was not missing — it was version-blind, and that is the transferable
lesson.** `tests/test_skill_positional_substitution.py::test_step3c_worktree_lookup_finds_
the_right_worktree` already extracted this bash and *executed* it. It resolves the shell
as `subprocess.run(["bash", ...])`, i.e. whatever `bash` `PATH` finds — homebrew 5.x on a
developer machine — so it never once ran the interpreter the defect lives in. This module
therefore parametrises over **every bash on the machine**, `/bin/bash` explicitly included,
rather than adding one more test that trusts `PATH`.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from skill_runner_text import text_of

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"


# Whatever `bash` resolves to first, PLUS /bin/bash explicitly — on macOS those are two
# different major versions, and testing only the first hides the one that fails.
def _shells() -> list[str]:
    """DETERMINISTIC and sorted — a `set` here made xdist workers collect different test
    ids and the whole run errored out. Order matters for parametrisation, not for the
    claim."""
    found = []
    for cand in ("/bin/bash", shutil.which("bash")):
        if cand and Path(cand).exists():
            real = str(Path(cand).resolve())
            if real not in found:
                found.append(real)
    return sorted(found)


_CANDIDATES = _shells()


def _step_3b_opener() -> str:
    """Step 3b step 0's invocation line — bash this phase ALSO introduced, and which the
    preamble span above does not reach. It parses on 3.2 today; nothing held it, which is
    how the defect this module exists for got in."""
    text = text_of(SKILL)
    i = text.index('python3 sysop/scripts/workspace_locate.py "<branch name>"')
    return text[i:text.index("\n", i) + 1]


NEW_BASH_BLOCKS = {"step-3b-step-0": _step_3b_opener()}
# Phase 421 (`Q-665`): Step 3c's preamble is gone. Its loops became `smoke_detect.py
# --branches`, because under `dontAsk` the step's `while read` and `case` loops bound no rule,
# so the shell-version floor this module exists for no longer applies to Step 3c. The tests
# below hold the behaviour the preamble carried, against the script.
SMOKE = REPO_ROOT / "core" / "companion" / "scripts" / "smoke_detect.py"
INVOCATION = 'python3 sysop/scripts/smoke_detect.py --branches "<default branch>" "<approved branch>" "<approved branch>"'


@pytest.mark.parametrize("shell", _CANDIDATES)
@pytest.mark.parametrize("name", sorted(NEW_BASH_BLOCKS))
def test_every_bash_block_this_phase_touched_parses(shell: str, name: str):
    """Not just the preamble. A span that covers one block and not its sibling is the
    same partial-population defect the guards elsewhere in this phase were caught on."""
    ver = subprocess.run([shell, "--version"], capture_output=True, text=True).stdout
    r = subprocess.run([shell, "-n", "-"], input=NEW_BASH_BLOCKS[name],
                       capture_output=True, text=True)
    assert r.returncode == 0, (
        f"{name} does not parse under {shell} "
        f"({ver.splitlines()[0] if ver else '?'}):\n{r.stderr}\n"
        f"A parse failure kills the whole block before anything in it runs."
    )


def test_at_least_one_candidate_is_bash_3_2():
    """The parametrisation is only meaningful if the old shell is actually present.

    **This module is inert in this project's CI**, and that is worth stating rather than
    discovering. `.github/workflows/*.yml` runs `ubuntu-24.04-arm`, whose `/bin/bash` is 5.x,
    so on the checked run every parametrisation lands on a shell that parses the *broken*
    form too — verified by the round against the pre-fix preamble: bash 5.3.9 parses it,
    bash 3.2.57 does not. The real coverage is a maintainer's macOS laptop. Skipping
    loudly here is the honest signal; a green run over one modern shell is not evidence
    about the floor, and reporting it as one would be the failure this phase is about."""
    versions = []
    for shell in _CANDIDATES:
        out = subprocess.run([shell, "--version"], capture_output=True, text=True).stdout
        versions.append(out.splitlines()[0] if out else "")
    if not any("version 3." in v for v in versions):
        pytest.skip(
            f"NO BASH 3.x ON THIS MACHINE — the floor is UNTESTED on this run, not clean. "
            f"Shells tested: {versions}"
        )
    assert True


def _repo_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "proj"
    repo.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    (repo / "tasks").mkdir()
    (repo / "tasks" / "index.yml").write_text("schema_version: 1\ntasks: []\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=repo, check=True, capture_output=True)
    wt = tmp_path / "proj-wt"
    subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "feat/wt"],
                   cwd=repo, check=True, capture_output=True)
    return repo, wt


def test_the_step_calls_the_branches_form():
    assert "\n" + INVOCATION + "\n" in text_of(SKILL)


def test_branches_reads_an_approved_branchs_worktree_doc(tmp_path: Path):
    """The table the preamble built, now built by the script: a pending doc authored in an
    approved branch's worktree must be read in place. An unread worktree is what the
    ISSUE-0050 blindness looked like."""
    repo, wt = _repo_with_worktree(tmp_path)
    pd = wt / "sysop" / "runtime" / "pending-docs"
    pd.mkdir(parents=True)
    (pd / "feat-wt.md").write_text('---\nbranch: "feat/wt"\n---\n\n## Manual smoke\nclick it\n',
                                   encoding="utf-8")
    run = lambda *b: subprocess.run([sys.executable, str(SMOKE), "--branches", "main", *b],
                                    cwd=repo, capture_output=True, text=True, timeout=30)
    r = run("feat/wt")
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("SMOKE_REQUIRED:"), r.stdout
    r = run()
    assert r.returncode == 0 and r.stdout.startswith("NO_SMOKE_REQUIRED"), (r.stdout, r.stderr)


def test_an_unsubstituted_placeholder_still_hard_errors(tmp_path: Path):
    """The loud-failure contract the preamble carried: a placeholder left in place must exit
    3, not scan nothing and report NO_SMOKE_REQUIRED."""
    repo, _ = _repo_with_worktree(tmp_path)
    for args in (["--branches", "main", "<approved branch>"], ["--branches"],
                 ["--branches", "<default branch>", "feat/wt"],
                 # Phase 421's round, lens A: a mistyped approved branch linked no lock and read
                 # NO_SMOKE_REQUIRED, exit 0.
                 ["--branches", "main", "feat/w"]):
        r = subprocess.run([sys.executable, str(SMOKE), *args], cwd=repo, capture_output=True,
                           text=True, timeout=30)
        assert r.returncode == 3, (args, r.returncode, r.stdout, r.stderr)
        assert r.stdout == "", r.stdout
