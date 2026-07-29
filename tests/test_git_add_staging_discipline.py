"""Phase 151 — `git add` is all-or-nothing across its pathspecs, and the skills now say so.

Upstream #203 reported that `/review-close` Step 4c leaves a half-staged index. Verifying
it surfaced the same root cause at seven more sites in `/codebase-review` and
`/security-audit`, where the shipped prose asserted — falsely — that `2>/dev/null`
"tolerates their absence". It does not: it suppresses the *message*. The invocation still
aborts and stages **nothing**, so the `git commit` on the next line had nothing of the
round to record.

**Phase 153 superseded the *shape* of that fix while keeping its diagnosis.** Phase 151
tolerated absence at the shell level, with a `for p in …; do git add -A -- "$p"
2>/dev/null || true; done` loop at six sites. That is unauthorizable: `for` and `done` are
not documented command separators and `true` is not in the documented read-only set, so
the invocation matches no allow-rule — `Bash(git add:*)` included — and `dontAsk`
auto-denies the entire staging step. The replacement stages only the paths the step
actually wrote, one plain `git add -A -- <path>` each, which needs no shell-level
tolerance at all. Both properties are still pinned below, now against the new shape.

Five layers of coverage, because the fix is mostly prose and prose rots quietly:

1. **The git behaviour the prose claims, made falsifiable.** If a future git releases
   tolerant pathspec handling, or `-A` starts skipping misses, these go red and the shipped
   justification gets revisited rather than silently becoming a lie.
2. **The replacement idiom actually executed** against a fixture repo — including a
   deliberately absent path (the source repo's permanent state, with `.project.*` overlays
   missing) and a *deleted* path, which an existence-guarded form silently drops. It also
   pins that a `fatal:` on one line does not stop the lines after it, which is what lets
   the per-path form drop the `|| true`.
3. **A drift guard** against the retired multi-pathspec form re-accreting in the skills,
   with a non-vacuity test asserting the guard fires on every form actually replaced,
   including the inline `` - Commit: `git add a b && git commit …` `` shape.
4. **Drift guards against the two Phase 151 shapes** — a `git add` inside a `for … done`,
   and a live command ending in `|| true` — each with its own non-vacuity test, plus a
   positive counterpart asserting both review skills still stage per-path (a ban alone
   would pass on a skill that stages nothing, reintroducing the original bug).
5. **A targeted guard for the install docs**, where a blanket ban would be wrong (there,
   most listed paths are guaranteed to exist) but the one *conditional* path is known.

Every git subprocess runs with the ambient config pinned off (Phase 150's lesson: a
regression test that reads a developer's global git config is a test that can pass with the
bug restored).
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from tests import shape_lib as S

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "core" / "skills"


def _git_env() -> dict:
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    # GIT_CONFIG_COUNT/KEY_n/VALUE_n override config even with the files pinned to
    # /dev/null, and GIT_TEMPLATE_DIR can plant hooks at `git init` — drop both.
    for leak in [k for k in env if k.startswith(("GIT_CONFIG_KEY", "GIT_CONFIG_VALUE"))]:
        del env[leak]
    env.pop("GIT_CONFIG_COUNT", None)
    env.pop("GIT_TEMPLATE_DIR", None)
    return env


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, env=_git_env())
    return path


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(repo), capture_output=True, text=True, env=_git_env(),
    )


def _staged(repo: Path) -> list[str]:
    return sorted(_git(repo, "diff", "--cached", "--name-only").stdout.split())


def _bash(repo: Path, script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [script], shell=True, cwd=str(repo), capture_output=True, text=True, env=_git_env()
    )


# --------------------------------------------------------------------------------------
# 1. The claim itself
# --------------------------------------------------------------------------------------

def test_git_add_is_all_or_nothing_across_pathspecs(tmp_path):
    """One unmatched pathspec aborts the whole invocation and stages NONE of the rest.

    This is the property every corrected site in this phase depends on.
    """
    repo = _init_repo(tmp_path / "r")
    (repo / "present.md").write_text("x", encoding="utf-8")

    r = _git(repo, "add", "present.md", "absent.md")

    assert r.returncode != 0, "git add tolerated a missing pathspec — the shipped prose is now wrong"
    assert "did not match any files" in r.stderr
    assert _staged(repo) == [], (
        "git add staged the matching pathspec despite the miss — the all-or-nothing claim "
        f"in the skills is no longer true (staged={_staged(repo)})"
    )


def test_git_add_dash_A_does_not_tolerate_a_missing_pathspec(tmp_path):
    """`-A` does not rescue an explicit pathspec that matches nothing.

    Pinned because upstream #203's *proposed* fix was
    `git add -A PROJECT_STATUS.md changelog.md UI_Iterations.md tasks/`, on the stated
    premise that "paths that do not exist are skipped by `-A` with an explicit pathspec".
    They are not — and `changelog.md` / `UI_Iterations.md` are written only for `bugfix` /
    `ui-iteration` entries (or, for changelog, by the §6 rotation) and are never created by
    the installer, so that command would have aborted on the majority of close-outs, staged
    nothing, and let the following `git commit` record the rename alone: the reported bug,
    reached by a new route.
    """
    repo = _init_repo(tmp_path / "r")
    (repo / "present.md").write_text("x", encoding="utf-8")

    r = _git(repo, "add", "-A", "present.md", "absent.md")

    assert r.returncode != 0
    assert _staged(repo) == []


def test_a_failed_add_after_git_mv_leaves_the_index_exactly_as_git_mv_left_it(tmp_path):
    """Precision about the #203 trap, which is easy to overstate.

    `git add <stale-old-path> <new-path>` after a `git mv` does NOT *unstage* anything —
    `git mv` already staged both halves, and the aborted add is a no-op on the index. The
    trap is subtler than "it makes things worse": it looks like staging was attempted,
    changes nothing, and the following `git commit` still succeeds on the rename-only
    index. Pinned because the phase originally shipped the stronger, false claim.
    """
    repo = _init_repo(tmp_path / "r")
    (repo / "a.md").write_text("x", encoding="utf-8")
    (repo / "other.md").write_text("y", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")

    _git(repo, "mv", "a.md", "b.md")
    (repo / "other.md").write_text("y2", encoding="utf-8")
    before = _staged(repo)

    r = _git(repo, "add", "a.md", "b.md")

    assert r.returncode != 0
    assert _staged(repo) == before == ["b.md"], (
        "the aborted add changed the index — the SKILL.md wording about what it does to the "
        "already-staged rename would need revisiting"
    )
    # `other.md` was never staged either before or after: nothing was "taken down".
    assert "other.md" not in _staged(repo)


def test_per_path_add_stages_a_deletion_and_an_absent_path_costs_only_its_own_line(tmp_path):
    """The shipped idiom (Phase 153), in isolation — two properties, both load-bearing.

    `-A` stages a *deletion*, which matters precisely because Step 9b is the demotion
    step — the one that removes things — and a prior draft's `[ -e "$p" ]` guard silently
    dropped exactly those.

    And a `fatal:` on one line does **not** stop the following lines. That is what makes
    one-plain-`git add`-per-path a correct shape on its own terms rather than merely a
    permission workaround: it is why Phase 153 could drop the `2>/dev/null || true` that
    the loop needed, instead of having to replace it with something else.
    """
    repo = _init_repo(tmp_path / "r")
    (repo / "kept.md").write_text("x", encoding="utf-8")
    (repo / "removed.md").write_text("y", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    (repo / "kept.md").write_text("x2", encoding="utf-8")
    (repo / "removed.md").unlink()

    # The absent path is FIRST, so if a failure aborted the block the two real adds would
    # never run and the assertions below would catch it.
    r = _bash(repo, "git add -A -- absent.project.md\n"
                    "git add -A -- kept.md\n"
                    "git add -A -- removed.md\n")

    assert "did not match any files" in r.stderr, (
        "the absent path no longer reports a fatal — the shipped prose tells the agent to "
        "expect that line and read past it, so the prose would now be wrong"
    )
    status = dict(
        (line[3:], line[0]) for line in
        _git(repo, "status", "--porcelain").stdout.splitlines()
    )
    assert status.get("kept.md") == "M", (
        f"a failed add stopped the adds after it — the per-path form would need `|| true` "
        f"back, and that shape matches no allow-rule (status={status})"
    )
    assert status.get("removed.md") == "D", (
        f"the deletion was not staged — an existence guard would do this (status={status})"
    )


def test_the_existence_guarded_form_is_the_one_that_drops_deletions(tmp_path):
    """Non-vacuity for the test above: prove the rejected idiom really does fail here."""
    repo = _init_repo(tmp_path / "r")
    (repo / "removed.md").write_text("y", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    (repo / "removed.md").unlink()

    _bash(repo, 'for p in removed.md; do [ -e "$p" ] && git add "$p"; done')

    assert _staged(repo) == [], "[ -e ] unexpectedly staged a deleted path"


# --------------------------------------------------------------------------------------
# 2. The idiom as the skills actually ship it
# --------------------------------------------------------------------------------------

# Loops over a set discovered at RUNTIME cannot be unrolled — there is no static path list
# to write out — so a blanket ban would be a lie. Each surviving loop is listed here with
# why it is acceptable, mirroring the `SEEDED_WITHOUT_SKILL_MENTION` pattern Phase 152 used
# for the same problem one layer up. `test_every_surviving_loop_is_accounted_for` fails on
# a NEW loop; `test_no_allowlisted_loop_has_gone_stale` fails when an entry stops matching,
# so the list cannot rot in either direction.
KNOWN_RUNTIME_SET_LOOPS: dict[str, str] = {
    "while IFS=$'\\t' read -r wt_path branch; do":
        "Step 1a worktree classification — iterates `git worktree list --porcelain` "
        "output. Read-only body.",
    "for branch in $BRANCHES_TO_MERGE; do":
        "Step 4a archive-rotation pre-check — iterates refs discovered at runtime. "
        "Read-only body (merge-base / diff / grep / echo).",
    "while IFS= read -r _b; do":
        "Step 4a branch enumeration. Read-only body.",
    "while IFS= read -r line; do":
        "Step 1a/3b `git status --porcelain` symlink classifier. Read-only body; the "
        "non-greedy regex can also swallow the sibling strip loop that follows it.",
    'for f in "<worktree-path>"/sysop/runtime/pending-docs/*.md; do':
        "Step 3b stale pending-docs strip. GLOB-DRIVEN, so it cannot be unrolled, and it "
        "wraps `rm -f` behind `[ -e … ] &&` — a write inside two unmatched shapes at once. "
        "Genuinely uncovered; recorded as such in WORKFLOW.md § 8.2a rather than fixed.",
}


def test_every_surviving_loop_is_accounted_for():
    """No skill may grow a loop that is not on the list above.

    Phase 153 removed the six `git add` loops Phase 151 introduced. What it could NOT
    remove is a loop over a set discovered at runtime, and pretending otherwise was one of
    the overclaims its adversarial review caught: the first draft of this guard matched
    only loops containing the literal string `git add`, so a `git commit`, `git push` or
    `gh pr merge` inside `for … done` — the identical unauthorizable shape — sailed
    through, as did the `for sha in $(git rev-list …); do git cherry-pick` loop living in
    `/review-close` at the time.
    """
    unknown = []
    for skill in S.skill_files():
        for m in S.loops(skill.read_text(encoding="utf-8")):
            head = S.loop_header(m)
            if head not in KNOWN_RUNTIME_SET_LOOPS:
                unknown.append(f"{skill.relative_to(REPO_ROOT)}: {head}")
    assert unknown == [], (
        "a `for`/`while … done` loop appeared that is not accounted for. `for`/`done` are "
        "not documented command separators, so NO allow-rule matches the invocation. "
        "Either write the set out as plain commands, or add it to KNOWN_RUNTIME_SET_LOOPS "
        "with the reason it cannot be:\n" + "\n".join(unknown)
    )


def test_no_allowlisted_loop_has_gone_stale():
    """The other direction: an entry that no longer matches anything is dead weight that
    would silently start permitting a future loop with the same header."""
    seen = {
        S.loop_header(m)
        for skill in S.skill_files()
        for m in S.loops(skill.read_text(encoding="utf-8"))
    }
    stale = sorted(set(KNOWN_RUNTIME_SET_LOOPS) - seen)
    assert stale == [], "KNOWN_RUNTIME_SET_LOOPS entries match nothing any more:\n" + "\n".join(stale)


def test_no_write_command_runs_inside_a_loop_except_the_one_documented_case():
    """Severity split: a read-only loop is a permission question, a write loop is a defect.

    Exactly one surviving loop writes — Step 3b's glob-driven `rm -f` strip — and it is
    named here so a second one cannot appear quietly.
    """
    writing = []
    for skill in S.skill_files():
        for m in S.loops(skill.read_text(encoding="utf-8")):
            if S.WRITE_CMD_RE.search(m.group("body")):
                writing.append(S.loop_header(m))
    assert set(writing) <= {
        'for f in "<worktree-path>"/sysop/runtime/pending-docs/*.md; do',
        "while IFS= read -r line; do",   # regex overlap with the strip loop below it
    }, f"a new write-containing loop appeared: {writing}"


def test_the_loop_guard_is_not_vacuous():
    """Non-vacuity through the production predicate, across the spellings the first draft
    missed — its regex required `; do` on one line and a `for` (never a `while`)."""
    for retired in (
        # the verbatim pre-Phase-153 staging loop
        "```bash\nfor p in CLAUDE.md .claude/checks.yml; do\n"
        '  git add -A -- "$p" 2>/dev/null || true\ndone\n```',
        # `do` on its own line — the standard multi-line style
        "```bash\nfor p in CLAUDE.md .claude/checks.yml\ndo\n"
        '  git add -A -- "$p"\ndone\n```',
        # a `while` loop
        '```bash\nwhile read -r p; do git add -A -- "$p"; done < list\n```',
        # the cherry-pick loop Phase 153 replaced with a range
        "```bash\nfor sha in $(git rev-list --reverse origin/main..main); do\n"
        '  git cherry-pick "$sha"\ndone\n```',
    ):
        assert S.loops(retired), f"loop predicate missed:\n{retired}"

    assert S.loops("```bash\ngit add -A -- CLAUDE.md\ngit cherry-pick origin/main..main\n```") == []


def test_both_review_skills_still_stage_per_path():
    """The ban needs a positive counterpart.

    A guard that only forbids the old shape passes just as happily on a skill that stages
    nothing at all — which would reintroduce Phase 151's original bug (a `git commit` with
    nothing of the round in the index) by a different route.
    """
    for name in ("codebase-review", "security-audit"):
        text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
        adds = [ln.strip() for ln in text.splitlines()
                if ln.strip().startswith("git add -A -- ")]
        assert len(adds) >= 6, (
            f"{name} ships only {len(adds)} per-path adds across Steps 2a/9/9b: {adds}"
        )
        # One pathspec each — the property the loop existed to provide.
        for add in adds:
            assert _pathspec_count(add[len("git add"):]) == 1, (
                f"{name} stages several paths in one command again: {add}"
            )


def test_the_rejected_existence_guard_is_not_shipped_anywhere():
    """`[ -e "$p" ] && git add …` has a test proving it is wrong and, until now, none
    preventing it.

    Two independent reasons it must not come back: it silently drops a *deleted* path
    (proved directly above, and Step 9b is the demotion step — the one that removes
    things), and `[` / `test` is not in Claude Code's documented read-only set, so the
    compound is unauthorizable as well as semantically wrong.
    """
    offenders = [
        f"{skill.relative_to(REPO_ROOT)}: {ln}"
        for skill in S.skill_files()
        for ln in S.live_command_lines(skill.read_text(encoding="utf-8"))
        if re.search(r"\[\s+-[ef]\s+[^\]]*\]\s*&&\s*git\s+add", ln)
    ]
    assert offenders == [], (
        "the existence-guarded add is back — it drops staged deletions:\n" + "\n".join(offenders)
    )


# --------------------------------------------------------------------------------------
# 3. Drift guard — the skills
# --------------------------------------------------------------------------------------

_ADD_RE = re.compile(r"git add (?P<rest>[^\n`]*)")
# Single chars, because the tokenizer below splits `&&`/`||` into separate `&`/`|`.
_TERMINATORS = ("&", "|", ";", "#")


def _pathspecs(rest: str) -> list[str]:
    """The pathspec operands following a `git add`, stopping at the first terminator.

    Terminators include redirections (`2>`, `1>`, `>`), so `git add x 2>/dev/null` counts
    one pathspec, and shell operators, so a compound line is attributed per-command rather
    than being read as one long argument list.
    """
    tokens: list[str] = []
    # Shell operators bind tight to the preceding argument (`.gitignore;`, `foo&&`), so
    # split them off before tokenizing or the terminator check never fires.
    rest = re.sub(r"([;|&])", r" \1 ", rest)
    for tok in rest.split():
        if tok.startswith(_TERMINATORS) or re.match(r"^\d?[<>]", tok):
            break
        if tok.startswith("-"):          # flags: -A, -u, --
            continue
        tokens.append(tok)
    return tokens


def _pathspec_count(rest: str) -> int:
    return len(_pathspecs(rest))


def _multi_pathspec_add_lines(text: str) -> list[str]:
    """Every `git add` with 2+ pathspecs, wherever it appears on a line.

    Unlike an earlier draft this is NOT anchored to line-initial `git add`: the two sites
    this phase fixed in Step 2a were inline — ``- Commit: `git add a b && git commit …` `` —
    and a line-initial matcher missed them entirely.

    Blockquote lines are skipped. The corrected prose deliberately *quotes* the retired form
    to explain why it was wrong, and every such quote lives in a `>` blockquote while every
    executable instruction does not.
    """
    offenders = []
    for line in text.splitlines():
        if line.lstrip().startswith(">"):
            continue
        for m in _ADD_RE.finditer(line):
            if _pathspec_count(m.group("rest")) > 1:
                offenders.append(line.strip())
                break
    return offenders


def test_no_skill_ships_a_multi_pathspec_git_add():
    """The retired form. One missing path in the list silently stages nothing.

    Where a path is optional, give it its own `git add` (a miss then costs only that line)
    or use the shipped `git add -A -- "$p"` loop. Never list several pathspecs in one
    command and reach for `2>/dev/null` — that hides the abort, it does not prevent it.
    """
    offenders: list[str] = []
    for skill in sorted(SKILLS_DIR.rglob("*.md")):
        for line in _multi_pathspec_add_lines(skill.read_text(encoding="utf-8")):
            offenders.append(f"{skill.relative_to(REPO_ROOT)}: {line}")
    assert offenders == [], "multi-pathspec `git add` re-accreted:\n" + "\n".join(offenders)


def test_the_drift_guard_detects_every_form_this_phase_replaced():
    """Non-vacuity, using the ACTUAL pre-fix text of all four replaced shapes."""
    retired = (
        # Step 7 of both review skills (line-initial, inside a fenced block)
        "git add review_tasks.md review_tasks_archive.md 2>/dev/null\n"
        # Step 9 / 9b promotion + demotion commits (indented, inside a fenced block)
        "   git add CLAUDE.md .claude/convention_map.md .claude/convention_map.project.md "
        ".claude/checks.yml .claude/semgrep/ review_tasks.md 2>/dev/null\n"
        # Step 2a coverage commit — INLINE in a bullet, which a line-initial matcher missed
        "- Commit: `git add .claude/convention_map.md .claude/convention_map.project.md "
        '.claude/security_map.md && git commit -m "docs: update coverage"`\n'
        # #203's proposed fix, and the instinct it was meant to replace
        "git add -A PROJECT_STATUS.md changelog.md UI_Iterations.md tasks/\n"
        "cd worktree && git add tasks/open/X.md tasks/archive/X.md\n"
    )
    assert len(_multi_pathspec_add_lines(retired)) == 5

    # …and must NOT fire on the forms this phase deliberately ships.
    kept = (
        "git add PROJECT_STATUS.md                 # every type\n"
        "git add review_tasks_archive.md 2>/dev/null   # may not exist yet\n"
        'git add tasks/index.yml && git commit -m "claim: mark X as in-progress"\n'
        'cd <WORKTREE_PATH> && git add -A && git commit -m "fix: x"\n'
        "   git add -A -- .claude/convention_map.md\n"   # the Phase 153 per-path form
        "git add .agents/ 2>/dev/null   # only present when the Codex links were installed\n"
        "> the older form, `git add a.md b.md 2>/dev/null`, staged nothing at all\n"
    )
    assert _multi_pathspec_add_lines(kept) == []


def test_the_false_2devnull_tolerance_claim_is_gone():
    """The shipped justification was wrong, not merely terse — pin the correction.

    `codebase-review/SKILL.md` used to read "`2>/dev/null` tolerates their absence in the
    source repo". Both review skills must now state the real mechanism instead.
    """
    for name in ("codebase-review", "security-audit"):
        text = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
        assert "tolerates their absence" not in text, f"{name} still ships the false claim"
        assert "all-or-nothing across its pathspecs" in text, (
            f"{name} no longer explains why the per-path form is required"
        )


# --------------------------------------------------------------------------------------
# 4. Drift guard — the install docs
# --------------------------------------------------------------------------------------

_INSTALL_DOCS = ("README.md", "docs/getting-started.md", "docs/loop-mode.md",
                 "docs/install-and-update.md")


def test_install_docs_never_list_the_conditional_agents_path_alongside_others():
    """`.agents/` is conditional; listing it with other paths aborts the whole `git add`.

    A blanket multi-pathspec ban would be wrong for these docs — `.claude/`, `sysop/`,
    `tasks/`, `CLAUDE.md`, `.gitignore` are all created by every install, so listing them
    together is safe. `.agents/` is not: `install.sh --no-codex-links` and the Phase 142
    capability-probe fallback both leave it absent, and a copy-pasted
    `git add .claude/ .agents/ sysop/ …` then stages NOTHING and commits nothing — on the
    highest-traffic surface Sysop has.
    """
    offenders = []
    for rel in _INSTALL_DOCS:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            for m in _ADD_RE.finditer(line):
                paths = _pathspecs(m.group("rest"))
                if ".agents/" in paths and len(paths) > 1:
                    offenders.append(f"{rel}: {line.strip()}")
    assert offenders == [], (
        "`.agents/` listed alongside other pathspecs in an install command:\n"
        + "\n".join(offenders)
    )


def test_that_agents_guard_would_catch_the_shape_this_phase_removed():
    """Non-vacuity, using the exact pre-fix README/getting-started/loop-mode lines."""
    sample = "git add .claude/ .agents/ sysop/ tasks/ CLAUDE.md .gitignore\n"
    hits = [
        line for line in sample.splitlines()
        for m in _ADD_RE.finditer(line)
        if ".agents/" in _pathspecs(m.group("rest")) and len(_pathspecs(m.group("rest"))) > 1
    ]
    assert len(hits) == 1

    # And must NOT fire on the corrected form: `.agents/` alone in its own command.
    ok = "git add .agents/ 2>/dev/null   # only present when the Codex links were installed\n"
    assert [
        line for line in ok.splitlines()
        for m in _ADD_RE.finditer(line)
        if ".agents/" in _pathspecs(m.group("rest")) and len(_pathspecs(m.group("rest"))) > 1
    ] == []
