"""Phase 335 (`Q-570`) — every reviewer writes to a scratch directory of its own.

`/review-close` Step 2b pinned each lens to its own checkout to READ, and handed every lens
the same place to WRITE: *"run it from a heredoc or write under `/tmp`"*, substituted
identically into every prompt of the wave. A consumer's seven-lens wave had one lens's
captured diff replaced by a sibling's between two of its own reads. It noticed; a lens that
captured once and read once would have returned `VERDICT: APPROVED` over another target's
diff, and nothing would look corrupt, because both files are real diffs of real targets.
`/codebase-review` and `/security-audit` pasted the same sentence into every fan-out agent.

The fix is the checkout pin's shape: the orchestrator makes one `mktemp -d` per agent and
writes that path into the agent's prompt. **So the weight of this module is EXECUTION**: it
runs the prescribed placement blocks and checks that two agents get two real, distinct
directories outside the repository, and that a temp dir inside the repository refuses
before any directory is made. The prose checks read data flow (which variable the placement
makes, which placeholder the prompt names) rather than wording, and each has a negative
control that must turn it red.
"""
from __future__ import annotations

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

from _prose_guard_helpers import locate, swap

REPO = Path(__file__).resolve().parent.parent
RC = REPO / "core/skills/review-close/SKILL.md"
PARTIAL = REPO / "core/skills/_shared/adversarial-review.md"
FANOUT = {
    "codebase-review": REPO / "core/skills/codebase-review/SKILL.md",
    "security-audit": REPO / "core/skills/security-audit/SKILL.md",
}

_MKTEMP = re.compile(r'(\w+)=\$\(mktemp -d "\$\{TMPDIR:-/tmp\}/([A-Za-z0-9_-]+?)X{3,}"\)')
_ADD = re.compile(r'git worktree add --detach "\$\{?(\w+)\}?"')
_FENCE = re.compile(r"^[ \t]*```(?:bash|sh)[ \t]*\n(.*?)^[ \t]*```[ \t]*$", re.M | re.S)
# A licence to write to a bare, shared `/tmp` path. The refusal the prompts now carry
# ("a fixed `/tmp` name may be another agent's") does not match: it names `/tmp` as a
# hazard, not as a place to write.
_TMP_LICENCE = re.compile(
    r"\b(?:write|writ\w+|save|put|capture|store|keep|stash|dump|place|leave|redirect|send|pipe|cache)"
    r"\b[^.:]{0,40}?\b(?:under|to|in|into|at|as)\s+`?\"?"
    r"(?:(?:/private)?/tmp\b|/var/tmp\b|\$\{TMPDIR\b|\$TMPDIR\b)",
    re.I)
# The placeholder must name THIS agent's directory: `<the fleet's shared scratch directory>`
# is a placeholder too, and it is the defect.
# The fan-out's command: `mktemp -d` under the temp root, which the lead makes absolute with a
# `cd … && pwd -P` so an agent never gets a path relative to someone else's CWD (round 2).
_FANOUT_MKTEMP = re.compile(r'`(mktemp -d "\$\(cd "\$\{TMPDIR:-/tmp\}" && pwd -P\)/([A-Za-z0-9_-]+?)X{3,}")`')
_PLACEHOLDER = re.compile(r"<[^<>]*\bthis\s+agent's\b[^<>]*scratch\s+director[^<>]*>")
# The one legal mention of `/tmp` in a prompt: the hazard it names. Any other `/tmp` is a
# place to write, however the sentence around it is worded.
_TMP_HAZARD = "fixed `/tmp"
# Every spelling of a shared temp root: a prompt that swaps `/tmp` for `$TMPDIR` restores the
# defect with the literal gone (round 1, lens 3).
_TEMP_ROOT = re.compile(r"(?:/private)?/tmp\b|/var/tmp\b|\$\{?TMPDIR\b|\btemp(?:orary)? director(?:y|ies)\b",
                        re.I)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _between(text: str, start: str, end: str, what: str) -> str:
    a = locate(text, start)
    b = text.find(end, a.end())
    assert b != -1, f"could not locate the end of {what}: {end!r}"
    return text[a.start():b]


# --------------------------------------------------------------------------------------
# Spans
# --------------------------------------------------------------------------------------

def _rc_placement(text: str) -> str:
    """Step 2b item 3: the placement header through the spawn it precedes."""
    return _between(text, "**Create each reviewer's checkout AT the target's commit",
                    "Then spawn an Agent with:", "Step 2b's placement")


def _rc_prompt(text: str) -> str:
    return _between(text, "You are the final convention gate before this branch merges",
                    "3b. **Spawn the security twin", "the Step 2b convention prompt")


def _rc_twin_sentence(text: str) -> str:
    return _between(text, "Spawn one Agent per surviving target", "The prompt is step 3's",
                    "the security twin's spawn sentence")


def _rc_recheck(text: str) -> str:
    return _between(text, "4. **Re-check the fix commit with one agent.**",
                    "5. **Act on the verdict.**", "4a-fix item 4")


def _fence(span: str, needle: str) -> str:
    hits = [textwrap.dedent(m.group(1)) for m in _FENCE.finditer(span) if needle in m.group(1)]
    assert len(hits) == 1, f"expected one shell fence carrying {needle!r}, found {len(hits)}"
    return hits[0]


_LEAD = "**Containment rule — paste into every agent's prompt, verbatim"


def _fanout_lead(text: str) -> str:
    """The containment rule's lead paragraph: its instructions to the orchestrator."""
    return _between(text, _LEAD,
                    "```", "the containment rule's lead")


def _fanout_block(text: str) -> str:
    """The containment rule itself: the block pasted into every agent's prompt."""
    lead = locate(text, _LEAD)
    m = re.compile(r"^```[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S).search(text, lead.end())
    assert m is not None, "the containment rule's fenced block is gone"
    return m.group(1)


# --------------------------------------------------------------------------------------
# Predicates. Each returns a list of problems; the real files must yield none.
# --------------------------------------------------------------------------------------

def placement_problems(block: str) -> list[str]:
    """Does the placement make a scratch directory of its own, beside the pin?

    Read by data flow: the pin is whichever variable `git worktree add` checks out into,
    and a scratch directory is any OTHER `mktemp -d` the block makes.
    """
    problems: list[str] = []
    made = _MKTEMP.findall(block)
    add = _ADD.search(block)
    if add is None:
        return ["the placement no longer runs `git worktree add --detach \"$<VAR>\"`"]
    pin_var = add.group(1)
    pin_prefix = dict(made).get(pin_var)
    scratch = [(v, p) for v, p in made if v != pin_var]
    if not scratch:
        return ["no scratch directory is made beside the pinned checkout, so the prompt's "
                "scratch placeholder has nothing to name and the lens falls back to `/tmp`"]
    if not re.search(rf"\b(?:echo|printf)\b[^\n]*\${{?{pin_var}\b", block):
        problems.append(f"`{pin_var}` is never printed; the prompt's pinned-checkout path "
                        "has nothing to be read from")
    if not re.search(r'case\s+"\$\(git\s+-C\s+"\$\{?' + pin_var + r'\}?"\s+rev-parse\s+--show-toplevel\b', block):
        problems.append("the containment check does not ask git where the pin is; a string "
                        "comparison is beaten by a symlinked, relative or case-variant TMPDIR "
                        "(round 2 measured bash's `pwd -P` keeping the typed case)")
    for var, prefix in scratch:
        if pin_prefix and prefix.startswith(pin_prefix.rstrip("-")) or "sysop-2b-" in prefix:
            problems.append(
                f"the scratch directory `{prefix}XXXXXX` shares the pinned checkouts' prefix; "
                "Step 2b's removal loop and leak assertion find checkouts by that string")
        if not re.search(rf"\b(?:echo|printf)\b[^\n]*\${{?{var}\b", block):
            problems.append(
                f"`{var}` is made but never printed; no variable survives to the next call, so "
                "the orchestrator cannot learn the path it must write into the prompt")
        made_at = re.search(rf"\b{var}=\$\(mktemp", block)
        at = made_at.start() if made_at else -1
        esac = block.find("esac")
        if esac == -1 or at < esac:
            problems.append(
                f"`{var}` is made before the containment check refuses a temp dir inside the "
                "repository, so a refused run has already left a directory in the tree")
    return problems


def prompt_problems(prompt: str) -> list[str]:
    problems: list[str] = []
    if not _PLACEHOLDER.search(prompt):
        problems.append("the prompt names no per-agent scratch directory to write under")
    licence = _TMP_LICENCE.search(prompt)
    if licence:
        problems.append(f"the prompt licenses a shared `/tmp` write: {licence.group(0)!r}")
    for m in _TEMP_ROOT.finditer(prompt):
        if not re.search(r"\bfixed\s+`$", prompt[:m.start()]):
            problems.append("the prompt names a shared temp root other than as the hazard "
                            f"({prompt[max(0, m.start() - 40):m.end() + 20]!r})")
    return problems


def placement_prose_problems(span: str) -> list[str]:
    """The bullet that tells the runner the directory is PER AGENT, outside the fence.

    A deletion detector over prose (`Q-560`'s limit applies), kept because the fence alone
    does not say whether the block runs once per agent or once per close.
    """
    prose = _FENCE.sub("", span)
    if not re.search(r"scratch[^.]{0,40}\bone per agent\b|\bone per agent\b[^.]{0,40}scratch",
                     prose):
        return ["the placement's prose no longer says the scratch directory is one per agent"]
    return []


def fanout_problems(text: str) -> list[str]:
    """The orchestrator is told to make one directory per agent and fill the placeholder."""
    problems = prompt_problems(_fanout_block(text))
    lead = _fanout_lead(text)
    block_ph = set(_PLACEHOLDER.findall(_fanout_block(text)))
    lead_ph = set(_PLACEHOLDER.findall(lead))
    if not block_ph & lead_ph:
        problems.append(f"the lead fills {sorted(lead_ph)} but the pasted rule names "
                        f"{sorted(block_ph)}; the orchestrator is told to fill a placeholder "
                        "the agent never sees")
    cmd = _FANOUT_MKTEMP.search(lead)
    if cmd is None:
        problems.append("the lead no longer gives the `mktemp -d` that makes each directory, "
                        "absolute (a relative TMPDIR prints a path each agent resolves elsewhere)")
    elif "sysop-2b-" in cmd.group(2):
        problems.append("the scratch prefix is the pinned checkouts' prefix")
    if not re.search(r"XXXXXX\\?\"\)?`[^.]{0,20}\b(?:once per agent|for each agent)", lead):
        problems.append("the lead does not make the directory PER AGENT; one shared directory "
                        "is the defect")
    if not re.search(r"git -C <printed path> rev-parse --show-toplevel`[^.]{0,120}write `\(none", lead):
        problems.append("the lead has no arm for a printed path inside the repository; a "
                        "project-local TMPDIR then puts agent scratch in the primary tree")
    if not re.search(r"mktemp`? is denied", lead) or "write no file" not in lead:
        problems.append("the lead has no arm for a denied `mktemp`; under `dontAsk` the "
                        "placeholder would be left unfilled")
    return problems


def twin_problems(sentence: str) -> list[str]:
    if not re.search(r"\bits\s+own\s+`\$[A-Z_]+`", sentence):
        return ["the security twin's spawn sentence gives it no scratch directory of its own"]
    return []


def partial_problems(text: str) -> list[str]:
    """The shared rule predates this phase (Phase 326). A deletion detector over it, so the
    source text the runners were brought into line with cannot silently disappear."""
    if not re.search(r"\*\*Name a private scratch directory in each prompt too\*\*, one you "
                     r"created for that lens", text):
        return ["the shared rule no longer names a spawner-made scratch directory per lens"]
    return []


# --------------------------------------------------------------------------------------
# The real files
# --------------------------------------------------------------------------------------

def test_step_2b_placement_makes_a_scratch_directory() -> None:
    assert placement_problems(_fence(_rc_placement(_read(RC)), "git worktree add")) == []


def test_step_2b_placement_says_the_scratch_directory_is_per_agent() -> None:
    assert placement_prose_problems(_rc_placement(_read(RC))) == []


def test_4a_fix_placement_makes_a_scratch_directory() -> None:
    assert placement_problems(_fence(_rc_recheck(_read(RC)), "git worktree add")) == []


def test_step_2b_prompt_names_the_agents_own_scratch_directory() -> None:
    assert prompt_problems(_rc_prompt(_read(RC))) == []


def test_the_security_twin_gets_its_own_scratch_directory() -> None:
    assert twin_problems(_rc_twin_sentence(_read(RC))) == []


@pytest.mark.parametrize("skill", sorted(FANOUT))
def test_the_fanout_containment_rule_names_a_per_agent_scratch_directory(skill: str) -> None:
    assert fanout_problems(_read(FANOUT[skill])) == []


def test_the_shared_rule_gives_each_reviewer_a_scratch_directory() -> None:
    assert partial_problems(_read(PARTIAL)) == []


def _runners() -> list[Path]:
    """Every shipped markdown file an agent or a consumer reads: `core/` and `packs/`, minus the
    skills' `REFERENCE.md` files, which are editor text and quote the retired sentence on
    purpose. Round 1 found the first cut reading `SKILL.md` and `_shared/` only, so a licence
    added to `core/companion/docs/WORKFLOW.md` passed."""
    files = sorted(p for root in ("core", "packs") for p in (REPO / root).rglob("*.md")
                   if p.name != "REFERENCE.md")
    for must in (RC, PARTIAL, *FANOUT.values(), REPO / "core/companion/docs/WORKFLOW.md",
                 REPO / "packs/python/companion/convention_map.md"):
        assert must in files, f"the sweep's population lost {must.relative_to(REPO)}"
    return files


def test_no_shipped_review_prompt_still_licenses_a_shared_tmp_write() -> None:
    """The class, not the three sites: any shipped skill that tells an agent to write under
    a bare `/tmp`. Phase 334's lesson was that the first count of a class is a claim."""
    hits = [f"{p.relative_to(REPO)}: {h!r}" for p in _runners() for h in licences(_read(p))]
    assert hits == [], hits


def test_no_runner_climbs_out_of_a_minted_directory() -> None:
    hits = [f"{p.relative_to(REPO)}: {h!r}" for p in _runners() for h in escapes(_read(p))]
    assert hits == [], hits


# --------------------------------------------------------------------------------------
# Execution: run what the skill prescribes
# --------------------------------------------------------------------------------------

def _env(tmpdir: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"TMPDIR": str(tmpdir), "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmpdir),
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"})
    return env


def _git(cwd: Path, env: dict, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout.strip()


@pytest.fixture()
def repo(tmp_path: Path):
    work, tmpdir = tmp_path / "work", tmp_path / "tmp"
    tmpdir.mkdir()
    env = _env(tmpdir)
    _git(tmp_path, env, "init", "-q", "-b", "main", str(work))
    (work / "a.md").write_text("a\n")
    _git(work, env, "add", "-A")
    _git(work, env, "commit", "-q", "-m", "base")
    _git(work, env, "checkout", "-q", "-b", "feature")
    (work / "b.md").write_text("b\n")
    _git(work, env, "add", "-A")
    _git(work, env, "commit", "-q", "-m", "feature")
    _git(work, env, "checkout", "-q", "main")
    return work, tmpdir, env


def _step_2b_script() -> str:
    """Step 2b's block with its feature-branch arm chosen, as the step says to write it."""
    block = _fence(_rc_placement(_read(RC)), "git worktree add")
    lines = [l for l in block.splitlines() if not l.startswith("PIN=$(git rev-parse HEAD)")]
    return "\n".join(lines).replace("<target branch>", "feature")


def _recheck_script(sha: str) -> str:
    return _fence(_rc_recheck(_read(RC)), "git worktree add").replace("<fix-sha>", sha)


def _run(work: Path, env: dict, script: str) -> subprocess.CompletedProcess:
    """The block exactly as the skill writes it. Round 1 found this helper appending the echo
    the skill left out, so the test proved a print the orchestrator never saw."""
    return subprocess.run(["/bin/bash", "-c", script], cwd=work, env=env,
                          capture_output=True, text=True)


def _scratch_var(block: str) -> str:
    pin = _ADD.search(block).group(1)
    others = [v for v, _ in _MKTEMP.findall(block) if v != pin]
    assert len(others) == 1, f"expected one scratch variable beside the pin, found {others}"
    return others[0]


def _printed(out: str, key: str) -> Path:
    """A path the BLOCK printed, as `KEY=<path>` on its own output."""
    m = re.search(rf"(?:^|\s){key}=(\S+)", out, re.M)
    assert m, f"the block did not print {key}=:\n{out}"
    path = Path(m.group(1))
    assert path.is_absolute(), f"{key}= printed a relative path, which the agent resolves elsewhere: {path}"
    return path


@pytest.mark.parametrize("which", ["step-2b", "4a-fix"])
def test_two_agents_get_two_real_scratch_directories_outside_the_repo(repo, which) -> None:
    work, tmpdir, env = repo
    sha = _git(work, env, "rev-parse", "feature")
    script = _step_2b_script() if which == "step-2b" else _recheck_script(sha)
    first, second = _run(work, env, script), _run(work, env, script)
    for r in (first, second):
        assert r.returncode == 0, r.stderr + r.stdout
    key = _scratch_var(script)
    a, b = _printed(first.stdout, key), _printed(second.stdout, key)
    assert a != b, "two agents were handed the same scratch directory"
    for d in (a, b):
        assert d.is_dir(), f"{d} was not created"
        assert d.resolve().is_relative_to(tmpdir.resolve()), f"{d} is not under TMPDIR"
        assert not d.resolve().is_relative_to(work.resolve()), f"{d} is inside the repository"
        assert list(d.iterdir()) == [], "a fresh scratch directory is not empty"
    pinned = _printed(first.stdout, _ADD.search(script).group(1))
    assert _git(pinned, env, "rev-parse", "HEAD") == sha
    listed = _git(work, env, "worktree", "list", "--porcelain")
    assert str(a) not in listed and str(b) not in listed, "a scratch directory became a worktree"
    # What Step 2b's HARD RULE sweeps by: a scratch directory must never match it.
    assert "/sysop-2b-" not in str(a) and "/sysop-2b-" not in str(b)


def _inside_spellings(work: Path, tmp_path: Path) -> dict:
    """A temp dir INSIDE the repository, spelled three ways. Round 1 found the check
    comparing strings: the macOS `/var` -> `/private/var` symlink spelling and a relative
    TMPDIR both passed it and put the pin and the scratch directory in the tree."""
    inside = work / "tmp-inside"
    inside.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(work, target_is_directory=True)
    # Case: APFS and NTFS are case-insensitive, and bash's `pwd -P` keeps the case you typed
    # while git reports the case on disk (round 2). The fixture's own filesystem decides
    # whether this spelling reaches the same directory; `_case_insensitive` skips it if not.
    cased = str(work.parent / work.name.upper() / "tmp-inside")
    return {"resolved": str(inside), "symlinked": str(alias / "tmp-inside"), "relative": "tmp-inside",
            "case-variant": cased}


@pytest.mark.parametrize("spelling", ["resolved", "symlinked", "relative", "case-variant"])
@pytest.mark.parametrize("which", ["step-2b", "4a-fix"])
def test_a_temp_dir_inside_the_repo_refuses_before_any_scratch_is_made(repo, tmp_path, which,
                                                                       spelling) -> None:
    work, _, env = repo
    spellings = _inside_spellings(work, tmp_path)
    if spelling == "case-variant" and not Path(spellings[spelling]).is_dir():
        pytest.skip("case-sensitive filesystem: the case-variant spelling names no directory")
    env = dict(env, TMPDIR=spellings[spelling])
    sha = _git(work, env, "rev-parse", "feature")
    script = _step_2b_script() if which == "step-2b" else _recheck_script(sha)
    r = _run(work, env, script)
    assert r.returncode != 0 and "REFUSING" in r.stdout, r.stdout + r.stderr
    entries = sorted(p.name for p in (work / "tmp-inside").iterdir())
    # The refused run may leave its one empty pin directory (made before the check, and
    # invisible to git); anything else was made after a check that should have stopped it.
    assert len(entries) <= 1 and all(e.startswith("sysop-2b-") for e in entries), (
        f"something besides the empty pin was made inside the repository: {entries}")
    assert "sysop-2b-" not in _git(work, env, "worktree", "list", "--porcelain")


@pytest.mark.parametrize("which", ["step-2b", "4a-fix"])
def test_a_relative_temp_dir_outside_the_repo_prints_absolute_paths(repo, which) -> None:
    work, tmpdir, env = repo
    env = dict(env, TMPDIR=os.path.relpath(tmpdir, work))
    sha = _git(work, env, "rev-parse", "feature")
    script = _step_2b_script() if which == "step-2b" else _recheck_script(sha)
    r = _run(work, env, script)
    assert r.returncode == 0, r.stderr + r.stdout
    for key in (_ADD.search(script).group(1), _scratch_var(script)):
        assert _printed(r.stdout, key).resolve().is_relative_to(tmpdir.resolve())


@pytest.mark.parametrize("skill", sorted(FANOUT))
def test_the_fanout_mktemp_makes_distinct_directories(skill: str, tmp_path: Path) -> None:
    lead = _fanout_lead(_read(FANOUT[skill]))
    found = _FANOUT_MKTEMP.search(lead)
    assert found, "the lead no longer gives the `mktemp -d` command"
    cmd = found.group(1)
    (tmp_path / "t").mkdir()
    # A relative TMPDIR, run from a directory the agents do not share: the printed paths must
    # still be absolute, or each agent resolves them against its own CWD (round 2, lens 5).
    env = dict(_env(tmp_path), TMPDIR="t")
    out = subprocess.run(["/bin/bash", "-c", f"{cmd}\n{cmd}"], cwd=tmp_path, env=env,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    dirs = [Path(l) for l in out.stdout.split()]
    assert len(dirs) == 2 and dirs[0] != dirs[1] and all(d.is_dir() for d in dirs), out.stdout
    assert all(d.is_absolute() for d in dirs), f"a printed path is relative: {out.stdout}"
    assert all(d.resolve().is_relative_to((tmp_path / "t").resolve()) for d in dirs)


# Fixed names under the shared temp root, in any runner file. Round 1 (lens 3) found Step 4a's
# conflict recipe writing `sysop-notes-*.md` and `sysop-ours.yml` there, so two concurrent
# closes on one machine read each other's stage extracts. A templated `mktemp` name, a name
# carrying a `<placeholder>`, and `$VAR/...` under a minted directory are not fixed names.
_FIXED_TEMP_NAME = re.compile(
    r'(?:\$\{TMPDIR:-/tmp\}"?|\$\{TMPDIR\}"?|\$TMPDIR"?|(?<![\w./$}-])(?:/private)?/tmp)'
    r'/([A-Za-z0-9_.\-/]*[A-Za-z0-9_.\-])(?![A-Za-z0-9_.\-/<$])')
# A write that climbs out of a directory minted for one agent or one run lands in the shared
# temp root again (round 2, lens 5: `<pinned checkout>/../review.diff`, `$STAGES/../x`).
_ESCAPE = re.compile(r"(?:<[^<>\n]*(?:pinned checkout|scratch director)[^<>\n]*>|\$\{?(?:SCRATCH|PINNED|STAGES)\}?)/\.\.")


def licences(text: str) -> list[str]:
    return [m.group(0) for m in _TMP_LICENCE.finditer(text)]


def fixed_names(text: str, where: str = "") -> list[str]:
    hits = []
    for m in _FIXED_TEMP_NAME.finditer(text):
        if re.search(r"X{3,}", m.group(1)) or (where, m.group(1)) in _FIXED_NAME_KEPT:
            continue
        hits.append(m.group(1))
    return hits


def escapes(text: str) -> list[str]:
    return [m.group(0) for m in _ESCAPE.finditer(text)]


# Assessed and kept. `4a-post`'s inherited-failure probe is `git worktree add --detach
# "${TMPDIR:-/tmp}/sysop-base-probe" …`: a fixed name, but `git worktree add` REFUSES a
# non-empty existing path, and the arm then stops ("you have not established this"). It fails
# loud and closed, where a `>` redirect overwrites silently. Minting it would put an
# assignment in front of the call, which then binds none of full mode's seeded
# `Bash(git worktree add:*)`, so an autonomous close would lose the arm to a denied prompt.
#
# `WORKFLOW.md`'s `--accept-upstream-list /tmp/accept.txt` is an example of a path a HUMAN types
# for a file they write themselves: one person, no agent, no concurrency. Found by the round-2
# widening of the sweep to every shipped markdown file.
#
# Each entry names the text that must sit directly before the site, so an entry cannot be
# widened to cover a different kind of write without its own reason.
_FIXED_NAME_KEPT = {
    ("core/skills/review-close/SKILL.md", "sysop-base-probe"): 'git worktree add --detach "',
    ("core/companion/docs/WORKFLOW.md", "accept.txt"): "--accept-upstream-list ",
}


def test_no_runner_writes_a_fixed_name_under_the_shared_temp_root() -> None:
    hits = [f"{p.relative_to(REPO)}: {h}" for p in _runners()
            for h in fixed_names(_read(p), str(p.relative_to(REPO)))]
    assert hits == [], hits


# Planted examples: every spelling round 2 walked past the first sweeps, and the house forms
# they must keep passing. A sweep with no control of its own reads an empty population and a
# neutered pattern the same way (lens 5, F2 and F4).
@pytest.mark.parametrize("text", [
    "Store scratch output under `/tmp` for later.",
    "Write scratch output under `${TMPDIR:-/tmp}`.",
    "agents may keep their notes in `/private/tmp/sysop-review/`",
    "write the capture and its notes under `/tmp`",
    "Save the diff to $TMPDIR before reading it.",
])
def test_the_licence_sweep_sees_every_spelling(text: str) -> None:
    assert licences(text), text


@pytest.mark.parametrize("text", [
    "a fixed `/tmp` name may be another agent's.",
    "Compute from a heredoc, or write only under <this agent's scratch directory>.",
])
def test_the_licence_sweep_passes_the_hazard_and_the_placeholder(text: str) -> None:
    assert licences(text) == [], text


@pytest.mark.parametrize("text", [
    'git show :2:x > "${TMPDIR:-/tmp}/sysop-ours.yml"',
    "see ${TMPDIR:-/tmp}/sysop-index-resolved.yml, then",
    'cat > ${TMPDIR:-/tmp}/sysop-tagmsg.md;',
    '"${TMPDIR:-/tmp}"/sysop-tagmsg.md',
    "${TMPDIR:-/tmp}/sysop/tagmsg.md",
    "cp x /tmp/sysop-tagmsg.md",
    'cp x "$TMPDIR/sysop-tagmsg.md"',
])
def test_the_fixed_name_sweep_sees_every_spelling(text: str) -> None:
    assert fixed_names(text), text


@pytest.mark.parametrize("text", [
    'mktemp -d "${TMPDIR:-/tmp}/sysop-scratch-XXXXXX"',
    '"${TMPDIR:-/tmp}/sysop-issue-<id>.md"',
    'mktemp -d "$(cd "${TMPDIR:-/tmp}" && pwd -P)/sysop-scratch-XXXXXX"',
    "a fixed `/tmp` name",
])
def test_the_fixed_name_sweep_passes_minted_and_keyed_names(text: str) -> None:
    assert fixed_names(text) == [], text


@pytest.mark.parametrize("text", [
    "Save the diff as `<absolute path to the pinned checkout>/../review.diff`.",
    'git diff a b > "$SCRATCH/../sysop-2b.diff"',
    'git show :2:x > "$STAGES/../sysop-ours.yml"',
])
def test_the_escape_sweep_sees_a_climb_out(text: str) -> None:
    assert escapes(text), text


def test_every_kept_fixed_name_sits_in_its_stated_context() -> None:
    """Each allowance holds only in its context. If a site becomes a redirect or a copy, it
    overwrites silently and the allowance no longer holds. Every entry is checked, so widening
    the allow-list alone cannot pass a new fixed name (lens 5, F1)."""
    for (where, name), before in _FIXED_NAME_KEPT.items():
        text = _read(REPO / where)
        sites = [m for m in _FIXED_TEMP_NAME.finditer(text) if m.group(1) == name]
        assert sites, f"{where}: the kept name {name!r} is gone; drop its allowance"
        for m in sites:
            assert text[:m.start()].endswith(before), (where, name, text[max(0, m.start() - 60):m.end()])


def test_step_4a_stage_blocks_print_their_directory() -> None:
    text = _read(RC)
    blocks = [f for f in (textwrap.dedent(m.group(1)) for m in _FENCE.finditer(text))
              if re.search(r"git show :[123]:tasks/", f)]
    assert len(blocks) == 2, f"expected the notes and index stage blocks, found {len(blocks)}"
    for block in blocks:
        made = _MKTEMP.findall(block)
        assert made, "a stage block writes its extracts somewhere it did not mint"
        var = made[0][0]
        assert re.search(rf"\b(?:echo|printf)\b[^\n]*\${{?{var}\b", block), (
            f"`{var}` is never printed, so the resolution cannot name the extracts it reads")
        assert stage_write_problems(block, var) == [], stage_write_problems(block, var)


def stage_write_problems(block: str, var: str) -> list[str]:
    writes = re.findall(r'>\s*"?([^"\s;]+)"?', block)
    if not writes:
        return ["the stage block writes nothing"]
    return [w for w in writes if not w.startswith(f"${var}/") or "/../" in w or w.endswith("/..")]


@pytest.mark.parametrize("write", ['"$STAGES/../ours.yml"', '"${TMPDIR:-/tmp}/sysop-ours.yml"', "/tmp/ours.yml"])
def test_the_stage_write_check_refuses_a_write_outside_the_run(write: str) -> None:
    block = 'STAGES=$(mktemp -d "${TMPDIR:-/tmp}/sysop-stages-XXXXXX") && echo "STAGES=$STAGES"\n'
    assert stage_write_problems(block + f"git show :2:x > {write}\n", "STAGES"), write


# --------------------------------------------------------------------------------------
# Negative controls: each softening must turn its predicate red
# --------------------------------------------------------------------------------------

_SCRATCH_LINE = ('SCRATCH=$(mktemp -d "${TMPDIR:-/tmp}/sysop-scratch-XXXXXX")'
                 ' && echo "PINNED=$(cd "$PINNED" && pwd -P) SCRATCH=$(cd "$SCRATCH" && pwd -P)"')
_CASE_LINE = 'case "$(git -C "$PINNED" rev-parse --show-toplevel 2>/dev/null)" in "$(git rev-parse --show-toplevel)")'
# What precedes the scratch line in Step 2b ONLY: the 4a-fix copy has no comment above its
# `case`, so this context makes each Step 2b control name one site. (Not a trailing context:
# `anchor()` does not match across the blank line after the fence.)
_BEFORE_2B = ('# So verify containment rather than assuming it.\n   ' + _CASE_LINE + '\n'
              '     echo "REFUSING: temp dir is inside the repository ($PINNED)"; exit 1 ;; esac\n   ')
_2B_BLOCK = lambda t: _fence(_rc_placement(t), "git worktree add")
_4A_BLOCK = lambda t: _fence(_rc_recheck(t), "git worktree add")
_RECHECK = "4. **Re-check the fix commit"

CONTROLS = [
    ("2b prompt restores /tmp", RC, _rc_prompt, prompt_problems,
     "write under <absolute path to this agent's scratch directory> and nowhere else",
     "write under `/tmp` and nowhere else", None),
    ("2b prompt drops the placeholder", RC, _rc_prompt, prompt_problems,
     "<absolute path to this agent's scratch directory>", "a directory of your choosing", None),
    ("2b placement drops scratch", RC, _2B_BLOCK, placement_problems,
     _BEFORE_2B + _SCRATCH_LINE, _BEFORE_2B.rstrip(" "), None),
    ("2b scratch shares the pin prefix", RC, _2B_BLOCK, placement_problems,
     _BEFORE_2B + _SCRATCH_LINE,
     _BEFORE_2B + _SCRATCH_LINE.replace("sysop-scratch-", "sysop-2b-scratch-"), None),
    ("2b placement stops printing the paths", RC, _2B_BLOCK, placement_problems,
     _BEFORE_2B + _SCRATCH_LINE, _BEFORE_2B + _SCRATCH_LINE.split(" && ")[0], None),
    ("2b containment compares the spelled path", RC, _2B_BLOCK, placement_problems,
     "# So verify containment rather than assuming it.\n   " + _CASE_LINE,
     '# So verify containment rather than assuming it.\n   case "$(cd "$PINNED" && pwd -P)"/ in "$(git rev-parse --show-toplevel)"/*)',
     None),
    ("4a-fix placement drops scratch", RC, _4A_BLOCK, placement_problems,
     _SCRATCH_LINE + "\n   git worktree add --detach \"$PINNED\" \"$PIN\"",
     "git worktree add --detach \"$PINNED\" \"$PIN\"", _RECHECK),
    ("4a-fix stops printing the paths", RC, _4A_BLOCK, placement_problems,
     _SCRATCH_LINE, _SCRATCH_LINE.split(" && ")[0], _RECHECK),
    ("4a-fix containment compares the spelled path", RC, _4A_BLOCK, placement_problems,
     _CASE_LINE, 'case "$(cd "$PINNED" && pwd -P)"/ in "$(git rev-parse --show-toplevel)"/*)', _RECHECK),
    ("2b scratch made before the containment check", RC, _2B_BLOCK, placement_problems,
     _BEFORE_2B + _SCRATCH_LINE,
     "# So verify containment rather than assuming it.\n   " + _SCRATCH_LINE + "\n   " + _CASE_LINE
     + '\n     echo "REFUSING: temp dir is inside the repository ($PINNED)"; exit 1 ;; esac', None),
    ("twin reuses step 3's scratch", RC, _rc_twin_sentence, twin_problems,
     "and its own `$SCRATCH`, both created", "and step 3's `$SCRATCH`, both created", None),
    ("2b bullet shares one scratch", RC, _rc_placement, placement_prose_problems,
     "**The scratch directory is one per agent too, for the same reason:**",
     "**One scratch directory serves the whole fleet:**", None),
    ("2b prompt adds a /tmp alternative", RC, _rc_prompt, prompt_problems,
     "and nowhere else:", "or anywhere under `/tmp`:", None),
    ("2b prompt adds a $TMPDIR alternative", RC, _rc_prompt, prompt_problems,
     "and nowhere else:", "or under `$TMPDIR`:", None),
    ("2b prompt names a shared placeholder", RC, _rc_prompt, prompt_problems,
     "<absolute path to this agent's scratch directory>",
     "<absolute path to the fleet's shared scratch directory>", None),
    ("twin loses its own scratch", RC, _rc_twin_sentence, twin_problems,
     "and its own `$SCRATCH`, both created", "created", None),
    ("shared rule loses scratch", PARTIAL, lambda t: t, partial_problems,
     "**Name a private scratch directory in each prompt too**, one you created for that lens",
     "**Reviewers may write scratch files under `/tmp`**", None),
]
for _skill, _path in FANOUT.items():
    CONTROLS += [
        (f"{_skill} block restores /tmp", _path, lambda t: t, fanout_problems,
         "write only\nunder <this agent's scratch directory> and at no other path",
         "write\nunder `/tmp` and at no other path", None),
        (f"{_skill} lead fills a different placeholder", _path, lambda t: t, fanout_problems,
         "into that agent's prompt as `<this agent's scratch directory>`",
         "into that agent's prompt as `<scratch path>`", None),
        (f"{_skill} lead makes one shared directory", _path, lambda t: t, fanout_problems,
         "sysop-scratch-XXXXXX\"` once per agent (", "sysop-scratch-XXXXXX\"` once (", None),
        (f"{_skill} lead prints a relative path", _path, lambda t: t, fanout_problems,
         '`mktemp -d "$(cd "${TMPDIR:-/tmp}" && pwd -P)/sysop-scratch-XXXXXX"`',
         '`mktemp -d "${TMPDIR:-/tmp}/sysop-scratch-XXXXXX"`', None),
        (f"{_skill} block adds a /tmp alternative", _path, lambda t: t, fanout_problems,
         "a fixed `/tmp` name included.", "a fixed `/tmp` name included, but `/tmp/<your name>-*` is fine.",
         None),
        (f"{_skill} lead uses the pin prefix", _path, lambda t: t, fanout_problems,
         "sysop-scratch-XXXXXX\"` once per agent (", "sysop-2b-XXXXXX\"` once per agent (", None),
        (f"{_skill} lead drops the denied arm", _path, lambda t: t, fanout_problems,
         "If `mktemp` is denied, or `git -C", "If `git -C", None),
        (f"{_skill} lead drops the inside-the-repo arm", _path, lambda t: t, fanout_problems,
         ", or `git -C <printed path> rev-parse --show-toplevel` prints this repository's own toplevel "
         "(a project-local `TMPDIR` puts the path inside it),", ",", None),
        (f"{_skill} lead judges the path by eye", _path, lambda t: t, fanout_problems,
         "`git -C <printed path> rev-parse --show-toplevel` prints this repository's own toplevel",
         "a printed path looks like it is inside the repository", None),
    ]


@pytest.mark.parametrize("name,path,span,pred,old,new,after", CONTROLS,
                         ids=[c[0] for c in CONTROLS])
def test_a_softening_is_caught(name, path, span, pred, old, new, after) -> None:
    text = _read(path)
    assert pred(span(text)) == [], f"{name}: the control's baseline is already red"
    mutated = swap(text, old, new, after=after)
    assert mutated != text
    assert pred(span(mutated)), f"{name}: the softening walked through the guard"


def test_a_consistent_rename_of_the_scratch_variable_stays_green() -> None:
    """Data flow, not spelling: `SCRATCH` -> `WORKDIR` throughout is a legal edit."""
    block = _fence(_rc_placement(_read(RC)), "git worktree add").replace("SCRATCH", "WORKDIR")
    assert placement_problems(block) == []


def test_the_licence_pattern_reads_the_refusal_as_a_refusal() -> None:
    """The prompts now name `/tmp` only as a hazard; that must not read as a licence,
    and the old sentence must."""
    assert not _TMP_LICENCE.search("a fixed `/tmp` name may be another agent's.")
    assert _TMP_LICENCE.search("run it from a heredoc or write under `/tmp`.")
    assert _TMP_LICENCE.search("Compute from a heredoc or write\nunder `/tmp`.")


def test_the_notes_stage_block_runs_on_a_real_conflict(repo) -> None:
    """Run the shipped block where the skill runs it: mid-rebase, on a `tasks/notes.md`
    conflict. Two runs (two closes on one machine) must get two directories."""
    work, tmpdir, env = repo
    (work / "tasks").mkdir()
    (work / "tasks/notes.md").write_text("- one\n- two\n")
    _git(work, env, "add", "-A")
    _git(work, env, "commit", "-q", "-m", "notes")
    _git(work, env, "checkout", "-q", "-b", "side")
    (work / "tasks/notes.md").write_text("- one\n- two\n- from side\n")
    _git(work, env, "commit", "-qam", "side note")
    _git(work, env, "checkout", "-q", "main")
    (work / "tasks/notes.md").write_text("- one\n- two\n- from main\n")
    _git(work, env, "commit", "-qam", "main note")
    _git(work, env, "checkout", "-q", "side")
    r = subprocess.run(["git", "rebase", "main"], cwd=work, env=env, capture_output=True, text=True)
    assert r.returncode != 0, "the fixture did not conflict"
    block = [f for f in (textwrap.dedent(m.group(1)) for m in _FENCE.finditer(_read(RC)))
             if "git show :1:tasks/notes.md" in f]
    assert len(block) == 1
    first, second = _run(work, env, block[0]), _run(work, env, block[0])
    for out in (first, second):
        assert out.returncode == 0, out.stderr + out.stdout
    a, b = _printed(first.stdout, "STAGES"), _printed(second.stdout, "STAGES")
    assert a != b, "two runs wrote their stage extracts to the same directory"
    for d in (a, b):
        assert d.resolve().is_relative_to(tmpdir.resolve())
        assert (d / "base.md").read_text() == "- one\n- two\n"
        assert (d / "ours.md").read_text() == "- one\n- two\n- from main\n"
        assert (d / "theirs.md").read_text() == "- one\n- two\n- from side\n"
    # No side deleted a base line, so both `comm` lines print nothing past the STAGES= line.
    assert first.stdout.strip().splitlines() == [f"STAGES={a}"], first.stdout
    assert not list(tmpdir.glob("sysop-notes-*")), "a fixed-name extract was written"
