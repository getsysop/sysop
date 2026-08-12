"""Phase 191 — the batch status decision, and the header that eats its neighbour.

Two § High filings from Phase 190's round, plus the class that checking the
second one turned up.

**Every test here calls the real code with a fixture and asserts on what it
DID** — exit codes, files on disk, parsed records. None of them match source
text. That is deliberate and it is the lesson Phase 190's round paid for: its
guard string-matched `case` arms, so an independent battery deleted the whole
status ladder, left one bullet mentioning the value, and the suite stayed green
(2 of 26 defects killed, 12 of 15 behaviour-preserving controls false-killed).
A test that runs the thing cannot be fooled that way and cannot false-kill a
rename, a requote or a line wrap.

The three subjects:

1. **The claim path had no status decision at all.** `batch_work.sh <N>` wrote a
   branch, a worktree and a lock for every status that parsed — `Merged`,
   `Complete`, `Ready for Review` and undeclared values alike. The guard everyone
   assumed existed is `claim_batch()`'s `!= "Pending"` early return, which
   performs only the `review_tasks.md` flip and whose `return 0` returns from a
   *function* — so the script continues to the writes regardless. (It is called
   on the line *above* those writes, not after them; the round corrected that.
   Function scope is the mechanism, not statement order.) Measured before the
   fix: batches in all seven parseable statuses each left a `BATCH-<N>.lock` and
   a worktree on disk.

2. **`close_batch.sh` aborted mid-rewrite with zero diagnostic.** The status
   extraction had no `|| true`, so under `set -euo pipefail` a status carrying a
   hyphen or a digit killed the run *before* the `*)` arm written for exactly
   that case. Measured: `close_batch.sh 1 2 8` flipped two batches to `Merged` in
   the working tree, printed a bare `── Batch 8 ──`, exited 1 with an **empty**
   stderr, and left `review_tasks.md` dirty and uncommitted.

3. **A header the status charset cannot parse donates its metadata to the
   batch above it.** Not filed — found by checking the filed item's siblings.
   Two populations, deliberately not the same four, because an earlier draft of
   this docstring conflated them and was false under either reading. **Four
   files carried `[A-Za-z ]+`**: `batch_work.sh`, `close_batch.sh`,
   `review_index.py`, `sitrep_survey.py` — and `close_batch.sh` does *not* fall
   through, it bounds a batch by a broader `^##` grep. **Four parsers fall
   through**: those first three plus `next_task.py`, which never carried the
   charset at all (its status alphabet was always permissive; the defect there
   is the missing closer). Each falls through a non-matching `### Batch` line
   with the previous batch still open, so that batch's `Branch:`/`Scope:`/
   `Verify:` (and, in `sitrep_survey.py` and `next_task.py`, its task list) are
   overwritten by the orphan's. Measured in both `batch_work.sh` parser
   paths: `batch_work.sh 7` on a `Pending` batch 7 created a worktree named
   `…-batch-7` **on branch `review/batch-8`**, carrying batch 8's scope and batch
   8's verify command. `sitrep_survey.py` has the fix for this class one branch
   above the defect — `## ` closes the open batch; a malformed `### Batch` did
   not.
"""
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
BATCH_WORK = SCRIPTS / "batch_work.sh"
CLOSE_BATCH = SCRIPTS / "close_batch.sh"

sys.path.insert(0, str(SCRIPTS))

# The six declared values plus two undeclared ones. `Review Ready` is LIVE and
# `Ready for Review` is TERMINAL — near-homophones wired as opposites, verified
# by execution in Phase 190's round against `close_batch.sh` and `--release`.
# `On-Hold` and `Round 2` are the two undeclared shapes that matter: the hyphen
# and the digit are what the `[A-Za-z ]+` charset cannot hold.
DECLARED_LIVE = ["Pending", "In Progress", "Review Ready"]
DECLARED_TERMINAL = ["Complete", "Merged", "Ready for Review"]
UNDECLARED_ALPHA = "Blocked"
UNDECLARED_PUNCT = ["On-Hold", "Round 2"]


def _git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(cwd), check=check,
                          capture_output=True, text=True)


def _tasks(entries):
    """Render a review_tasks.md from [(number, status), ...].

    Each batch gets its OWN branch/scope/verify, named after its own number, so
    a carry-over is visible as a mismatch rather than having to be inferred.
    """
    out = ["# Review Tasks", ""]
    for n, status in entries:
        head = f"### Batch {n} — Batch {n} title"
        if status is not None:
            head += f" `{status}`"
        out += [
            head,
            "",
            f"> **Branch:** `review/batch-{n}`",
            f"> **Scope:** scope-{n}",
            f"> **Verify:** pytest -k batch{n}",
            "",
            f"- [ ] **TASK-{n:04d}**: task for batch {n}",
            "",
        ]
    return "\n".join(out) + "\n"


def _repo(root, entries, with_index=True):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "review_tasks.md").write_text(_tasks(entries))
    (root / "README.md").write_text("# seed\n")
    # Install the vendor scripts the way a consumer has them, so `INDEX_SCRIPT`
    # resolves and the Python index path is the one under test. Omitting
    # review_index.py forces the inline bash fallback — both are exercised.
    sd = root / "sysop" / "scripts"
    sd.mkdir(parents=True)
    names = ["batch_work.sh", "close_batch.sh", "_log.py"]
    if with_index:
        names.append("review_index.py")
    for name in names:
        src = SCRIPTS / name
        if src.exists():
            shutil.copy(src, sd / name)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(cwd, script, *args):
    return subprocess.run(["bash", str(script), *args], cwd=str(cwd),
                          capture_output=True, text=True)


def _claimed(repo, n):
    """What a claim actually leaves behind: lock, worktree, branch."""
    lock = repo / "sysop/runtime/locks" / f"BATCH-{n}.lock"
    worktree = repo.parent / f"{repo.name}-batch-{n}"
    branches = _git(repo, "branch", "--format=%(refname:short)").stdout.split()
    return {
        "lock": lock.exists(),
        "worktree": worktree.exists(),
        "branches": branches,
    }


# ══════════════════════════════════════════════════════════════════════
# 1. The claim path decides on status BEFORE it writes anything
# ══════════════════════════════════════════════════════════════════════

class TestClaimPathStatusGate:
    """`batch_work.sh <N>` must not hand out a worktree on a finished batch.

    The harm is the lock: `close_batch.sh` and `--release` are the only things
    that remove one, so a second agent claiming a batch the first still holds
    gets a worktree on the same branch with the first agent's lock still live.
    """

    def test_pending_still_claims(self, tmp_path):
        """The dominant path. If this breaks, the gate is worthless."""
        repo = _repo(tmp_path / "repo", [(1, "Pending")])
        r = _run(repo, BATCH_WORK, "1")
        assert r.returncode == 0, r.stdout + r.stderr
        got = _claimed(repo, 1)
        assert got["lock"], "a Pending batch must still get its lock"
        assert got["worktree"], "a Pending batch must still get its worktree"

    def test_in_progress_still_claims_so_resume_survives(self, tmp_path):
        """Re-running on your own in-flight batch is how you resume after a
        dropped session. The gate must not turn that into an error."""
        repo = _repo(tmp_path / "repo", [(1, "In Progress")])
        r = _run(repo, BATCH_WORK, "1")
        assert r.returncode == 0, r.stdout + r.stderr
        assert _claimed(repo, 1)["worktree"]

    def test_terminal_statuses_are_refused_without_force(self, tmp_path):
        """`Complete`, `Merged` and `Ready for Review` are finished work.

        Before the fix the first two printed a warning and continued and the
        third said nothing at all.
        """
        for status in DECLARED_TERMINAL:
            repo = _repo(tmp_path / f"repo-{status.replace(' ', '-')}",
                         [(1, status)])
            r = _run(repo, BATCH_WORK, "1")
            assert r.returncode != 0, (
                f"{status!r} was claimed: {r.stdout}"
            )
            got = _claimed(repo, 1)
            assert not got["lock"], f"{status!r} left a lock behind"
            assert not got["worktree"], f"{status!r} left a worktree behind"
            assert "review/batch-1" not in got["branches"], \
                f"{status!r} created a branch"

    def test_review_ready_is_refused_because_it_is_someone_elses_claim(self, tmp_path):
        """`Review Ready` is LIVE — work finished and awaiting review. Claiming
        it is the colleague-collision the filing names, so it refuses; it is not
        grouped with the terminal three because `--release` still owns it."""
        repo = _repo(tmp_path / "repo", [(1, "Review Ready")])
        r = _run(repo, BATCH_WORK, "1")
        assert r.returncode != 0, r.stdout
        assert not _claimed(repo, 1)["lock"]

    def test_force_restores_the_follow_up_affordance(self, tmp_path):
        """Claiming a finished batch for follow-up work was a deliberate
        affordance (the old `Proceeding anyway (you may be doing follow-up
        work)` warning). The gate must keep it reachable, not delete it.

        Covers all three terminal statuses, not just `Merged`. Battery row A02
        dropped `Ready for Review` out of the terminal arm and survived a
        Merged-only version: the status then fell through to the undeclared
        `*)` arm, which also refuses — so every "was it refused" assertion still
        held, while a declared status was being reported as one the workflow does
        not define, and `--force` no longer reached it. Which arm refuses is the
        thing worth pinning, and the observable difference is `--force`.

        `Review Ready` is included, and the round is why: it is refused for a
        different reason from the terminal three (it is someone else's live
        claim, not finished work), and `--force` is advertised for it by the
        arm's own message and by WORKFLOW.md. Iterating only `DECLARED_TERMINAL`
        left that arm free to refuse unconditionally with the suite green.
        """
        for status in DECLARED_TERMINAL + ["Review Ready"]:
            repo = _repo(tmp_path / f"force-{status.replace(' ', '-')}",
                         [(1, status)])
            bare = _run(repo, BATCH_WORK, "1")
            assert bare.returncode != 0, \
                f"[{status}] precondition: the bare claim must be refused"
            r = _run(repo, BATCH_WORK, "--force", "1")
            assert r.returncode == 0, f"[{status}] {r.stdout}{r.stderr}"
            assert _claimed(repo, 1)["worktree"], \
                f"[{status}] --force must still claim"

    def test_undeclared_status_is_refused_even_with_force(self, tmp_path):
        """An unknown status cannot be classified live or terminal, so there is
        no safe thing to do with it. `--release`'s `*)` arm already refuses "to
        guess at the inverse"; the claim path now refuses to guess at all. The
        remedy is to fix the record, and the message must say so."""
        repo = _repo(tmp_path / "repo", [(1, UNDECLARED_ALPHA)])
        for args in (("1",), ("--force", "1")):
            r = _run(repo, BATCH_WORK, *args)
            assert r.returncode != 0, f"{args} claimed an undeclared status"
            assert not _claimed(repo, 1)["lock"]
        assert UNDECLARED_ALPHA in r.stdout + r.stderr, \
            "the diagnostic must name the status the operator has to fix"

    def test_refusal_happens_before_any_write(self, tmp_path):
        """A gate that refuses after creating the branch is not a gate. No
        branch, worktree, lock, or `review_tasks.md` edit may survive a refused
        claim.

        Scoped to *claim artifacts* rather than to a byte-identical tree, and
        the distinction is derived rather than assumed: `.claude/review_index.
        json` is a derived cache the shadow index rebuilds on any read, and it
        appears on `--list` too — verified against the unmodified script on
        `main`. Asserting a clean `git status` here would fail on that
        pre-existing truth, which is a false kill, not a finding. Tracked files
        are still held byte-identical, so a real mutation cannot hide behind the
        carve-out.

        Parametrised over ALL THREE refusing arms. The round inserted a
        `git branch` before the `Review Ready` and undeclared refusals and this
        test stayed green, because it exercised only `Merged` and the other two
        arms' tests asserted `not lock` alone — so a branch left behind by two
        of the three arms was invisible. "Nothing is written" has to be checked
        wherever nothing is supposed to be written.
        """
        for status, why in [("Merged", "terminal"),
                            ("Review Ready", "live, someone else's claim"),
                            ("On-Hold", "undeclared")]:
            repo = _repo(tmp_path / f"repo-{status.replace(' ', '-')}", [(1, status)])
            before = (repo / "review_tasks.md").read_text()
            r = _run(repo, BATCH_WORK, "1")
            assert r.returncode != 0, f"[{why}] expected a refusal"
            assert (repo / "review_tasks.md").read_text() == before, f"[{why}]"
            tracked = _git(repo, "status", "--porcelain", "--untracked-files=no")
            assert tracked.stdout.strip() == "", f"[{why}] {tracked.stdout}"
            got = _claimed(repo, 1)
            assert not got["lock"], f"[{why}] a refused claim left a lock"
            assert not got["worktree"], f"[{why}] a refused claim left a worktree"
            assert "review/batch-1" not in got["branches"], \
                f"[{why}] a refused claim left a branch behind"

    def test_in_progress_resume_announces_the_existing_claim(self, tmp_path):
        """The resume arm is the one place the gate deliberately proceeds on a
        batch another agent may hold, so its announcement IS the safety
        mechanism — it is what tells a second agent the batch is taken. The
        round replaced the whole block with `if false` and the suite stayed
        green: new code, an eight-line comment explaining its `|| CLAIM_LOCK_DIR=""`
        subtlety, and nothing asserting it ever printed.

        Not asserting the exact wording — battery row X02 showed diagnostics can
        be reworded without behaviour change, and pinning strings is how the
        false kills in this round happened. Asserts the two facts an operator
        needs: that a resume is announced as a resume, and that the existing
        lock's owner is surfaced rather than stepped over."""
        # The fixture carries `In Progress` directly rather than claiming a
        # `Pending` batch first: with no remote, `git pull --ff-only` fails and
        # `claim_batch` skips the status flip, so a claim-then-reclaim sequence
        # never reaches this arm at all. (That early return is also the one whose
        # own message — "The worktree and the lock are still created" — shows the
        # helper runs BEFORE the writes.)
        repo = _repo(tmp_path / "repo", [(1, "In Progress")])
        first = _run(repo, BATCH_WORK, "1")
        assert first.returncode == 0, first.stdout + first.stderr
        assert _claimed(repo, 1)["lock"], "precondition: the first claim locks"

        second = _run(repo, BATCH_WORK, "1")
        out = second.stdout + second.stderr
        assert second.returncode == 0, f"a resume must not be refused: {out!r}"
        assert "resum" in out.lower(), \
            f"a re-claim must announce itself as a resume, not run silently: {out!r}"
        assert "workspace:" in out or "agent:" in out, (
            "the existing claim's owner must be surfaced — that line is what "
            f"tells a SECOND agent the batch is already held: {out!r}"
        )

    def test_trailing_force_is_rejected_like_release_rejects_it(self, tmp_path):
        """`--release` already refuses a flag after the positional rather than
        silently no-opping it (`Flags must come before <BATCH_NUMBER>`). The
        claim path parses the same flag, so it owes the same error — a silent
        no-op here means a claim the operator believes was forced.

        Asserts the flag-placement error specifically. Battery row A07 deleted
        the trailing-flag guard and survived the weaker version: with the flag
        ignored, `CLAIM_FORCE` stays false, the `Merged` status is refused on its
        own account, and `returncode != 0` holds for entirely the wrong reason.
        """
        repo = _repo(tmp_path / "repo", [(1, "Merged")])
        r = _run(repo, BATCH_WORK, "1", "--force")
        assert r.returncode != 0
        out = r.stdout + r.stderr
        assert "Flags must come before" in out, (
            "a trailing flag must be rejected as misplaced, not silently "
            f"dropped into an unrelated refusal: {out!r}"
        )
        assert not _claimed(repo, 1)["worktree"], \
            "a trailing --force must not silently claim"


# ══════════════════════════════════════════════════════════════════════
# 2. close_batch.sh reaches its own `*)` arm instead of dying before it
# ══════════════════════════════════════════════════════════════════════

class TestCloseBatchDoesNotAbortOnAnOddStatus:

    def test_punctuated_status_reaches_the_skip_arm(self, tmp_path):
        """The `*)` arm exists for exactly this input and was unreachable.

        Asserts the *unrecognized* wording, not merely that the status appears
        somewhere in the output. Battery row R03 — narrow the extraction charset
        again while keeping the `|| true` — survived a looser version of this
        test: the status came out EMPTY, took the no-status arm, and that arm
        echoes the whole header, which contains the status text. So a substring
        check was satisfied by the wrong message about the wrong problem.
        """
        for status in UNDECLARED_PUNCT:
            repo = _repo(tmp_path / f"cb-{status.replace(' ', '_')}",
                         [(1, status)], with_index=False)
            r = _run(repo, CLOSE_BATCH, "1")
            assert r.returncode == 0, (
                f"{status!r} aborted the run: rc={r.returncode} "
                f"stdout={r.stdout!r} stderr={r.stderr!r}"
            )
            assert f"Unrecognized batch status '{status}'" in r.stdout, (
                f"the status was not extracted as {status!r} — got {r.stdout!r}"
            )
            assert "1:bad-status" in r.stdout, \
                "the skip verdict must record WHY it skipped"

    def test_an_odd_status_does_not_strand_the_earlier_batches(self, tmp_path):
        """The measured harm: `close_batch.sh 1 2 8` flipped 1 and 2 in the
        working tree, then died on 8 before committing — leaving
        `review_tasks.md` dirty with two uncommitted `Merged` flips and printing
        nothing on stderr at all."""
        repo = _repo(
            tmp_path / "repo",
            [(1, "Pending"), (2, "Pending"), (3, "On-Hold")],
            with_index=False,
        )
        r = _run(repo, CLOSE_BATCH, "1", "2", "3")
        assert r.returncode == 0, (
            f"rc={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}"
        )
        # The run must reach its end: the two good batches committed, the tree
        # clean, and the odd one reported rather than silently swallowed.
        assert _git(repo, "status", "--porcelain").stdout.strip() == "", \
            "the close left uncommitted mutations behind"
        text = (repo / "review_tasks.md").read_text()
        assert "Batch 1 title `Merged`" in text
        assert "Batch 2 title `Merged`" in text
        assert "Batch 3 title `On-Hold`" in text, \
            "the unrecognized batch must be left exactly as it was"

    def test_a_header_with_no_status_token_is_reported_not_crashed(self, tmp_path):
        """`grep -o` finding nothing is the other half of the same pipefail
        hazard, and it produces an empty status rather than an odd one — so the
        message has to distinguish the two cases to be actionable.

        Pins the distinction, not just the survival: battery row K01 folded the
        empty case back into the generic arm and a bare `rc == 0` check could
        not see it. `Unrecognized batch status ''` names nothing the operator can
        go and fix.
        """
        repo = _repo(tmp_path / "repo", [(1, None)], with_index=False)
        r = _run(repo, CLOSE_BATCH, "1")
        assert r.returncode == 0, (
            f"rc={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r}"
        )
        assert "No trailing `status` token" in r.stdout, r.stdout
        assert "1:no-status" in r.stdout, \
            "the skip verdict must distinguish a missing status from a bad one"
        assert "Unrecognized batch status" not in r.stdout, \
            "a missing status must not be reported as an unrecognized one"

    def test_a_backticked_title_does_not_steal_the_status(self, tmp_path):
        """The ISSUE-0044 end-anchor, which this phase edited and did not pin.
        The round replaced `` grep -oE '`[^`]+`[[:space:]]*$' `` with
        `` grep -oE '`[^`]+`' | head -1 `` and the whole suite stayed green —
        while a batch titled ``fix `foo` regression`` then reported
        `Unrecognized batch status 'foo'` and was skipped instead of merged.
        Widening the charset made this MORE reachable, not less: `[^`]+` accepts
        anything between backticks, so only the end-anchor still distinguishes a
        title's quoted word from the status."""
        repo = _repo(tmp_path / "repo", [(1, "Pending")], with_index=False)
        tasks = repo / "review_tasks.md"
        tasks.write_text(tasks.read_text().replace(
            "### Batch 1 — Batch 1 title `Pending`",
            "### Batch 1 — fix `foo` regression `Merged`",
        ))
        _git(repo, "commit", "-qam", "backticked title")
        r = _run(repo, CLOSE_BATCH, "--dry-run", "1")
        out = r.stdout + r.stderr
        assert "foo" not in out.replace("fix `foo` regression", ""), (
            "the title's backticked word was read as the status — only the "
            f"end-anchor separates them: {out!r}"
        )
        assert "Unrecognized" not in out, \
            f"a well-formed `Merged` batch was reported as unrecognized: {out!r}"

    def test_alphabetic_bad_status_still_reports_as_before(self, tmp_path):
        """The pre-existing `*)` behaviour for an alphabetic unknown must be
        unchanged — this is the arm `tests/test_close_batch_sh.py` already pins,
        and widening the extraction must not move it."""
        repo = _repo(tmp_path / "repo", [(1, "Weird")], with_index=False)
        r = _run(repo, CLOSE_BATCH, "1")
        assert r.returncode == 0
        assert "Unrecognized batch status" in r.stdout
        assert "Weird" in r.stdout


# ══════════════════════════════════════════════════════════════════════
# 3. A malformed header must not eat the batch above it
# ══════════════════════════════════════════════════════════════════════

# Header shapes the strict pattern rejects. Each is an ordinary authoring slip,
# and each used to leave the PREVIOUS batch open to absorb its metadata.
#
# **Every member must be dash-free-tolerant as a SET.** Phase 191's adversarial
# round found that the first four all carried a dash after the batch number, so
# a closer narrowed to *require* a dash passed all of them — the § High this
# file exists to guard, re-openable invisibly. The corpus was shaped like the
# fix, which is the same defect as a grep shaped like its hypothesis. Members
# are also deliberately not all numbered 7/8; see `_neighbour_fixture`.
MALFORMED = [
    ("### Batch 8 — Batch 8 title", "no trailing status token"),
    ("### Batch 8 - Batch 8 title `Pending`", "hyphen instead of em-dash"),
    ("### Batch 8 — Batch 8 title `Pending` (draft)", "status not at end of line"),
    # No dash of any kind. Added by the round: a closer narrowed to require
    # `[—-]` after the number passes every other member of this list, in all
    # four readers, while re-opening the full carry-over. Probed at the time:
    # batch 7 came back with `review/batch-8`, `scope-8` and 2 tasks.
    ("### Batch 8: Batch 8 title", "colon — no dash at all"),
    # Both slips at once. Rows 1, 3 and 4 are all orphans for every parser —
    # the property that makes THIS row load-bearing is the conjunction: an
    # orphan everywhere AND invisible to an em-dash-only closer. Rows 1 and 3
    # carry the em-dash, so a narrowed closer still catches them, which is
    # exactly why C10 survived until this row existed.
    #
    # It exists because `next_task.py`'s strict pattern tolerates
    # an ASCII hyphen where the other three require the em-dash, so row 2 above
    # parses cleanly there and never reaches its closer. Without this row a
    # closer narrowed to `— ` passes the whole suite (battery row C10 survived
    # on exactly that), which would leave /next-task — the resolver an operator
    # is told to trust — carrying its neighbour's branch again.
    ("### Batch 8 - Batch 8 title", "hyphen AND no status token"),
]


# Whitespace variants of an otherwise well-formed batch 8 header. These are NOT
# in MALFORMED because they are not orphans everywhere: `next_task.py` and the
# bash fallback spell their strict patterns with `\s+`/`[[:space:]]+`, so these
# parse cleanly there, while `review_index.py` and `sitrep_survey.py` spell
# theirs with literal single spaces and see an orphan.
#
# That asymmetry is the whole point. Phase 191's first fix gave the permissive
# twins literal single spaces too, so a header the strict pattern rejected was
# ALSO invisible to the closer written to catch it — the carry-over reproduced
# on the fixed tree, and the archiver relocated a round holding an open batch.
# A twin must be strictly more permissive than its strict pattern in every
# dimension that pattern constrains, and only executing every shape against
# every parser shows whether it is.
WHITESPACE_SHAPES = [
    ("###\tBatch 8 — Batch 8 title `Pending`", "TAB after ###"),
    ("###  Batch 8 — Batch 8 title `Pending`", "two spaces after ###"),
    ("### Batch  8 — Batch 8 title `Pending`", "two spaces before the number"),
    ("###   Batch   8 — Batch 8 title `Pending`", "padding at both joints"),
]


def _neighbour_fixture(header, a=7, b=8):
    """A well-formed batch `a` followed by a malformed batch `b`.

    Parametrised over the batch numbers because the round found the fixed pair
    7/8 hardcoded everywhere: a closer narrowed to `^### Batch [78]\\b` — which
    matches nothing a real tracker contains — passed the entire suite in all
    four readers. A guard whose corpus only ever shows it two integers cannot
    tell "recognises a batch header" from "recognises these two batches".

    `header` is expected to name batch `b`; callers building a non-default pair
    substitute it themselves.
    """
    return (
        "# Review Tasks\n\n"
        f"### Batch {a} — Batch {a} title `Pending`\n\n"
        f"> **Branch:** `review/batch-{a}`\n"
        f"> **Scope:** scope-{a}\n"
        f"> **Verify:** pytest -k batch{a}\n\n"
        f"- [ ] **TASK-{a:04d}**: task for batch {a}\n\n"
        f"{header}\n\n"
        f"> **Branch:** `review/batch-{b}`\n"
        f"> **Scope:** scope-{b}\n"
        f"> **Verify:** pytest -k batch{b}\n\n"
        f"- [ ] **TASK-{b:04d}**: task for batch {b}\n"
    )


# The same malformed shapes on a batch pair that is not 7/8. Kept as a separate
# list rather than folded into MALFORMED so the default-pair tests stay readable
# and this one states exactly what it buys: closers that recognise batch headers
# rather than these two integers.
MALFORMED_OTHER_PAIR = [
    ("### Batch 42 — Batch 42 title", 41, 42, "no status token, pair 41/42"),
    ("### Batch 103: Batch 103 title", 102, 103, "colon, three-digit pair"),
    ("### Batch 6 - Batch 6 title", 5, 6, "hyphen and no status, pair 5/6"),
]


class TestOrphanHeaderDoesNotCorruptItsPredecessor:

    def test_punctuated_status_now_parses_at_all(self, tmp_path):
        """The reported symptom: `--release <N>` answers "not found" for a batch
        plainly in the file, because the charset cannot hold a hyphen."""
        repo = _repo(tmp_path / "repo", [(1, "Pending"), (2, "On-Hold")])
        r = _run(repo, BATCH_WORK, "--list-all")
        assert "Batch 2 title" in r.stdout, \
            f"a hyphenated status hid the batch entirely: {r.stdout}"

    def test_every_parser_sees_a_punctuated_status(self, tmp_path):
        """All four structural readers, asked the same question directly.

        The three orphan tests below use MALFORMED headers carrying an ordinary
        `Pending`, so they exercise the closer and say nothing about the charset.
        Battery rows C06/C07/C08 narrowed one parser's charset at a time and
        survived on that gap — each reader has to be asked itself, because the
        four are duplicated-and-pinned rather than shared through an import.
        """
        import review_index as ri
        import sitrep_survey as ss

        for status in UNDECLARED_PUNCT:
            repo = _repo(tmp_path / f"px-{status.replace(' ', '_')}",
                         [(1, status)])
            f = str(repo / "review_tasks.md")

            got = ri.parse_review_tasks(f)["batches"]["1"]["status"]
            assert got == status, f"review_index read {got!r}"

            got = ss._read_review_batches(repo)[0]["status"]
            assert got == status, f"sitrep_survey read {got!r}"

            # batch_work.sh, both parser paths — the index present, then absent.
            assert status in _run(repo, BATCH_WORK, "--list-all").stdout
            bare = _repo(tmp_path / f"px-bare-{status.replace(' ', '_')}",
                         [(1, status)], with_index=False)
            assert status in _run(bare, BATCH_WORK, "--list-all").stdout

    def test_claim_uses_its_own_branch_python_index_path(self, tmp_path):
        """The measured corruption, through the shadow index: `batch_work.sh 7`
        built a worktree named `…-batch-7` on branch `review/batch-8`."""
        for header, why in MALFORMED:
            repo = _repo(tmp_path / f"idx-{abs(hash(header))}", [(1, "Pending")])
            (repo / "review_tasks.md").write_text(_neighbour_fixture(header))
            _git(repo, "commit", "-qam", "fixture")
            r = _run(repo, BATCH_WORK, "7")
            assert r.returncode == 0, f"[{why}] {r.stdout} {r.stderr}"
            branches = _git(repo, "branch", "--format=%(refname:short)").stdout.split()
            assert "review/batch-8" not in branches, (
                f"[{why}] batch 7 was claimed on batch 8's branch"
            )
            assert "review/batch-7" in branches, f"[{why}] wrong branch: {branches}"

    def test_claim_uses_its_own_branch_bash_fallback_path(self, tmp_path):
        """Same assertion with review_index.py absent, because the fallback
        parser has the same structure and the same defect — the Python index is
        not a safety net for it."""
        for header, why in MALFORMED:
            repo = _repo(tmp_path / f"bash-{abs(hash(header))}", [(1, "Pending")],
                         with_index=False)
            (repo / "review_tasks.md").write_text(_neighbour_fixture(header))
            _git(repo, "commit", "-qam", "fixture")
            r = _run(repo, BATCH_WORK, "7")
            assert r.returncode == 0, f"[{why}] {r.stdout} {r.stderr}"
            branches = _git(repo, "branch", "--format=%(refname:short)").stdout.split()
            assert "review/batch-8" not in branches, (
                f"[{why}] batch 7 was claimed on batch 8's branch"
            )

    def test_review_index_keeps_each_batchs_own_metadata(self, tmp_path):
        import review_index as ri
        for header, why in MALFORMED:
            f = tmp_path / f"ri-{abs(hash(header))}.md"
            f.write_text(_neighbour_fixture(header))
            data = ri.parse_review_tasks(str(f))
            seven = data["batches"]["7"]
            assert seven["branch"] == "review/batch-7", f"[{why}] {seven['branch']}"
            assert seven["scope"] == "scope-7", f"[{why}] {seven['scope']}"
            assert seven["verify"] == "pytest -k batch7", f"[{why}] {seven['verify']}"

    def test_sitrep_keeps_each_batchs_own_branch_and_tasks(self, tmp_path):
        """`sitrep_survey.py` absorbs the orphan's TASK lines too, so the
        done/total arithmetic behind /sitrep's "ready for /review-close" signal
        is wrong as well as the branch. The fix for this exact class is one
        branch above the defect in that file: `## ` closes the open batch, a
        malformed `### Batch` did not."""
        import sitrep_survey as ss
        for header, why in MALFORMED:
            root = tmp_path / f"ss-{abs(hash(header))}"
            root.mkdir()
            (root / "review_tasks.md").write_text(_neighbour_fixture(header))
            batches = ss._read_review_batches(root)
            seven = next(b for b in batches if b["number"] == 7)
            assert seven["branch"] == "review/batch-7", f"[{why}] {seven['branch']}"
            ids = [t.get("id") for t in seven["tasks"]]
            assert "TASK-0008" not in ids, \
                f"[{why}] batch 7 absorbed batch 8's task: {ids}"

    def test_next_task_keeps_each_batchs_own_branch_and_tasks(self):
        """The sharpest member of the family, and the one the filing did not
        name. `/next-task` is the deterministic resolver an operator is told to
        trust, so a batch 7 carrying batch 8's branch and verify command is
        handed out as the next thing to work on. Its status charset was already
        permissive, which is why a charset-shaped sweep did not surface it — the
        defect is the missing closer, not the alphabet."""
        import next_task as nt
        for header, why in MALFORMED:
            batches = nt.parse_review_batches(_neighbour_fixture(header))
            seven = next(b for b in batches if b["number"] == 7)
            assert seven["branch"] == "review/batch-7", f"[{why}] {seven['branch']}"
            assert seven["verify"] == "pytest -k batch7", f"[{why}] {seven['verify']}"
            assert len(seven["tasks"]) == 1, \
                f"[{why}] batch 7 absorbed batch 8's task: {seven['tasks']}"

    def test_closers_recognise_batch_headers_not_two_integers(self, tmp_path):
        """The corpus-shape guard. Every other test in this class uses batches
        7 and 8, so a closer narrowed to `^### Batch [78]\\b` — matching nothing
        a real tracker contains — passed the whole suite in all four readers
        until this existed. Same defect as a grep shaped like its hypothesis,
        one level up: the fixture encoded the answer."""
        import review_index as ri
        import sitrep_survey as ss
        import next_task as nt
        for header, a, b, why in MALFORMED_OTHER_PAIR:
            body = _neighbour_fixture(header, a=a, b=b)
            root = tmp_path / f"pair-{a}-{b}"
            root.mkdir()
            (root / "review_tasks.md").write_text(body)

            first = ri.parse_review_tasks(str(root / "review_tasks.md"))["batches"][str(a)]
            assert first["branch"] == f"review/batch-{a}", f"[review_index {why}]"
            assert first["scope"] == f"scope-{a}", f"[review_index {why}]"

            s = next(x for x in ss._read_review_batches(root) if x["number"] == a)
            assert s["branch"] == f"review/batch-{a}", f"[sitrep {why}]"
            assert f"TASK-{b:04d}" not in [t.get("id") for t in s["tasks"]], \
                f"[sitrep {why}] absorbed the orphan's task"

            n = next(x for x in nt.parse_review_batches(body) if x["number"] == a)
            assert n["branch"] == f"review/batch-{a}", f"[next_task {why}]"
            assert len(n["tasks"]) == 1, f"[next_task {why}]"

    def test_whitespace_shapes_do_not_corrupt_the_predecessor(self, tmp_path):
        """The class Phase 191's own round reopened. Every parser must keep
        batch 7's metadata whatever whitespace batch 8's header uses — whether
        that parser reads batch 8 as a real batch (its strict pattern is
        flexible) or as an orphan (its strict pattern is rigid). Both are
        acceptable answers; donating batch 8's branch to batch 7 is not."""
        import review_index as ri
        import sitrep_survey as ss
        import next_task as nt
        for header, why in WHITESPACE_SHAPES:
            body = _neighbour_fixture(header)
            root = tmp_path / f"ws-{abs(hash(header))}"
            root.mkdir()
            (root / "review_tasks.md").write_text(body)

            seven = ri.parse_review_tasks(str(root / "review_tasks.md"))["batches"]["7"]
            assert seven["branch"] == "review/batch-7", f"[review_index {why}]"
            assert seven["verify"] == "pytest -k batch7", f"[review_index {why}]"

            s7 = next(b for b in ss._read_review_batches(root) if b["number"] == 7)
            assert s7["branch"] == "review/batch-7", f"[sitrep {why}]"
            assert "TASK-0008" not in [t.get("id") for t in s7["tasks"]], \
                f"[sitrep {why}] batch 7 absorbed batch 8's task"

            n7 = next(b for b in nt.parse_review_batches(body) if b["number"] == 7)
            assert n7["branch"] == "review/batch-7", f"[next_task {why}]"
            assert len(n7["tasks"]) == 1, f"[next_task {why}]"

    def test_archiver_counts_a_whitespace_spelled_open_batch(self):
        """The denominator half of the same class, and the one that loses data.
        Widening `ANY_BATCH_HEADER_RE` alone was NOT enough: the counter sits in
        the outside-a-batch branch, so while the open batch never closed it was
        never reached. A round holding an open batch must never archive."""
        import archive_review_tasks as a

        def doc(h8, status, tail=" — Eight"):
            return (
                "## Round 9 (2026-01-01) — Test\n\n"
                "### Batch 7 — Seven `Merged`\n\n"
                "- [x] **TASK-0001**: done\n\n"
                f"{h8}{tail} `{status}`\n\n"
                "- [ ] **TASK-0002**: STILL OPEN\n"
            ).splitlines()

        for h8, tail, why in [
            ("###\tBatch 8", " — Eight", "TAB after ###"),
            ("###  Batch 8", " — Eight", "two spaces after ###"),
            ("### Batch  8", " — Eight", "two spaces before the number"),
            ("###   Batch   8", " — Eight", "padding at both joints"),
            # Dash-free, for the same reason MALFORMED carries a colon member:
            # the round narrowed this denominator to require a dash and every
            # em-dash fixture still passed, while a round holding an open batch
            # was relocated into the archive. The corpus was shaped like the fix.
            ("### Batch 8", ": Eight", "colon — no dash at all"),
            ("### Batch 8", " Eight", "no separator at all"),
            # Not the 7/8 pair, for the closer-recognises-two-integers reason.
            ("### Batch 104", ": One-oh-four", "colon, three-digit number"),
        ]:
            rounds = a.parse_archivable_batches(doc(h8, "Pending", tail))
            assert rounds, f"[{why}] the round vanished entirely"
            assert not rounds[0]["all_merged"], (
                f"[{why}] a round holding an OPEN batch was marked archivable — "
                "the archiver would relocate live work"
            )
        # Control: the ordinary fully-merged round must still archive, or the
        # fix above is just a permanent refusal to archive anything.
        done = a.parse_archivable_batches(doc("### Batch 8", "Merged"))
        assert done and done[0]["all_merged"], \
            "a fully merged round must still be archivable"

    def test_list_does_not_advertise_what_the_claim_path_refuses(self, tmp_path):
        """The two surfaces have to agree or the gate just relocates the
        confusion: before, `--list` hid only `Complete`/`Merged`, so it offered
        `Ready for Review` as workable and the claim path then refused it."""
        entries = [(n, s) for n, s in
                   enumerate(DECLARED_LIVE + DECLARED_TERMINAL, 1)]
        repo = _repo(tmp_path / "repo", entries)
        listed = _run(repo, BATCH_WORK, "--list").stdout

        # Stated as a fixed expectation, not derived from what --list happened
        # to print. Battery row L03 replaced the hide-set with "everything that
        # is not Pending or In Progress", which hides `Review Ready` — live work
        # that needs a review — and a purely relational check stayed green,
        # because a hidden batch that is also unclaimable satisfies it.
        assert {n for n, _ in entries if f"Batch {n} title" in listed} == {1, 2, 3}, \
            f"--list must show exactly the three LIVE batches:\n{listed}"

        for n, status in entries:
            offered = f"Batch {n} title" in listed
            r = _run(repo, BATCH_WORK, str(n))
            claimable = r.returncode == 0
            if not offered:
                assert not claimable, \
                    f"{status!r} is hidden from --list but still claimable"
            # `Review Ready` is the deliberate exception: shown because it needs
            # attention, refused because the attention it needs is a review.
            if offered and not claimable:
                assert status == "Review Ready", \
                    f"--list offers {status!r} but the claim path refuses it"

    def test_every_declared_status_gets_its_own_glyph(self, tmp_path):
        """`❓` has to mean "not a status this workflow defines". It cannot also
        mean `Review Ready`, which the generators advertise as the value to use.

        The round caught this test not testing its own name: it asserted only
        that `❓` was absent, so collapsing all six declared statuses onto a
        single shared glyph passed. It now asserts the distinctness the name
        promises — bounded honestly at **three** distinct glyphs, because the
        shipped arm deliberately gives `Complete`, `Merged` and
        `Ready for Review` the same `✅` (they are one terminal state wearing
        three spellings). Three live-vs-terminal groups, three glyphs.
        """
        entries = [(n, s) for n, s in
                   enumerate(DECLARED_LIVE + DECLARED_TERMINAL, 1)]
        entries.append((99, UNDECLARED_ALPHA))
        repo = _repo(tmp_path / "repo", entries)
        rows = {}
        for line in _run(repo, BATCH_WORK, "--list-all").stdout.splitlines():
            for n, _ in entries:
                if f"Batch {n} title" in line:
                    rows[n] = line
        for n, status in entries:
            assert n in rows, f"batch {n} ({status}) missing from --list-all"
            if status == UNDECLARED_ALPHA:
                assert "❓" in rows[n], "an undeclared status must be flagged"
            else:
                assert "❓" not in rows[n], \
                    f"declared status {status!r} rendered as unrecognized"

        # Distinctness, which the name claims and the old assertions did not.
        glyphs = {}
        for n, status in entries:
            if status == UNDECLARED_ALPHA:
                continue
            found = [g for g in ("⬜", "🔵", "👀", "✅") if g in rows[n]]
            assert len(found) == 1, \
                f"{status!r} should carry exactly one declared glyph, got {found}"
            glyphs[status] = found[0]
        assert len(set(glyphs.values())) >= 3, (
            "the declared statuses collapsed onto fewer than three glyphs, so "
            f"the table no longer distinguishes them: {glyphs}"
        )
        live = [glyphs[s] for s in DECLARED_LIVE]
        assert len(set(live)) == len(live), (
            "the three LIVE statuses must be pairwise distinguishable — an "
            "operator reads this table to decide what to claim: "
            f"{ {s: glyphs[s] for s in DECLARED_LIVE} }"
        )

    def test_archiver_does_not_relocate_a_round_holding_an_open_batch(self):
        """The fifth charset site, and the one where the failure is data loss.

        `archive_review_tasks.py` computes `all_merged` as
        `round_total_batches == len(merged_batches)`, and increments the
        denominator only for headers `ANY_BATCH_HEADER_RE` can see. Its charset
        was `\\w[\\w ]*` — narrower than the four structural readers and
        different from all of them — so a batch it could not parse vanished from
        the denominator and the round reported itself fully merged. An
        `all_merged` round is RELOCATED into the archive, open task and all.

        This is why the widening elsewhere could not stop here: making
        hyphenated statuses ordinary and visible everywhere else would have made
        this reachable rather than exotic.
        """
        import archive_review_tasks as a

        def round_with(header):
            return (
                "## Round 9 (2026-01-01) — Test\n\n"
                "### Batch 1 — Done one `Merged`\n\n"
                "- [x] **TASK-0001**: a\n\n"
                f"{header}\n\n"
                "- [ ] **TASK-0002**: b\n"
            ).splitlines()

        # `Pending` was always counted; the rest are the shapes that were not.
        # `Round 2` passed before only because `\\w` happens to cover digits.
        headers = [f"### Batch 2 — Still open `{s}`" for s in
                   ["Pending", "On-Hold", "Blocked/waiting", "Re-open",
                    "Round 2", "Review Ready"]]
        # The malformed shapes belong here too, and battery rows D02/D03
        # survived without them: a denominator that merely widened its CHARSET
        # still drops a header carrying no status token at all, and dropping it
        # is what archives the round. The counter's question has to be "is this
        # a batch header", not "can I classify this batch".
        headers += [
            "### Batch 2 — Still open",
            "### Batch 2 - Still open `Pending`",
            "### Batch 2 — Still open `Pending` (draft)",
        ]
        for header in headers:
            rounds = a.parse_archivable_batches(round_with(header))
            assert rounds, f"[{header}] the round vanished entirely"
            assert not rounds[0]["all_merged"], (
                f"[{header}] a round with an unmerged batch reported all_merged "
                "— it would be archived with live work inside it"
            )

        # The control: a genuinely finished round must still archive, or the
        # fix has simply disabled the feature.
        done = (
            "## Round 9 (2026-01-01) — Test\n\n"
            "### Batch 1 — Done one `Merged`\n\n"
            "- [x] **TASK-0001**: a\n\n"
            "### Batch 2 — Done two `Complete`\n\n"
            "- [x] **TASK-0002**: b\n"
        ).splitlines()
        rounds = a.parse_archivable_batches(done)
        assert rounds and rounds[0]["all_merged"], \
            "a fully merged round must still be archivable"

    def test_the_three_python_parsers_agree_on_a_declared_status(self, tmp_path):
        """A cross-reader consistency check on ordinary input, and the negative
        control for the malformed-header tests above: if a fix made one parser
        diverge from the others on a well-formed file, this goes red.

        The name counts what this actually drives — **three** distinct Python
        parsers. The `--list-all` assertion below is a fourth *assertion*, not a
        fourth parser: `_repo` installs `review_index.py` by default (see its
        comment), so that subprocess re-enters the parser the first assertion
        already checks directly. It earns its place as an end-to-end round-trip
        through the CLI, not as independent coverage. The bash fallback is a
        genuinely separate parser and is driven by the `with_index=False` tests
        above."""
        import review_index as ri
        import sitrep_survey as ss
        import next_task as nt
        entries = [(n, s) for n, s in enumerate(DECLARED_LIVE + DECLARED_TERMINAL, 1)]
        repo = _repo(tmp_path / "repo", entries)
        want = {n: s for n, s in entries}
        tasks_md = repo / "review_tasks.md"

        data = ri.parse_review_tasks(str(tasks_md))
        assert {int(k): v["status"] for k, v in data["batches"].items()} == want

        assert {b["number"]: b["status"]
                for b in ss._read_review_batches(repo)} == want

        assert {b["number"]: b["status"]
                for b in nt.parse_review_batches(tasks_md.read_text())} == want

        listed = _run(repo, BATCH_WORK, "--list-all").stdout
        for n, status in entries:
            assert status in listed, f"batch {n} ({status}) missing from --list-all"
