"""The offset arithmetic at the end of every grep-fallback batch range (Q-199, Phase 208).

All three shell fallbacks bound a batch the same way::

    offset_end=$(tail -n +"$((START + 1))" "$TASKS_FILE" | grep -n '^##' | head -1 | cut -d: -f1)
    BATCH_END=$((START + offset_end - 1))

The arithmetic is **correct**: ``tail -n +$((S+1))`` starts at file line ``S+1``,
so the tail's k-th line is file line ``S+k``; the first ``^##`` is therefore at
``S+k``, and the batch's last line is the one before it, ``S+k-1``.

`Q-199` is not a claim that the arithmetic is wrong. It is a claim that **nothing
guards it** — the twin of the ``wc -l`` defect Phase 198 fixed one line above,
carrying the same three symptoms (batch flips, last task stays ``[ ]``, count
under-reports) and killed by no test.

**Why the corpus could not see it.** The mutation is only observable when the
batch's final line is a **task checkbox** that sits *immediately* before the next
``^##`` heading. Derived over every triple-quoted fixture in ``tests/`` at the
time of writing: **zero** had that shape. Every fixture separates its last task
from the next heading with a blank line, and a blank line is exactly what the
off-by-one consumes harmlessly. So ``- 1`` → ``- 2`` survived the entire suite at
all three sites simultaneously.

That is also why each case below asserts the *shape of its own input* before
asserting behaviour. A later fixture reformat that reinserts the blank line would
otherwise make all three guards silently vacuous again — the Phase 207 lesson
that non-emptiness is not substance, applied to a fixture rather than a roster.

The three sites are guarded separately because they are three copies, not one
call: a fix applied to one is not a fix applied to the others, which is the whole
reason `Q-115` had to be re-scoped after Phase 198 patched a single site.
"""
import re
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLOSE_BATCH = REPO_ROOT / "core/companion/scripts/close_batch.sh"
SCRIPTS = REPO_ROOT / "core/companion/scripts"
BATCH_WORK = SCRIPTS / "batch_work.sh"


# ── The shape that makes the mutation observable ───────────────────────
#
# A task checkbox as the batch's LAST line, with the next `^##` heading on the
# very next line. No blank line between them — that blank line is what every
# pre-existing fixture had, and what made the off-by-one invisible.

def _tracker(*, status: str, last_task: str, branch: bool = True) -> str:
    return (
        "# Review Tasks\n"
        "\n"
        f"### Batch 1 — Offset boundary `{status}`\n"
        "\n"
        + ("> **Branch:** `feat/one`\n\n" if branch else "")
        + "- [ ] **TASK-1**: not the last line\n"
        f"{last_task}\n"
        "## Statistics\n"
        "\n"
        "Trailing section so the batch is NOT the file's last.\n"
    )


TASK_THEN_HEADING_RE = re.compile(r"^- \[[ x/]\] .*\n^## ", re.MULTILINE)


def _assert_shape_is_still_hostile(tracker: str) -> None:
    """The input assertion. Without it these guards go vacuous on a reformat."""
    assert TASK_THEN_HEADING_RE.search(tracker), (
        "This fixture no longer places a task checkbox immediately before the next "
        "`##` heading, so the `- 1` offset is unobservable and this guard proves "
        "nothing. Restore the shape before touching the assertion below."
    )


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root: Path, tasks: str, *, origin: bool = False, index: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "review_tasks.md").write_text(tasks)
    (root / "README.md").write_text("# seed\n")
    # Phase 209: `batch_work.sh` retired its inline parser, so `review_index.py`
    # must be present or the script refuses. The .gitignore mirrors a real
    # consumer, which ignores the auto-generated index.
    #
    # Phase 211: that copy is ALSO what made this module vacuous. With the index
    # present `--range` answers and the shell fallback is never taken, so the
    # offset arithmetic these guards name is unreachable — mutating
    # `close_batch.sh`'s `- 1` to `- 2` left all three green. `index=False` is
    # the only way to reach `close_batch.sh`'s fallback, which is the sole
    # surviving copy of that arithmetic.
    sd = root / "sysop" / "scripts"
    sd.mkdir(parents=True, exist_ok=True)
    _names = ("review_index.py", "_log.py") if index else ("_log.py",)
    for _n in _names:
        _s = SCRIPTS / _n
        if _s.exists():
            shutil.copy(_s, sd / _n)
    (root / ".gitignore").write_text(".claude/review_index.json\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    if origin:
        bare = root.parent / "origin.git"
        subprocess.run(["git", "init", "--bare", "-q", str(bare)],
                       check=True, capture_output=True)
        _git(root, "remote", "add", "origin", str(bare))
        _git(root, "push", "-q", "origin", "main")
    return root


def _run(script: Path, cwd: Path, *args, env=None):
    import os
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        ["bash", str(script), *args],
        cwd=str(cwd), capture_output=True, text=True, env=e,
    )


# ── Site 1: close_batch.sh's find_batch_range ──────────────────────────

def test_close_flips_the_task_on_the_batchs_final_line(tmp_path):
    """`close_batch.sh` via the INDEX path — the last task must close.

    Guards `review_index.py --range`'s boundary, not the shell arithmetic. Kept
    separate from the fallback case below because they are two different range
    computations reached by two different conditions, and only one of them
    contains the `- 1`.
    """
    tracker = _tracker(status="Pending", last_task="- [ ] **TASK-2**: the batch's last line")
    _assert_shape_is_still_hostile(tracker)
    repo = _repo(tmp_path / "repo", tracker)

    r = _run(CLOSE_BATCH, repo, "1")

    text = (repo / "review_tasks.md").read_text()
    assert "- [x] **TASK-1**: not the last line" in text, text
    assert "- [x] **TASK-2**: the batch's last line" in text, (
        "The batch's final task line was left open — the index bounded the range "
        f"one line short.\nstdout={r.stdout}\nstderr={r.stderr}\n{text}"
    )


def test_close_flips_the_final_line_through_the_grep_fallback(tmp_path):
    """`close_batch.sh` with NO index — the surviving copy of the `- 1`.

    This is the case the module was written for and the one Phase 209 silently
    disarmed. `close_batch.sh` keeps its grep fallback (unlike `batch_work.sh`,
    whose two copies Phase 211 retired), and `index=False` is the only condition
    that reaches it. Mutating `BATCH_END=$((BATCH_START + offset_end - 1))` to
    `- 2` must red THIS test; with the index present it reds nothing.
    """
    tracker = _tracker(status="Pending", last_task="- [ ] **TASK-2**: the batch's last line")
    _assert_shape_is_still_hostile(tracker)
    repo = _repo(tmp_path / "repo", tracker, index=False)

    r = _run(CLOSE_BATCH, repo, "1")

    text = (repo / "review_tasks.md").read_text()
    assert not (repo / "sysop" / "scripts" / "review_index.py").exists(), (
        "The index is present, so `--range` answered and the grep fallback was "
        "never taken — this guard is vacuous again."
    )
    assert "- [x] **TASK-1**: not the last line" in text, text
    assert "- [x] **TASK-2**: the batch's last line" in text, (
        "The batch's final task line was left open — the grep fallback's offset "
        f"bounded the range one line short.\nstdout={r.stdout}\nstderr={r.stderr}\n{text}"
    )


# ── Site 2: batch_work.sh's claim path — fallback RETIRED (Q-017) ───────

def test_claim_marks_the_task_on_the_batchs_final_line(tmp_path):
    """`batch_work.sh <N>` — the last task must be marked claimed.

    The claim path now has one range computation, `--range`. A reachable origin
    is required: without one the `git pull --ff-only` guard returns *before* the
    range is ever computed, and the case would pass while exercising nothing.
    """
    tracker = _tracker(status="Pending", last_task="- [ ] **TASK-2**: the batch's last line")
    _assert_shape_is_still_hostile(tracker)
    repo = _repo(tmp_path / "repo", tracker, origin=True)

    r = _run(BATCH_WORK, repo, "1", env={"WORKTREE_PREFIX": "bw"})
    assert r.returncode == 0, r.stderr
    assert "Claimed Batch 1 on main" in r.stdout, (
        "The claim did not run, so the range was never computed and this guard is "
        f"vacuous.\nstdout={r.stdout}\nstderr={r.stderr}"
    )

    text = (repo / "review_tasks.md").read_text()
    assert "- [/] **TASK-1**: not the last line" in text, text
    assert "- [/] **TASK-2**: the batch's last line" in text, (
        "The batch's final task line was not marked claimed — the range bounded "
        f"one line short.\n{text}"
    )


# ── Site 3: batch_work.sh --release ────────────────────────────────────

def test_release_counts_completed_work_on_the_batchs_final_line(tmp_path):
    """`batch_work.sh --release <N>` — the last `- [x]` must be counted.

    This is the site where a short range is a **safety-guard bypass** rather
    than a miscount: `REL_DONE` bounded away from the finished work lets
    `--release` revert a batch that has results, which the guard at the
    `Completed work is not abandonable by default` comment exists to prevent.
    """
    tracker = _tracker(
        status="In Progress",
        last_task="- [x] **TASK-2**: done, and the batch's last line",
    )
    _assert_shape_is_still_hostile(tracker)
    repo = _repo(tmp_path / "repo", tracker)

    r = _run(BATCH_WORK, repo, "--release", "1")

    assert r.returncode != 0, (
        "--release succeeded on a batch whose completed task sits on its final "
        f"line — the range excluded that line from the `- [x]` count.\n"
        f"stdout={r.stdout}\nstderr={r.stderr}"
    )
    assert "completed task(s) marked [x]" in r.stderr, r.stderr
    # …and it refused *before* touching anything.
    assert "`In Progress`" in (repo / "review_tasks.md").read_text()


# ── The near-miss header: the two scripts disagree, and that is Q-017 ──
#
# `_BATCH_HEADER_RE` demands an em-dash and a backticked status; the grep
# `^### Batch N ` demands neither. Phase 211 checked which paths that shape
# actually reaches instead of assuming, because the first cut of this section
# asserted a refusal `batch_work.sh` already produced for a different reason.

def _near_miss_tracker(status: str) -> str:
    """A header with an ASCII hyphen where the index requires an em-dash."""
    return (
        "# Review Tasks\n"
        "\n"
        f"### Batch 1 - Hyphen not em-dash `{status}`\n"
        "\n"
        "> **Branch:** `feat/one`\n"
        "\n"
        "- [ ] **TASK-1**: first\n"
        "- [ ] **TASK-2**: the batch's last line\n"
        "## Statistics\n"
        "\n"
        "Trailing section.\n"
    )


def test_claim_refuses_a_header_the_index_cannot_match(tmp_path):
    """`batch_work.sh` refuses the near-miss — and writes nothing.

    NOT a Phase 211 behaviour change: the status lookup upstream of the range
    block already refused this shape, which is why retiring the grep fallback
    could not be justified by it. Pinned because the refusal is the correct
    half of the asymmetry the next test records, and nothing else asserts it.
    """
    repo = _repo(tmp_path / "repo", _near_miss_tracker("Pending"), origin=True)

    r = _run(BATCH_WORK, repo, "1", env={"WORKTREE_PREFIX": "bw"})

    assert r.returncode != 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "not found in review_tasks.md" in r.stderr, r.stderr
    text = (repo / "review_tasks.md").read_text()
    assert "- [ ] **TASK-1**: first" in text, text
    assert "`Pending`" in text, text
    locks = repo / "sysop" / "runtime" / "locks"
    assert not locks.exists() or not list(locks.glob("BATCH-*.lock"))


def test_close_still_closes_a_header_the_index_cannot_match(tmp_path):
    """`close_batch.sh` closes it anyway, through its surviving grep fallback.

    This is Q-017's remaining half, pinned as CURRENT BEHAVIOUR rather than as
    an endorsement — the twin of
    ``test_without_python3_behaviour_is_the_old_behaviour``. The index cannot
    see this batch, so the range came from a fence-BLIND grep; on a tracker
    carrying a fenced example that range can over-reach. Retiring this fallback
    is a caller-contract change (`if ! find_batch_range` cannot observe a return
    code), deliberately not taken here.

    If a later phase retires it, this test must flip to asserting a refusal.
    """
    repo = _repo(tmp_path / "repo", _near_miss_tracker("Pending"))

    r = _run(CLOSE_BATCH, repo, "1")

    text = (repo / "review_tasks.md").read_text()
    assert "`Merged`" in text, (
        "close_batch.sh no longer closes an index-invisible batch. If that was "
        f"deliberate, this pin is the thing to update.\nstderr={r.stderr}\n{text}"
    )
    assert "- [x] **TASK-2**: the batch's last line" in text, text
