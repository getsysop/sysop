"""`close_batch.sh`'s merge target is STATED, never inferred from `HEAD` (Phase 248, `Q-308`).

Phase 233 pointed the ancestry gate at `HEAD` (with `main` as a fallback) and
required STRICT SHA containment. Both halves were measured wrong here, in
opposite directions, and they compounded:

* **False ACCEPT** (`Q-308`, the filed defect) — a branch cut FROM the batch
  branch with its own commits on top is strictly contained in `HEAD`. The work is
  in `HEAD`, but nothing establishes `HEAD` reaches `main`. A `pr` integration
  branch and that scratch branch agree on **every** ancestry column ON STEP 4a's
  LOCAL-ONLY (`--ff-only`) ARM, first-parent reachability included, so no local
  predicate separates them there. On the published `--no-ff` arm first-parent
  does separate them — and a predicate right on one of the two arms is not a
  gate. Both are pinned, by
  `test_no_local_ancestry_column_separates_the_two_on_the_ff_arm` and
  `test_the_published_arm_is_separable_and_that_does_not_rescue_the_predicate`.
  The first version of this claim was universal and was demonstrated on the arm
  where it fails; the round caught it.
* **False REFUSE**, on the dominant `pr` path, every run — `/review-close` Step 4a
  merges a local-only branch with `git merge --ff-only`, which moves the merge
  target TO the branch tip. `head_sha == branch_sha` for the LAST branch merged,
  and for the ONLY branch of a single-branch cycle, so strict containment skipped
  its arm and `main` refused. Step 4b's shipped prose asserted the opposite.

The repair: the caller states the target (`--merge-target`), otherwise it comes
from `<project>/CLAUDE.md § Merge policy` — `main` under `direct`, and under `pr`
it is left UNRESOLVED on purpose, so only the `main` arm runs. Identity between
target and branch is compared by resolved **ref name**, never by SHA: after an
ff-merge they legitimately share a SHA while being different refs, and standing
on the unmerged branch they are the same ref.
"""
import re
import subprocess
from pathlib import Path

import pytest

import sitrep_survey as ss
from _reversal import assert_no_reversal

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "core/companion/scripts/close_batch.sh"


# Helpers are local rather than imported from `test_close_batch_sh`: no module in
# this suite imports a sibling test module, and pytest's rootdir does not put
# `tests/` on `sys.path`, so the import fails at collection.
def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root, tasks):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "review_tasks.md").write_text(tasks)
    (root / "README.md").write_text("# seed\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(cwd, *args):
    return subprocess.run(["bash", str(SCRIPT), *args],
                          cwd=str(cwd), capture_output=True, text=True)

_TASKS = """\
# Review Tasks

### Batch 1 — First batch `Pending`

> **Branch:** `feat/one`

- [ ] task one
"""


def _policy(repo, word):
    """Declare `<repo>/CLAUDE.md § Merge policy`, or leave the repo without one
    when `word` is None (which is what a `direct` consumer looks like).

    The commit is GATED on something being staged. `git commit` with an empty
    index exits 1 under `check=True` and takes the whole fixture down — the same
    empty-commit class `Q-360` filed against `install.sh`, met here while
    building the guard for a different entry.
    """
    p = repo / "CLAUDE.md"
    if word is None:
        p.unlink(missing_ok=True)
    else:
        p.write_text(f"# Fixture\n\n## Merge policy\n\n{word}\n")
    _git(repo, "add", "-A")
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"],
                            cwd=str(repo), capture_output=True)
    if staged.returncode != 0:
        _git(repo, "commit", "-qm", "policy")


def _with_batch_branch(root, policy="pr"):
    """A repo whose batch branch `feat/one` carries work and is merged nowhere."""
    repo = _repo(root, _TASKS)
    _policy(repo, policy)
    _git(repo, "checkout", "-qb", "feat/one")
    (repo / "w.txt").write_text("work\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "batch work")
    _git(repo, "checkout", "-q", "main")
    return repo


def _refusal_block(stdout: str) -> str:
    """The refusal itself, not 'everything after the first ❌'.

    Phase 250's round-2 lens defeated the naive split by printing an unrelated ❌
    line earlier: `split("❌", 1)[1]` then returns the whole remainder, and the
    two assertions can be satisfied by text that has nothing to do with the
    refusal — while the refusal itself is reverted to the `--force` message.

    Anchor on the line that IS the refusal, and take it plus its continuation
    lines (the indented advice that follows, up to the next verdict line).
    """
    lines = stdout.splitlines()
    idx = [i for i, ln in enumerate(lines) if "is NOT merged into" in ln]
    assert len(idx) == 1, (
        f"expected exactly one merge refusal, found {len(idx)}:\n{stdout}"
    )
    out = [lines[idx[0]]]
    for ln in lines[idx[0] + 1:]:
        if ln.strip().startswith(("❌", "✓", "⚠")) or not ln.startswith("  "):
            break
        out.append(ln)
    return "\n".join(out)


def _merged(r):
    """The script's own accept/refuse verdict, read off the batch line."""
    if "verified merged" in r.stdout:
        return True
    if "is NOT merged into" in r.stdout:
        return False
    raise AssertionError(f"no merge verdict in output:\n{r.stdout}\n{r.stderr}")


# ─────────────────────────────────────────────────────────────────────────────
# The false ACCEPT — `Q-308` proper
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("policy", ["pr", "direct", None])
def test_a_branch_cut_from_the_batch_branch_is_refused(tmp_path, policy):
    """**The filed defect.** Standing on a branch cut FROM the batch branch, with
    its own commits on top, the batch branch is strictly contained in `HEAD` and
    the shipped gate printed `✓ verified merged` and flipped the header.

    Refused under every policy, and for a different reason in each: `direct`
    resolves the target to `main` (which does not contain it), `pr` leaves the
    target unresolved so only the `main` arm runs. Parametrised because a fix
    that closed one and not the other is this repo's recurring shape.
    """
    repo = _with_batch_branch(tmp_path / "repo", policy=policy)
    _git(repo, "checkout", "-q", "-b", "scratch/exp", "feat/one")
    (repo / "s.txt").write_text("scratch\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "scratch work")

    # Precondition, asserted rather than assumed: the shape really is the one the
    # entry describes — strictly contained in HEAD, absent from main.
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", "feat/one", "HEAD"],
        cwd=str(repo), capture_output=True).returncode == 0
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", "feat/one", "main"],
        cwd=str(repo), capture_output=True).returncode != 0
    assert _git_sha(repo, "HEAD") != _git_sha(repo, "feat/one"), (
        "fixture is wrong: HEAD sits at the branch tip, which is a DIFFERENT "
        "defect (Phase 233's) and would pass this test for the wrong reason"
    )

    r = _run(repo, "1")

    assert not _merged(r), (
        "a branch contained in HEAD but absent from main was accepted; HEAD is "
        f"being read as evidence the work reaches `main`.\n{r.stdout}"
    )
    assert "1:unmerged" in r.stdout, r.stdout
    assert "`Pending`" in (repo / "review_tasks.md").read_text(), (
        "the header was flipped despite the refusal"
    )


def _git_sha(repo, ref):
    return subprocess.run(["git", "rev-parse", ref], cwd=str(repo),
                          capture_output=True, text=True).stdout.strip()


def _ancestry_columns(repo, branch="feat/one"):
    """Every local ancestry question a gate could ask, on one repo."""
    def anc(a, b):
        return subprocess.run(["git", "merge-base", "--is-ancestor", a, b],
                              cwd=str(repo), capture_output=True).returncode == 0
    first_parent = subprocess.run(
        ["git", "rev-list", "--first-parent", "HEAD"],
        cwd=str(repo), capture_output=True, text=True).stdout.split()
    merges = subprocess.run(
        ["git", "rev-list", "--count", "--merges", "HEAD", "^origin/main"],
        cwd=str(repo), capture_output=True, text=True).stdout.strip()
    return {
        "branch_in_head": anc(branch, "HEAD"),
        "head_is_branch_tip": _git_sha(repo, "HEAD") == _git_sha(repo, branch),
        "origin_main_in_head": anc("origin/main", "HEAD"),
        "branch_in_main": anc(branch, "main"),
        "branch_on_first_parent": _git_sha(repo, branch) in first_parent,
        "merges_ahead_of_origin_main": merges,
    }


def _shape(root, *, kind, merge):
    """`integration` or `scratch`, built with Step 4a's own commands.

    `merge` selects which of Step 4a's TWO arms built the integration branch:
    `ff` is the local-only arm (rebase-then-`--ff-only`, the common case by the
    step's own words) and `noff` is the published arm.
    """
    repo = _with_batch_branch(root)
    bare = root.parent / f"{root.name}-origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True,
                   capture_output=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "fetch", "-q", "origin", "main")
    if kind == "scratch":
        _git(repo, "checkout", "-q", "-b", "head-branch", "feat/one")
    else:
        _git(repo, "checkout", "-q", "-b", "head-branch", "origin/main")
        if merge == "noff":
            _git(repo, "merge", "-q", "--no-ff", "-m", "merge", "feat/one")
        else:
            _git(repo, "merge", "-q", "--ff-only", "feat/one")
    (repo / "extra.txt").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "extra")
    return repo


def test_no_local_ancestry_column_separates_the_two_on_the_ff_arm(tmp_path):
    """**Why the fix is a contract change and not a narrower predicate.**

    On Step 4a's **local-only** arm — rebase then `git merge --ff-only`, which the
    step calls "the common case" — a legitimate integration branch and the
    `Q-308` scratch branch are identical on **every** ancestry column a local gate
    could consult, first-parent reachability and merge count included. There is
    nothing left to key a predicate on, which is why the target has to be stated.

    **This test previously built the `--no-ff` arm and asserted the same thing,
    which is false there** — see the companion test below. The round caught it:
    the claim was true of the shape that matters and was being demonstrated on
    the shape where it fails.
    """
    cols = {k: _ancestry_columns(_shape(tmp_path / k, kind=k, merge="ff"))
            for k in ("integration", "scratch")}
    assert cols["integration"] == cols["scratch"], (
        "the two shapes now differ on a local ancestry column on the FF arm, so "
        f"`--merge-target` may no longer be the only honest instrument:\n{cols}"
    )


def test_the_published_arm_is_separable_and_that_does_not_rescue_the_predicate(tmp_path):
    """The limit of the test above, asserted rather than left for a reader to find.

    On Step 4a's **published** arm (`git merge --no-ff`) first-parent reachability
    DOES separate the two shapes — the batch tip hangs off the merge commit's
    second parent. A first-parent predicate would therefore be correct here and
    wrong on the ff arm, and a gate that is right on one of Step 4a's two arms is
    not a gate. That is the whole reason this is recorded as a test instead of as
    a sentence: if the ff arm ever becomes separable, the test above goes red and
    the contract can be revisited; until then the asymmetry is the argument.
    """
    integ = _ancestry_columns(_shape(tmp_path / "integ", kind="integration", merge="noff"))
    scratch = _ancestry_columns(_shape(tmp_path / "scratch", kind="scratch", merge="noff"))
    assert integ["branch_on_first_parent"] is False
    assert scratch["branch_on_first_parent"] is True
    assert integ != scratch, "the published arm is no longer separable"


# ─────────────────────────────────────────────────────────────────────────────
# The false REFUSE — the ff-merge shapes Step 4a actually produces
# ─────────────────────────────────────────────────────────────────────────────

def _ff_cycle(root, branches):
    """`/review-close` Step 4a's local-only arm, verbatim: rebase-then-ff, oldest
    first, onto an integration branch. The LAST branch merged ends up sharing a
    SHA with the integration branch — that is what ff-only means."""
    tasks = "# Review Tasks\n\n" + "\n".join(
        f"### Batch {i} — Batch {i} `Pending`\n\n> **Branch:** `{b}`\n\n- [ ] task {i}\n"
        for i, b in enumerate(branches, start=1)
    )
    repo = _repo(root, tasks)
    _policy(repo, "pr")
    bare = root.parent / f"{root.name}-origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True,
                   capture_output=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "main")
    for b in branches:
        _git(repo, "checkout", "-q", "main")
        _git(repo, "checkout", "-qb", b)
        (repo / f"{b.replace('/', '_')}.txt").write_text("work\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", f"work {b}")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "merge/rc", "origin/main")
    for b in branches:
        _git(repo, "checkout", "-q", b)
        subprocess.run(["git", "rebase", "-q", "merge/rc"], cwd=str(repo),
                       check=True, capture_output=True)
        _git(repo, "checkout", "-q", "merge/rc")
        _git(repo, "merge", "-q", "--ff-only", b)
    return repo


@pytest.mark.parametrize("branches,batch,label", [
    (["feat/one"], "1", "single-branch cycle"),
    (["feat/one", "feat/two"], "2", "last branch of a two-branch cycle"),
    (["feat/one", "feat/two"], "1", "first branch of a two-branch cycle"),
])
def test_ff_merged_branches_are_accepted(tmp_path, branches, batch, label):
    """**The second defect, and it is the one an operator meets every run.**

    Step 4a merges local-only branches with `--ff-only`, so the merge target and
    the last-merged branch share a SHA. Strict SHA containment skipped its arm
    there and `main` refused — a correctly merged branch reported `unmerged` on
    the dominant path, which is what trains an operator to reach for `--force`,
    which in turn disarms the gate for every other branch in the same run.
    """
    repo = _ff_cycle(tmp_path / "repo", branches)
    r = _run(repo, "--merge-target", "merge/rc", batch)

    assert _merged(r), f"{label}: a correctly ff-merged branch was refused.\n{r.stdout}"
    assert f"{batch}:unmerged" not in r.stdout, r.stdout


def test_the_last_ff_merged_branch_really_does_share_a_sha(tmp_path):
    """The non-vacuity control for the case above: if the fixture stopped
    producing the SHA collision, the test would pass against a gate that still
    had the defect."""
    repo = _ff_cycle(tmp_path / "repo", ["feat/one", "feat/two"])
    assert _git_sha(repo, "HEAD") == _git_sha(repo, "feat/two"), (
        "fixture no longer reproduces the ff SHA collision, so "
        "test_ff_merged_branches_are_accepted proves nothing about it"
    )
    assert _git_sha(repo, "HEAD") != _git_sha(repo, "feat/one")


# ─────────────────────────────────────────────────────────────────────────────
# Phase 233's HIGH, and the PR-reuse refusal, both preserved by REF IDENTITY
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("target", [None, "feat/one"])
def test_standing_on_the_unmerged_batch_branch_is_still_refused(tmp_path, target):
    """**Phase 233's round finding, kept closed by a different mechanism.**

    `batch_work.sh` creates the batch worktree checked out ON the batch branch,
    so this is where an operator actually stands. SHA strictness used to catch
    it; ref identity catches it now — including when the target is *named*, as
    `HEAD` or as the branch itself, which is the PR-reuse shape.
    """
    repo = _with_batch_branch(tmp_path / "repo")
    _git(repo, "checkout", "-q", "feat/one")
    args = ["1"] if target is None else ["--merge-target", target, "1"]

    r = _run(repo, *args)

    assert not _merged(r), (
        f"target={target!r}: standing on the unmerged batch branch was accepted; "
        f"containment in a target that IS the branch says nothing.\n{r.stdout}"
    )
    assert "1:unmerged" in r.stdout, r.stdout


def test_force_still_overrides(tmp_path):
    """The documented escape is unchanged: cherry-picked work is genuinely not an
    ancestor, and `--force` is its stated remedy."""
    repo = _with_batch_branch(tmp_path / "repo")
    _git(repo, "checkout", "-q", "feat/one")
    r = _run(repo, "--force", "1")
    assert "accepting cherry-pick" in r.stdout, r.stdout
    assert "Closed: 1" in r.stdout, r.stdout


def test_a_branch_already_on_main_verifies_without_a_target(tmp_path):
    """The `main` arm is retained unconditionally. Work that genuinely landed on
    `main` in an earlier cycle is merged by any reading, and that arm cannot
    produce the `Q-308` shape because `main` is the thing being established."""
    repo = _with_batch_branch(tmp_path / "repo", policy="pr")
    _git(repo, "merge", "-q", "--ff-only", "feat/one")
    r = _run(repo, "1")
    assert _merged(r), r.stdout


# ─────────────────────────────────────────────────────────────────────────────
# Target resolution: the policy reader and the flag
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("claude_md,expected", [
    (None, "merge target: 'main' (§ Merge policy: direct)"),
    ("# P\n\n## Merge policy\n\ndirect\n", "merge target: 'main' (§ Merge policy: direct)"),
    ("# P\n\n## Merge policy\n\npr\n", "merge target: UNRESOLVED (§ Merge policy: pr)"),
    ("# P\n\n## Merge policy\n\nPR\n", "merge target: UNRESOLVED (§ Merge policy: pr)"),
    ("# P\n\n## Merge policy\n\npr — main is protected\n",
     "merge target: UNRESOLVED (§ Merge policy: pr)"),
    # A fenced template is an ILLUSTRATION, not the setting. `WORKFLOW.md` ships
    # this exact block, so a consumer quoting it must not thereby configure `pr`.
    ("# P\n\n```markdown\n## Merge policy\n\npr\n```\n",
     "merge target: 'main' (§ Merge policy: direct)"),
    # ...and a real section AFTER a fenced example still wins.
    ("# P\n\n```markdown\n## Merge policy\n\npr\n```\n\n## Merge policy\n\ndirect\n",
     "merge target: 'main' (§ Merge policy: direct)"),
    # Anything that is not one of the two documented words falls back, loudly-by-
    # default rather than silently to `pr`.
    ("# P\n\n## Merge policy\n\nsquash\n", "merge target: 'main' (§ Merge policy: direct)"),
])
def test_the_policy_reader_resolves_the_target(tmp_path, claude_md, expected):
    repo = _with_batch_branch(tmp_path / "repo", policy=None)
    if claude_md is not None:
        (repo / "CLAUDE.md").write_text(claude_md)
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "policy")
    else:
        assert not (repo / "CLAUDE.md").exists(), "fixture wrote a CLAUDE.md it should not have"
    r = _run(repo, "1")
    assert expected in r.stdout, f"claude_md={claude_md!r}\n{r.stdout}"


def test_an_operand_overrides_the_policy(tmp_path):
    repo = _with_batch_branch(tmp_path / "repo", policy="direct")
    r = _run(repo, "--merge-target", "refs/heads/main", "1")
    assert "merge target: 'refs/heads/main' (--merge-target)" in r.stdout, r.stdout


@pytest.mark.parametrize("form", ["space", "equals"])
def test_both_operand_forms_parse(tmp_path, form):
    repo = _ff_cycle(tmp_path / "repo", ["feat/one"])
    args = (["--merge-target", "merge/rc"] if form == "space"
            else ["--merge-target=merge/rc"])
    r = _run(repo, *args, "1")
    assert "merge target: 'merge/rc' (--merge-target)" in r.stdout, r.stdout
    assert _merged(r), r.stdout


def test_a_valueless_merge_target_exits_1_rather_than_eating_a_batch_number(tmp_path):
    """A `for arg in "$@"` loop has no `shift`, so the value is carried one
    iteration. A trailing `--merge-target` must be a loud exit — silently leaving
    the target unset would resolve it from policy and read as a normal run."""
    repo = _with_batch_branch(tmp_path / "repo")
    r = _run(repo, "1", "--merge-target")
    assert r.returncode == 1, r.stdout
    assert "--merge-target requires a value" in r.stderr, r.stderr


def test_the_usage_line_names_the_flag(tmp_path):
    repo = _with_batch_branch(tmp_path / "repo")
    r = _run(repo, "--not-a-flag")
    assert r.returncode == 1
    assert "--merge-target <ref>" in r.stderr, r.stderr


def test_the_pr_handrun_refusal_names_the_flag(tmp_path):
    """**The cost of fail-closed, pinned rather than hidden.** A `pr` consumer
    running the script by hand with no `--merge-target` loses the integration-
    branch acceptance Phase 233 gave them. That is deliberate — `HEAD` is not
    evidence — but the refusal has to be actionable in one step, so the message
    names the flag that resolves it."""
    repo = _with_batch_branch(tmp_path / "repo", policy="pr")
    _git(repo, "checkout", "-q", "-b", "merge/rc", "main")
    _git(repo, "merge", "-q", "--no-ff", "feat/one", "-m", "merge")

    r = _run(repo, "1")

    assert not _merged(r), r.stdout
    # NOT a whole-stdout substring test. `--merge-target` is also named on the
    # UNRESOLVED provenance line, which prints on EVERY `pr` run — including a
    # clean close — so a stdout-wide check passes whatever the refusal says.
    # Phase 250's round found exactly that: the refusal itself named `--force`,
    # the one remedy that is wrong here, and this assertion could not see it.
    # Scope to the refusal block: the ❌ line and what follows it.
    block = _refusal_block(r.stdout)
    assert "--merge-target <ref>" in block, (
        "the refusal does not name its own remedy\n" + r.stdout
    )
    assert re.search(r"--force is not the fix", block, re.I), (
        "the refusal does not warn off --force. On this shape --force accepts the "
        "branch unverified and disarms cherry-pick detection for the whole run, "
        "and Phase 248 recorded that a false refuse is what trains an operator to "
        "reach for it\n" + r.stdout
    )
    # ...and the same run with the flag is accepted, so the remedy is real.
    r2 = _run(repo, "--merge-target", "merge/rc", "1")
    assert _merged(r2), r2.stdout


# ─────────────────────────────────────────────────────────────────────────────
# Closures for the author-side battery's survivors (tools/phase248_mutations.py)
# ─────────────────────────────────────────────────────────────────────────────

def test_a_heading_that_merely_starts_with_the_section_name_is_not_the_section(tmp_path):
    """**Battery survivor `CB-6`, closed.** The header match is end-anchored, and
    nothing asserted it: dropping `[[:space:]]*$` left the suite green while
    `## Merge policy notes` — or a `## Merge policy (why)` aside — began resolving
    the policy. Over-acceptance is the direction that hides."""
    repo = _with_batch_branch(tmp_path / "repo", policy=None)
    (repo / "CLAUDE.md").write_text("# P\n\n## Merge policy notes\n\npr\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "policy")
    r = _run(repo, "1")
    assert "merge target: 'main' (§ Merge policy: direct)" in r.stdout, (
        "a heading that only starts with the section name resolved the policy\n"
        + r.stdout
    )


def test_an_unresolvable_merge_target_refuses_rather_than_crashing(tmp_path):
    """A typo'd or deleted `--merge-target` must produce a REFUSAL, not an abort.

    **This test does not close battery row `CB-11`, and an earlier version of this
    docstring said it did.** `CB-11` (dropping `_ref_id`'s `|| printf` fallback)
    was discarded as a **no-op**: `git rev-parse --symbolic-full-name` echoes an
    unresolvable argument back on stdout and exits 128, so `grep .` matches and
    the fallback never fires. Nothing here can distinguish its presence from its
    absence — this test pins the *behaviour* (refuse, exit 0, do not abort), which
    is what a consumer meets, and which holds either way."""
    repo = _with_batch_branch(tmp_path / "repo")
    r = _run(repo, "--merge-target", "no/such/ref", "1")
    assert r.returncode == 0, f"the run aborted instead of refusing\n{r.stderr}"
    assert not _merged(r), r.stdout
    assert "1:unmerged" in r.stdout, r.stdout

    # ...and the degenerate case the fallback exists for: target and branch are
    # the same unresolvable string, which must still compare equal.
    r2 = _run(repo, "--merge-target", "also/missing", "1")
    assert r2.returncode == 0, r2.stderr


# ── Step 4b's contract, asserted positionally and with a reversal layer ──────

_SKILL = REPO_ROOT / "core/skills/review-close/SKILL.md"

# THE REVERSAL LAYER lives in `tests/_reversal.py` (Phase 253, `Q-367`). This guard
# carried a 27-entry private list until then: four generic softeners borrowed from the
# precedent module, ten more generic ones the round that filed `Q-367` wrote bypasses
# with, and thirteen phrasings that reverse THIS step and nothing else. The generic
# ones now live in the shared list; the step-specific ones stay here as `extra=`, so
# they never redden a step they were not written about. Three entries that read as
# generic but name this step's own objects (the flag, the gate, the target) stay here
# for the same reason.
_STEP_4B_EXTRA = (
    "leave the flag off",
    "usually the gate",
    "sound target on its own",
    "optional under `pr`",
    "a fine substitute",
    "the ordinary way through",
    "infers the target from head",
    "inferred from head",
    "falls back to head",
    "--force is the remedy",
    "reach for `--force`",
    "override it and move on",
    "misreading",
    "it is actually the two shas",
    "sound after all",
    "is sound after all",
)


def _step_4b() -> str:
    text = _SKILL.read_text(encoding="utf-8")
    start = text.index("### 4b. Close Merged Batches")
    end = text.index("### 4c.", start)
    block = text[start:end]
    assert block.count("\n") > 20, "Step 4b slice looks wrong"
    return block


def test_step4b_names_the_merge_target_contract():
    """**Battery survivors `DOC-1` and `DOC-2`, closed.**

    `DOC-2`: the prescribed invocation must carry the flag. Without it, under
    `pr`, the command Step 4b tells an operator to run prints
    `merge target: UNRESOLVED` and refuses every batch Step 4a merged.

    `DOC-1`: the contract sentence must say the flag is NOT optional. Asserted on
    the clause, then re-checked against the reversal vocabulary, because a
    presence check cannot see a contradiction added beside the string it pins.
    """
    block = _step_4b()
    # POSITIONAL, and over EVERY prescribed invocation rather than one anywhere.
    # The first cut asked whether the flagged literal appeared somewhere in the
    # block — which the round satisfied by deleting the flag from the fenced
    # command and mentioning the longer form in a prose aside, and which the
    # SHIPPED tree already satisfied while Step 4b's own recovery command ran
    # flagless on the `pr` mainline.
    invocations = [
        ln.strip() for ln in block.splitlines()
        if "close_batch.sh" in ln and "<N1>" in ln
    ]
    assert invocations, "Step 4b prescribes no close_batch.sh invocation at all"
    flagless = [ln for ln in invocations if "--merge-target" not in ln]
    assert not flagless, (
        "Step 4b prescribes close_batch.sh without --merge-target at these sites, "
        "which under `pr` refuses every batch Step 4a merged:\n  "
        + "\n  ".join(flagless)
    )
    assert "**`--merge-target` is not optional under `pr`, and `--force` is not its substitute**" in block, (
        "Step 4b no longer states the contract, or states it in different words — "
        "if the rewording is deliberate, re-point this assertion in the same commit"
    )
    # Exempt spans, stripped before the scan -- the same shape
    # `assert_no_reversal` uses in tests/test_prescan_merge_gate.py. Each is a
    # phrase the step ships ON PURPOSE, and each is asserted present first, so a
    # stale exemption cannot silently widen what this guard permits.
    exempt = (
        # The pinned contract itself contains "optional under `pr`" -- negated.
        "**`--merge-target` is not optional under `pr`, and `--force` is not its substitute**",
        # A declared NEGATIVE use: the step tells the operator NOT to reach for it.
        "that is not a reason to reach for `--force`",
    )
    # Positive claims, because a vocabulary list can only ever catch the phrasings
    # someone thought of. The round's sharpest bypass carried NO flagged word: it
    # rewrote the UNRESOLVED guidance into "that is the normal state under `pr`
    # policy and no action is needed". These pin what the step must still say.
    assert "you omitted the flag under `pr` policy" in block, (
        "Step 4b no longer tells the operator what `merge target: UNRESOLVED` "
        "means — that line is the only cue the script gives, and the step routes "
        "them off it by name"
    )
    assert "supply the target" in block, (
        "Step 4b no longer names supplying the target as the remedy for "
        "UNRESOLVED; without it the operator's next move is `--force`, which "
        "disarms cherry-pick detection for every batch in the run"
    )

    # The reversal layer — shared, with this step's own phrasings as `extra=`. The
    # exempt spans are asserted present exactly once and stripped before the scan;
    # the helper carries the `count == 1` rule this guard introduced.
    assert_no_reversal(block, "review-close Step 4b", exempt=exempt, extra=_STEP_4B_EXTRA)


def test_step4b_states_both_defects_it_was_written_from():
    """The prose's load-bearing content, not just its conclusion. A Step 4b that
    keeps the flag and drops WHY leaves the next operator to rediscover that
    `--force` is the wrong reach — which is the loop that made the false accept
    reachable in the first place."""
    block = _step_4b()
    for claim, why in (
        ("accepted work that reaches nothing", "the Q-308 false accept"),
        ("refused work that landed correctly", "the ff-merge false refuse"),
        ("--ff-only", "the mechanism of the false refuse"),
        ("ref name", "identity is by ref name, not SHA"),
        ("UNRESOLVED", "the diagnostic an operator will actually see"),
    ):
        assert claim in block, f"Step 4b no longer states {why} ({claim!r})"


def test_the_roadmap_json_enum_names_the_batch_stall_states():
    """**Battery survivor `DOC-4`, closed.** `/roadmap --json` documents the
    `review_batches[].state` enum for payload consumers. A value the payload emits
    and the contract does not name is undocumented API — and the additive-not-
    substituted claim is what tells a consumer they need only a default arm."""
    text = (REPO_ROOT / "core/skills/roadmap/SKILL.md").read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if l.startswith("- **`state`**"))

    # POSITIONAL, and the first cut of this test was not — which is why the
    # battery's DOC-4 row survived a guard written specifically to kill it. A
    # whole-line `"`parked`" in line` is satisfied by the *explanatory sentence*
    # further along the SAME line ("`parked` and `awaiting approval` are new…"),
    # so deleting both values from the enum itself left the assertion green.
    # Phase 247's lesson — a file-level `in <text>` check is satisfied by the
    # wrong occurrence — reproduced inside a single line.
    enum_span = line[line.index("one of "):line.index(". **Every one of these")]
    listed = {v.strip() for v in enum_span.replace("one of ", "").split("`") if v.strip(" ,")}
    for state in (ss._PARKED_STATE, ss._AWAITING_STATE):
        assert state in listed, (
            f"/roadmap's documented state ENUM omits {state!r}, which the payload "
            f"emits. Enum values found: {sorted(listed)}"
        )
    assert "ADDED to this enum, not" in line, (
        "the enum no longer records that the two states were added rather than "
        "substituted — the fact a --json consumer needs in order to size the change"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Round findings (execute lens): the identity test compared SPELLINGS
# ─────────────────────────────────────────────────────────────────────────────

def _alias_repo(tmp_path):
    """A batch branch merged NOWHERE, with every alias for its own tip on hand."""
    repo = _with_batch_branch(tmp_path / "repo")
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True,
                   capture_output=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "main")
    _git(repo, "push", "-q", "origin", "feat/one")
    _git(repo, "tag", "mytag", "feat/one")
    return repo


@pytest.mark.parametrize("alias", ["sha", "mytag", "origin/feat/one"])
def test_an_alias_for_the_branchs_own_tip_is_refused(tmp_path, alias):
    """**Round finding (execute lens), HIGH — four false accepts on a branch merged
    nowhere.**

    `_ref_id` compares ref SPELLINGS while `merge-base --is-ancestor` compares
    resolved COMMITS, and `--is-ancestor X X` is trivially true. So any name for
    the batch branch's own tip that is not its `refs/heads/…` spelling walked
    straight through the identity test.

    `origin/feat/one` is the one that mattered: it is the ref a PR actually
    tracks, and Step 4b states that under PR-reuse the target and branch "resolve
    to the same ref" so reuse "still needs `--force`". Spelling the same branch
    through `refs/remotes/` defeated that and green-lit a close with, in the
    skill's own words, no ancestry evidence that the work landed. `HEAD` while
    DETACHED at the tip is Phase 233's own round finding returning through a
    namespace its fix did not consider — attached HEAD refused, detached accepted,
    and nothing documented the asymmetry.

    Closed by requiring the target to resolve under `refs/heads/`.
    """
    repo = _alias_repo(tmp_path)
    if alias == "sha":
        target = _git_sha(repo, "feat/one")
    elif alias == "HEAD-detached":
        _git(repo, "checkout", "-q", "--detach", "feat/one")
        target = "HEAD"
    else:
        target = alias

    r = _run(repo, "--merge-target", target, "1")

    assert not _merged(r), (
        f"--merge-target {target!r} named the batch branch's own tip under another "
        f"spelling and was accepted\n{r.stdout}"
    )
    assert "1:unmerged" in r.stdout, r.stdout


@pytest.mark.parametrize("target", ["merge/rc", "refs/heads/merge/rc"])
def test_a_local_branch_target_is_still_accepted(tmp_path, target):
    """The non-vacuity control for the refusal above. Every documented invocation
    names a local branch — `main` under `direct`, the integration branch under
    `pr`, the approved branch under reuse — so the narrowing must refuse nothing an
    operator is actually told to do, including via an attached `HEAD`."""
    repo = _ff_cycle(tmp_path / "repo", ["feat/one"])
    r = _run(repo, "--merge-target", target, "1")
    assert _merged(r), f"target {target!r} was refused\n{r.stdout}"


@pytest.mark.parametrize("form", ["space", "equals"])
def test_an_empty_merge_target_value_exits_1(tmp_path, form):
    """**Round finding (execute lens).** `--merge-target "$MERGE_TARGET"` with a
    variable that did not survive its fenced block is exactly the hazard
    `WORKFLOW.md` § 8.2a warns about at four sites. It used to fall back to the
    policy default **and** print a provenance line attributing that fallback to a
    `§ Merge policy` section the operator never wrote — the silent-degradation
    shape, wearing a config file's name."""
    repo = _with_batch_branch(tmp_path / "repo")
    args = ["--merge-target", ""] if form == "space" else ["--merge-target="]
    r = _run(repo, *args, "1")
    assert r.returncode == 1, r.stdout
    assert "empty value" in r.stderr, r.stderr


def test_the_gate_runs_on_the_dry_run_path_too(tmp_path):
    """**Round finding (execute lens): a guard hole, not a live defect.** An
    independent mutation added `! $DRY_RUN &&` to the branch check and every guard
    stayed green — `--dry-run` appeared nowhere in this module, so the preview path
    was unexercised. A preview that reports `✓ verified merged` over a branch the
    real run would refuse is a preview that teaches the wrong thing."""
    repo = _with_batch_branch(tmp_path / "repo")
    r = _run(repo, "--dry-run", "1")
    assert not _merged(r), (
        f"--dry-run reported a verdict the real run does not give\n{r.stdout}"
    )
    assert "1:unmerged" in r.stdout, r.stdout


def test_the_target_survives_every_batch_in_a_multi_batch_run(tmp_path):
    """**Round finding (execute lens): the shape Step 4b prescribes was unguarded.**
    Step 4b's invocation is `--merge-target <t> <N1> <N2> <N3>`, and neither
    close_batch guard module carried a single multi-operand invocation. An
    independent mutation that cleared `MERGE_TARGET_REF` after the first accepted
    batch left 84 tests green while refusing every batch after the first."""
    repo = _ff_cycle(tmp_path / "repo", ["feat/one", "feat/two"])
    r = _run(repo, "--merge-target", "merge/rc", "1", "2")
    assert r.stdout.count("verified merged") == 2, (
        f"the stated target did not survive to the second batch\n{r.stdout}"
    )
    assert "unmerged" not in r.stdout.replace("an unmerged branch", ""), r.stdout


@pytest.mark.parametrize("claude_md,expected,why", [
    ("# P\r\n\r\n## Merge policy\r\n\r\npr\r\n", "UNRESOLVED",
     "a CRLF-authored CLAUDE.md failed the end-anchored heading match and read "
     "`direct` for every setting"),
    ("# P\n\n~~~markdown\n## Merge policy\n\npr\n~~~\n", "'main'",
     "a tilde-fenced illustration was read as the setting"),
    ("# P\n\n  ```markdown\n  ## Merge policy\n\n  pr\n  ```\n", "'main'",
     "an indented fence was read as the setting"),
])
def test_the_policy_reader_handles_the_shapes_the_round_found(tmp_path, claude_md, expected, why):
    """**Round findings (execute lens).** The fence skip claimed more than it did
    and the heading match was byte-fragile. These change no VERDICT — the `main`
    arm runs either way — but the provenance line is the operator's only cue to
    pass `--merge-target`, and Step 4b routes them off it by name."""
    repo = _with_batch_branch(tmp_path / "repo", policy=None)
    (repo / "CLAUDE.md").write_text(claude_md)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "policy")
    r = _run(repo, "1")
    assert f"merge target: {expected}" in r.stdout, f"{why}\n{r.stdout}"


@pytest.mark.parametrize("value", ["HEAD", "@"])
def test_head_is_refused_as_a_stated_target(tmp_path, value):
    """**Round finding (guards lens), HIGH — `Q-308` reinstated by the flag meant
    to close it.**

    This script's thesis is that the merge target is STATED and `HEAD` is never
    read for it. `--merge-target HEAD` read it: standing on a branch cut FROM the
    batch branch, the gate printed `✓ verified merged` again — the filed defect,
    restored, through the mechanism that fixed it.

    The refusal message invites the construction ("pass `--merge-target <ref>` to
    verify against **the branch this close is landing in**" — and from a checkout
    `HEAD` *is* that branch), so the refusal names the alternative rather than
    just saying no.

    `test_standing_on_the_unmerged_batch_branch_is_still_refused` parametrised
    `HEAD` and created the appearance of coverage: it only ever passed `HEAD`
    while standing ON the batch branch, where ref identity blocks it anyway.
    """
    repo = _with_batch_branch(tmp_path / "repo")
    _git(repo, "checkout", "-q", "-b", "scratch/exp", "feat/one")
    (repo / "s.txt").write_text("s\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "scratch")

    r = _run(repo, "--merge-target", value, "1")

    assert r.returncode == 1, (
        f"--merge-target {value} was accepted as a stated target\n{r.stdout}"
    )
    assert "does not accept 'HEAD'" in r.stderr, r.stderr
    assert "`Pending`" in (repo / "review_tasks.md").read_text()


@pytest.mark.parametrize("form", ["space", "equals"])
@pytest.mark.parametrize("swallowed", ["--dry-run", "--force", "--allow-open-fence"])
def test_a_flag_is_not_taken_as_the_target_value(tmp_path, form, swallowed):
    """**Round finding (guards lens), HIGH — a preview became a real close.**

    The parse loop is `for arg in "$@"` with a one-iteration carry, and the carry
    took the next argument WHATEVER IT WAS. `--merge-target --dry-run 1` set the
    target to `--dry-run` and **silently dropped the dry run**, so a preview
    flipped headers and committed. Every other flag in this script is order-free,
    so nothing warned that this one is not.

    The comment beside the parser reasoned only about the *trailing* case, and the
    test written for it guarded only that case — which is why this stood.
    """
    repo = _with_batch_branch(tmp_path / "repo")
    args = (["--merge-target", swallowed] if form == "space"
            else [f"--merge-target={swallowed}"])
    r = _run(repo, *args, "1")
    assert r.returncode == 1, (
        f"{swallowed} was consumed as the target value and the run continued "
        f"without it\n{r.stdout}"
    )
    assert "which is a flag, not a ref" in r.stderr, r.stderr


def test_a_valid_distinct_target_that_does_not_contain_the_branch_is_refused(tmp_path):
    """**Battery survivor `L3b`, closed — the population hole that let the whole
    ancestry check be deleted.**

    The guards lens replaced the ancestry test with *"accept whenever
    `--merge-target` names a ref that resolves"* — a line-count-neutral edit — and
    **the entire suite stayed green**. Any batch would have closed as `Merged` on
    the dominant `/review-close` path with no containment check at all.

    The cause was enumerable: of every `--merge-target` invocation in the suite,
    none paired a **valid, distinct, resolvable** target with a branch that is
    genuinely *not* merged into it. The targets were the branch itself (caught by
    the identity arm), unresolvable (caught by the fallback), or ones the branch
    really was contained in. `test_an_operand_overrides_the_policy` came closest
    and asserts only the printed provenance line, never a verdict.

    So the ancestry call itself had no test. This is that test.
    """
    repo = _with_batch_branch(tmp_path / "repo")
    # A real, resolvable, local branch that is NOT the batch branch and does NOT
    # contain it: cut from main, with a commit of its own.
    _git(repo, "checkout", "-q", "-b", "merge/elsewhere", "main")
    (repo / "other.txt").write_text("other\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "unrelated")

    # Preconditions asserted, so this cannot pass for the wrong reason.
    assert _git_sha(repo, "merge/elsewhere") != _git_sha(repo, "feat/one")
    assert subprocess.run(
        ["git", "merge-base", "--is-ancestor", "feat/one", "merge/elsewhere"],
        cwd=str(repo), capture_output=True).returncode != 0, (
        "fixture is wrong: the target DOES contain the branch"
    )
    assert subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "merge/elsewhere"],
        cwd=str(repo), capture_output=True).returncode == 0, (
        "fixture is wrong: the target does not resolve, so the fallback arm "
        "would refuse it and the ancestry call would still be untested"
    )

    r = _run(repo, "--merge-target", "merge/elsewhere", "1")

    assert not _merged(r), (
        "a batch branch absent from a valid, distinct merge target was accepted — "
        f"the ancestry check is not running.\n{r.stdout}"
    )
    assert "1:unmerged" in r.stdout, r.stdout
    assert "`Pending`" in (repo / "review_tasks.md").read_text()


def test_workflow_md_states_the_merge_target_contract():
    """**Round finding (guards lens), B6 — `WORKFLOW.md` was unguarded on this
    contract entirely.**

    Six independent mutations survived there: the § 8.4 signature dropping
    `[--merge-target <ref>]`; the never-inferred-from-`HEAD` sentence reversed,
    replaced with "falls back to `HEAD`", or deleted outright; and § 2.8 step 6's
    command dropping the flag or changing it to `--merge-target HEAD`. The two
    anchors re-pointed earlier in this phase were deliberately loosened to "script
    name plus `<N1>`", which is exactly what let the flag vanish from the command
    they anchor on.
    """
    text = (REPO_ROOT / "core/companion/docs/WORKFLOW.md").read_text(encoding="utf-8")

    # EVERY close_batch.sh row, and the SIGNATURE cell of each: the description cell
    # beside a signature also says `--merge-target <ref>`, so `in row` was satisfied
    # with the flag gone from the signature (the reconstructed reviewer row F1 walked
    # through it, Phase 253), and a first-match `next()` let a flagless second row
    # stand (round: C-S02). A row prescribing the script without the flag is the
    # `Q-308` shape whatever else it documents, so `--dry-run` variants carry it too.
    cb_rows = [ln for ln in text.splitlines() if ln.startswith("| `close_batch.sh")]
    assert cb_rows, "§ 8.4 has no close_batch.sh row"
    for row in cb_rows:
        # The backticked span, not the first `|`-delimited cell: a signature such as
        # `[--merge-target <ref>|HEAD]` carries a raw pipe, and a cell split hands
        # `HEAD` to the next cell where nothing looks (round: C-S03 survived the
        # first cut for exactly that reason).
        m = re.match(r"\|\s*`([^`]*)`", row)
        assert m, f"§ 8.4 close_batch.sh row has no backticked signature: {row[:60]!r}"
        signature = m.group(1)
        assert "--merge-target" in signature, (
            f"a § 8.4 close_batch.sh signature omits --merge-target: {signature.strip()!r}"
        )
        # `[--merge-target <ref>|HEAD]` documents the one value the script refuses
        # (round: C-S03).
        assert "HEAD" not in signature, (
            f"a § 8.4 close_batch.sh signature offers HEAD as a target: {signature.strip()!r}"
        )
    row = next(r for r in cb_rows if "--merge-target <ref>" in r or "--merge-target=<ref>" in r)
    assert "never inferred from `HEAD`" in row, (
        "§ 8.4 no longer states that the target is never inferred from HEAD — "
        "the sentence the whole Q-308 repair rests on"
    )
    step6 = next(ln for ln in text.splitlines()
                 if "close_batch.sh" in ln and "<N1>" in ln)
    # The same banned phrasings, over BOTH sites: an aside in § 2.8 licensing the
    # fallback is the same reversal as one in § 8.4 (round: C-S06 — its own wording,
    # "derives the target from HEAD", is outside this list on purpose; the layer is a
    # blocklist of measured phrasings, not a closure).
    for banned in ("falls back to `HEAD`", "inferred from `HEAD` when"):
        assert banned not in row, f"§ 8.4's row now says {banned!r}"
        assert banned not in step6, f"§ 2.8 step 6 now says {banned!r}"
    assert "--merge-target" in step6, (
        "§ 2.8 step 6's command no longer passes --merge-target; under `pr` it "
        "refuses every batch step 5 merged"
    )
    assert "--merge-target HEAD" not in step6, (
        "§ 2.8 step 6 prescribes --merge-target HEAD, which hands the question "
        "back to the checkout and reinstates Q-308"
    )


def test_the_policy_is_read_from_the_repo_root_not_the_cwd(tmp_path):
    """**Round finding (guards lens), B9/A18 — a guard hole, not a live defect.**
    The shipped code reads `${REPO_ROOT}/CLAUDE.md` and is correct; nothing
    asserted it, so a mutation making the read CWD-relative survived. A `pr`
    consumer running from a subdirectory would then print
    `§ Merge policy: direct` — a false provenance line on the one output added to
    make refusals actionable."""
    repo = _with_batch_branch(tmp_path / "repo", policy="pr")
    sub = repo / "sub" / "dir"
    sub.mkdir(parents=True)
    r = subprocess.run(["bash", str(SCRIPT), "--dry-run", "1"],
                       cwd=str(sub), capture_output=True, text=True)
    assert "merge target: UNRESOLVED (§ Merge policy: pr)" in r.stdout, (
        "the policy was resolved against the CWD rather than the repo root\n"
        + r.stdout
    )


def test_the_remote_arm_refusal_names_the_flag_too(tmp_path):
    """Phase 250 round 2 — the sibling arm the round-1 fix did not reach.

    `close_batch.sh` refuses an unmerged branch in two places: a local arm and,
    when no local branch exists, a **remote** arm eighteen lines below it. The
    round-1 fix landed on the local one, and the tightened guard beside it could
    not see the gap because `_with_batch_branch` only ever builds a local branch.

    The remote arm is the one a `pr` consumer reaches routinely: a fresh clone, a
    pruned local branch, a worktree that never had it. Fixing one of two sibling
    arms in the same function is the shape Phase 218 recorded as "the same
    blindness 300 lines away in the same commit".
    """
    repo = _with_batch_branch(tmp_path / "repo", policy="pr")
    # A bare origin holding feat/one, merged into an integration branch but not
    # into main — then drop the local branch, so only the remote arm can fire.
    origin = tmp_path / "origin.git"
    _git(repo, "checkout", "-q", "-b", "merge/rc", "main")
    _git(repo, "merge", "-q", "--no-ff", "feat/one", "-m", "merge")
    _git(repo, "checkout", "-q", "main")
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-q", "origin", "main", "feat/one", "merge/rc")
    _git(repo, "branch", "-D", "feat/one")

    r = _run(repo, "1")
    assert "Remote branch" in r.stdout, (
        "the remote arm never fired; this fixture no longer reaches it\n" + r.stdout
    )
    assert not _merged(r), r.stdout
    block = _refusal_block(r.stdout)
    assert "--merge-target <ref>" in block, (
        "the REMOTE refusal does not name its own remedy\n" + r.stdout
    )
    assert re.search(r"--force is not the fix", block, re.I), (
        "the REMOTE refusal still offers --force, which on this shape accepts the "
        "branch unverified and disarms cherry-pick detection for the whole run\n"
        + r.stdout
    )
