"""Phase 158 — `/review-close` Step 2 reviews the branch, not the branch minus main.

Three upstream reports, one skill, one root shape: the review gate was reading something
other than what the branch contributed. #241 (two-dot diffs — `main..<branch>` compares
tips, so everything `main` gained after the cut renders as a branch deletion), #234
(convention reviewers spawned unisolated into the primary worktree, where one ran
`git checkout` mid-close), #240 (no doc-only skip, so a docs cycle spawned an Opus agent
over a convention list about code).

**This file was rebuilt after its own adversarial round, which disqualified the first
version.** Three reviewers ran 43 + 24 mutations against it; **28 survived**, and 22 of
32 tests passed with all four touched files blanked. The defect was uniform and worth
naming, because it is the easy failure mode for guards over prose: *every assertion
checked that a token was present, never what the token claimed*. Concretely —

* `assert 'isolation: "worktree"' in block` passed on `Do NOT set \x60isolation:
  "worktree"\x60`, which is not a hypothetical phrasing: it is the shipped literal in the
  four sibling skills, so the likeliest real regression (a harmonisation sweep) was the
  one reversal the guard could not see. Deletion — the only mutation the author tried —
  is the single case a substring check does catch.
* The two-dot scan exempted any *line* that also showed a three-dot form. Step 2b's
  diff-basis line carries two commands, so regressing one of them was exempt out of the
  box, and every other site could be laundered by appending `(cf. \x60git diff
  main...<branch>\x60)`.
* Nothing asserted the skip's *predicate*, so inverting it at both sites — every
  code-bearing branch skips the gate, docs-only branches get reviewed — passed 32/32.

So the rules this file now follows:

1. **Allowlist, don't pattern-exclude.** Every two-dot `git diff` in the shipped tree is
   an offender unless its exact line is pinned in `ALLOWED_TWO_DOT`. Pinning the whole
   line means a laundered command fails (the line changed), a reworded rationale fails
   (the line changed), and the three genuinely-correct two-dot ranges stay legal. It also
   catches the shapes a shape-based regex missed: `$VAR..$VAR`, `HEAD..`, `master..`,
   `main@{u}..`, and a range split across a line continuation.
2. **Assert the claim, not the token.** A negated instruction must fail. A prohibition
   outside the prompt fence — never sent to the sub-agent — must fail. An inverted
   predicate must fail.
3. **No test may pass on an empty file.** Every assertion here reads shipped content.
   The premise tests (git's own range semantics) are kept, but they are labelled premise
   and are not counted as coverage of the deliverable.

The mutation harness was committed at `tools/phase158_mutations.py` until Phase 187 promoted the shared
harness to `tools/mutation_battery.py` and Phase 194 deleted the superseded one-offs. It stayed committed rather than living in a
session scratchpad because — during the round a sibling reviewer overwrote the scratch copy, and
an artefact that is the sole evidence for a headline claim should not be destroyable by a
concurrent process. It also fails closed on a nominated test name that no longer exists,
which is how the first version scored a false kill.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "core" / "skills"
DOCS_DIR = REPO_ROOT / "core" / "companion" / "docs"
REVIEW_CLOSE = SKILLS_DIR / "review-close" / "SKILL.md"
PARTIAL = SKILLS_DIR / "_shared" / "adversarial-review.md"

# Any `git diff` whose range uses two dots — no assumption about the operands, so shell
# variables, `HEAD`, `master` and `main@{u}` are all caught.
TWO_DOT_DIFF = re.compile(r"git diff\b[^`\n]*?(?<!\.)\.\.(?!\.)")

# The only lines in the shipped tree permitted to contain one. Pinned whole, so any edit
# to them — including appending a corrected form to launder a regression — fails.
ALLOWED_TWO_DOT: dict[str, set[str]] = {
    # Two entries, two different reasons:
    #  1. Step 1c's sweep — `:186` sets base=$(git merge-base main "$branch"), so it is
    #     already merge-base-relative and asks the inverse question (what did *main* gain
    #     since the cut).
    #  2. Step 2a's rationale note, which quotes the anti-pattern in order to explain it.
    #     Pinned whole so it is also guarded against inversion — the round showed the note
    #     could be rewritten to recommend two dots while every other guard stayed green,
    #     and 2b/2d both defer to it ("three dots, per Step 2a's note").
    "core/skills/review-close/SKILL.md": {
        'if git diff --name-only "$base..main" -- | grep -qE "$ARCHIVE_RE"; then',
        '> **Three dots on every `git diff` in Step 2 — 2a, 2b and 2d (internal tracker #241).** `git diff main..<branch>` compares the two *tips*, so everything `main` gained after the branch was cut renders as though the branch **deleted** it. That is not a rare condition: `/review-close` manufactures it, because Step 1b commits `review_tasks.md` to `main` before any branch is inspected. `git diff main...<branch>` diffs against the merge-base and shows exactly what the branch contributed. A false BLOCK costs a human round-trip; a **false APPROVE** — real hunks buried under phantom deletions — is the worse direction and gets likelier the staler the branch is. **`git log main..<branch>` keeps two dots**: for `log`, two-dot already means "commits on the branch and not on `main`," which is what step 1 wants. The rule is per-command, not a blanket search-and-replace.',
    },
    "core/companion/docs/WORKFLOW.md": set(),
    "docs/install-and-update.md": set(),
    "install.sh": set(),
}
# Left operand is an ancestor (the pre-update snapshot commit), so two-dot == three-dot.
_UPDATER = "git diff <snapshot-hash>..HEAD"
_UPDATER_SH = "git diff <snapshot>..HEAD"


def _shipped_files() -> list[Path]:
    """Everything a consumer installs or reads. Excludes the meta-repo's own records
    (`PHASE_LOG.md`, `REVIEW_*.md`, `CLAUDE.md`), which quote superseded text by design,
    and `tests/`."""
    out: list[Path] = []
    for root, patterns in (
        (REPO_ROOT / "core", ("*.md", "*.sh", "*.py")),
        (REPO_ROOT / "packs", ("*.md",)),
        (REPO_ROOT / "docs", ("*.md",)),
    ):
        for pattern in patterns:
            out.extend(p for p in root.rglob(pattern) if "__pycache__" not in p.parts)
    out.append(REPO_ROOT / "install.sh")
    out.append(REPO_ROOT / "README.md")
    return sorted(out)


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """Join shell line-continuations so a range split across `\\` + newline is one line."""
    joined: list[tuple[int, str]] = []
    buf, start = "", None
    for line_no, raw in enumerate(text.splitlines(), 1):
        if start is None:
            start = line_no
        if raw.rstrip().endswith("\\"):
            buf += raw.rstrip()[:-1]
            continue
        joined.append((start, buf + raw))
        buf, start = "", None
    if start is not None:
        joined.append((start, buf))
    return joined


def _two_dot_offenders(text: str, rel: str = "") -> list[tuple[int, str]]:
    allowed = ALLOWED_TWO_DOT.get(rel, set())
    hits = []
    for line_no, line in _logical_lines(text):
        if not TWO_DOT_DIFF.search(line):
            continue
        stripped = line.strip()
        if stripped in allowed:
            continue
        if rel in ("core/companion/docs/WORKFLOW.md", "docs/install-and-update.md") and _UPDATER in line:
            continue
        if rel == "install.sh" and _UPDATER_SH in line:
            continue
        hits.append((line_no, stripped))
    return hits


# ---------------------------------------------------------------------------
# Premise — git's own semantics, which the shipped rationale asserts.
# Not coverage of the deliverable; these pass on an empty repo tree by design.
# ---------------------------------------------------------------------------


def _git_env() -> dict:
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    for leak in [k for k in env if k.startswith(("GIT_CONFIG_KEY", "GIT_CONFIG_VALUE"))]:
        del env[leak]
    env.pop("GIT_CONFIG_COUNT", None)
    env.pop("GIT_TEMPLATE_DIR", None)
    return env


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, env=_git_env(), capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture(scope="module")
def stale_branch_repo(tmp_path_factory) -> Path:
    """A branch cut before `main` advanced — the normal `/review-close` condition."""
    repo = tmp_path_factory.mktemp("stale_branch")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "shared.py").write_text("original = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "A")
    _git(repo, "branch", "feature")
    (repo / "main_only.md").write_text("a convention main gained after the cut\n")
    (repo / "shared.py").write_text("original = 1\nadded_on_main = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "B")
    _git(repo, "checkout", "-q", "feature")
    (repo / "branch_only.py").write_text("def contributed():\n    return True\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "C")
    _git(repo, "checkout", "-q", "main")
    return repo


def test_premise_two_dot_diff_reports_main_content_as_a_branch_deletion(stale_branch_repo):
    out = _git(stale_branch_repo, "diff", "main..feature", "--name-status")
    statuses = {}
    for line in out.strip().splitlines():
        status, path = line.split("\t")
        statuses[path] = status
    assert statuses["main_only.md"] == "D", (
        "two-dot no longer reports main-ahead content as a branch deletion — the shipped "
        f"rationale needs revisiting. Got: {out!r}"
    )
    assert "-added_on_main = 2" in _git(
        stale_branch_repo, "diff", "main..feature", "--", "shared.py"
    )


def test_premise_three_dot_diff_shows_only_what_the_branch_contributed(stale_branch_repo):
    out = _git(stale_branch_repo, "diff", "main...feature", "--name-status")
    assert [line.split("\t") for line in out.strip().splitlines()] == [["A", "branch_only.py"]]


def test_premise_two_dot_is_correct_for_log_which_is_why_the_fix_is_per_command(
    stale_branch_repo,
):
    """A blanket `..` → `...` sweep would be its own regression."""
    assert _git(stale_branch_repo, "log", "main..feature", "--format=%s").split() == ["C"]
    assert "B" in _git(stale_branch_repo, "log", "main...feature", "--format=%s").split()


def test_premise_three_dot_would_drop_uncommitted_work(stale_branch_repo, tmp_path):
    """Why `_shared/ui-verify.md` uses the merge-base form rather than three dots."""
    repo = stale_branch_repo
    _git(repo, "checkout", "-q", "feature")
    tracked = repo / "shared.py"
    original = tracked.read_text()
    tracked.write_text(original + "edited_but_not_committed = 3\n")
    try:
        three_dot = _git(repo, "diff", "--name-only", "main...HEAD")
        base = _git(repo, "merge-base", "main", "HEAD").strip()
        merge_base = _git(repo, "diff", "--name-only", base)
        assert "shared.py" not in three_dot, "three-dot is commit-to-commit only"
        assert "shared.py" in merge_base, "the merge-base form must see the working tree"
    finally:
        tracked.write_text(original)
        _git(repo, "checkout", "-q", "main")


# ---------------------------------------------------------------------------
# #241 — the two-dot scan, allowlist-based
# ---------------------------------------------------------------------------


def test_no_unpinned_two_dot_git_diff_anywhere_in_the_shipped_tree():
    offenders = []
    for path in _shipped_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for line_no, line in _two_dot_offenders(path.read_text(errors="ignore"), rel):
            offenders.append(f"{rel}:{line_no}: {line}")
    assert not offenders, (
        "two-dot `git diff` outside the pinned allowlist (upstream #241). Two-dot is "
        "correct only when the left operand is a merge-base or an ancestor; if this is "
        "one of those, add the exact line to ALLOWED_TWO_DOT with the reason:\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize(
    "regression",
    [
        # The four sites this phase fixed.
        "2. `git diff main..<branch> --stat` — scope of changes",
        "Retrieve the full diff (`git diff main..<branch>`).",
        "     <full unified diff from git diff main..<branch>>",
        "**0. Per-branch doc-only skip.** If this branch's diff (`git diff main..<branch>`)",
        "1. Review each feature branch: `git diff main..<branch>`",
        # Shapes the previous shape-based regex could not see (round finding F7).
        "git diff $MAIN..$BRANCH --stat",
        "git diff HEAD..<branch> --stat",
        "git diff master..<branch> --stat",
        "git diff <branch>..main --stat",
        "git diff main@{u}..<branch> --stat",
        "git diff origin/main..HEAD",
        # Laundering: appending the correct form no longer buys an exemption (F3).
        "<full unified diff from git diff main..<branch>>   (see `git diff main...<branch>`)",
        "`git diff main..<branch>`, formerly `git diff main...<branch>`",
    ],
)
def test_two_dot_scan_catches_every_known_regression_shape(regression):
    assert _two_dot_offenders(regression), f"scan blind to {regression!r}"


def test_two_dot_scan_catches_a_range_split_across_a_line_continuation():
    """`_logical_lines` exists for this; without it the range is invisible."""
    assert _two_dot_offenders("git diff \\\n    main..<branch> --stat")


@pytest.mark.parametrize(
    "correct",
    [
        "2. `git diff main...<branch> --stat` — scope of changes",
        "`git diff --name-only origin/main...HEAD`",
        "1. `git log main..<branch> --oneline` — what commits are on it",
        'ahead=$(git log --oneline "main..$branch" 2>/dev/null | wc -l | tr -d \' \')',
        "`git rev-list --count origin/main..main`",
        'git diff --name-only "$(git merge-base main HEAD)" -- frontend/',
    ],
)
def test_two_dot_scan_does_not_fire_on_correct_forms(correct):
    """Three-dot diffs, two-dot *log*/*rev-list* ranges, and the merge-base form."""
    assert not _two_dot_offenders(correct), f"false positive on {correct!r}"


def test_the_three_legal_two_dot_ranges_are_still_present_and_still_legal():
    """A ban alone passes on a tree that deleted the correct usages too."""
    rc = REVIEW_CLOSE.read_text()
    assert 'git diff --name-only "$base..main"' in rc, "Step 1c's merge-base-relative sweep"
    assert "base=$(git merge-base main \"$branch\")" in rc, (
        "Step 1c's `$base..main` is only correct because `base` is a merge-base — if that "
        "assignment goes, the allowlist entry becomes a hole"
    )
    assert "`git log main..<branch> --oneline`" in rc, (
        "Step 2a's commit listing must keep TWO dots — three-dot `git log` lists main's "
        "commits as though they were the branch's"
    )


def test_every_step_2_diff_site_uses_the_merge_base_form():
    """Enumerated, not counted: the round showed a `>= 4` threshold left two spare sites
    that could be regressed together while the count still passed."""
    rc = REVIEW_CLOSE.read_text()
    for site in (
        "`git diff main...<branch> --stat` — scope of changes",            # 2a
        "| feature branch `<branch>` | `git diff main...<branch>` |",       # 2b/2d basis table
        "| unpushed-main group | `git diff origin/main...HEAD` |",          # the group target
        "<full unified diff from the target's diff basis>",                 # prompt placeholder
        "`git diff main...<branch>` — three dots, per Step 2a's note",      # 2d predicate
    ):
        assert site in rc, f"missing merge-base diff site: {site!r}"


def test_the_rationale_note_still_recommends_three_dots():
    """The note is what 2b and 2d defer to ("per Step 2a's note"), so inverting it inverts
    them. The round showed it was permanently exempt from the scan and unguarded."""
    rc = REVIEW_CLOSE.read_text()
    note = rc[rc.index("> **Three dots on every `git diff` in Step 2") :]
    note = note[: note.index("\n\n")]
    assert "compares the two *tips*" in note
    assert "diffs against the merge-base and shows exactly what the branch contributed" in note
    assert "keeps two dots" in note, "the per-command carve-out for `git log` must survive"
    assert not re.search(r"prefer\s+`git diff main\.\.<", note), "note inverted"


# ---------------------------------------------------------------------------
# #234 — isolation and the portable floor
# ---------------------------------------------------------------------------


def _step_2b(text: str) -> str:
    start = text.index("### 2b. Prevention Convention Check")
    return text[start : text.index("### 2c.", start)]


def _prompt_fence(block: str) -> tuple[int, int]:
    """Offsets of the sub-agent prompt template's fenced body within Step 2b."""
    open_at = block.index("     ```\n") + len("     ```\n")
    close_at = block.index("     ```", open_at)
    return open_at, close_at


def test_step_2b_sets_isolation_as_a_spawn_parameter():
    block = _step_2b(REVIEW_CLOSE.read_text())
    bullets = [ln for ln in block.splitlines() if re.match(r"^\s*-\s+`isolation:", ln)]
    assert len(bullets) == 1, f"expected exactly one isolation bullet, got {bullets!r}"
    assert bullets[0].lstrip().startswith('- `isolation: "worktree"`'), (
        f"isolation bullet is not an affirmative instruction: {bullets[0]!r}"
    )


def test_step_2b_does_not_negate_isolation():
    """The round's sharpest finding: `Do NOT set \x60isolation: "worktree"\x60` — the shipped
    literal in the four sibling skills — contains the substring the old guard asserted, so
    a harmonisation sweep reversed the fix invisibly."""
    block = _step_2b(REVIEW_CLOSE.read_text())
    negations = re.findall(r"[Dd]o\s+\*{0,2}(?:NOT|not)\*{0,2}\s+set\s+`isolation", block)
    assert not negations, f"Step 2b now tells the runner NOT to isolate: {negations!r}"
    assert "<!--" not in block.split("`isolation:")[0][-200:], "isolation bullet commented out"


def test_the_do_not_mutate_floor_is_inside_the_prompt_the_subagent_receives():
    """Outside the fence it is never sent — which is the whole point of the portable floor.
    The old guard sliced to the end of the section and passed either way."""
    block = _step_2b(REVIEW_CLOSE.read_text())
    open_at, close_at = _prompt_fence(block)
    body = block[open_at:close_at]
    marker = block.index("Do NOT mutate repository state")
    assert open_at < marker < close_at, (
        "the do-not-mutate clause sits outside the prompt template fence, so the "
        "sub-agent never receives it"
    )
    prohibition = block[marker:close_at]
    for verb in ("checkout", "switch", "reset", "stash", "merge", "rebase", "commit"):
        assert verb in prohibition, f"prohibition does not name `{verb}`"
    assert "git show <sha>:<path>" in prohibition, (
        "a prohibition with no alternative is an instruction to improvise"
    )
    # Scan the whole prompt body, not the slice from the marker: a negation prepended
    # *before* the marker ("You may mutate state if needed, though ideally Do NOT…")
    # survives a slice that starts at it. Found by this file's own mutation harness.
    assert not re.search(r"(?i)you\s+may\s+mutate|mutation\s+is\s+(?:ok|fine)", body), (
        "the prohibition is contradicted elsewhere in the prompt the sub-agent receives"
    )


def test_the_prompt_tells_the_agent_the_diff_is_merge_base_relative():
    """#241 asked for this by name beyond the command change; the round found it unguarded."""
    block = _step_2b(REVIEW_CLOSE.read_text())
    open_at, close_at = _prompt_fence(block)
    body = block[open_at:close_at]
    assert "Merge-base-relative" in body
    assert "never a deletion this branch made" in body


def test_leaked_agent_worktrees_are_a_stated_hard_rule():
    """Isolation materializes a real branch + worktree in the shared namespace, and this
    skill enumerates every branch. Found by the round, not by the filing."""
    block = _step_2b(REVIEW_CLOSE.read_text())
    assert "HARD RULE — the agents' worktrees must be gone before Step 3b" in block
    assert "worktree-agent-" in block
    assert "git worktree list --porcelain" in block


@pytest.mark.parametrize("enumeration", ["step_1c", "step_2a"])
def test_branch_enumerations_exclude_agent_worktree_branches(enumeration):
    rc = REVIEW_CLOSE.read_text()
    if enumeration == "step_1c":
        assert "grep -v '^worktree-agent-'" in rc, (
            "Step 1c's for-each-ref sweep would warn about review agents' scratch branches"
        )
    else:
        head = rc[rc.index("### 2a. Feature Branches") :]
        assert "excluding any **agent worktree branch**" in head[:1200], (
            "Step 2a would review a leaked agent branch as though it were feature work"
        )


@pytest.mark.parametrize("skill", ["claim-task", "auto-build", "auto-fix", "auto-judge"])
def test_pre_existing_worktree_sites_still_refuse_isolation(skill):
    """The fix is site-specific: these four spawn into a worktree an earlier step made."""
    text = (SKILLS_DIR / skill / "SKILL.md").read_text()
    assert re.search(r"(?i)do\s+\*{0,2}not\*{0,2}\s+set\s+`isolation", text), (
        f"/{skill} lost its 'do NOT set isolation' instruction"
    )


def test_shared_partial_names_the_shipped_sites_without_a_pre_existing_worktree():
    partial = PARTIAL.read_text()
    for site in ("/review-close` Step 2b", "/codebase-review", "/security-audit"):
        assert site in partial, f"adversarial-review.md does not name {site}"


# ---------------------------------------------------------------------------
# #240 — the doc-only skip
# ---------------------------------------------------------------------------


def _code_extensions(paragraph: str) -> set[str]:
    return set(re.findall(r"`(\.[a-z]+)`", re.split(r"—\s*only", paragraph)[0]))


def _paragraph_starting(text: str, marker: str) -> str:
    start = text.index(marker)
    return text[start : text.index("\n\n", start)]


def test_all_three_doc_only_skips_share_one_code_file_set():
    text = REVIEW_CLOSE.read_text()
    sets = {
        "3": _code_extensions(_paragraph_starting(text, "4. **If the diff is doc-only**")),
        "2b": _code_extensions(_paragraph_starting(text, "**0. Per-target doc-only skip")),
        "2d": _code_extensions(_paragraph_starting(text, "**0. Per-branch doc-only skip")),
    }
    for name, found in sets.items():
        assert ".py" in found and len(found) == 11, f"Step {name}'s code-file set: {found}"
    assert ".md" not in sets["3"], "doc counter-examples leaked into the code-file set"
    assert sets["2b"] == sets["3"] == sets["2d"]


@pytest.mark.parametrize(
    "marker,predicate",
    [
        ("**0. Per-target doc-only skip", "touches **no** code files"),
        ("**0. Per-branch doc-only skip", "touches no code files"),
    ],
)
def test_the_skip_predicates_are_not_inverted(marker, predicate):
    """Inverting both (`no` → `any`) passed 32/32 against the first version, and is
    strictly worse than never having shipped the skip: every code branch skips the gate."""
    para = _paragraph_starting(REVIEW_CLOSE.read_text(), marker)
    assert predicate in para, f"skip predicate changed or inverted: {para[:160]!r}"
    assert not re.search(r"touches \*{0,2}any\*{0,2} code files", para)


def test_the_skip_actuator_still_skips():
    para = _paragraph_starting(REVIEW_CLOSE.read_text(), "**0. Per-target doc-only skip")
    assert "skip the agent for that target" in para


def test_the_skip_is_gated_on_no_applicable_convention_not_on_the_extension_alone():
    """The first version shipped "a diff with no code in it cannot violate one". Sysop's
    own maps disprove it — `.claude/skills/**/*.md`, beancount's vendor `README.md` and
    `<ledger>.beancount`, the llm pack's prompt templates all carry conventions, and the
    beancount one is explicitly not scanner-shaped."""
    block = _step_2b(REVIEW_CLOSE.read_text())
    assert "cannot violate one" not in block, "the false premise is back"
    assert "no rule that governs the file types the diff *does* touch" in block
    assert "do not skip" in block, "the escape hatch must be an instruction, not a hint"
    for evidence in ("convention_map.md", "beancount", "Synthetic content only"):
        assert evidence in block, f"the counter-example evidence for {evidence} is gone"


def test_the_skip_does_not_waive_secret_scanning():
    block = _step_2b(REVIEW_CLOSE.read_text())
    para = _paragraph_starting(block, "> **Check the second condition")
    assert "A02" in para and "security_map.md" in para
    assert "neither touches nor waives it" in para, (
        "the carve-out must state the skip does not waive the scan — a round mutation "
        "reworded it to *waive* A02 while both greps stayed satisfied"
    )


def test_a_skipped_target_is_not_reported_as_approved():
    block = _step_2b(REVIEW_CLOSE.read_text())
    assert "never as `APPROVED`" in block
    assert "an agent that was never spawned has approved nothing" in block


def test_step_2b_results_have_somewhere_to_render():
    """A skip nobody can see is not a fix. Step 8 had no convention line at all.

    Matched by content, not by list number. This assertion used to read
    `"4. **Record outcomes for Step 8.**"`; Phase 200 inserted a step ahead of
    it, everything renumbered, and the guard went red on a change that did not
    touch its subject at all. A guard keyed to an ordinal is walked through by
    any insertion above it -- and reports the wrong defect when it fires.
    """
    rc = REVIEW_CLOSE.read_text()
    assert re.search(r"^\s*\d+\.\s+\*\*Record outcomes for Step 8\.\*\*",
                     _step_2b(rc), re.M), (
        "Step 2b no longer has a numbered step recording outcomes for Step 8"
    )
    report = rc[rc.index("## Step 8: Report") :]
    assert "Conventions:" in report, "Step 8 has no line for convention-check results"
    assert "N skipped (doc-only)" in report


def test_2b_targets_exclude_branches_step_2a_skipped():
    """A SKIP'd branch is not merging this run; a BLOCKED verdict on it would halt the
    close over work already declared out of scope."""
    block = _step_2b(REVIEW_CLOSE.read_text())
    assert "**SKIP — paused work present** is *not* a target" in block


def test_the_unpushed_main_group_has_a_retrieval_command_not_just_a_predicate():
    """The first version specified the group's diff for the skip predicate only, then said
    "For each remaining **branch**" — reproducing, for its own new work, the exact
    fix-the-placeholder-not-the-generator error it caught for #241."""
    block = _step_2b(REVIEW_CLOSE.read_text())
    assert "| unpushed-main group | `git diff origin/main...HEAD` |" in block
    assert "**For each remaining target:**" in block, "loop header still says 'branch'"
    assert "the target's **diff basis** from the table above" in block
    assert '<branch name, or "unpushed main commits">' in block, "prompt is branch-shaped"


def test_the_group_target_is_guarded_on_having_a_remote_and_being_on_main():
    block = _step_2b(REVIEW_CLOSE.read_text())
    assert "If the repo has no `origin` remote, or `HEAD` is not `main`" in block


# ---------------------------------------------------------------------------
# Docs kept in step with the skill (all unguarded in the first version)
# ---------------------------------------------------------------------------


def test_workflow_spec_records_all_three_fixes():
    line = next(
        ln
        for ln in (DOCS_DIR / "WORKFLOW.md").read_text().splitlines()
        if "Spawn an Opus adversarial sub-agent per branch" in ln
    )
    assert "isolated in its own worktree" in line
    assert "merge-base-relative" in line
    assert "Skipped for a doc-only diff" in line


def test_workflow_guide_by_hand_variant_says_why_three_dots():
    line = next(
        ln
        for ln in (DOCS_DIR / "WORKFLOW_GUIDE.md").read_text().splitlines()
        if ln.startswith("1. Review each feature branch:")
    )
    assert "main...<branch>" in line and "three dots" in line


def test_ui_verify_diffs_against_the_merge_base():
    """Same defect class as #241 in a different shape — a bare `main` tip comparison —
    which the scan cannot see by construction. Three dots is the wrong fix here: it would
    drop the uncommitted changes the step exists to catch."""
    text = (SKILLS_DIR / "_shared" / "ui-verify.md").read_text()
    assert 'git diff --name-only "$(git merge-base main HEAD)" -- frontend/' in text
    assert "git diff --name-only main -- frontend/" not in text


@pytest.mark.parametrize("script", ["claim_task.sh", "batch_work.sh"])
def test_task_body_seed_hints_are_merge_base_relative(script):
    text = (REPO_ROOT / "core" / "companion" / "scripts" / script).read_text()
    assert "git diff --name-only main...HEAD" in text
    assert "git diff --name-only main)" not in text
