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
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"


def _preamble() -> str:
    """Step 3c's bash preamble, bounded on the heredoc TERMINATOR, not its opener.

    Bounding on the first `BR_LIST` gives the opener line (`done <<BR_LIST`) and silently
    truncates the block mid-heredoc — a script that then swallows whatever is appended to
    it as heredoc data. That mistake produced a confidently wrong reading of this very
    block while this test was being written.
    """
    text = SKILL.read_text(encoding="utf-8")
    i = text.index('SMOKE_WORKTREE_DIRS=""')
    k = text.index("done <<BR_LIST\n", i)
    j = text.index("\nBR_LIST\n", k) + len("\nBR_LIST\n")
    body = text[i:j]
    assert body.rstrip().endswith("BR_LIST"), "preamble was cut mid-heredoc"
    assert body.count("BR_LIST") == 2, body.count("BR_LIST")
    return body


PREAMBLE = _preamble()

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
    text = SKILL.read_text(encoding="utf-8")
    i = text.index('python3 - "<branch name>"')
    return text[i:text.index("<<'PY'", i)] + "<<'PY'\ncat >/dev/null\nPY\n"


NEW_BASH_BLOCKS = {"step-3c-preamble": 'APPROVED_BRANCHES=""\n' + PREAMBLE,
                   "step-3b-step-0": _step_3b_opener()}


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
    discovering. `.github/workflows/*.yml` runs `ubuntu-latest`, whose `/bin/bash` is 5.x,
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


@pytest.mark.parametrize("shell", _CANDIDATES)
def test_the_preamble_maps_a_branch_to_its_worktree(shell: str, tmp_path: Path):
    """Parsing is necessary, not sufficient: assert the table it builds is right, per
    case. An empty `SMOKE_WORKTREE_DIRS` is what the ISSUE-0050 blindness looked like."""
    repo = tmp_path / "proj"
    repo.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    (repo / "f.txt").write_text("x\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=repo, check=True, capture_output=True)
    wt = tmp_path / "proj-wt"
    subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "feat/wt"],
                   cwd=repo, check=True, capture_output=True)

    script = ('APPROVED_BRANCHES="feat/wt"\n' + PREAMBLE
              + '\nprintf "DIRS=[%s]\\n" "$SMOKE_WORKTREE_DIRS"\n')
    r = subprocess.run([shell, "-"], input=script, cwd=str(repo),
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert str(wt.resolve()) in r.stdout.replace(str(tmp_path.resolve()), str(tmp_path)), (
        f"{shell} produced no worktree dir for an approved branch that has one:\n{r.stdout}"
    )


@pytest.mark.parametrize("shell", _CANDIDATES)
def test_an_unsubstituted_placeholder_still_hard_errors(shell: str):
    """The loud-failure contract predates this change and must survive it: a placeholder
    left in place must exit 3, not scan nothing and report NO_SMOKE_REQUIRED."""
    text = SKILL.read_text(encoding="utf-8")
    i = text.index("APPROVED_BRANCHES='<approved-branch-1>")
    j = text.index("\nSMOKE_WORKTREE_DIRS=", i)
    r = subprocess.run([shell, "-"], input=text[i:j], capture_output=True, text=True)
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
    assert "substitute APPROVED_BRANCHES" in r.stderr
