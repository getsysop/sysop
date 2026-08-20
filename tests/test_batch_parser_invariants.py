"""The `Q-228` survivors: six invariants around the batch range/parse paths.

Filed 2026-08-16 by Phase 208's round as an 88-row independent battery — these
are the rows the phase did NOT close, kept as a list so they would not be
rediscovered. Every one was verified to survive the whole suite by mutation
before this module existed.

**The row count was wrong in every record that carried it, and the correction
is the reason this module exists at all.** `Q-228`, the runway and the
Phase 211 brief all said *five* remaining rows, on the strength of Phase 209
closing rows (3)+(4). Phase 209's guard (`tests/test_close_awk_fence_masking.py`)
asserts against ``review_index._fenced_mask`` — but the same close-predicate
existed a SECOND time inside ``unterminated_structural_span``, which is the copy
``--check-fences`` actually runs. Mutating that one reported ``fences ok`` over a
file the mask still considered open, with the full suite green. So rows (3)+(4)
were closed for the copy they were not about. Phase 211 removed the duplication
(``_unterminated_fence``) rather than adding a second guard, and pins the
predicate here.

Two rows died rather than being guarded, and that is recorded rather than
silently dropped: `Q-017`'s retirement of `batch_work.sh`'s two grep fallbacks
deleted that script's copies of rows (1), (2) and (7). `close_batch.sh` keeps
its fallback, so each of those rows survives at ONE site instead of three, and
each test below says which.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
CLOSE_BATCH = SCRIPTS / "close_batch.sh"

sys.path.insert(0, str(SCRIPTS))
import review_index as ri  # noqa: E402
sys.path.remove(str(SCRIPTS))


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root: Path, tasks: str, *, index: bool) -> Path:
    """`index=False` is the ONLY way to reach close_batch.sh's grep fallback.

    Phase 209 added an unconditional `review_index.py` copy to a sibling
    module's fixture and silently made three guards vacuous; that is the
    mistake this parameter exists to keep visible.
    """
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "review_tasks.md").write_text(tasks)
    (root / "README.md").write_text("# seed\n")
    sd = root / "sysop" / "scripts"
    sd.mkdir(parents=True, exist_ok=True)
    names = ("review_index.py", "_log.py") if index else ("_log.py",)
    for n in names:
        if (SCRIPTS / n).exists():
            shutil.copy(SCRIPTS / n, sd / n)
    (root / ".gitignore").write_text(".claude/review_index.json\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _close(repo: Path, *args):
    return subprocess.run(["bash", str(CLOSE_BATCH), *args],
                          cwd=str(repo), capture_output=True, text=True)


# ── Rows (3)+(4): the fence-CLOSE predicate, both halves ───────────────

def test_a_longer_opener_is_not_closed_by_a_shorter_marker():
    """Row (3) — the LENGTH half. CommonMark: a closing fence must be at least
    as long as the opener, so ``````` `````` ``` is not closed by ``` ``` ```.
    """
    lines = ["````text", "not closed by the next line", "```", "### Batch 9 — x `Pending`"]
    hit = ri._unterminated_fence(lines)
    assert hit is not None, (
        "a 4-backtick opener was treated as closed by a 3-backtick line; the "
        "length half of the close predicate is gone"
    )
    assert hit == (0, "````"), hit


def test_a_backtick_opener_is_not_closed_by_a_tilde_marker():
    """Row (4) — the MARKER-CHARACTER half. A `~~~` line does not close ```."""
    lines = ["```text", "body", "~~~", "### Batch 9 — x `Pending`"]
    hit = ri._unterminated_fence(lines)
    assert hit is not None, (
        "a backtick fence was treated as closed by a tilde line; the "
        "marker-character half of the close predicate is gone"
    )
    assert hit == (0, "```"), hit


def test_the_close_predicate_accepts_the_legal_closes():
    """Non-vacuity control for both halves above.

    Without this, a predicate that never closes ANY fence passes both tests
    while refusing every legal tracker.
    """
    assert ri._unterminated_fence(["```text", "body", "```", "after"]) is None
    assert ri._unterminated_fence(["````text", "body", "````", "after"]) is None
    # Longer-than-opener is legal too.
    assert ri._unterminated_fence(["```text", "body", "`````", "after"]) is None


def test_the_close_predicate_exists_in_exactly_one_place():
    """Rows (3)+(4) were 'closed' against the wrong copy once already.

    `_fenced_mask` is pinned byte-identical across four parsers by
    `test_flag_contract.py`, and is a separate mechanism. What this asserts is
    that `review_index.py` does not grow a SECOND hand-rolled scan beside it —
    the state that let `--check-fences` and `_fenced_mask` disagree.
    """
    text = (SCRIPTS / "review_index.py").read_text(encoding="utf-8")
    copies = text.count("m.group(1)[0] == marker[0]")
    assert copies == 2, (
        f"expected exactly 2 close-predicate copies (`_fenced_mask` and "
        f"`_unterminated_fence`), found {copies}. A third copy is how rows "
        f"(3)+(4) survived a guard that claimed to close them."
    )


# ── Row (5): the batch-header predicate is the parser's, not a prefix ──

def test_a_two_space_batch_header_is_still_a_batch_header():
    """Row (5) — `_BATCH_HEADER_ANY_RE.match` → `startswith("### Batch ")`.

    Data-reachable: `###  Batch 99` (two spaces) is a legal ATX heading and the
    parser's own regex (`^###\\s+Batch\\s+\\d+`) matches it, while the string
    prefix does not. The docstring on `unterminated_structural_span` claims the
    predicates are "taken from the parser", and this is what enforces that.
    """
    assert ri._BATCH_HEADER_ANY_RE.match("###  Batch 99 — Two spaces `Pending`"), (
        "the parser's own header regex no longer matches a two-space heading"
    )
    assert not "###  Batch 99 — x".startswith("### Batch "), (
        "the fixture no longer distinguishes the regex from the prefix, so this "
        "guard proves nothing"
    )
    span = ri.unterminated_batch_span([
        "# Review Tasks", "", "```markdown", "###  Batch 99 — Two spaces `Pending`",
    ])
    assert span is not None, (
        "a two-space fenced batch header was invisible to the refusal — the "
        "prefix form of this predicate is back"
    )


# ── Row (6): the --range fence preflight ──────────────────────────────

def test_range_refuses_on_a_collision(tmp_path):
    """Row (6) — deleting `_refuse_on_structural_fence()` from the `--range`
    handler had ZERO coverage, for a call defended by a 12-line comment.

    That comment's safety argument USED to be "the callers' `|| true` drops
    them to the grep fallback, which is correct on this shape". Phase 211
    retired `batch_work.sh`'s fallback, so for that caller the refusal is now
    load-bearing rather than advisory — which is why it gets a test.
    """
    repo = _repo(tmp_path / "r6", (
        "# Review Tasks\n\n"
        "### Batch 7 — Real `Merged`\n\n"
        "> **Branch:** `review/real`\n\n"
        "- [x] **TASK-1**: done\n\n"
        "```markdown\n"
        "### Batch 7 — EXAMPLE `Pending`\n\n"
        "- [ ] **TASK-X**: illustration\n"
    ), index=True)
    r = subprocess.run(["python3", "sysop/scripts/review_index.py", "--range", "7"],
                       cwd=str(repo), capture_output=True, text=True)
    assert r.returncode != 0, (
        "`--range` answered over a collision — the preflight is gone and the "
        f"caller receives a range for the fenced example.\nstdout={r.stdout}"
    )


# ── Rows (1), (2), (7): close_batch.sh's surviving grep fallback ───────
#
# `batch_work.sh`'s copies of all three died with Q-017's retirement, so each
# of these guards one site where the filing named three.

_TWO_HEADERS = (
    "# Review Tasks\n\n"
    "### Batch 1 — First `Pending`\n\n"
    "> **Branch:** `review/first`\n\n"
    "- [ ] **TASK-1**: in the first batch\n\n"
    "## Divider\n\n"
    "### Batch 1 — Second `Pending`\n\n"
    "> **Branch:** `review/second`\n\n"
    "- [ ] **TASK-2**: in the second batch\n\n"
    "## Statistics\n\nend\n"
)


def test_the_fallback_takes_the_first_of_two_same_numbered_headers(tmp_path):
    """Row (1) — `head -1` → `tail -1` at close_batch.sh's batch-start grep.

    "The consumer takes the first, the real one" is the claim Phase 208's
    "the fallback degrades to the right answer" argument rests on, and it was
    pinned by nothing. Reached with `index=False`, because the duplicate
    refusal is index-gated and the fallback is the path under test.
    """
    repo = _repo(tmp_path / "r1", _TWO_HEADERS, index=False)
    _close(repo, "1")
    text = (repo / "review_tasks.md").read_text()
    assert "- [x] **TASK-1**: in the first batch" in text, (
        "the fallback did not close the FIRST same-numbered batch — `head -1` "
        f"became `tail -1` and the consumer now takes the later header.\n{text}"
    )
    assert "- [ ] **TASK-2**: in the second batch" in text, (
        f"the close reached into the second batch\n{text}"
    )


def test_batch_1_does_not_match_batch_12(tmp_path):
    """Row (2) — dropping the trailing space from `grep -n "^### Batch ${n} "`."""
    tracker = (
        "# Review Tasks\n\n"
        "### Batch 12 — Twelve `Pending`\n\n"
        "> **Branch:** `review/twelve`\n\n"
        "- [ ] **TASK-12**: belongs to batch 12\n\n"
        "## Divider\n\n"
        "### Batch 1 — One `Pending`\n\n"
        "> **Branch:** `review/one`\n\n"
        "- [ ] **TASK-1**: belongs to batch 1\n\n"
        "## Statistics\n\nend\n"
    )
    repo = _repo(tmp_path / "r2", tracker, index=False)
    _close(repo, "1")
    text = (repo / "review_tasks.md").read_text()
    assert "- [ ] **TASK-12**: belongs to batch 12" in text, (
        "closing Batch 1 reached Batch 12 — the anchoring space is gone from "
        f"the batch-start grep.\n{text}"
    )
    assert "- [x] **TASK-1**: belongs to batch 1" in text, text


def test_the_close_does_not_reach_the_next_batchs_header(tmp_path):
    """Row (7) — the `Q-199` offset in the OVER-reach direction (`- 1` → `+0`).

    The filing called this "harmless only because the boundary line is always a
    heading today, so the guard is directional". This is the other direction:
    with `+0` the range includes the next `^##` line itself, so the following
    batch's header is inside the rewrite window.
    """
    tracker = (
        "# Review Tasks\n\n"
        "### Batch 1 — One `Pending`\n\n"
        "> **Branch:** `review/one`\n\n"
        "- [ ] **TASK-1**: last line of batch 1\n"
        "### Batch 2 — Two `Pending`\n\n"
        "> **Branch:** `review/two`\n\n"
        "- [ ] **TASK-2**: in batch 2\n\n"
        "## Statistics\n\nend\n"
    )
    repo = _repo(tmp_path / "r7", tracker, index=False)
    _close(repo, "1")
    text = (repo / "review_tasks.md").read_text()
    assert re.search(r"^### Batch 2 — Two `Pending`", text, re.M), (
        "closing Batch 1 rewrote Batch 2's header — the range over-reached onto "
        f"the boundary line.\n{text}"
    )


def test_the_fallback_is_actually_reached_by_these_fixtures(tmp_path):
    """The control for rows (1), (2) and (7) together.

    Every test above depends on `index=False` routing through the grep
    fallback. If a later change makes `close_batch.sh` require the index — as
    `batch_work.sh` already does — these guards go vacuous exactly the way
    `test_batch_range_offset_guard.py` did, and this is what says so.
    """
    repo = _repo(tmp_path / "ctl", _TWO_HEADERS, index=False)
    assert not (repo / "sysop" / "scripts" / "review_index.py").exists()
    r = _close(repo, "1")
    text = (repo / "review_tasks.md").read_text()
    assert "`Merged`" in text, (
        "close_batch.sh no longer closes anything without review_index.py, so "
        "the grep fallback is unreachable and rows (1), (2) and (7) above are "
        f"vacuous.\nstdout={r.stdout}\nstderr={r.stderr}"
    )
