"""Skill bodies must contain no shell positional parameters (Phase 188, upstream #360).

WHAT THE HARNESS DOES, MEASURED — not inferred from the docs. A probe skill was installed
and invoked in a fresh session with the argument string ``alpha beta gamma``; it echoed its
own body back. Results:

    $0 -> alpha        $1 -> beta        $2 -> gamma      (0-based: $0 is the FIRST word)
    $9 -> $9           (index out of range: left unchanged)
    ${1} -> ${1}       ${1:-FALLBACK} -> ${1:-FALLBACK}   (the BRACED form is NOT touched)
    $ARGUMENTS -> alpha beta gamma
    inside a ```bash fence:  awk -F/ '{print $1}'  ->  awk -F/ '{print beta}'

That last line is the load-bearing one: **there is no fenced-code-block exclusion.** A shell
snippet in a skill body is rewritten before any shell sees it.

WHY THIS CANNOT BE OPTED OUT OF. Sysop depends on the same substitution deliberately —
``$ARGUMENTS`` appears on 43 lines across all 23 skills. The feature is used on purpose and
suffered accidentally, so the rule is not "turn substitution off" but "write no positionals".

WHY ELIMINATE RATHER THAN ESCAPE. ``\\$1`` is Claude Code's documented escape, but it is
Claude-Code-only: Sysop also ships to Codex via the Phase-142 symlinks and to arbitrary
agents via the bash installer, and for every one of those readers ``awk '{print \\$1}'`` is
broken syntax the file did not previously have. So the escape is explicitly NOT accepted as
compliance below.

THE BRACED FORM IS FORBIDDEN TOO, AND THAT GOES BEYOND THE LIVE DEFECT — recorded here
rather than left implicit. ``${1:-1}`` is measured above as safe *today*. It is still
refused, for three reasons: the non-substitution is undocumented and could change; a
``${1}`` in a skill body is in practice a sibling of a bare ``$1`` in the same helper (which
is exactly how `/daily-summary` carried both); and "no positional parameters in a skill
body" is one rule an author can hold, where "bare ones break but braced ones are fine" is a
distinction they will get wrong. The filed brief argued the braced form was itself a live
defect; the measurement above refutes that, and the rule survives on the reasons given.

HOW TO WRITE ABOUT POSITIONALS in a skill body, since the tokens cannot be typed: use the
form ``$<1>`` / ``$<N>``. ``$`` followed by ``<`` is not a positional and is left alone. The
shipped skills use that convention where they explain this defect.
"""
from __future__ import annotations

import datetime
import re
import subprocess
import sys
from pathlib import Path

import pytest
from skill_runner_text import text_of

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_MD = sorted((REPO_ROOT / "core" / "skills").glob("**/*.md"))

# `$1`, `${1}`, `${1:-x}` — every positional shape, bare or braced.
POSITIONAL_RE = re.compile(r"\$\{?[0-9]")
# The Claude-Code-only escape. Compliance is elimination, never this.
ESCAPED_POSITIONAL_RE = re.compile(r"\\\$\{?[0-9]")


# ======================================================================================
# The harness contract, reproduced
# ======================================================================================

def substitute(text: str, argument_string: str) -> str:
    """Rewrite `text` the way the skill runner does, per the measurement in the docstring.

    Bare `$N` only, 0-based, out-of-range left alone, braced form untouched, `$ARGUMENTS`
    expanded to the whole string, and no exclusion for fenced blocks.
    """
    args = argument_string.split()
    out = text.replace("$ARGUMENTS", argument_string)

    def _repl(m: re.Match) -> str:
        idx = int(m.group(1))
        return args[idx] if idx < len(args) else m.group(0)

    # `(?<!\\)` so the escaped form is left alone — that is what makes the "an escape is
    # not compliance" test below able to tell the two apart.
    return re.sub(r"(?<!\\)\$([0-9])(?![0-9])", _repl, out)


def test_the_substitution_model_matches_what_was_measured():
    """If this ever fails, the harness changed and every conclusion below is stale."""
    probe = "P0=[$0] P1=[$1] P2=[$2] P9=[$9] B=[${1}] BD=[${1:-F}] A=[$ARGUMENTS]"
    got = substitute(probe, "alpha beta gamma")
    assert got == (
        "P0=[alpha] P1=[beta] P2=[gamma] P9=[$9] B=[${1}] BD=[${1:-F}] "
        "A=[alpha beta gamma]"
    ), got
    # No fenced-block exclusion — the whole reason a shell snippet is not safe here.
    assert substitute("```bash\nawk -F/ '{print $1}'\n```", "--scope backend") == (
        "```bash\nawk -F/ '{print backend}'\n```"
    )


# ======================================================================================
# The static rule
# ======================================================================================

def _offenders(pattern: re.Pattern) -> list[str]:
    hits = []
    for path in SKILL_MD:
        rel = path.relative_to(REPO_ROOT)
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                hits.append(f"{rel}:{n}: {line.strip()[:110]}")
    return hits


def test_no_skill_markdown_contains_a_shell_positional():
    hits = _offenders(POSITIONAL_RE)
    assert not hits, (
        "A skill body contains a positional parameter. The skill runner replaces it with an "
        "argument word before any shell sees it. Eliminate it — use `cut -f1`, parameter "
        "expansion, or a named variable — and write ABOUT positionals as `$<1>`:\n  "
        + "\n  ".join(hits)
    )


def test_the_escape_is_not_accepted_as_compliance():
    """`\\$1` fixes Claude Code and ships broken syntax to every other reader."""
    hits = _offenders(ESCAPED_POSITIONAL_RE)
    assert not hits, (
        "A skill body escapes a positional instead of eliminating it. `\\$1` is "
        "Claude-Code-only; Codex (Phase-142 symlinks) and the bash-installer path both get "
        "literally-broken shell:\n  " + "\n  ".join(hits)
    )
    # Not vacuous: the escaped form is real, and the two patterns really do differ.
    escaped = r"awk '{print \$1}'"
    assert ESCAPED_POSITIONAL_RE.search(escaped), "the escape pattern matches nothing"
    assert not ESCAPED_POSITIONAL_RE.search("awk '{print $1}'"), (
        "the escape pattern also matches the bare form, so the two tests are the same test"
    )


def test_arguments_is_permitted_and_the_scan_is_not_vacuous():
    """A zero-invariant is worthless if it read nothing. Pin the population BY NAME.

    A bare count floor was the first draft here, and this phase's own battery walked
    straight through it: `>= 24` relaxed to `>= 0` survived, because nothing else asserted
    what the population contains. Named membership cannot be relaxed the same way — the
    `_shared/` entry in particular is what keeps the glob from narrowing to `*/SKILL.md`.
    """
    rel = {str(p.relative_to(REPO_ROOT)) for p in SKILL_MD}
    skills = [p for p in SKILL_MD if p.name == "SKILL.md"]
    assert len(skills) >= 23, f"expected at least 23 SKILL.md, found {len(skills)}"
    for required in (
        "core/skills/review-close/SKILL.md",
        "core/skills/codebase-review/SKILL.md",
        "core/skills/security-audit/SKILL.md",
        "core/skills/daily-summary/SKILL.md",
        "core/skills/auto-build/SKILL.md",
        "core/skills/_shared/adversarial-review.md",   # non-SKILL.md: pins the glob width
    ):
        assert required in rel, f"{required} dropped out of the scanned population"

    # `$ARGUMENTS` is the deliberate dependency, and its presence proves the scan reads
    # content rather than empty strings.
    with_args = [p for p in skills if "$ARGUMENTS" in p.read_text(encoding="utf-8")]
    assert len(with_args) == len(skills), (
        "every skill takes $ARGUMENTS; if that changed, re-check whether the substitution "
        f"still applies at all — {len(with_args)} of {len(skills)}"
    )
    assert not POSITIONAL_RE.search("$ARGUMENTS"), "the rule must not flag $ARGUMENTS"
    assert not POSITIONAL_RE.search("$<1>"), "the `$<N>` writing convention must not flag"


def test_the_offender_scanner_actually_finds_things():
    """Positive control on `_offenders` itself.

    Both zero-invariants above call it, so neutering it turns both green at once — which
    is exactly what this phase's battery did (`W03`). This row is the thing that goes red.
    """
    found = _offenders(re.compile(r"\$ARGUMENTS"))
    assert len(found) >= 23, (
        f"_offenders() found only {len(found)} `$ARGUMENTS` lines across "
        f"{len(SKILL_MD)} files — the scanner is not reading, so the zero-invariants above "
        "are passing vacuously"
    )
    assert all(":" in f for f in found), "offender lines lost their file:line prefix"


# ======================================================================================
# Execution — the part that would actually have caught #360
# ======================================================================================

def _fenced_block_containing(path: Path, needle: str) -> str:
    """The ```bash block in `path` that contains `needle`, verbatim.

    Derived from the file at run time rather than retyped here: Phase 186 hand-copied two
    gate lines as constants, its own fixes edited them, and seven mutations silently did
    not run.
    """
    text = text_of(path)
    blocks = re.findall(r"```bash\n(.*?)```", text, re.DOTALL)
    matching = [b for b in blocks if needle in b]
    assert len(matching) == 1, (
        f"{path.relative_to(REPO_ROOT)}: expected exactly one ```bash block containing "
        f"{needle!r}, found {len(matching)} — the extractor's anchor has drifted"
    )
    return matching[0]


@pytest.fixture()
def tree(tmp_path):
    """A git repo whose top-level entries are known, so the enumeration has a right answer."""
    root = tmp_path / "proj"
    (root / "api" / "deep").mkdir(parents=True)
    (root / "web").mkdir()
    (root / "api" / "deep" / "x.py").write_text("x\n")
    (root / "api" / "y.py").write_text("y\n")
    (root / "web" / "app.tsx").write_text("t\n")
    (root / "README.md").write_text("r\n")
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed"],
        cwd=root, check=True, capture_output=True,
    )
    return root


def _run(script: str, cwd: Path) -> str:
    p = subprocess.run(["bash", "-c", script], cwd=str(cwd), capture_output=True, text=True)
    assert p.returncode == 0, f"{script}\n{p.stderr}"
    return p.stdout


EXPECTED_TOP_LEVEL = ["README.md", "api", "web"]


@pytest.mark.parametrize("skill", ["codebase-review", "security-audit"])
@pytest.mark.parametrize("argument_string", [
    "",                       # no arguments — always was safe
    "--dry-run",              # one word
    "--scope backend",        # TWO words: the documented invocation that broke it
    "--scope backend --full",
])
def test_2a0_enumeration_survives_every_documented_invocation(skill, argument_string, tree):
    """Step 2a-0's whole-repo enumeration, RUN, after the runner has rewritten it.

    This is the check the class needed: nothing in the suite executed these snippets, so
    `awk -F/ '{print $1}'` becoming `{print backend}` was invisible until an operator hit it
    — and it failed by affirmatively reporting complete map coverage over an empty inventory.
    """
    block = _fenced_block_containing(
        REPO_ROOT / "core" / "skills" / skill / "SKILL.md", "git ls-files"
    )
    got = sorted(_run(substitute(block, argument_string), tree).split())
    assert got == EXPECTED_TOP_LEVEL, (
        f"{skill} 2a-0 enumeration is wrong under {argument_string!r}: {got}"
    )


@pytest.mark.parametrize("argument_string", ["--scope backend", "a b c"])
def test_the_old_awk_form_still_reproduces_the_defect(argument_string, tree):
    """Positive control. Without this, a green test above proves nothing.

    If this ever stops failing, the substitution model or the fixture has drifted and the
    tests above are passing for the wrong reason.
    """
    old = "git ls-files | awk -F/ '{print $1}' | sort -u\n"
    rewritten = substitute(old, argument_string)
    assert "{print $1}" not in rewritten, "the control was not rewritten at all"
    got = _run(rewritten, tree).split()
    assert got == [], f"the control no longer reproduces #360 — it returned {got}"
    # And the shipped form under the identical treatment is correct.
    new = "git ls-files | cut -d/ -f1 | sort -u\n"
    assert sorted(_run(substitute(new, argument_string), tree).split()) == EXPECTED_TOP_LEVEL


def _seed_review_tasks(tree, body="a\nb\nc\n"):
    (tree / "review_tasks.md").write_text(body)
    subprocess.run(["git", "add", "-A"], cwd=tree, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "rt"],
        cwd=tree, check=True, capture_output=True,
    )


# Step 1a's classifier and Step 1b's numstat parse were shell the runner rewrote: a `$<N>` in
# the block became an argument word before bash saw it (#360). Phase 421 (`Q-665`) moved both,
# and Step 1c's loop, into `close_state.py`, which the runner never rewrites. What is left to
# pin is that the blocks that call it carry no `$` at all, so the rewrite has nothing to reach,
# and that the script still does what the shell did for the two numstat cases awk's `+0`
# coerced: no output, and a binary row (`-<TAB>-`).

STEP1_CALLS = ('python3 sysop/scripts/close_state.py worktrees "<default branch>"',
               "python3 sysop/scripts/close_state.py review-tasks",
               'python3 sysop/scripts/close_state.py archive-rotation "<default branch>"')


@pytest.mark.parametrize("call", STEP1_CALLS)
@pytest.mark.parametrize("argument_string", ["", "--dry-run", "--prepare",
                                             "--resume 20261007T000000Z-abcd", "a b c"])
def test_review_close_step1_blocks_give_the_rewrite_nothing_to_reach(call, argument_string):
    block = _fenced_block_containing(REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md", call)
    assert block.strip() == call, f"Step 1's block is no longer the one call: {block!r}"
    assert "$" not in block
    assert substitute(block, argument_string) == block


def _review_tasks(tree) -> str:
    p = subprocess.run([sys.executable, str(REPO_ROOT / "core/companion/scripts/close_state.py"),
                        "review-tasks"], cwd=tree, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    return p.stdout.strip()


def test_review_close_step1b_reads_clean_and_net_deletions(tree):
    _seed_review_tasks(tree)
    assert _review_tasks(tree) == "REVIEW_TASKS: clean", "Step 1b no longer short-circuits on a clean file"
    (tree / "review_tasks.md").write_text("a\n")            # 2 deletions, 0 additions
    assert _review_tasks(tree) == "REVIEW_TASKS: save (+0 -2)"
    (tree / "review_tasks_archive.md").write_text("b\nc\n")  # untracked sibling
    assert _review_tasks(tree) == "REVIEW_TASKS: rotation (+0 -2, review_tasks_archive.md dirty)"


def test_review_close_step1b_coerces_a_binary_numstat_row_to_zero(tree):
    """awk's `+0` turned numstat's `-<TAB>-` into 0; a `-` reaching `DELETED > ADDED` died with
    `[: -: integer expected`. The script must read it as 0 and still classify."""
    _seed_review_tasks(tree)
    (tree / "review_tasks.md").write_bytes(b"bin\x00ary\n")
    (tree / "review_tasks_archive.md").write_text("x\n")
    assert _review_tasks(tree) == "REVIEW_TASKS: save (+0 -0)"


def test_the_old_worktree_awk_form_still_reproduces_the_defect(tree):
    """Positive control for the Step 1a parser — three arguments empty the table."""
    old = ("git worktree list --porcelain | awk '\n"
           "  /^worktree / { path = $2 }\n"
           "  /^branch /   { br = substr($2, length(\"refs/heads/\") + 1);"
           " print path \"\\t\" br }\n'\n")
    assert _run(substitute(old, ""), tree).strip(), "control: unsubstituted form must work"
    rewritten = substitute(old, "a b c")
    assert "$2" not in rewritten, "the control was not rewritten"
    assert _run(rewritten, tree).strip() == "", (
        "the control no longer reproduces #360 — the ISSUE-0016 guard's input was emptied "
        "by exactly this"
    )


# --------------------------------------------------------------------------------------
# Execution coverage for the remaining two sites
# --------------------------------------------------------------------------------------
# Added by this phase's own review round, which measured the gap rather than arguing it:
# five semantic mutations to Step 3c's lookup and to daily-summary's Step 1 (a wrong
# worktree path, a never-matching branch compare, an inverted date offset, a garbage GNU
# fallback, a 999-day offset) ALL survived the full suite. The rows the author's battery
# had for those two sites only reintroduced a literal positional, which the *static* rule
# catches for free — that proves the file is wired to the scan, never that the replacement
# works. "The new guard is an execution test" was true for three of six sites.


def test_step3c_worktree_lookup_finds_the_right_worktree(tmp_path):
    """Step 3c resolves a branch name to its worktree path, executed.

    The old form used `substr($<0>,10)`, so ONE argument — `/review-close --dry-run`, which
    the skill's own `argument-hint` documents — was enough to break it, and it then printed
    NO_SMOKE_REQUIRED over a worktree it never scanned.
    """
    root = tmp_path / "main"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
    (root / "f.txt").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "s"],
                   cwd=root, check=True, capture_output=True)
    wt = tmp_path / "wt with space"
    subprocess.run(["git", "worktree", "add", "-q", str(wt), "-b", "task/FEAT-1"],
                   cwd=root, check=True, capture_output=True)

    # Since Phase 421 (`Q-665`) the lookup is `smoke_detect.py --branches`, in Python, which the
    # runner never rewrites, and the step's block is the one call with no `$` in it. So the
    # lookup is run through the script: a doc in the worktree is read, under a path with a space.
    block = _fenced_block_containing(
        REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md", "smoke_detect.py --branches"
    )
    assert "$" not in block and "awk" not in block
    for argument_string in ("", "--dry-run", "--prepare", "--resume 20261007T000000Z-abcd", "a b c"):
        assert substitute(block, argument_string) == block
    (root / "tasks").mkdir()
    (root / "tasks" / "index.yml").write_text("schema_version: 1\ntasks: []\n")
    pd = wt / "sysop" / "runtime" / "pending-docs"
    pd.mkdir(parents=True)
    (pd / "d.md").write_text('---\nbranch: "task/FEAT-1"\n---\n\n## Manual smoke\nrun it\n')
    smoke = REPO_ROOT / "core" / "companion" / "scripts" / "smoke_detect.py"
    def detect(*branches):
        p = subprocess.run([sys.executable, str(smoke), "--branches", "main", *branches], cwd=root,
                           capture_output=True, text=True, timeout=30)
        assert p.returncode == 0, p.stderr
        return p.stdout
    assert detect("task/FEAT-1").startswith("SMOKE_REQUIRED:"), (
        "Step 3c did not read the approved branch's worktree")
    # It must also scan nothing for a branch that has no worktree — otherwise the smoke
    # gate would scan an arbitrary directory. The branch exists: since Phase 421's round a name
    # that is not a local branch exits 3 (`test_review_close_smoke_gate_portability`).
    subprocess.run(["git", "branch", "no/worktree"], cwd=root, check=True, capture_output=True)
    assert detect("no/worktree").startswith("NO_SMOKE_REQUIRED")


def test_daily_summary_step1_computes_real_dates(tmp_path):
    """Step 1's three values, executed, after `<days>` is substituted as the skill says."""
    block = _fenced_block_containing(
        REPO_ROOT / "core" / "skills" / "daily-summary" / "SKILL.md", "WEEK_DAYS="
    )
    for argument_string in ("", "--week-only", "--date 2026-08-10", "--days 7 --week-only"):
        out = _run(substitute(block, argument_string).replace("'<days>'", "7"), tmp_path)
        vals = {}
        for line in out.strip().splitlines():
            k, _, v = line.replace("--- ", "").partition(":")
            vals[k.strip()] = v.strip()
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", vals["TARGET_DATE"]), vals
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", vals["WEEK_START"]), vals
        assert vals["DAY_NAME"] in {
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"
        }, vals
        d0 = datetime.date.fromisoformat(vals["TARGET_DATE"])
        assert (d0 - datetime.date.fromisoformat(vals["WEEK_START"])).days == 7, vals
        assert d0.strftime("%A") == vals["DAY_NAME"], vals


def test_daily_summary_step1_refuses_to_run_unsubstituted(tmp_path):
    """The placeholder is quoted so an unsubstituted run fails LOUDLY, not as a parse error.

    The round found the first draft's `WEEK_DAYS=<days>` was a bare redirection syntax
    error on the block's first line, and that the `--date` instruction ("replace the
    `TARGET_DATE=` line") was unfollowable because that assignment spanned two lines with a
    backslash continuation — replacing it stranded the `|| date …)` half.
    """
    block = _fenced_block_containing(
        REPO_ROOT / "core" / "skills" / "daily-summary" / "SKILL.md", "WEEK_DAYS="
    )
    p = subprocess.run(["bash", "-c", block], cwd=str(tmp_path), capture_output=True, text=True)
    assert p.returncode == 3, f"expected the placeholder guard's exit 3, got {p.returncode}"
    assert "substitute <days>" in p.stderr

    # And the --date override is followable: replacing the whole TARGET_DATE line works.
    lines = block.replace("'<days>'", "7").splitlines()
    idx = [i for i, l in enumerate(lines) if l.startswith("TARGET_DATE=")]
    assert len(idx) == 1, "TARGET_DATE= must be exactly one line for the instruction to hold"
    lines[idx[0]] = "TARGET_DATE=2026-08-10"
    out = _run("\n".join(lines), tmp_path)
    assert "TARGET_DATE: 2026-08-10" in out and "WEEK_START:  2026-08-03" in out, out
    assert "DAY_NAME:    Monday" in out, out
