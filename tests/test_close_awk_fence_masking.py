"""CLOSE_AWK must not close a task that lives inside a fenced block (Q-017).

`review_index.py --range` has been fence-aware since Phase 181. `CLOSE_AWK` —
the program that actually rewrites the checkboxes inside that range — was not,
and contains no backtick or tilde token anywhere in its body. So the
fence-awareness in the parser bought nothing for the rewriter.

Measured 2026-08-16 on the fixture below, before the fix:

    index present  ->  "4 tasks closed" on a THREE-task batch, with the fenced
                       documentation example marked [x]
    index absent   ->  "1 tasks closed", TASK-202 and TASK-303 left open under
                       a `Merged` header

Both wrong, in opposite directions. `Q-017` is filed against the second and
prescribes routing the shells through `--range` as its "cheapest fix" — which
would have swapped a silent under-reach for silent data corruption. The real
fix is here, in the rewriter.

The mask is not recomputed in awk. `review_index.py --fenced-lines` exports
`_fenced_mask` itself, because a fence parser written in awk would be a SIXTH
implementation of a rule that already exists four times in Python and had two
divergent copies in bash — the exact defect class this phase removes.
"""
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
CLOSE_BATCH = SCRIPTS / "close_batch.sh"

FENCED_BODY = """\
# Review tasks

## Round 1 — 2026-08-16

### Batch 5 — Fenced-body batch `Pending`
> **Branch:** `review/batch-5`
> **Scope:** src/thing.py
> **Verify:** pytest -q

- [ ] **TASK-101** first real task

An example of a deferred section, quoted from the docs:

```markdown
## Deferred
- [ ] **TASK-999** this is a DOC EXAMPLE, not real work
```

- [ ] **TASK-202** second real task
- [ ] **TASK-303** third real task

## Statistics
"""

# Identical, minus the fenced block. The control: closing must be unchanged.
NO_FENCE_BODY = """\
# Review tasks

## Round 1 — 2026-08-16

### Batch 5 — Plain batch `Pending`
> **Branch:** `review/batch-5`
> **Scope:** src/thing.py
> **Verify:** pytest -q

- [ ] **TASK-101** first real task
- [ ] **TASK-202** second real task
- [ ] **TASK-303** third real task

## Statistics
"""


def _git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(cwd), check=check,
                          capture_output=True, text=True)


def _repo(root, tasks, *, with_index=True):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "review_tasks.md").write_text(tasks)
    (root / ".gitignore").write_text(".claude/review_index.json\n")
    sd = root / "sysop" / "scripts"
    sd.mkdir(parents=True, exist_ok=True)
    names = ["close_batch.sh", "_log.py", "_git_lib.sh"] + (["review_index.py"] if with_index else [])
    for name in names:
        src = SCRIPTS / name
        if src.exists():
            shutil.copy(src, sd / name)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    _git(root, "branch", "review/batch-5")
    return root


def _close(cwd, *args):
    return subprocess.run(["bash", str(CLOSE_BATCH), *args], cwd=str(cwd),
                          capture_output=True, text=True)


def _boxes(repo):
    """Map TASK id -> checkbox char, from the file after the run."""
    out = {}
    for line in (repo / "review_tasks.md").read_text().splitlines():
        s = line.strip()
        if s.startswith("- [") and "**TASK-" in s:
            tid = s.split("**TASK-")[1].split("**")[0]
            out["TASK-" + tid] = s[3]
    return out


def test_a_fenced_task_is_not_closed(tmp_path):
    """The defect, exactly: TASK-999 exists only inside a fenced example."""
    repo = _repo(tmp_path / "fenced", FENCED_BODY)
    r = _close(repo, "--force", "5")
    assert r.returncode == 0, r.stderr
    boxes = _boxes(repo)
    assert boxes["TASK-999"] == " ", \
        "a task inside a fenced documentation example was marked complete"
    for real in ("TASK-101", "TASK-202", "TASK-303"):
        assert boxes[real] == "x", f"{real} is real work and must close"


def test_the_reported_count_matches_the_real_tasks(tmp_path):
    """The count and the rewrite share one gate, so they cannot disagree.

    Pinned separately from the checkboxes because the count feeds the Grand
    Total: a batch that closes the right boxes while reporting the wrong number
    still corrupts the totals that describe it.
    """
    repo = _repo(tmp_path / "count", FENCED_BODY)
    r = _close(repo, "--force", "5")
    assert "(3 tasks closed)" in r.stdout, \
        f"expected 3 real tasks, got: {r.stdout}"


def test_the_fenced_line_is_preserved_byte_for_byte(tmp_path):
    """Skipped, never dropped. The fenced task still has to be reprinted."""
    repo = _repo(tmp_path / "bytes", FENCED_BODY)
    before = (repo / "review_tasks.md").read_text().splitlines()
    _close(repo, "--force", "5")
    after = (repo / "review_tasks.md").read_text().splitlines()
    assert len(before) == len(after), "the rewrite changed the line count"
    original = "- [ ] **TASK-999** this is a DOC EXAMPLE, not real work"
    assert original in after, "the fenced task line was altered or lost"


def test_a_batch_with_no_fence_closes_exactly_as_before(tmp_path):
    """THE CONTROL. Reds if the mask ever over-reaches and starts skipping real
    tasks — the failure direction that would be worse than the bug, since it
    leaves completed work looking unfinished."""
    repo = _repo(tmp_path / "plain", NO_FENCE_BODY)
    r = _close(repo, "--force", "5")
    assert r.returncode == 0, r.stderr
    assert "(3 tasks closed)" in r.stdout, r.stdout
    assert all(c == "x" for c in _boxes(repo).values()), \
        "the mask skipped a task that is not inside any fence"


def test_fenced_lines_export_names_the_fence_interior(tmp_path):
    """`--fenced-lines` is the seam between the one fence implementation and
    awk. If it drifts, the guard above silently stops guarding."""
    repo = _repo(tmp_path / "export", FENCED_BODY)
    r = subprocess.run([sys.executable, str(repo / "sysop/scripts/review_index.py"),
                        "--fenced-lines"], cwd=str(repo), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    nums = [int(x) for x in r.stdout.strip().split(",") if x]
    lines = (repo / "review_tasks.md").read_text().splitlines()
    assert nums, "no fenced lines reported for a file that has a fence"

    # EXACT identity against `_fenced_mask`, not membership. A membership test
    # ("the example is in the set, the real tasks are not") passes under a
    # one-line shift, because the shifted span still happens to contain the
    # example — battery row A07 survived exactly that weaker assertion. The
    # expected set is DERIVED from the shipped mask rather than written out, so
    # it cannot drift from the implementation it is checking.
    sys.path.insert(0, str(repo / "sysop/scripts"))
    for mod in ("review_index",):
        sys.modules.pop(mod, None)
    import review_index as ri
    expected = [i + 1 for i, m in enumerate(ri._fenced_mask(lines)) if m]
    assert nums == expected, (
        f"exported mask {nums} != _fenced_mask {expected} — an off-by-one here "
        "silently shifts which lines the rewriter protects"
    )

    # And the boundary is pinned explicitly: the fence DELIMITERS are masked
    # too, so the first and last reported lines must be the ``` lines
    # themselves. This is what a shift breaks first.
    assert lines[nums[0] - 1].startswith("```"), \
        f"first masked line is {lines[nums[0] - 1]!r}, not a fence opener"
    assert lines[nums[-1] - 1].startswith("```"), \
        f"last masked line is {lines[nums[-1] - 1]!r}, not a fence closer"

    target = next(i + 1 for i, ln in enumerate(lines) if "TASK-999" in ln)
    assert target in nums, "the fenced task line is not in the exported mask"
    for real in ("TASK-101", "TASK-202", "TASK-303"):
        i = next(i + 1 for i, ln in enumerate(lines) if real in ln)
        assert i not in nums, f"{real} was masked but is not inside a fence"


def test_the_fence_close_predicate_needs_both_marker_char_and_length(tmp_path):
    """Battery rows B03/B04, and `Q-228` rows 3-4 filed them as unguarded.

    Pre-existing, but this phase made `--fenced-lines` depend on the predicate,
    so a tracker whose fence "closes" with the wrong marker now decides which
    tasks `close_batch.sh` rewrites. Both halves are attacked independently
    because dropping either one alone leaves the other passing.
    """
    sys.path.insert(0, str(SCRIPTS))
    import review_index as ri

    # A ~~~ must NOT close a ``` fence (marker CHAR).
    mixed = ["```markdown", "- [ ] **TASK-999** example", "~~~", "- [ ] **TASK-1** real"]
    mask = ri._fenced_mask(mixed)
    assert not any(mask), (
        "a ~~~ closed a ``` fence, so the span is treated as balanced and its "
        "contents become structural"
    )

    # A 3-backtick line must NOT close a 4-backtick fence (marker LENGTH).
    short = ["````markdown", "- [ ] **TASK-999** example", "```", "- [ ] **TASK-1** real"]
    assert not any(ri._fenced_mask(short)), \
        "a shorter delimiter closed a longer fence"

    # Control: a correct close DOES mask, or the two asserts above would pass
    # on a mask function that never returns True at all.
    good = ["```markdown", "- [ ] **TASK-999** example", "```", "- [ ] **TASK-1** real"]
    assert ri._fenced_mask(good) == [True, True, True, False], \
        "a correctly-closed fence must mask its interior and delimiters"


def test_without_python3_behaviour_is_the_old_behaviour(tmp_path):
    """Fails to the PRE-EXISTING state, not to a new one.

    With no `review_index.py`, `FENCED_LINES` is empty and `close_batch.sh`
    falls back to its grep range — which under-reaches. That is Q-017's filed
    defect.

    **Scoped 2026-08-26 (Phase 233): this is now the ONLY arm where it survives.**
    `Q-017` was closed on the `fallback` arm by filtering the boundary search
    through `$FENCED_LINES` — the same mask `CLOSE_AWK` rewrites around. That
    mask needs `python3` and `$INDEX_SCRIPT`, which is precisely what this test
    removes, so there is nothing to filter with here and the pre-existing
    answer is the honest degradation.

    Still pinned, for the reason it always was: so a phase cannot be read as
    having closed what it did not. See
    `tests/test_batch_header_near_miss.py::test_the_fence_blind_claim_is_made_only_on_the_arm_where_it_is_true`,
    which asserts the warning names the right arm in both directions.
    """
    repo = _repo(tmp_path / "noindex", FENCED_BODY, with_index=False)
    r = _close(repo, "--force", "5")
    assert r.returncode == 0, r.stderr
    boxes = _boxes(repo)
    assert boxes["TASK-999"] == " ", "the doc example must never close"
    assert boxes["TASK-101"] == "x"
    # The under-reach: the grep range stops at the fenced `## Deferred`.
    assert boxes["TASK-202"] == " " and boxes["TASK-303"] == " ", (
        "this asserts the KNOWN-BAD fallback behaviour on purpose — if it now "
        "closes them, the fallback was fixed and this test should be rewritten, "
        "not deleted"
    )


def test_the_source_reader_preserves_leading_indentation():
    """`_read_source_lines` must strip only the newline. Round finding L08.

    `_FENCE_OPEN_RE` is anchored `^ {0,3}` by CommonMark design — four spaces of
    indentation makes an indented code block, not a fence, and `Q-037`'s own
    amendment turns on exactly that rule. So a reader that strips leading
    whitespace silently promotes indented example blocks into real fences and
    changes which lines `--fenced-lines` tells the rewriter to protect.

    Mutating `rstrip("\\n")` to `strip()` left the whole suite green.
    """
    import tempfile, os
    sys.path.insert(0, str(SCRIPTS))
    import review_index as ri
    body = "# R\n\n    ```markdown\n    not a fence: indented 4 spaces\n    ```\n\n- [ ] **TASK-1** real\n"
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(body)
        path = fh.name
    try:
        lines = ri._read_source_lines(path)
        assert lines[2].startswith("    ```"), \
            f"leading indentation was lost: {lines[2]!r}"
        # ...and the consequence: at 4 spaces there is no fence, so nothing masks.
        assert not any(ri._fenced_mask(lines)), (
            "a 4-space-indented block was treated as a fence — CommonMark makes "
            "it an indented code block, and _FENCE_OPEN_RE is ^ {0,3} for that reason"
        )
    finally:
        os.unlink(path)
