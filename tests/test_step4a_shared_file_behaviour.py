"""Phase 178 — EXECUTABLE guards for Step 4a's shared-append recipe (upstream #307).

Why this module exists, stated plainly: the first version of this phase shipped
19 prose-ordering tests, and an independent reviewer ran 52 mutations through
them and watched **49 survive**. Two of the three legs could be deleted wholesale
with the suite green, and every polarity in the change was unguarded -- flipping
"`0` means merged" to "`0` means NOT merged" passed. A separate reviewer then
found four HIGH defects by *running* the recipe, none of which the prose tests
could see.

So these tests build real git repositories and run the prescribed commands. They
pin the recipe's load-bearing FACTS, which no rewording can drift and no
substring pin can fake:

  1. The marker-strip union corrupts, still parses, and the validator rejects it
     with the specific errors the skill quotes.
  2. The stage numbers are what the skill says they are.
  3. `rev-list --count <b> "^HEAD"` really does separate merged from unmerged
     pre-squash **for a rebase-then-ff-merge**, and does NOT for a cherry-pick.
     The docstring here used to say "in all three merge shapes"; nothing built
     an integration branch or a cherry-pick, so the claim was pinned by a test
     that never exercised it.
  4. That same test is INVALID post-squash -- which is why Step 6 must not use
     it, and this test fails if someone reintroduces it there.
  5. The `^` operand must be quoted, because unquoted it is a zsh glob.

Companion prose/ordering guards live in test_step4a_shared_file_conflicts.py.
Those check the recipe is written down; these check it is true.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
VALIDATOR = REPO / "core" / "companion" / "scripts" / "validate_tasks.py"
SKILL = REPO / "core" / "skills" / "review-close" / "SKILL.md"

INDEX_HEAD = """schema_version: 2

phases:
  - number: 6
    title: "Active phase"
    status: in_progress
    current_focus: true

tasks:
  - id: FEAT-SEED
    title: "Seed task"
    phase: 6
    status: open
    effort: Low
    blast_radius: single-file
    user_action: false
    depends_on: []
    surfaced_by: []
    body: open/FEAT-SEED.md
"""


def _entry(tid: str, title: str) -> str:
    return f"""
  - id: {tid}
    title: "{title}"
    phase: 6
    status: open
    effort: Low
    blast_radius: single-file
    user_action: false
    depends_on: []
    surfaced_by: []
    body: open/{tid}.md
"""


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True
    )


def _init(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", ".")
    # Pin the initial branch name. `init.defaultBranch` is unset on many CI
    # images, where git still defaults to `master` -- and every fixture here
    # names `main`. `symbolic-ref` works on every git version, unlike `init -b`.
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")
    for d in ("tasks/open", "tasks/deferred", "tasks/archive"):
        (repo / d).mkdir(parents=True, exist_ok=True)
    (repo / "tasks/index.yml").write_text(INDEX_HEAD)
    (repo / "tasks/open/FEAT-SEED.md").write_text("# FEAT-SEED\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")


def _file_a_followup(repo: Path, tid: str, title: str) -> None:
    """What /document-work's follow-up carve-out requires a branch to do."""
    idx = repo / "tasks/index.yml"
    idx.write_text(idx.read_text() + _entry(tid, title))
    (repo / f"tasks/open/{tid}.md").write_text(f"# {tid}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"file {tid}")


def _validate(repo: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VALIDATOR), "--path", str(repo / "tasks")],
        capture_output=True,
        text=True,
    )


@pytest.fixture
def two_branch_conflict(tmp_path: Path) -> Path:
    """Two branches each file a follow-up; B lands, A rebases -> conflict."""
    repo = tmp_path / "r"
    _init(repo)
    for tid, title in (("FEAT-AAAA", "Alpha follow-up"), ("FEAT-BBBB", "Beta follow-up")):
        _git(repo, "checkout", "-q", "-b", f"feat/{tid}", "main")
        _file_a_followup(repo, tid, title)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/FEAT-BBBB")
    _git(repo, "checkout", "-q", "feat/FEAT-AAAA")
    r = _git(repo, "rebase", "main")

    # A non-zero exit is NOT evidence of a conflict: `fatal: invalid upstream`
    # returns non-zero too. That is exactly how this fixture passed locally and
    # failed on CI, where git defaults to `master` and every `main` reference
    # errored -- the fixture reported "conflict" while nothing had conflicted.
    # Assert the conflict STATE instead: unmerged index entries.
    assert r.returncode != 0, f"rebase unexpectedly succeeded:\n{r.stdout}{r.stderr}"
    unmerged = _git(repo, "ls-files", "-u").stdout.strip()
    assert unmerged, (
        "expected UNMERGED INDEX ENTRIES (a real conflict), got none — the "
        f"rebase failed for another reason:\n{r.stdout}{r.stderr}"
    )
    assert "tasks/index.yml" in unmerged, "the conflict must be in tasks/index.yml"
    return repo


# ---------------------------------------------------------------------------
# FACT 1 — the corruption, and the validator errors the skill quotes verbatim
# ---------------------------------------------------------------------------


def test_marker_strip_union_corrupts_but_still_parses(two_branch_conflict: Path) -> None:
    """The whole reason the skill forbids marker-stripping. If this ever stops
    being true, the prohibition's stated rationale is stale."""
    repo = two_branch_conflict
    idx = repo / "tasks/index.yml"
    kept = [
        ln
        for ln in idx.read_text().split("\n")
        if not ln.startswith(("<<<<<<<", "=======", ">>>>>>>"))
    ]
    idx.write_text("\n".join(kept))

    data = yaml.safe_load(idx.read_text())
    tasks = data["tasks"]
    ids = [t.get("id") for t in tasks]

    assert len(ids) == len(set(ids)), "the corruption must keep ids UNIQUE — that is what hides it"
    starved = [t for t in tasks if len(t) < 10]
    assert starved, "expected at least one field-starved entry from the marker strip"
    assert any(
        t.get("phase") is None or t.get("status") is None for t in tasks
    ), "the starved entry must be missing required fields"


def test_validator_rejects_the_marker_strip_union_with_the_quoted_errors(
    two_branch_conflict: Path,
) -> None:
    """Pins SKILL.md's quoted error text to what the shipped script actually emits."""
    repo = two_branch_conflict
    idx = repo / "tasks/index.yml"
    kept = [
        ln
        for ln in idx.read_text().split("\n")
        if not ln.startswith(("<<<<<<<", "=======", ">>>>>>>"))
    ]
    idx.write_text("\n".join(kept))

    r = _validate(repo)
    assert r.returncode != 0, "the validator MUST reject a marker-stripped union"
    out = r.stdout + r.stderr
    assert "must be int or float, got NoneType" in out
    assert "orphan body file" in out

    quoted = "task 'phase' must be int or float, got NoneType"
    assert quoted in out, "the error SKILL.md quotes must be what the script emits"
    assert quoted in SKILL.read_text(encoding="utf-8"), (
        "SKILL.md no longer quotes the error this test pins — one of them drifted"
    )


def test_validator_distinguishes_schema_errors_from_environment_failures() -> None:
    """SKILL.md routes exit 1 and exit 2 to DIFFERENT actions; pin the split."""
    r = subprocess.run(
        [sys.executable, str(VALIDATOR), "--path", "/nonexistent/tasks/dir"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 2, (
        "an environment failure must exit 2, not 1 — the skill says do NOT abort "
        "the rebase on a 2"
    )


# ---------------------------------------------------------------------------
# FACT 2 — stage numbering, asserted against git rather than against a sentence
# ---------------------------------------------------------------------------


def test_stage_2_is_the_merge_target_and_stage_3_is_the_replayed_branch(
    two_branch_conflict: Path,
) -> None:
    repo = two_branch_conflict
    stage2 = _git(repo, "show", ":2:tasks/index.yml").stdout
    stage3 = _git(repo, "show", ":3:tasks/index.yml").stdout

    assert "FEAT-BBBB" in stage2 and "FEAT-AAAA" not in stage2, (
        "stage 2 must be the MERGE TARGET (carrying the already-merged sibling)"
    )
    assert "FEAT-AAAA" in stage3 and "FEAT-BBBB" not in stage3, (
        "stage 3 must be the COMMIT BEING REPLAYED (this branch's own entry)"
    )


def test_prescribed_union_resolution_produces_a_valid_index(
    two_branch_conflict: Path,
) -> None:
    """Run the recipe end to end: stages -> union by id -> validate -> continue."""
    repo = two_branch_conflict
    ours = yaml.safe_load(_git(repo, "show", ":2:tasks/index.yml").stdout)
    theirs_txt = _git(repo, "show", ":3:tasks/index.yml").stdout
    theirs = yaml.safe_load(theirs_txt)

    have = {t["id"] for t in ours["tasks"]}
    new = [t for t in theirs["tasks"] if t["id"] not in have]
    assert [t["id"] for t in new] == ["FEAT-AAAA"]

    base_txt = _git(repo, "show", ":2:tasks/index.yml").stdout.rstrip("\n")
    blocks = []
    for t in new:
        cap, blk = False, []
        for ln in theirs_txt.split("\n"):
            if ln.startswith(f"  - id: {t['id']}"):
                cap = True
            elif cap and (ln.startswith("  - id:") or (ln and not ln.startswith("    "))):
                break
            if cap:
                blk.append(ln)
        blocks.append("\n".join(blk).rstrip())
    (repo / "tasks/index.yml").write_text(base_txt + "\n\n" + "\n\n".join(blocks) + "\n")

    r = _validate(repo)
    assert r.returncode == 0, f"the prescribed resolution must validate clean:\n{r.stdout}{r.stderr}"

    _git(repo, "add", "tasks/index.yml")
    cont = subprocess.run(
        ["git", "rebase", "--continue"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={"GIT_EDITOR": "true", "PATH": "/usr/bin:/bin:/usr/local/bin"},
    )
    assert cont.returncode == 0, f"rebase --continue failed: {cont.stderr}"
    final = yaml.safe_load((repo / "tasks/index.yml").read_text())
    assert {t["id"] for t in final["tasks"]} == {"FEAT-SEED", "FEAT-AAAA", "FEAT-BBBB"}


# ---------------------------------------------------------------------------
# FACT 3/4 — the containment test: valid pre-squash, INVALID post-squash
# ---------------------------------------------------------------------------


def _count(repo: Path, branch: str, excl: str) -> int:
    r = _git(repo, "rev-list", "--count", branch, excl)
    assert r.returncode == 0, r.stderr
    return int(r.stdout.strip())


def test_containment_separates_merged_from_unmerged_pre_squash(tmp_path: Path) -> None:
    """Step 4c's filter, for the shape it is actually valid on.

    0 == merged, non-zero == not -- for a **rebase-then-ff-merge**. This test
    builds only that shape, which is why the module docstring no longer claims
    it covers three. The cherry-pick shapes are covered below.
    """
    repo = tmp_path / "r"
    _init(repo)
    _git(repo, "checkout", "-q", "-b", "feat/merged", "main")
    _file_a_followup(repo, "FEAT-M", "Merged")
    _git(repo, "checkout", "-q", "-b", "feat/skipped", "main")
    _file_a_followup(repo, "FEAT-S", "Skipped")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/merged")

    assert _count(repo, "feat/merged", "^HEAD") == 0, "a merged branch must score 0"
    assert _count(repo, "feat/skipped", "^HEAD") > 0, "an unmerged branch must score non-zero"

    # main advances -> a merged branch must STILL score 0
    (repo / "unrelated.txt").write_text("x")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "advance main")
    assert _count(repo, "feat/merged", "^HEAD") == 0


def _unapplied(repo: Path, upstream: str, head: str) -> int:
    """`git cherry` '+' count -- commits in `head` whose patch is NOT upstream."""
    r = subprocess.run(
        ["git", "cherry", upstream, head],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return sum(1 for ln in r.stdout.splitlines() if ln.startswith("+"))


def test_containment_is_broken_by_a_cherry_pick_which_step4pre_prescribes(
    tmp_path: Path,
) -> None:
    """Q-189. The ancestry test scores non-zero on a FULLY APPLIED branch.

    Step 4-pre's `pr` policy runs `git cherry-pick origin/main..main`, so this
    is not an operator improvisation -- it is the prescribed path. If this test
    ever reports 0, the fallback in Step 4c step 1b can be reconsidered; until
    then the skill must not skip on `rev-list` alone.
    """
    repo = tmp_path / "r"
    _init(repo)
    _git(repo, "checkout", "-q", "-b", "feat/picked", "main")
    _file_a_followup(repo, "FEAT-P", "Picked")
    _git(repo, "checkout", "-q", "main")
    # Make main diverge first, so the cherry-pick cannot reproduce the same SHA.
    (repo / "diverge.txt").write_text("x")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "advance main before the pick")
    _git(repo, "cherry-pick", "feat/picked")

    assert _count(repo, "feat/picked", "^HEAD") > 0, (
        "a cherry-picked branch is NOT an ancestor -- if this is 0 the whole "
        "premise of Q-189 has changed"
    )
    # ...while the content is provably present.
    assert _unapplied(repo, "HEAD", "feat/picked") == 0, (
        "git cherry must see through the pick -- this is the fallback the "
        "skill now prescribes"
    )


def test_the_two_tests_disagree_only_on_the_applied_branch(tmp_path: Path) -> None:
    """The fallback must not rubber-stamp a genuinely unmerged branch.

    A guard that says "applied" for everything is worse than no guard. This
    pins the discriminating case: cherry-picked scores 0 unapplied, genuinely
    unmerged scores non-zero, and `rev-list` cannot tell them apart.
    """
    repo = tmp_path / "r"
    _init(repo)
    _git(repo, "checkout", "-q", "-b", "feat/picked", "main")
    _file_a_followup(repo, "FEAT-P", "Picked")
    _git(repo, "checkout", "-q", "-b", "feat/never", "main")
    _file_a_followup(repo, "FEAT-N", "Never")
    _git(repo, "checkout", "-q", "main")
    (repo / "diverge.txt").write_text("x")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "advance main before the pick")
    _git(repo, "cherry-pick", "feat/picked")

    # rev-list: identical verdicts -- zero discriminating power.
    assert _count(repo, "feat/picked", "^HEAD") > 0
    assert _count(repo, "feat/never", "^HEAD") > 0

    # git cherry: separates them.
    assert _unapplied(repo, "HEAD", "feat/picked") == 0, "applied -> 0"
    assert _unapplied(repo, "HEAD", "feat/never") > 0, (
        "a branch that never landed must still score non-zero unapplied, or "
        "the fallback would consolidate unmerged work"
    )


def test_git_cherry_false_reports_after_a_conflict_resolved_pick(
    tmp_path: Path,
) -> None:
    """The fallback's stated limit, pinned so the prose cannot drop it.

    `git cherry` is patch-id based, so resolving a conflict during the pick
    changes the patch and the commit reads as unapplied. The skill says this
    out loud; if this test goes green-by-inversion someone has softened it.
    """
    repo = tmp_path / "r"
    _init(repo)
    (repo / "shared.txt").write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base shared")

    _git(repo, "checkout", "-q", "-b", "feat/conflict", "main")
    (repo / "shared.txt").write_text("branch version\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "branch edits shared")

    _git(repo, "checkout", "-q", "main")
    (repo / "shared.txt").write_text("main version\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "main edits shared")

    # Cherry-pick conflicts; resolve to the branch's content.
    subprocess.run(
        ["git", "cherry-pick", "feat/conflict"],
        cwd=repo, capture_output=True, text=True,
    )
    (repo / "shared.txt").write_text("branch version\n")
    _git(repo, "add", "-A")
    _git(repo, "-c", "core.editor=true", "cherry-pick", "--continue")

    assert _unapplied(repo, "HEAD", "feat/conflict") > 0, (
        "a conflict-resolved pick changes the patch-id, so git cherry reports "
        "it unapplied even though the content landed -- this is exactly why "
        "the skill says neither test is authoritative alone"
    )


def test_containment_is_invalid_after_a_squash_so_step6_must_not_use_it(
    tmp_path: Path,
) -> None:
    """The HIGH the round found. This test EXISTS to keep it from coming back.

    After a squash the branch is provably not an ancestor, so an ancestry test
    scores non-zero for a correctly merged branch AND for a skipped one --
    identical answers, zero discriminating power.
    """
    repo = tmp_path / "r"
    _init(repo)
    _git(repo, "checkout", "-q", "-b", "feat/merged", "main")
    _file_a_followup(repo, "FEAT-M", "Merged")
    _git(repo, "checkout", "-q", "-b", "feat/skipped", "main")
    _file_a_followup(repo, "FEAT-S", "Skipped")

    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--squash", "feat/merged")
    _git(repo, "commit", "-qm", "Merged PR #1 (squash)")

    merged = _count(repo, "feat/merged", "^HEAD")
    skipped = _count(repo, "feat/skipped", "^HEAD")
    assert merged > 0, (
        "post-squash, a correctly merged branch scores NON-ZERO — if this ever "
        "returns 0, re-read Step 6 before trusting it"
    )
    assert merged == skipped or (merged > 0 and skipped > 0), (
        "post-squash the test cannot separate merged from skipped"
    )

    # Step 6 must therefore not PRESCRIBE it. Scope to prescriptive lines only:
    # the section explains at length WHY the check is wrong, and naming it there
    # is correct prose. A guard that reds on its own rationale is the
    # over-strictness failure mode, not a catch.
    body = SKILL.read_text(encoding="utf-8")
    i = body.index("**`pr` policy — per-branch cleanup**")
    j = body.index("For each **SKIP'd** branch", i)
    prescriptive = "\n".join(
        ln
        for ln in body[i:j].split("\n")
        if not ln.lstrip().startswith(">")  # blockquote == rationale, not instruction
    )
    assert "rev-list --count" not in prescriptive, (
        "Step 6's `pr` cleanup PRESCRIBES an ancestry containment check again — "
        "it can never return its pass value after a squash. Key it on the "
        "4a-SKIP verdict instead. (Explaining why it is wrong, inside the "
        "blockquote, is fine and is not what this asserts.)"
    )


def test_the_caret_operand_must_be_quoted_because_zsh_globs_it(tmp_path: Path) -> None:
    """HIGH-4: unquoted `^HEAD` under zsh extended_glob silently inverts the answer."""
    repo = tmp_path / "r"
    _init(repo)
    _git(repo, "checkout", "-q", "-b", "feat/merged", "main")
    _file_a_followup(repo, "FEAT-M", "Merged")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/merged")

    # zsh is absent from most Linux CI images, and a missing binary raises
    # FileNotFoundError rather than returning non-zero -- so the returncode
    # check alone let this test hard-error instead of skipping.
    try:
        quoted = subprocess.run(
            ["zsh", "-f", "-c", "setopt extended_glob; git rev-list --count feat/merged '^HEAD'"],
            cwd=repo, capture_output=True, text=True,
        )
        unquoted = subprocess.run(
            ["zsh", "-f", "-c", "setopt extended_glob; git rev-list --count feat/merged ^HEAD"],
            cwd=repo, capture_output=True, text=True,
        )
    except (FileNotFoundError, OSError):
        pytest.skip("zsh unavailable — the glob hazard is platform-specific")
    if quoted.returncode != 0:
        pytest.skip("zsh unavailable")

    assert quoted.stdout.strip() == "0", "quoted form must report the merged branch as merged"
    assert unquoted.stdout.strip() != "0", (
        "if this ever equals 0, the glob hazard is gone and the skill's warning "
        "can be revisited — until then it is real"
    )

    # And the shipped prose must use the quoted form.
    body = SKILL.read_text(encoding="utf-8")
    assert '"^HEAD"' in body, "the shipped command must quote the ^ operand"
    assert 'count "<branch from frontmatter>" ^HEAD' not in body, (
        "an unquoted ^HEAD operand is back in the shipped command"
    )
