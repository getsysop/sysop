"""Phase 254 (`Q-377`) — no skill body asserts or diffs against the literal `main`.

WHAT THIS CLASS IS
------------------
A skill is markdown an agent executes. Where it compares `HEAD` to a branch name, or names
a diff base, the name is the *consumer's* default branch — `main` on many, `master` or
`develop` on others. Phase 252 taught the three lifecycle scripts to resolve it; the skill
bodies that call them kept the literal, so on a `master` consumer `/claim-task` Step 4d
halted with *"HEAD is not main"* on a repository whose HEAD was `master` and correct, while
the script it wraps had just started working.

The remedy is a `<default branch>` placeholder resolved once per step by running
`sysop/scripts/default_branch.sh` bare — see `_shared/main-push-guard.md` § Rule A for why
it is a placeholder and not a shell variable (two independent reasons: an allow rule does
not match past a variable assignment, and nothing survives between fenced blocks).

WHY THE GUARD IS SHAPED THIS WAY
--------------------------------
1. **Zero-invariant over a DERIVED population, not a filename list.** The scan walks every
   skill file under `core/skills/`, so a skill added later is covered without anyone
   remembering to add it. Phase 254's own triage is the argument: `Q-377` named four
   skills and the loosest predicate found eight, the largest omission being a `_shared/`
   partial five skills paste from.
2. **The predicate is not fence-scoped.** MOST of this class's sites are backticked
   commands in *prose*, which a code-fence-scoped sweep never reaches. Derive the split
   rather than quoting one — Phase 254's published 119/80/57/53 are recorded as **not
   reproducible** in `tools/ROUND_YIELD_LEDGER.md`, and Phase 255 republished 57/119 in
   this very paragraph before its round caught it. Measured over `aad1c5c~1` with the
   predicate below: 118 sites, 39 inside fences and 79 outside, so a fence-scoped scan
   would report a green zero over two thirds of the class.
3. **The escape hatches are pinned verbatim.** The cheapest way to silence this guard is
   to add a line to `KEEPS` or a file to `DEFERRED`, so both are asserted exactly, and
   `DEFERRED` additionally has to stay non-vacuous (below).
"""
from __future__ import annotations

import re
from pathlib import Path

from tests import shape_lib as S

SKILLS = S.REPO_ROOT / "core" / "skills"

# ---------------------------------------------------------------------------------------
# The predicate. REWRITTEN after this phase's own round (see the module docstring's point 4).
# ---------------------------------------------------------------------------------------
# Emphasis is stripped first: `**main**` is the same token as `main`, and a guard that a
# pair of asterisks walks through is a guard keyed to typography.
_EMPH = re.compile(r"\*\*|__|\*")

# Python dunders are stripped to nothing by `_EMPH` (`__main__` -> `main`), so
# `if __name__ == "__main__":` would trip Tier 1's `== "main"`. Masked BEFORE emphasis is
# stripped. Dormant today -- no skill `.md` carries a Python main-guard -- but it is the
# over-strictness direction the module docstring calls the one that hides, and it would
# fire the moment this population widened to `.py` or a skill pasted a Python block
# (Phase 255 round, guards lens).
_DUNDER = re.compile(r"__[A-Za-z0-9_]+__")

# Tier 1 — `main` in a REF POSITION. A violation wherever it appears, quoted or not,
# because none of these shapes has a non-git reading.
REF_SHAPE = re.compile(
    r'origin/main\b'
    r'|\bmain\.\.\.'          # three-dot, name on the left
    r'|\.\.main\b'             # ...and on the right, which the first predicate missed
    r'|\bmain\.\.(?!\.)'
    # Refspec destination — `"${PUSHED_SHA}:main"`, `HEAD:main`. Anchored on the
    # delimiter rather than "any colon", so a docker tag (`ghcr.io/org/app:main`)
    # is not swept in. `@main` needs no such guard: `actions/checkout@main` names
    # the branch, which is exactly the class.
    r'|(?:\}|>|["\']|\bHEAD):main\b'
    r'|@main\b'
    r'|\bmain@\{'              # `main@{u}`
    r'|(?:refs/)?heads/main\b'
    r'|[=!]=?\s*[`\'"]main[`\'"]'   # `= `main`` / `= "main"` / `!= \'main\''
    r'|[=!]=?\s*main\b'             # ...and unquoted
)

# Tier 2 — `main` as a bare OPERAND of a git/gh command on the same line. This is what
# catches `git switch main`, `git rebase main`, `git push --force-with-lease origin main`
# and the eighteen other verbs and flag positions that Tier 1 cannot enumerate.
_GIT_CMD = re.compile(r'\b(?:git|gh)\s')

# A backticked span counts as a command when a git/gh invocation appears ANYWHERE in it,
# not only at its start. The first cut anchored with `re.match`, and the round's guards lens
# measured 117 spans in the shipped skills that carry a git/gh command without opening with
# one -- `cd sysop && git checkout main`, `(git checkout main)`, `PATH=… git …`, a `!`
# shell-escape. Each was a site the guard could not see in the very file it was written for.
#
# The leading-boundary alternation is what keeps this from matching prose: `git` must start
# the span, or follow a shell separator/opener (`&&`, `||`, `;`, `|`, `(`, `{`, `!`) or an
# env assignment. So "the `main` branch, per git convention" is still not a command.
_SPAN_IS_COMMAND = re.compile(
    r'(?:^|[;&|(){}]|\bthen\b|\bdo\b|!)\s*'
    r'(?:[A-Za-z_][A-Za-z0-9_]*=\S*\s+)*'
    r'(?:git|gh)\s'
)
# Excludes the git-common-dir sense — "the main checkout / repo / worktree / root" — which
# is a filesystem noun, not a ref, and must never be rewritten.
_BARE_OPERAND = re.compile(
    r'(?<![\w./`-])["\']?main["\']?'
    r'(?!\s+(?:checkout|repo|repository|worktree|root|venv|branch))'
    # `main's` is a possessive, never a git operand — and `git` appears as an English
    # word often enough ("without git the base path…") to put such a line in command mode.
    r'(?![\w`\'’-])'
)


def is_executable_default_branch_literal(line: str) -> bool:
    """True when `line` uses the literal `main` as a git ref rather than as English.

    Two tiers, because one predicate cannot do both jobs. Tier 1 enumerates ref SHAPES
    (`origin/main`, `..main`, `:main`, `= "main"`, …), which are violations wherever they
    appear — backticked or not — because none has a non-git reading. Tier 2 catches `main`
    as a bare OPERAND of a git/gh command, which is where the long tail lives: nineteen
    different verbs and flag positions defeated the first draft of this guard.

    An inline backtick span counts as a command when it STARTS with `git`/`gh` — so
    ``git switch main`` in prose is a violation while "commits land on `main`" is not.
    That is the same discriminator `shape_lib.phantom_inline_commands` uses, and it is the
    line between a prose mention (a different class, deliberately not this invariant) and
    an instruction an agent executes.
    """
    line = _EMPH.sub("", _DUNDER.sub("DUNDER", line))
    if REF_SHAPE.search(line):
        return True

    # Split into backticked spans and the text between them.
    parts, i, in_span = [], 0, False
    for chunk in line.split("`"):
        parts.append((chunk, in_span))
        in_span = not in_span

    for chunk, spanned in parts:
        if spanned:
            # A quoted span is a command only if it opens with one -- allowing for the two
            # prefixes this tree actually puts in front of one. `!` is the shell-escape the
            # skills tell a user to type at their own prompt, and `VAR=value` is the
            # venv-aware `PATH=` prefix Phase 183 established; both were invisible to the
            # first cut, which hid `! git push origin main` at review-close:2589 -- a real
            # executable site, in the file the whole invariant was written for (Phase 255
            # round, claims lens, `M5`).
            if not _SPAN_IS_COMMAND.search(chunk):
                continue
        elif not _GIT_CMD.search(chunk):
            continue
        if _BARE_OPERAND.search(chunk):
            return True
    return False


# EMPTY since Phase 255 (`Q-381`), and that is the point: `/review-close` was the last
# member, carrying 76 of the class's 80 remaining sites. The invariant is now a true
# zero over every skill, with no file-level exemption at all. Re-adding a member is a
# deliberate decision — `test_deferred_is_exactly_the_known_set` pins the set exactly,
# and the non-vacuity check below refuses a member that exempts nothing.
DEFERRED: frozenset[str] = frozenset()

# Sites deliberately left, each with a reason. Pinned by the WHOLE normalized line, not a
# substring: this phase's round appended a live defect to the end of a keep's line and the
# exemption still swallowed it, while the uniqueness test stayed green.
KEEPS = {
    # This phase's own sentence explaining why the literal fails; it has to name it.
    ("_shared/ui-verify.md",
     "`git merge-base main HEAD` on a repo without a `main` ref fails outright, which makes the"),
    # Rule B/C rationale: `main` as the canonical example of the race, not an instruction.
    ("_shared/main-push-guard.md",
     "`origin/main` advances at unpredictable times. A direct `git push origin main` can"),
    ("_shared/main-push-guard.md",
     "A non-fast-forward rejection on `main` means an **auto-merged commit** is on `origin/main`"),
}


def _skill_files() -> list[Path]:
    return sorted(p for p in SKILLS.rglob("*.md") if p.is_file())


def _rel(p: Path) -> str:
    return str(p.relative_to(SKILLS))


def _norm(line: str) -> str:
    """Whitespace-normalised, so a reflow does not break a keep but a reword does."""
    return " ".join(line.split())


def _keep_lines() -> set[tuple[str, str]]:
    return {(r, _norm(t)) for r, t in KEEPS}


def _logical_lines(text: str) -> list[tuple[int, str, str]]:
    """`(first_line_no, joined_text, raw_line)` per logical line.

    A backslash continuation separates an operand from the command word that governs it,
    so a PER-LINE predicate cannot see that `| grep -v '^main$' \\` belongs to the
    `git for-each-ref` above it. That is how `/review-close`'s Step 1c filter survived
    this phase's own sweep and was found by an independent lens running the block (Phase
    255 round, execute lens, `M3`) — the exact "keyed to a physical line" assumption
    § *Before you spawn anyone* rule 1 names.

    Reported against the FIRST line of the group, and the raw line is kept so a `KEEPS`
    entry still pins one physical line rather than a joined blob.
    """
    out: list[tuple[int, str, str]] = []
    buf, start = "", None
    for n, line in enumerate(text.splitlines(), 1):
        if start is None:
            start = n
        buf += (" " if buf else "") + line.rstrip("\\").rstrip()
        if line.rstrip().endswith("\\"):
            continue
        out.append((start, buf, line))
        buf, start = "", None
    if start is not None:
        out.append((start, buf, buf))
    return out


def _violations(include_deferred: bool = False) -> list[str]:
    keeps = _keep_lines()
    out: list[str] = []
    for path in _skill_files():
        rel = _rel(path)
        if not include_deferred and path.parts[len(SKILLS.parts)] in DEFERRED:
            continue
        for n, line, raw in _logical_lines(path.read_text(encoding="utf-8")):
            if not is_executable_default_branch_literal(line):
                continue
            # WHOLE-line equality, not `in`: appending to a kept line must un-keep it.
            # Matched against the RAW physical line so a keep stays a one-line pin.
            if (rel, _norm(raw)) in keeps or (rel, _norm(line)) in keeps:
                continue
            out.append(f"{rel}:{n}: {line.strip()[:120]}")
    return out


# --------------------------------------------------------------------------------------
# The invariant
# --------------------------------------------------------------------------------------
def test_no_skill_body_uses_the_literal_default_branch():
    bad = _violations()
    assert not bad, (
        "skill site(s) hard-coding `main` as the default branch — on a `master` consumer "
        "each of these halts or silently compares the wrong refs. Substitute the "
        "`<default branch>` placeholder and have the step resolve it with "
        "`bash sysop/scripts/default_branch.sh` (run BARE — see `_shared/main-push-guard.md` "
        "§ Rule A for why not a variable):\n  " + "\n  ".join(bad)
    )


def test_every_keep_matches_exactly_one_line_verbatim():
    """A keep is a whole line. If the line it names has been reworded — or ADDED TO — the
    keep stops matching and the site returns as a violation, which is the point: this
    phase's round hid a live defect by appending it to a kept line."""
    for k_rel, k_txt in sorted(KEEPS):
        path = SKILLS / k_rel
        assert path.is_file(), f"keep names a file that does not exist: {k_rel}"
        want = _norm(k_txt)
        hits = [ln for ln in path.read_text(encoding="utf-8").splitlines()
                if _norm(ln) == want]
        assert len(hits) == 1, (
            f"keep {k_rel!r} matches {len(hits)} lines verbatim, not 1 — the line was "
            "reworded or added to. Re-pin it against the current text, or drop it and fix "
            "the site."
        )
        assert is_executable_default_branch_literal(hits[0]), (
            f"keep {k_rel!r} exempts a line the predicate does not even flag — it is "
            "covering nothing and should be deleted"
        )


def test_the_deferred_set_is_pinned():
    """The cheapest way to silence this guard is to add a directory to DEFERRED. The round
    did exactly that — added `auto-build`, hid a defect in it, and the suite stayed green,
    because nothing asserted the set's membership."""
    assert DEFERRED == frozenset(), (
        f"DEFERRED is {sorted(DEFERRED)}. Adding a directory here exempts an entire skill "
        "from the invariant. That is a decision with a filed queue entry behind it "
        "(`review-close` has `Q-381`), not an edit."
    )


def test_every_deferred_entry_is_non_vacuous():
    """The ratchet, and it is PER ENTRY. Aggregating it meant one populated exclusion
    satisfied the check for every other one."""
    all_v = _violations(include_deferred=True)
    for name in sorted(DEFERRED):
        hits = [v for v in all_v if v.split("/", 1)[0] == name]
        assert hits, (
            f"`{name}` is in DEFERRED but carries no executable default-branch literal, so "
            "the exclusion now covers nothing. Remove it from DEFERRED (and close its queue "
            "entry) rather than leaving a stale exemption behind."
        )


def test_the_predicate_catches_the_shapes_that_defeated_its_first_draft():
    """Non-vacuity with teeth. Every string below is a spelling an independent reviewer
    inserted into a shipped skill file while the first version of this guard stayed green.
    They are kept as a corpus because the failure was not a missing case — it was a
    predicate that enumerated command SHAPES and therefore could never cover the verbs and
    flag positions it had not thought of."""
    must_catch = [
        "git switch main", "git rev-parse --verify main", "gh pr create --base main --fill",
        "git merge main --no-ff", "git checkout \"main\"", "git checkout -B main",
        'test "$(git rev-parse --abbrev-ref HEAD)" = \'main\' || exit 1',
        "git merge-base --fork-point main HEAD", "git push --force-with-lease origin main",
        "git fetch --prune origin main", "git rev-parse main@{u}", "git rebase main",
        "git ls-remote origin heads/main", "git pull --ff-only origin main",
        'if [[ "$(git branch --show-current)" != main ]]; then exit 1; fi',
        "git reset --hard main", "git diff main HEAD", "git worktree add ../wt main",
        "git log --oneline origin/main", 'git diff --name-only "$base..main"',
        "Assert `git rev-parse --abbrev-ref HEAD` = `main`",
        'git push origin "${PUSHED_SHA}:main"', "uses: actions/checkout@main",
        # Phase 255's round, guards lens: shapes that walked through the SECOND draft.
        # The span arm anchored the git verb at the START of a backticked span, and the
        # lens measured 117 spans in the shipped skills carrying a git/gh command without
        # opening with one. Every entry below was full-suite green when it was found.
        "Run `cd sysop && git checkout main` first.",
        "Use `(git checkout main)` in a subshell.",
        "`PATH=.venv/bin:$PATH git checkout main`",
        "`! git push origin main`",
        # A backslash continuation separates the operand from its command word; joined by
        # `_logical_lines`. This one shipped, at /review-close Step 1c, and was found by an
        # independent lens RUNNING the block rather than reading it.
        "git for-each-ref --format='%(refname:short)' refs/heads/ | grep -v '^main$'",
    ]
    missed = [c for c in must_catch if not is_executable_default_branch_literal(c)]
    assert not missed, f"predicate no longer catches: {missed}"

    must_not_catch = [
        # Python dunders survive `_EMPH`'s `__` stripping only because they are masked
        # first; without that, `__main__` becomes `main` and Tier 1 fires on the `==`.
        'if __name__ == "__main__":',
        'if __name__ == "__main__": sys.exit(main())',
        "lands *one* batch of approved work on `main` and verifies *one* deploy",
        "## Rule C — NEVER force-push `main` (or any branch a squash PR will write it from)",
        "The directory lives in the **main** checkout, not the worktree",
        "Read the task from the main checkout, not the worktree.",
        "docker pull ghcr.io/org/app:main",
        "It prints one bare name (`main`, `master`, `develop`, …) and exits 0",
    ]
    false_pos = [c for c in must_not_catch if is_executable_default_branch_literal(c)]
    assert not false_pos, (
        f"predicate now flags prose it must not: {false_pos} — over-strictness is the "
        "direction that hides, because the noise gets silenced with a KEEPS entry"
    )


def test_the_scan_population_is_non_empty_and_reaches_prose():
    """Non-vacuity of the population, and specifically that the scan is not fence-scoped:
    the majority of this class's sites are prose commands, so a scan seeing only fenced
    code would report a green zero while more than half the class stood.

    **This used to take `/review-close` as its live specimen** — the one file with known
    violations, counted inside and outside fences. Phase 255 (`Q-381`) closed that file,
    so the class has no live specimen anywhere in the tree. That is the goal, and it also
    makes a specimen-based non-vacuity check impossible to keep honest: it would go red
    the moment the class was fully closed, and the only way to green it would be to
    reintroduce a defect.

    So the PREDICATE's reach is asserted directly instead, on the real shapes from the
    closed population — a fenced command line and a backticked command inside a sentence.

    **What this does not assert, stated rather than implied:** that `_violations` itself is
    not fence-scoped. That rests on reading its body (it iterates lines with no fence
    tracking at all), and adding fence tracking to it would leave this module green. The
    specimen test this replaced did cover the scanner; nothing here does. It is named
    because the round found the first draft claiming both properties were asserted.
    """
    files = _skill_files()
    assert len(files) > 15, f"only {len(files)} skill files scanned — population collapsed"

    fenced_form = 'git checkout main'
    prose_form = ("**Under `direct` it can be a superset**, and deliberately so: Step 4-pre "
                  "is a bare `git checkout main` with no fetch")
    assert is_executable_default_branch_literal(fenced_form), (
        "the predicate no longer fires on a bare fenced command — the population it "
        "reaches has collapsed to nothing")
    assert is_executable_default_branch_literal(prose_form), (
        "the predicate no longer fires on a backticked command inside a sentence, which is "
        "MOST of this class — a fence-scoped predicate would report a green zero over the "
        "majority of it. Derive the split; do not quote a number here (see the module "
        "docstring: Phase 254's figures are recorded as not reproducible)")

    # And an English mention of the branch must still NOT fire, or the "zero" above is
    # bought by a predicate that flags every sentence containing the word.
    assert not is_executable_default_branch_literal(
        "commits land on `main` locally, then the integration branch is cut")


