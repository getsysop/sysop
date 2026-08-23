"""Phase 218 (internal tracker `Q-238`) — `/review-close` Step 3b's workspace discovery.

`claim_task.sh --clone` produces a **full clone**, which `git worktree list` never lists.
Step 3b's pending-doc collect used to be nested under *"if a worktree exists"*, so a clone
workspace fell through to *"the branch is already free for checkout"*: the doc was never
collected, Step 4c never consolidated it, `roadmap_ids` never flipped to `done`, and the
body was never archived — silently.

These tests **extract and run the bash Step 3b prescribes**, against real git repositories
with real clones and real worktrees. Reading the prose cannot tell you whether the block
resolves a clone; running it can, and three of the last four phases' defects were found
exactly this way.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"


def _extract(start: str, end: str, *, dedent: int = 0) -> str:
    text = SKILL.read_text(encoding="utf-8")
    assert text.count(start) == 1, f"anchor is not unique in SKILL.md: {start!r}"
    i = text.index(start)
    j = text.index(end, i)
    body = text[i:j]
    if dedent:
        body = "\n".join(l[dedent:] if l.startswith(" " * dedent) else l
                         for l in body.splitlines())
    return body


def _extract_discovery() -> str:
    """Step 3b step 0's workspace-discovery heredoc, by its unique three-arg opener."""
    text = SKILL.read_text(encoding="utf-8")
    opener = ('python3 - "<branch name>" "$(git worktree list --porcelain)" '
              '"${WORKTREE_PREFIX:-$(basename "$(git rev-parse --show-toplevel)")}" <<\'PY\'\n')
    assert text.count(opener) == 1, "Step 3b discovery heredoc opener is not unique"
    i = text.index(opener) + len(opener)
    j = text.index("\nPY\n", i)
    return text[i:j]


DISCOVER_PY = _extract_discovery()

def _extract_collect() -> str:
    """The FIRST `python3 - "<worktree-path>" "<branch name>"` heredoc in Step 3b is the
    collect; the second is the ISSUE-0016 rollback. Anchor on order, and assert the body
    is the collect by a marker only the collect prints — an anchor that silently picks up
    the rollback would test the wrong mechanism and still be green."""
    text = SKILL.read_text(encoding="utf-8")
    opener = 'python3 - "<worktree-path>" "<branch name>" <<\'PY\'\n'
    assert text.count(opener) == 2, f"Step 3b heredoc count changed: {text.count(opener)}"
    i = text.index(opener) + len(opener)
    j = text.index("\n      PY\n", i)
    body = "\n".join(l[6:] if l.startswith(" " * 6) else l
                     for l in text[i:j].splitlines())
    assert "PENDING-DOC COLLECTED" in body, "extracted the rollback, not the collect"
    assert "ROLLED BACK" not in body, "extracted the rollback, not the collect"
    return body


COLLECT_PY = _extract_collect()


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)} failed:\n{r.stderr}"
    return r.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A main checkout with an `origin` remote, mirroring the shape claim_task.sh needs."""
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    main = tmp_path / "proj"
    subprocess.run(["git", "clone", "-q", str(bare), str(main)], check=True)
    _git(main, "config", "user.email", "t@t")
    _git(main, "config", "user.name", "T")
    (main / "README.md").write_text("hi\n", encoding="utf-8")
    (main / "sysop/runtime/pending-docs").mkdir(parents=True)
    _git(main, "add", "-A")
    _git(main, "commit", "-qm", "init")
    _git(main, "push", "-q", "origin", "HEAD:refs/heads/main")
    return main


def _discover(repo: Path, branch: str, *, prefix: str | None = None) -> tuple[str, str]:
    """Run the block exactly as Step 3b prescribes: branch, worktree listing, prefix."""
    listing = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=str(repo),
                             capture_output=True, text=True, check=True).stdout
    r = subprocess.run([sys.executable, "-c", DISCOVER_PY, branch, listing,
                        prefix if prefix is not None else repo.name],
                       cwd=str(repo), text=True, capture_output=True, timeout=30)
    assert r.returncode == 0, f"discovery block errored ({r.returncode}):\n{r.stderr}"
    line = r.stdout.strip().splitlines()[-1]
    ws, _, shape = line.partition(" shape=")
    return ws[len("workspace="):], shape


def _discover_raw(repo: Path, branch: str):
    listing = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=str(repo),
                             capture_output=True, text=True, check=True).stdout
    return subprocess.run([sys.executable, "-c", DISCOVER_PY, branch, listing, repo.name],
                          cwd=str(repo), text=True, capture_output=True, timeout=30)


def _make_clone(repo: Path, branch: str, dirname: str) -> Path:
    """A `claim_task.sh --clone` workspace: a full clone checked out on `branch`."""
    _git(repo, "branch", "-f", branch, "HEAD")
    _git(repo, "push", "-q", "origin", branch)
    dest = repo.parent / dirname
    subprocess.run(["git", "clone", "-q", str(repo.parent / "remote.git"), str(dest)],
                   check=True)
    _git(dest, "checkout", "-q", branch)
    return dest


def _write_lock(repo: Path, tid: str, *, branch: str, mode: str, workspace: Path) -> None:
    d = repo / "sysop/runtime/locks"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{tid}.lock").write_text(
        f"task_id: {tid}\nstatus: in_progress\nagent: a\nbranch: {branch}\n"
        f"mode: {mode}\nworkspace: {workspace}\n", encoding="utf-8")


# ── the four arms, each asserted by shape as well as by path ──

def test_arm_i_resolves_a_worktree(repo: Path):
    wt = repo.parent / "proj-wt"
    _git(repo, "worktree", "add", "-q", str(wt), "-b", "feat/wt")
    ws, shape = _discover(repo, "feat/wt")
    assert shape == "worktree", (ws, shape)
    assert Path(ws).resolve() == wt.resolve()


def test_arm_ii_resolves_a_clone_from_its_lock(repo: Path):
    """The defect: `git worktree list` does not list this, so arm (i) finds nothing."""
    clone = _make_clone(repo, "feat/z", "proj-feat-z")
    _write_lock(repo, "FEAT-Z", branch="feat/z", mode="clone", workspace=clone)
    ws, shape = _discover(repo, "feat/z")
    assert shape == "clone", (ws, shape)
    assert Path(ws).resolve() == clone.resolve()


def test_arm_iii_resolves_a_clone_with_no_lock_at_all(repo: Path):
    """`claim_task.sh` defaults to USE_LOCK=false, so `--clone` without `--lock` leaves
    no lock to read. A lock-only fix would be inert on exactly that invocation."""
    clone = _make_clone(repo, "feat/z", "proj-feat-z")
    assert not (repo / "sysop/runtime/locks").exists()
    ws, shape = _discover(repo, "feat/z")
    assert shape == "discovered", (ws, shape)
    assert Path(ws).resolve() == clone.resolve()


def test_arm_iii_is_verified_not_guessed(repo: Path):
    """A sibling directory matching the naming convention but sitting on a DIFFERENT
    branch is not this branch's workspace. The arm checks HEAD; it does not pattern-match
    a path and hope."""
    _make_clone(repo, "feat/other", "proj-feat-other")
    _git(repo, "branch", "feat/z")
    ws, shape = _discover(repo, "feat/z")
    assert (ws, shape) == ("<none>", "<none>"), (ws, shape)


def test_a_sibling_that_is_not_a_git_checkout_is_not_a_workspace(repo: Path):
    decoy = repo.parent / "proj-feat-z"
    decoy.mkdir()
    (decoy / "sysop/runtime/pending-docs").mkdir(parents=True)
    (decoy / "sysop/runtime/pending-docs/x.md").write_text("---\nbranch: feat/z\n---\n",
                                                           encoding="utf-8")
    _git(repo, "branch", "feat/z")
    ws, shape = _discover(repo, "feat/z")
    assert (ws, shape) == ("<none>", "<none>"), (ws, shape)


def test_the_main_checkout_is_refused_as_a_workspace(repo: Path):
    """`--branch` mode records WORKSPACE_PATH=$REPO_ROOT. Collecting main's pending-docs
    onto themselves is a self-copy; the docs are already where Step 4c looks."""
    _git(repo, "branch", "feat/b")
    _write_lock(repo, "FEAT-B", branch="feat/b", mode="branch", workspace=repo)
    ws, shape = _discover(repo, "feat/b")
    assert (ws, shape) == ("<none>", "main-checkout"), (ws, shape)


def test_main_checkout_refusal_survives_a_non_canonical_recorded_path(repo: Path):
    """`claim_task.sh` writes `workspace:` unresolved (it can contain `/../`), and on
    macOS the repo root reaches through /private. Comparing strings would let the
    self-copy through; the block compares `pwd -P`."""
    _git(repo, "branch", "feat/b")
    _write_lock(repo, "FEAT-B", branch="feat/b", mode="branch",
                workspace=Path(f"{repo}/../{repo.name}"))
    ws, shape = _discover(repo, "feat/b")
    assert (ws, shape) == ("<none>", "main-checkout"), (ws, shape)


def test_no_workspace_reports_none_rather_than_a_stale_value(repo: Path):
    _git(repo, "branch", "feat/nothing")
    assert _discover(repo, "feat/nothing") == ("<none>", "<none>")


def test_a_lock_for_another_branch_does_not_claim_this_branch(repo: Path):
    clone = _make_clone(repo, "feat/z", "proj-feat-z")
    _write_lock(repo, "FEAT-Q", branch="feat/q", mode="clone", workspace=clone)
    _git(repo, "branch", "feat/q2")
    ws, shape = _discover(repo, "feat/q2")
    assert (ws, shape) == ("<none>", "<none>"), (ws, shape)


def test_worktree_wins_over_a_stale_lock_for_the_same_branch(repo: Path):
    """Arm order is load-bearing: a lock left behind from an earlier claim must not
    redirect the collect away from the live worktree."""
    wt = repo.parent / "proj-wt"
    _git(repo, "worktree", "add", "-q", str(wt), "-b", "feat/wt")
    _write_lock(repo, "FEAT-W", branch="feat/wt", mode="clone",
                workspace=repo.parent / "gone")
    ws, shape = _discover(repo, "feat/wt")
    assert shape == "worktree", (ws, shape)
    assert Path(ws).resolve() == wt.resolve()


# ── and the whole point: the collect actually runs against a clone ──

def test_the_collect_brings_a_clone_authored_pending_doc_into_main(repo: Path):
    """End to end on the reported shape: discovery finds the clone, and the UNCHANGED
    collect heredoc — the one Step 3b already prescribes — copies its doc into main."""
    clone = _make_clone(repo, "feat/z", "proj-feat-z")
    _write_lock(repo, "FEAT-Z", branch="feat/z", mode="clone", workspace=clone)
    pd = clone / "sysop/runtime/pending-docs"
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "feat-z.md").write_text("---\nbranch: feat/z\nroadmap_ids: [FEAT-Z]\n---\n# doc\n",
                                  encoding="utf-8")

    ws, shape = _discover(repo, "feat/z")
    assert shape == "clone"

    r = subprocess.run([sys.executable, "-c", COLLECT_PY, ws, "feat/z"],
                       cwd=str(repo), capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert "PENDING-DOC COLLECTED: feat-z.md" in r.stdout, r.stdout
    assert (repo / "sysop/runtime/pending-docs/feat-z.md").is_file(), (
        "the clone-authored doc did not reach main — Q-238 is back"
    )


def test_the_collect_still_refuses_a_foreign_branch_doc_from_a_clone(repo: Path):
    """The provenance check is not weakened by the new workspace shape."""
    clone = _make_clone(repo, "feat/z", "proj-feat-z")
    pd = clone / "sysop/runtime/pending-docs"
    pd.mkdir(parents=True, exist_ok=True)
    (pd / "other.md").write_text("---\nbranch: feat/somebody-else\n---\n# doc\n",
                                 encoding="utf-8")
    r = subprocess.run([sys.executable, "-c", COLLECT_PY, str(clone), "feat/z"],
                       cwd=str(repo), capture_output=True, text=True, timeout=30)
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
    assert "refusing; nothing collected" in r.stdout, r.stdout
    assert not (repo / "sysop/runtime/pending-docs/other.md").exists(), r.stdout


# ── the caller, not just the block ──

def _flat(text: str) -> str:
    import re as _re
    return _re.sub(r"\s+", " ", text)


def test_step_3b_states_the_collect_is_not_conditional_on_a_worktree():
    """Guarding the extracted block only proves the block works. What regressed the
    class once already is the CALLER: the collect nested under `if a worktree exists`.
    If that nesting comes back, the block below can be perfect and never run.

    Presence alone is not enough, and the round proved it: keeping all three of the
    original assertions satisfied while APPENDING `"In practice, only run item (a) when
    SHAPE is worktree"` left the whole module green. So this also refuses the
    re-conditioning phrasings, not just the absence of the unconditional one."""
    body = SKILL.read_text(encoding="utf-8")
    flat = _flat(body)
    assert "**The remove is worktree-only; the collect is not.**" in flat
    assert "Collect this branch's pending-docs from the workspace step 0 resolved" in flat
    assert "If no worktree exists, the branch is already free for checkout" not in flat, (
        "the old worktree-conditional item 3 is back — a clone falls through it again"
    )
    for reconditioning in (
        "only run item (a) when", "only when `SHAPE` is `worktree`",
        "only run the collect when", "collect only when", "skip the collect",
        "are not at risk", "collected on a later cycle",
    ):
        assert reconditioning not in flat, (
            f"the collect has been re-conditioned on the workspace shape: {reconditioning!r}"
        )


def test_the_shape_gate_precedes_the_command_it_gates():
    """A rule an operator reaches AFTER the command it governs is not a gate.

    The round executed the step in written order on a clone: collect (a) succeeded,
    `git worktree remove` fatal'd, sub-item (b)'s own refusal prose said to roll the
    doc back, and the operator did — collecting the doc and then deleting it, with the
    branch left unmerged. That is worse than the bug this step fixes, and every
    presence-only assertion above stayed green through it."""
    body = SKILL.read_text(encoding="utf-8")
    gate = body.index("**ONLY WHEN `SHAPE=worktree`**")
    remove_cmd = body.index("git worktree remove <worktree-path>")
    collect = body.index("Collect this branch's pending-docs from the workspace step 0 resolved")
    step0 = body.index("**0. Locate the branch's workspace**")
    assert step0 < collect < gate < remove_cmd, (
        f"Step 3b's order is wrong: step0={step0} collect={collect} gate={gate} "
        f"remove={remove_cmd} — the shape gate must sit between the collect and the "
        f"removal command, not after it"
    )


def test_step_3b_forbids_running_worktree_remove_on_a_non_worktree():
    body = SKILL.read_text(encoding="utf-8")
    flat = _flat(body)
    assert "**Do not run `git worktree remove` on a shape that is not a worktree**" in flat
    assert "ISSUE-0016" in flat
    # ...and says, at the gate itself, that its failure is not the ISSUE-0016 refusal —
    # because that is the misreading which cost the doc.
    assert "carries **no** claim about untracked files" in flat
    assert "must never trigger the rollback below" in flat


def test_every_shape_step_0_can_emit_is_dispositioned():
    """The first disposition list named `SHAPE=branch`, which step 0 cannot emit, and
    omitted `recorded` and `unresolvable`, which it can. Derive the emitted set from the
    block itself rather than trusting the list."""
    import re as _re
    emitted = set(_re.findall(r'shape = ["\']([a-z-]+)["\']', DISCOVER_PY))
    emitted |= set(_re.findall(r'= [A-Za-z_.()\[\]"\' ]+, ["\']([a-z-]+)["\']', DISCOVER_PY))
    emitted |= {"worktree", "clone", "recorded", "discovered", "main-checkout", "unresolvable"} & emitted
    assert {"worktree", "discovered", "main-checkout", "unresolvable"} <= emitted, emitted
    body = SKILL.read_text(encoding="utf-8")
    disposition = body[body.index("**Step 0 emits exactly five shapes**"):
                       body.index("For **SKIP'd** branches")]
    for shape in sorted(emitted | {"clone", "recorded"}):
        assert f"`{shape}`" in disposition, (
            f"step 0 can emit shape={shape!r} and the disposition list does not name it"
        )
    assert "`SHAPE=branch`" not in disposition.replace(
        "named `SHAPE=branch`, which step 0 can *never* emit", ""), (
        "the disposition list names a shape step 0 cannot produce"
    )


def test_an_unsubstituted_branch_placeholder_hard_fails(repo: Path):
    """A block that resolves no workspace is indistinguishable from a branch that
    legitimately has none. Silence is the failure class this whole step is being fixed
    for, so the placeholder must exit non-zero rather than print `<none>` — the same
    discipline Step 3c's APPROVED_BRANCHES guard already applies."""
    r = _discover_raw(repo, "<branch name>")
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
    assert "substitute the branch name" in r.stderr
    assert "workspace=" not in r.stdout


def test_an_empty_branch_argument_hard_fails_too(repo: Path):
    r = _discover_raw(repo, "   ")
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)


def test_discovery_spawns_no_subprocess_of_its_own():
    """The listing is passed IN and HEAD is read from the object store, so the block is
    a single authorizable `python3 -` invocation. A `subprocess`/`os.system` here would
    reintroduce the unauthorizable shape the bash `for` loops had."""
    for forbidden in ("subprocess", "os.system", "os.popen", "shutil.which"):
        assert forbidden not in DISCOVER_PY, (
            f"{forbidden!r} reappeared in Step 3b's discovery block"
        )


def test_worktree_arm_reads_the_listing_it_is_given_not_the_ambient_repo(repo: Path):
    """The listing is an argument, so a caller that passes a stale or empty one gets the
    answer for THAT listing. This pins the contract rather than an incidental agreement
    between argv and cwd."""
    wt = repo.parent / "proj-wt"
    _git(repo, "worktree", "add", "-q", str(wt), "-b", "feat/wt")
    r = subprocess.run([sys.executable, "-c", DISCOVER_PY, "feat/wt", "", repo.name],
                       cwd=str(repo), text=True, capture_output=True, timeout=30)
    assert r.returncode == 0, r.stderr
    # Arm (i) reads argv, so an empty listing takes it out — it does NOT fall back to the
    # ambient repo (that would report shape=worktree). Arm (iii) then finds the same
    # directory by verified HEAD, which is the safety net doing its job.
    assert "shape=discovered" in r.stdout, r.stdout
    assert "shape=worktree" not in r.stdout, (
        "the worktree arm read the ambient repo instead of the listing it was given"
    )


# ── round findings: the discovery block's neighbourhood, not just its arms ──

def test_a_stale_lock_does_not_shadow_a_live_workspace(repo: Path):
    """Arm (ii) was unverified and ordered AHEAD of the verified arm (iii), so a lock
    pointing at a deleted directory won — and the collect then aborted on a path that
    no longer exists, with nothing naming the stale lock as the cause. An unverified arm
    must not outrank a verified one."""
    clone = _make_clone(repo, "feat/z", "proj-feat-z")
    _write_lock(repo, "FEAT-Z", branch="feat/z", mode="clone",
                workspace=repo.parent / "proj-feat-z-DELETED")
    ws, shape = _discover(repo, "feat/z")
    assert shape == "discovered", (ws, shape)
    assert Path(ws).resolve() == clone.resolve()


def test_a_lock_that_is_a_directory_does_not_kill_the_close(repo: Path):
    """Step 3c has this guard; the discovery block's fixtures only ever wrote well-formed
    locks, so its absence here was invisible."""
    clone = _make_clone(repo, "feat/z", "proj-feat-z")
    (repo / "sysop/runtime/locks").mkdir(parents=True)
    (repo / "sysop/runtime/locks/BAD.lock").mkdir()
    ws, shape = _discover(repo, "feat/z")
    assert shape == "discovered", (ws, shape)
    assert Path(ws).resolve() == clone.resolve()


def test_a_lock_missing_its_workspace_field_does_not_crash(repo: Path):
    clone = _make_clone(repo, "feat/z", "proj-feat-z")
    d = repo / "sysop/runtime/locks"
    d.mkdir(parents=True)
    (d / "FEAT-Z.lock").write_text("task_id: FEAT-Z\nbranch: feat/z\nmode: clone\n",
                                   encoding="utf-8")
    ws, shape = _discover(repo, "feat/z")
    assert shape == "discovered", (ws, shape)


def test_a_prefix_related_branch_does_not_claim_this_branchs_worktree(repo: Path):
    """Loosening the worktree match from `==` to `startswith` survived every earlier
    fixture, because none had two prefix-related branches in the listing. Step 3b would
    then collect from — and `git worktree remove` — the wrong branch's worktree."""
    a = repo.parent / "proj-a"
    b = repo.parent / "proj-b"
    _git(repo, "worktree", "add", "-q", str(a), "-b", "feat/x")
    _git(repo, "worktree", "add", "-q", str(b), "-b", "feat/x-followup")
    ws, shape = _discover(repo, "feat/x")
    assert shape == "worktree", (ws, shape)
    assert Path(ws).resolve() == a.resolve(), (
        "a prefix-related branch's worktree was claimed for this branch"
    )
    ws2, _ = _discover(repo, "feat/x-followup")
    assert Path(ws2).resolve() == b.resolve()


def test_a_prefix_set_at_claim_time_but_not_at_close_time_still_resolves(repo: Path):
    """`claim_task.sh` reads `WORKTREE_PREFIX` from the CLAIMING session and records it
    nowhere except a lock `--lock` may not have written. Re-deriving it from the closing
    session's environment resolved `<none>` — the same silent incompletion Q-238 exists
    to remove. The second pass scans every sibling and verifies HEAD, so widening it
    costs nothing."""
    clone = _make_clone(repo, "feat/z", "custom-t-9")
    ws, shape = _discover(repo, "feat/z")       # prefix NOT set at close time
    assert shape == "discovered", (ws, shape)
    assert Path(ws).resolve() == clone.resolve()


def test_the_widened_sibling_scan_still_verifies_head(repo: Path):
    """The second pass looks at every sibling directory, so its HEAD check is the only
    thing keeping it honest."""
    _make_clone(repo, "feat/other", "totally-unrelated-dir")
    _git(repo, "branch", "feat/z")
    assert _discover(repo, "feat/z") == ("<none>", "<none>")
