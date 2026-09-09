"""`Q-445` / `Q-447`, Phase 271 — a rollback must be VERIFIED, not widened.

`git checkout <path>` and `git checkout -- <path>` restore the path **from the
index**. Over a staged copy of the very change being rolled back, that is a
silent no-op: measured in a scratch repo, `Updated 0 paths from the index`,
**exit 0**, the task still `in_progress`, the staged diff intact — so the caller
reports a rollback that did not happen.

**The obvious fix was built, measured, and REFUSED.** `git checkout HEAD --
<path>` restores the index too. Where the staged content belongs to *another
session* it destroys that session's work: measured with session A rolling back
while session B held a staged claim for a different task, the bare form left B
`in_progress` (correct, precise) and the `HEAD --` form silently reset B to
`open` — exit 0, no output. Two further refusals came from the same lens: in a
conflicted merge `HEAD --` resolves the conflict and exits 0 where the bare form
correctly refuses; and for a newly-added-but-uncommitted file the bare form
restores while `HEAD --` fails outright.

And the one state in which the staged flip is reliably *ours* — after
`claim_task.sh --commit-claim` stages and then fails — is the state both skills
already tell you not to run a rollback in at all. So wherever this checkout
actually runs, staged content belongs to somebody else, and the wider command
only ever trades a false report for silent data loss.

**So the guard asserts a PAIRING, not a spelling.** Each site keeps the precise
bare checkout and gains a check for the exact precondition the no-op needs — the
path being staged. That closes the real defect, destroys nothing, and needs no
new permission, since `git diff` is read-only.
"""
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Phase 270's commit — the last tree that carried the bare form.
PRE_PHASE = "22d4a9b"

# The files whose rollback correctness this is about.
GUARDED_PATHS = ("tasks/index.yml", "review_tasks.md")

# Sites that prescribe or perform a rollback of one of those paths.
SITES = {
    "core/skills/claim-task/SKILL.md": "tasks/index.yml",
    "core/skills/auto-build/SKILL.md": "tasks/index.yml",
    "core/companion/scripts/batch_work.sh": "review_tasks.md",
}

# `restore` as well as `checkout`: `git restore <path>` is the modern spelling of
# exactly this defect (it restores from the index by default too), and an
# independent battery walked it straight through a checkout-only pattern. Flags,
# a `./` prefix, quoting and a `-c key=value` are all allowed between the verb and
# the path for the same reason — each was a surviving mutation, and none of them
# is adversarial; they are how people write.
_CHECKOUT = re.compile(
    r"(?:git|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?)\s+(?:-[cC]\s+\S+\s+)*"
    r"(?:checkout|restore)\s+(?!-b\b)"
    r"(?:(?:-[A-Za-z-]+(?:=\S+)?|--)\s+)*"
    r"['\"]?(?:\./)?(?P<path>" + "|".join(re.escape(p) for p in GUARDED_PATHS) + r")(?!\w)"
)

# The REFUSED form, in every spelling that restores from a commit. A battery
# walked three past a literal `checkout HEAD --`: `git restore --source=HEAD
# --staged --worktree`, `git checkout HEAD <path>` with no `--`, and `git
# checkout @ --` (`@` is a synonym for HEAD). All of them revert the index, which
# is the property that destroys a concurrent session's staged claim.
_HEAD_FORM = re.compile(
    r"(?:git|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?)\s+(?:-[cC]\s+\S+\s+)*"
    r"(?:"
    r"checkout\s+(?:HEAD|@|[0-9a-f]{7,40})\s+(?:--\s+)?"
    r"|restore\s+(?:[^\n]*?(?:--source(?:=|\s+)(?:HEAD|@)|--staged))[^\n]*?\s"
    r")"
    r"['\"]?(?:\./)?(?:" + "|".join(re.escape(p) for p in GUARDED_PATHS) + r")(?!\w)"
)

# The verification. Flag ORDER and spelling are free — a battery reddened the
# first version with `--quiet --cached` reversed, with `--exit-code` (the long
# form of the same thing), with the `--` separator dropped, and with a `./`
# prefix. None of those is adversarial; they are the same command.
def _verify_re(path: str) -> re.Pattern:
    """A verification naming THIS path specifically.

    The first version matched any guarded path, so a check on `review_tasks.md`
    satisfied a rollback of `tasks/index.yml`. The pairing has to be about the
    file being restored or it is not a pairing.
    """
    return re.compile(
        r"git\s+(?:-C\s+\S+\s+)?diff\s+"
        r"(?:(?:--cached|--staged|--quiet|--exit-code|HEAD|--)\s+)*"
        r"['\"]?(?:\./)?" + re.escape(path) + r"(?!\w)"
    )


def _prescription_lines(text: str, path: Path):
    """Only the lines that PRESCRIBE a command, never the prose about one.

    This is the distinction the first cut lacked, and it broke the guard in both
    directions at once. The explanatory paragraphs this phase added — which quote
    the bare form in order to explain why it is used — were counted as unverified
    prescriptions, so the pairing check failed on a correct tree; and an
    independent battery's control (`Never run `git checkout tasks/index.yml`
    here.`) reddened for the same reason, which is over-strictness on ordinary
    documentation.

    The cut, stated because it is load bearing rather than obvious:

    - **In markdown, everything inside a fenced block counts, comments included.**
      A `# roll back with …` line inside a bash fence IS telling an operator what
      to run — `/auto-build` Step 5.2 prescribes its rollback exactly that way —
      so excluding fenced comments made the guard blind to that whole site.
    - **Outside a fence, markdown never counts.** That is prose, and a paragraph
      explaining why a command is wrong is not a prescription of it.
    - **In a shell script, only executable lines count.** The inverse choice from
      markdown, and deliberate: a script's comments are where this project keeps
      its rationale, and this phase alone added several that quote the bare form
      in order to reject it.

    The limit this leaves, named rather than hidden: a rollback prescribed in a
    *shell comment* is not governed by the pairing check.
    """
    lines = _logical_lines(text)
    if path.suffix != ".md":
        return [(i, ln) for i, ln in enumerate(lines) if not ln.lstrip().startswith("#")]
    out, fence = [], None
    for i, ln in enumerate(lines):
        st = ln.lstrip()
        m = re.match(r"(`{3,}|~{3,})", st)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark
            elif mark[0] == fence[0] and len(mark) >= len(fence):
                fence = None
            continue
        if fence is not None:
            out.append((i, ln))
    return out
# The verification: a staged-state test naming the same path. `--cached` (index
# vs HEAD) at the skill sites detects the precondition directly; `diff --quiet
# HEAD` (worktree vs HEAD) at the script sites checks the postcondition without
# touching anyone else's stage. Either satisfies this.
_VERIFY = re.compile(
    r"git\s+(?:-C\s+\S+\s+)?diff\s+(?:--cached\s+)?--quiet(?:\s+HEAD)?\s+--\s+(?:"
    + "|".join(re.escape(p) for p in GUARDED_PATHS) + r")(?!\w)"
)


def _logical_lines(text: str):
    """Physical lines joined across trailing backslashes.

    A guard keyed to a physical line is walked through by a continuation, and an
    earlier version of this one was: `git checkout \\` + newline + `  tasks/index.yml`
    survived the author battery. Joining first makes the predicate read what the
    shell reads.
    """
    out, buf = [], ""
    for ln in text.splitlines():
        if ln.rstrip().endswith("\\"):
            # `.rstrip()` twice: once to find the trailing backslash, once to drop
            # the whitespace before it, so the join inserts exactly one separator.
            buf += ln.rstrip()[:-1].rstrip() + " "
            continue
        out.append(buf + ln)
        buf = ""
    if buf:
        out.append(buf)
    return out


# How far after a checkout the verification may sit. Small on purpose: the check
# has to be the next thing that happens, not somewhere else in the file.
_WINDOW = 14


def _counts(text: str, path: Path):
    """(checkout sites, checkouts verified for THEIR OWN path with a consequence).

    Three things the first version got wrong, each measured by a review battery:

    - It searched `_VERIFY` over **every** line, so a commented-out verification
      satisfied the pairing. The verification must itself be a prescription.
    - It matched any guarded path, so a check on one file paired with a rollback
      of another.
    - It never read the CONSEQUENCE, so `git diff --quiet … || true` counted. A
      verification whose failure is discarded verifies nothing, so a stop token
      must follow within a few lines.
    """
    pres = _prescription_lines(text, path)
    idx = {i for i, _ in pres}
    by_line = dict(pres)
    checkouts = [(i, m) for i, ln in pres if (m := _CHECKOUT.search(ln))]
    paired = 0
    for i, m in checkouts:
        vre = _verify_re(m.group("path"))
        window = [j for j in sorted(idx) if i < j <= i + _WINDOW]
        for j in window:
            cand = by_line[j]
            if not vre.search(cand):
                continue
            st = cand.lstrip()
            # A COMMENTED verification does not run. The checkout side counts
            # fenced comments on purpose (`/auto-build` Step 5.2 prescribes its
            # rollback that way), but the two sides are not symmetric: a comment
            # can TELL an operator to run something, and cannot itself check
            # anything. A battery commented the verify out and the pairing held.
            if st.startswith("#"):
                continue
            # An `echo`/`printf` of the command is a DIAGNOSTIC STRING, not a
            # check. The shipped block prints `Inspect with: git diff --cached --
            # tasks/index.yml`, and that line alone satisfied the pairing when the
            # real verification was mutated to name a different path.
            if re.match(r"(?:echo|printf)\b", st):
                continue
            if re.search(r"\|\|\s*true", cand):
                continue  # failure discarded
            tail = " ".join(by_line[k] for k in window if k >= j)
            if re.search(r"\bexit\b|\breturn\b|STOP|\bfail\b", tail, re.I):
                paired += 1
                break
    return len(checkouts), paired


def test_the_scanned_files_all_exist():
    """Vacuity: a scan over missing paths reports clean forever."""
    missing = [p for p in SITES if not (REPO_ROOT / p).is_file()]
    assert not missing, f"scanned files have moved: {missing}"


# A FLOOR per site, so deleting the rollback outright is not a way to pass. With
# only `paired < checkouts`, removing the checkout leaves 0 < 0, which is false —
# a battery deleted `batch_work.sh`'s rollback and the module stayed green.
MIN_CHECKOUTS = {
    "core/skills/claim-task/SKILL.md": 1,
    "core/skills/auto-build/SKILL.md": 1,
    "core/companion/scripts/batch_work.sh": 2,
}


def test_each_site_still_prescribes_its_rollback():
    """Deletion is a bypass, not a fix. If a rollback genuinely goes away, lower
    the floor here in the same commit and say why."""
    short = []
    for rel, floor in MIN_CHECKOUTS.items():
        checkouts, _ = _counts((REPO_ROOT / rel).read_text(encoding="utf-8"), REPO_ROOT / rel)
        if checkouts < floor:
            short.append(f"{rel}: {checkouts} rollback checkout(s), expected at least {floor}")
    assert not short, (
        "a rollback prescription disappeared — the pairing check cannot see a site that "
        "no longer has a checkout to pair:\n  " + "\n  ".join(short)
    )


def test_every_rollback_checkout_is_paired_with_a_verification():
    """The property is the PAIRING. A site that prescribes the checkout without a
    staged-state check reports a rollback it has not confirmed happened."""
    problems = []
    for rel in SITES:
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        checkouts, paired = _counts(text, REPO_ROOT / rel)
        if checkouts and paired < checkouts:
            problems.append(
                f"{rel}: {checkouts} rollback checkout(s), only {paired} followed by a "
                f"verification within {_WINDOW} lines")
    assert not problems, (
        "a rollback of a guarded path is not verified (`Q-445`/`Q-447`). "
        "`git checkout <path>` restores from the INDEX, so over a staged copy it "
        "exits 0 having changed nothing and the caller reports success. Pair it "
        "with `git diff --cached --quiet -- <path>` (or `git diff --quiet HEAD -- "
        "<path>`) and STOP when that fails. Do NOT 'fix' this by switching to "
        "`git checkout HEAD -- <path>`: that was measured destroying a concurrent "
        "session's staged claim, resolving a merge conflict, and failing on a "
        "newly-added file.\n  " + "\n  ".join(problems)
    )


def test_no_site_reintroduces_the_head_form():
    """The refused fix, pinned out. It reads as the safer spelling, which is
    exactly why it needs a guard rather than a comment."""
    offenders = []
    for rel in SITES:
        for ln in _logical_lines((REPO_ROOT / rel).read_text(encoding="utf-8")):
            if not _HEAD_FORM.search(ln):
                continue
            # Prose that names the form in order to REJECT it is the record of
            # why it is absent, not a use of it. Case-insensitive on the negation
            # words: a battery reddened this with a lowercase `not`.
            if re.search(r"refused|disqualified|destroy|do not|never|was built as the fix|"
                         r"would have|rather than|instead of|refutes?|no longer",
                         ln, re.I):
                continue
            offenders.append(f"{rel}: {ln.strip()[:120]}")
    assert not offenders, (
        "a site prescribes `git checkout HEAD -- <guarded path>` again. It reverts "
        "the INDEX too, so it destroys whatever another session had staged — "
        "measured: a second task's claim silently reset to `open`, exit 0.\n  "
        + "\n  ".join(offenders)
    )


def test_the_pairing_predicate_reds_on_the_pre_phase_tree():
    """Non-vacuity against REAL historical text.

    Before this phase every site had the checkout and none had a verification, so
    the pairing check must fire on all three. A guard that cannot see the defect
    it was written for is the failure mode this project has repeatedly paid for.

    The revision is a LITERAL SHA. An earlier cut used `git show HEAD:<path>` and
    was green — but only on a DIRTY tree, where `HEAD` was still the pre-fix
    commit; the moment the phase committed, `HEAD` became the fixed tree and the
    control went red having tested nothing. `HEAD~1` is no better: it moves under
    a squash-merge.
    """
    fired = []
    for rel in SITES:
        r = subprocess.run(["git", "show", f"{PRE_PHASE}:{rel}"],
                           cwd=REPO_ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            pytest.skip(
                f"{PRE_PHASE} is not reachable here (a shallow clone, or a tree published "
                "without this history); the predicate's detection cannot be checked. CI "
                "uses actions/checkout at its default fetch-depth of 1, so this is the "
                "NORMAL path there — asserting instead reds the required check on every "
                "push, which the first version of this control did. The precedent in "
                "`test_rollback_commit_stays_deleted.py` skips for the same reason, and "
                "this docstring cited it while doing the opposite."
            )
        checkouts, paired = _counts(r.stdout, Path(rel))
        assert checkouts, f"{rel} had no rollback checkout at {PRE_PHASE}; anchors moved"
        if paired < checkouts:
            fired.append(rel)
    assert sorted(fired) == sorted(SITES), (
        f"the pairing predicate does not fire on the pre-phase tree for every site: {fired}"
    )


@pytest.mark.parametrize("line,expected", [
    ("git checkout tasks/index.yml", True),
    ("git checkout -- tasks/index.yml", True),
    ('git -C "$MAIN_ROOT" checkout -- review_tasks.md 2>/dev/null || true', True),
    ("  # roll back with `git checkout tasks/index.yml`,", True),
    ("$GIT checkout tasks/index.yml", True),
    ("git checkout <default branch>", False),
    ("git checkout -b feature/x", False),
    ('git checkout "$BRANCH_NAME"', False),
])
def test_the_checkout_predicate_discriminates(line, expected):
    """Both directions. Over-strictness hides: a predicate that also fired on
    `git checkout <branch>` would be reverted by the first person it blocked."""
    assert bool(_CHECKOUT.search(line)) is expected, line


@pytest.mark.parametrize("line,expected", [
    ("git diff --cached --quiet -- tasks/index.yml || {", True),
    ('git -C "$MAIN_ROOT" diff --quiet HEAD -- review_tasks.md 2>/dev/null', True),
    ("git diff --cached --quiet -- some/other/file", False),
    ("git diff --stat -- tasks/index.yml", False),
])
def test_the_verification_predicate_discriminates(line, expected):
    assert bool(_VERIFY.search(line)) is expected, line


def test_a_continuation_split_checkout_is_still_seen():
    """The joiner is a MECHANISM, and a mechanism nobody asserts is decoration:
    reverting `_logical_lines` to a plain `splitlines()` once left the whole suite
    green."""
    split = "run the rollback:\ngit checkout \\\n  tasks/index.yml\nthen stop\n"
    assert any(_CHECKOUT.search(ln) for ln in _logical_lines(split))


def test_the_joiner_reassembles_exactly():
    assert _logical_lines("a \\\nb\nc\n") == ["a b", "c"]
    assert _logical_lines("no continuation\n") == ["no continuation"]
    assert _logical_lines("x \\\n") == ["x "]


@pytest.mark.parametrize("line", [
    # Every spelling that restores from a COMMIT and therefore reverts the index.
    "git restore --source=HEAD --staged --worktree tasks/index.yml",
    "git checkout HEAD tasks/index.yml",          # no `--`
    "git checkout @ -- tasks/index.yml",          # `@` is HEAD
    "git checkout HEAD -- tasks/index.yml",
    'git -C "$R" restore --staged review_tasks.md',
])
def test_the_refused_form_is_seen_in_every_spelling(line):
    """A battery walked three of these past a literal `checkout HEAD --`. The
    property is 'restores from a commit', not one way of writing it."""
    assert _HEAD_FORM.search(line), line


@pytest.mark.parametrize("line", [
    "git checkout tasks/index.yml",
    "git checkout -- tasks/index.yml",
    "git checkout <default branch>",
])
def test_the_refused_form_predicate_does_not_swallow_the_correct_one(line):
    assert not _HEAD_FORM.search(line), line


@pytest.mark.parametrize("line", [
    "git diff --cached --quiet -- tasks/index.yml",
    "git diff --quiet --cached -- tasks/index.yml",   # order reversed
    "git diff --cached --exit-code tasks/index.yml",  # long form, no `--`
    "git diff --quiet HEAD -- ./tasks/index.yml",     # `./` prefix
])
def test_the_verification_is_recognised_however_it_is_spelled(line):
    """Each of these reddened the first version, and none is adversarial — they
    are the same command. A guard that blocks the idiomatic spelling of the thing
    it demands gets reverted by whoever it blocks first."""
    assert _verify_re("tasks/index.yml").search(line), line


def test_a_verification_of_a_DIFFERENT_path_does_not_satisfy_the_pairing():
    """The pairing has to be about the file being restored. The first version
    matched any guarded path, so a check on one file paired a rollback of another."""
    assert not _verify_re("tasks/index.yml").search(
        "git diff --cached --quiet -- review_tasks.md")
