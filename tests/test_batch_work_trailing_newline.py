"""`batch_work.sh`'s two `wc -l` line counts (Q-115, Phase 208).

`wc -l` counts **newlines**, not lines. A `review_tasks.md` whose final byte is
not `\\n` therefore reports one fewer line than it has, and both of
`batch_work.sh`'s grep fallbacks use that count as the end of a batch that is the
file's last section. The batch's final task line falls outside
`[start, end]` and is silently skipped.

Phase 198 fixed **one** of the three sites carrying this defect —
`close_batch.sh`'s, which now reads `awk 'END { print NR }'` and is guarded by
``test_close_batch_block_scope.py::TestUnterminated::test_a_task_bullet_as_the_very_last_line_closes``.
`Q-115` stayed open against that already-fixed line number while the two live
sites went unnamed. These are those two sites.

**The two consequences are not the same severity, and only one of them was ever
executed before this phase.**

* The **claim** path (`total_lines`) drives
  ``sed "${batch_start},${batch_end}s/^- \\[ \\]/- [\\/]/"``, so the last task is
  never marked claimed — a miscount.
* The **`--release`** path (`REL_TOTAL`) bounds the ``- [x]`` count that
  implements *"Completed work is not abandonable by default"*. A count bounded
  away from the finished work lets `--release` revert a batch that has results.
  That is a **safety-guard bypass**, not a miscount, and `Q-115` recorded it as
  *"derived by inspection, not execution"*. It was executed for the first time in
  Phase 208 and it reproduces: exit 0, batch reverted to `Pending`, the `- [x]`
  still sitting in the file.

**Not self-healing here.** `Q-115` notes the defect is "partly self-healing"
because the rewrite appends a final newline, so the next run is unaffected. That
is true of `close_batch.sh`, whose `awk` pipeline does append one. It is **false
of both sites in this file**: `batch_work.sh` rewrites via `sed … > tmp; mv`, and
`sed` preserves a missing final newline. Verified with `xxd` — the file still
ends without `\\n` after a claim. So on these two sites the defect is persistent,
and every subsequent claim or release on that tracker stays wrong.

Each case asserts its own fixture really lacks the trailing newline. Writing the
fixture through a helper that appends one is the single edit that would make all
of this vacuous.
"""
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
BATCH_WORK = SCRIPTS / "batch_work.sh"


def _tracker(*, status: str, last_task: str) -> str:
    """A tracker whose batch is the file's LAST section and whose final byte is
    not a newline — the only shape in which `wc -l` and the real line count
    differ at a place that matters."""
    return (
        "# Review Tasks\n"
        "\n"
        f"### Batch 1 — Only batch `{status}`\n"
        "\n"
        "> **Branch:** `feat/one`\n"
        "\n"
        "- [ ] **TASK-1**: not the last line\n"
        f"{last_task}"  # deliberately no trailing newline
    )


def _assert_no_trailing_newline(tracker: str) -> None:
    assert not tracker.endswith("\n"), (
        "This fixture ends with a newline, so `wc -l` and the true line count "
        "agree and the guard below proves nothing."
    )


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root: Path, tasks: str, *, origin: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "review_tasks.md").write_text(tasks)
    (root / "README.md").write_text("# seed\n")
    # Phase 209: `batch_work.sh` retired its inline parser, so `review_index.py`
    # must be present or the script refuses. Installed the way a consumer has it.
    sd = root / "sysop" / "scripts"
    sd.mkdir(parents=True, exist_ok=True)
    for _n in ("review_index.py", "_log.py"):
        _s = SCRIPTS / _n
        if _s.exists():
            shutil.copy(_s, sd / _n)
    # Real consumers ignore the auto-generated index (BeanRider .gitignore:55,
    # gdp-query-system .gitignore:71). Mirror that, or the rebuild this script
    # performs after a mutation leaves an untracked file and every clean-tree
    # assertion below fires on an artifact rather than on a defect.
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


def _run(cwd: Path, *args, env=None):
    import os
    e = dict(os.environ)
    if env:
        e.update(env)
    return subprocess.run(
        ["bash", str(BATCH_WORK), *args],
        cwd=str(cwd), capture_output=True, text=True, env=e,
    )


# ── Site 1: the claim path (`total_lines`) ─────────────────────────────

def test_claim_marks_the_final_task_when_the_file_has_no_trailing_newline(tmp_path):
    tracker = _tracker(status="Pending", last_task="- [ ] **TASK-2**: the file's last byte")
    _assert_no_trailing_newline(tracker)
    repo = _repo(tmp_path / "repo", tracker, origin=True)

    r = _run(repo, "1", env={"WORKTREE_PREFIX": "bw"})
    assert r.returncode == 0, r.stderr
    assert "Claimed Batch 1 on main" in r.stdout, (
        f"The claim never ran, so this guard is vacuous.\n{r.stdout}\n{r.stderr}"
    )

    text = (repo / "review_tasks.md").read_text()
    assert "- [/] **TASK-1**: not the last line" in text, text
    assert "- [/] **TASK-2**: the file's last byte" in text, (
        "The final task was not marked claimed — `wc -l` bounded the batch one "
        f"line short of its own last line.\n{text}"
    )


def test_the_claim_rewrite_does_not_add_the_missing_newline(tmp_path):
    """The 'partly self-healing' note in Q-115 does not hold on this path.

    `close_batch.sh`'s awk pipeline appends a final newline, so a second run
    there is clean. `batch_work.sh` rewrites with `sed … > tmp; mv`, which
    preserves the missing byte — so the defect is persistent here, and a fix
    that relied on self-healing would be wrong.
    """
    tracker = _tracker(status="Pending", last_task="- [ ] **TASK-2**: the file's last byte")
    _assert_no_trailing_newline(tracker)
    repo = _repo(tmp_path / "repo", tracker, origin=True)

    _run(repo, "1", env={"WORKTREE_PREFIX": "bw"})

    raw = (repo / "review_tasks.md").read_bytes()
    assert not raw.endswith(b"\n"), (
        "The claim rewrite appended a trailing newline. If that is now true, this "
        "path really is self-healing and the sibling guard above should be "
        "re-derived rather than trusted."
    )


# ── Site 4: close_batch.sh's short-write guard ─────────────────────────
#
# Phase 208 checked this line, reasoned that `-lt` tolerates awk's appended
# newline, and cleared it. Its own round proved that wrong: `wc -l` also
# UNDER-reports the source when the source has no trailing newline, which spends
# the `-lt` slack in the wrong direction, so a one-line deletion installs through
# the data-loss guard built to stop it.
#
# The short write it defends against cannot be induced through the real pipeline,
# so this drives the guard's ACTUAL shipped expression — extracted from the
# script, not restated here — against crafted files. A restatement would pass
# whatever the script does.

def test_the_short_write_guard_catches_a_loss_on_a_file_with_no_trailing_newline(tmp_path):
    close_batch = REPO_ROOT / "core/companion/scripts/close_batch.sh"
    body = close_batch.read_text(encoding="utf-8")

    marker = '[[ ! -s "$TMP_FILE" ]] || \\\n'
    i = body.index(marker) + len(marker)
    condition = body[i:body.index("; then", i)].strip()
    assert "TMP_FILE" in condition and "TASKS_FILE" in condition, condition

    src = tmp_path / "src"
    out = tmp_path / "out"
    # 3 lines, no trailing newline → `wc -l` says 2, the true count is 3.
    src.write_bytes(b"a\nb\nc")
    # The rewrite lost line "b" but appended a final newline → `wc -l` says 2.
    out.write_bytes(b"a\nc\n")

    script = f'TMP_FILE="{out}"; TASKS_FILE="{src}"\nif {condition}; then echo FIRED; else echo PASSED; fi\n'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "FIRED", (
        "close_batch.sh's short-write guard let a one-line deletion through. On a "
        "source with no trailing newline `wc -l` under-reports it by one, which "
        "cancels the one line of slack the guard allows for awk's appended "
        f"newline.\ncondition = {condition}"
    )


def test_the_short_write_guard_does_not_fire_on_awks_appended_newline(tmp_path):
    """The control. A guard that fires on everything is not a guard — awk
    legitimately grows the count by one when the source lacks a final newline."""
    close_batch = REPO_ROOT / "core/companion/scripts/close_batch.sh"
    body = close_batch.read_text(encoding="utf-8")
    marker = '[[ ! -s "$TMP_FILE" ]] || \\\n'
    i = body.index(marker) + len(marker)
    condition = body[i:body.index("; then", i)].strip()

    src = tmp_path / "src2"
    out = tmp_path / "out2"
    src.write_bytes(b"a\nb\nc")      # 3 lines, no trailing newline
    out.write_bytes(b"a\nb\nc\n")    # same 3 lines, newline appended

    script = f'TMP_FILE="{out}"; TASKS_FILE="{src}"\nif {condition}; then echo FIRED; else echo PASSED; fi\n'
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    assert r.stdout.strip() == "PASSED", (
        f"the guard false-fired on a legal rewrite\ncondition = {condition}"
    )


# ── Site 2: the --release path (`REL_TOTAL`) ───────────────────────────

def test_release_refuses_when_the_completed_task_is_the_files_last_byte(tmp_path):
    """The safety-guard bypass. `Q-115` inferred this one; here it is executed."""
    tracker = _tracker(
        status="In Progress",
        last_task="- [x] **TASK-2**: done, and the file's last byte",
    )
    _assert_no_trailing_newline(tracker)
    repo = _repo(tmp_path / "repo", tracker)

    r = _run(repo, "--release", "1")

    assert r.returncode != 0, (
        "--release reverted a batch holding completed work: `REL_TOTAL` excluded "
        "the `- [x]` line from the count that exists to prevent exactly this.\n"
        f"stdout={r.stdout}\nstderr={r.stderr}"
    )
    assert "completed task(s) marked [x]" in r.stderr, r.stderr
    # …and it refused before touching anything.
    body = (repo / "review_tasks.md").read_text()
    assert "`In Progress`" in body, body
    assert "- [x] **TASK-2**: done, and the file's last byte" in body, body
