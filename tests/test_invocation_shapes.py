"""Phase 153 — cross-skill invocation-shape invariants.

Phase 152's adversarial pass established that a permission rule authorizes a *command*,
not a *step*: the matcher compares against the literal text the model sends, splits on
`&&`, `||`, `;`, `|`, `|&`, `&` and newlines, and requires each part to match. Phase 153
audited every shipped call site against that and reshaped the ones that could be reshaped.

The `/review-close`-local shapes have their own guards in `test_review_close_pr_policy.py`;
the staging discipline lives in `test_git_add_staging_discipline.py`. This file holds the
invariants that span *all* skills, so a newly-authored skill inherits them:

1. No skill captures `gh` output into a variable — in `$( )` or backtick form. Beyond the
   rule-matching cost, skill steps are separate shell calls, so the value would not survive.
2. No live command carries a `|| true` / `|| :` tail. `echo` is the sanctioned tolerant
   tail: it IS in the documented built-in read-only set, so the compound stays authorized.
3. Every temp-file path guards `$TMPDIR`. This is the defect the Phase 153 audit actually
   found in the give-back family — the filed premise (six skills passing `gh` operands from
   cross-step variables) turned out to be false, and this was what was there instead.

Every guard scans **live command lines only** (`shape_lib.live_command_lines`) and every
non-vacuity twin calls the same production predicate the guard does, so neutering a
predicate makes its own twin fail. Both properties were missing from the first draft and
were put there by its adversarial review.
"""
from __future__ import annotations

from pathlib import Path

from tests import shape_lib as S


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# --------------------------------------------------------------------------------------
# 0. The scan's own assumption
# --------------------------------------------------------------------------------------

def test_fences_are_balanced_in_every_skill():
    """The whole scan rests on ``` fences delimiting code.

    An odd fence count means the parser's in/out state inverts partway through a file,
    silently turning prose into "live commands" and — worse — real commands into prose,
    which would make every guard below quietly weaker. Pinned so that fails loudly here
    rather than as a mysterious non-detection somewhere else.
    """
    odd = [
        str(f.relative_to(S.REPO_ROOT)) for f in S.skill_files()
        if S.fence_count(_read(f)) % 2
    ]
    assert odd == [], "unbalanced ``` fences — the live-line scan is unreliable in:\n" + "\n".join(odd)


def test_the_scan_sees_a_meaningful_amount_of_bash():
    """Floor against the scan silently returning nothing.

    If a future refactor breaks `fenced_text`, every guard in this file would pass on an
    empty list. Cheap insurance for a whole file's worth of assertions.
    """
    total = sum(len(S.live_command_lines(_read(f))) for f in S.skill_files())
    assert total > 800, f"live-command scan found only {total} lines across the skills"


def test_a_trailing_comment_does_not_make_a_line_prose():
    """The exact hole the first draft shipped.

    It classified any line containing a backtick as prose. House style here is
    backtick-dense, so a trailing comment was a per-line opt-out that disabled every guard
    at once. Whole-line comments are still prose; trailing ones are not.
    """
    sample = "```bash\ngit branch -D x || true  # tolerate a `missing` branch\n# a real comment\n```"
    live = S.live_command_lines(sample)
    assert live == ["git branch -D x || true  # tolerate a `missing` branch"]
    assert S.has_noop_tail(sample) == live


# --------------------------------------------------------------------------------------
# 1. gh output is never captured into a variable
# --------------------------------------------------------------------------------------

def test_no_skill_captures_gh_output_into_a_variable():
    """An allow-rule does not match past an assignment, so `X="$(gh …)"` routes to the
    classifier and is auto-denied under `dontAsk` — even with `Bash(gh …:*)` seeded.

    Run gh bare and read the value off stdout. That is also the only shape that works
    across steps: the skill runner executes each step as a separate shell call, so a
    captured variable is gone by the time the next step wants it.
    """
    offenders = [
        f"{f.relative_to(S.REPO_ROOT)}: {ln}"
        for f in S.skill_files() for ln in S.has_gh_capture(_read(f))
    ]
    assert offenders == [], (
        "gh output captured into a variable — run it bare and read stdout:\n"
        + "\n".join(offenders)
    )


def test_that_gh_capture_guard_is_not_vacuous():
    """Non-vacuity through the production predicate, including the backtick form the
    first draft's regex missed entirely (it required `$(`)."""
    retired = (
        "```bash\n"
        'PR_REF="$(gh pr create --base main --head "$INTEGRATION_BRANCH" \\\n'
        'PR_NUMBER="$(gh pr list --head "$APPROVED_BRANCH" --base main --state open \\\n'
        "URL=$(gh issue create --repo x --title y)\n"
        "PR=`gh pr list --head main --json number`\n"
        "```"
    )
    assert len(S.has_gh_capture(retired)) == 4

    # Must NOT fire on a bare invocation, nor on a command substitution used as an
    # *argument* — only a leading assignment breaks the match.
    kept = (
        "```bash\n"
        'gh pr list --head "$APPROVED_BRANCH" --base main --state open\n'
        'gh pr merge --match-head-commit "$(git rev-parse HEAD)" --squash\n'
        "```"
    )
    assert S.has_gh_capture(kept) == []


# --------------------------------------------------------------------------------------
# 2. No `|| true` / `|| :` tails on live commands
# --------------------------------------------------------------------------------------

def test_no_skill_ships_a_noop_tail_on_a_live_command():
    """`true` is not in Claude Code's documented read-only set (an inference — the set is
    non-exhaustive — but the safe way to bet), so a `… || true` tail splits into its own
    unmatched part and costs the whole invocation its rule.

    The sanctioned tolerant tail is `|| echo "<why>"`: `echo` *is* in the documented set,
    so the compound stays authorized and the reader is told why the failure was expected.
    """
    offenders = [
        f"{f.relative_to(S.REPO_ROOT)}: {ln}"
        for f in S.skill_files() for ln in S.has_noop_tail(_read(f))
    ]
    assert offenders == [], (
        "`|| true` / `|| :` on a live skill command — use `|| echo \"<why>\"`:\n"
        + "\n".join(offenders)
    )


def test_that_noop_tail_guard_is_not_vacuous():
    """Non-vacuity through the production predicate, across the spellings that survived
    the first draft's `endswith("|| true")` check.

    Every one of these was reported as SURVIVED by the adversarial pass.
    """
    retired = (
        "```bash\n"
        'gh pr checks "$PR_REF" --watch --fail-fast || true\n'
        'git branch -D "$INTEGRATION_BRANCH" 2>/dev/null || true\n'
        "git add -A -- x.md || :\n"
        "git add -A -- y.md || true  # may already be gone\n"
        "git add -A -- z.md || true;\n"
        "git add -A -- w.md || true && echo done\n"
        "```"
    )
    assert len(S.has_noop_tail(retired)) == 6

    kept = (
        "```bash\n"
        'gh pr checks "<PR>" --watch --fail-fast || echo "not the verdict; continue"\n'
        'git branch -D "merge/review-close-<run id>" 2>/dev/null || echo "already deleted"\n'
        "git add -A -- a.md\n"
        "```"
    )
    assert S.has_noop_tail(kept) == []


# --------------------------------------------------------------------------------------
# 3. $TMPDIR is always guarded
# --------------------------------------------------------------------------------------

def test_every_skill_guards_tmpdir_with_a_fallback():
    """`TMPDIR` is set on macOS and usually unset on Linux.

    Unset, `"$TMPDIR/sysop-issue-<id>.md"` collapses to `/sysop-issue-<id>.md`. The body
    file is *written* by the `Write` tool (no shell expansion) and then *read* by
    `gh --body-file`, so what actually breaks is the read: gh is handed a path under `/`
    that does not exist, and the filing fails on the consumers least likely to have
    `TMPDIR` set. `install.sh` already used `${TMPDIR:-/tmp}`; the skills now match it.
    """
    offenders = [
        f"{f.relative_to(S.REPO_ROOT)}: {ln}"
        for f in S.skill_files() for ln in S.has_bare_tmpdir(_read(f))
    ]
    assert offenders == [], (
        "unguarded $TMPDIR — use ${TMPDIR:-/tmp}, which is unset on most Linux shells:\n"
        + "\n".join(offenders)
    )


def test_that_tmpdir_guard_is_not_vacuous():
    """Non-vacuity through the production predicate — including the *malformed* guard.

    `"$TMPDIR:-/tmp/x.md"` is the typo made when copying the real idiom from memory. The
    first draft exempted it, because it tested for the substring `TMPDIR:-` in a ±8-char
    window rather than for the `${TMPDIR:-…}` expansion itself. That path expands to
    `/var/folders/…:-/tmp/x.md` on macOS and `:-/tmp/x.md` on Linux — broken both ways,
    i.e. worse than the bug the guard exists to prevent.
    """
    retired = (
        "```bash\n"
        'gh issue create --repo <t> --body-file "$TMPDIR/sysop-issue-<id>.md"\n'
        'gh release create "<v>" --notes-file "$TMPDIR/sysop-release-<version>.md"\n'
        'git tag -a "<v>" -F "${TMPDIR}/sysop-tag-<version>.md"\n'
        '  -F body=@"$TMPDIR/sysop-wins-<date>.md" \\\n'
        'gh issue create --body-file "$TMPDIR:-/tmp/sysop-x.md"\n'
        "```"
    )
    assert len(S.has_bare_tmpdir(retired)) == 5

    kept = '```bash\n--body-file "${TMPDIR:-/tmp}/sysop-issue-<id>.md"\n```'
    assert S.has_bare_tmpdir(kept) == []


def test_the_four_give_back_skills_actually_stage_a_body_file():
    """Positive counterpart: the guard above passes trivially on a skill with no temp file.

    These four write the consented payload to a file and pass it by path precisely so the
    body never rides the shell (the RCE hazard `/report-issues` Step 4 fixed). If a skill
    stops doing that, this test is the one that notices.
    """
    for name in ("report-issues", "contribute-convention", "share-wins", "release"):
        text = _read(S.SKILLS_DIR / name / "SKILL.md")
        assert "${TMPDIR:-/tmp}/sysop-" in text, (
            f"/{name} no longer stages its payload through a guarded temp file"
        )
