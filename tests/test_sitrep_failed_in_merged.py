"""`/sitrep` names the tasks `close_batch.sh` left open with `> Failed:` (`Q-118`).

A FAIL verdict leaves the task open in a batch that still becomes `Merged`
(Phase 157). `/next-task` and `/sitrep`'s routing read `Pending` batches only,
so before this nothing automated named such a task again. Wade's ruling
(2026-09-30): `/sitrep` reports them with their ids; nothing routes or blocks.

The oracle for WHICH tasks count is `close_batch.sh` itself: the parity test
runs its `CLOSE_AWK` in count mode over the same text and compares the `HELD`
tasks it reports. A reader that disagreed with the script that held the tasks
would name the wrong ones.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "core" / "companion" / "scripts"))

import sitrep_survey as ss  # noqa: E402

CLOSE_BATCH = REPO_ROOT / "core" / "companion" / "scripts" / "close_batch.sh"

CORPUS = """\
# Review tasks

### Batch 1 — Merged with failures `Merged`
> **Branch:** `review/one`

- [x] **TASK-0001**: closed normally
- [ ] **TASK-0002**: failed, annotation directly under the task
> Failed: the test still errors
- [ ] **TASK-0003**: failed, annotation after an indented continuation
  `src/app.py:12` — provenance line
  > **FAILED**: judge said no
- [ ] unbolded task that failed
  > failed : spacing before the colon
- [ ] **TASK-0004**: open, no annotation
- [ ] **TASK-0005**: annotation detached by a blank line

> Failed: orphaned, protects nothing
- [x] **TASK-0006**: closed, its annotation is ignored
> Failed: a closed box is not held
- [/] **TASK-0007**: in progress, then failed
  > _Failed_: emphasis around the word
- [ ] **TASK-0008**: a near spelling, which close_batch.sh reports and closes
  > Fail: not the annotation word

```markdown
- [ ] **TASK-0099**: an example inside a fence
> Failed: example annotation
```

### Batch 9 - a header the strict pattern rejects, still pending `Pending`

- [ ] **TASK-0090**: failed under batch 9, which must not be read as batch 1's
> Failed: belongs to batch 9

### Batch 3 — Being worked `In Progress`
> **Branch:** `review/three`

- [ ] **TASK-0030**: failed in an in-progress batch, which the routers already see
> Failed: not this counter's business either

### Batch 2 — Still pending `Pending`
> **Branch:** `review/two`

- [ ] **TASK-0010**: failed in a pending batch, which the routers already see
> Failed: not this counter's business

### Batch 6 — Merged right before a section `Merged`
- [ ] **TASK-0060**: directly under the header, no metadata between
> Failed: still broken
- [ ] **TASK-0061**: annotated twice, counted once
> Failed: once
> Failed: twice
- [ ] **TASK-0062**: column-0 prose ends the block
plain prose at column 0
> Failed: after the prose, so orphaned
- [ ] **TASK-0063**: a whitespace-only line ends the block
<WS>
> Failed: after it, so orphaned

## Deferred

- [ ] **TASK-0020**: deferred, outside every batch
> Failed: outside every batch
""".replace("<WS>", "   ")

EXPECTED_BATCH_1 = [
    "TASK-0002",
    "TASK-0003",
    "unbolded task that failed",
    "TASK-0007",
]
EXPECTED_BATCH_6 = ["TASK-0060", "TASK-0061"]


def _write(tmp_path: Path, text: str) -> list[dict]:
    (tmp_path / "review_tasks.md").write_text(text, encoding="utf-8")
    return ss._read_review_batches(tmp_path)


def test_failed_tasks_in_a_merged_batch_are_named(tmp_path):
    batches = {b["number"]: b for b in _write(tmp_path, CORPUS)}
    assert batches[1]["failed_open"] == EXPECTED_BATCH_1
    assert batches[6]["failed_open"] == EXPECTED_BATCH_6


def test_only_a_merged_batch_contributes(tmp_path):
    batches = {b["number"]: b for b in _write(tmp_path, CORPUS)}
    assert batches[2]["failed_open"] == []  # Pending
    assert batches[3]["failed_open"] == []  # In Progress


def test_run_survey_reports_every_failed_task_of_every_merged_batch(tmp_path, monkeypatch):
    """The survey carries what the reader found, all of it, keyed by batch."""
    (tmp_path / "review_tasks.md").write_text(
        CORPUS + "\n### Batch 4 — Another merged one `Merged`\n\n"
        "- [ ] **TASK-0040**: failed too\n> Failed: still broken\n"
        "\n### Batch 5 - a near-miss header `Merged`\n\n"
        "- [ ] **TASK-0050**: failed under it\n> Failed: still broken\n", encoding="utf-8")
    monkeypatch.setattr(ss, "_resolve_main_repo_root", lambda: tmp_path)
    monkeypatch.setattr(ss, "_git", lambda *a, **k: "abc1234")
    monkeypatch.setattr(ss, "resolve_default_branch", lambda root: "main")
    monkeypatch.setattr(ss, "_read_worktrees", lambda root: [])
    monkeypatch.setattr(ss, "_read_index", lambda root, unreadable=None: {})
    monkeypatch.setattr(ss, "_read_locks", lambda root, unreadable=None: [])
    monkeypatch.setattr(ss, "_find_discrepancies", lambda *a, **k: [])
    survey = ss.run_survey()
    assert survey.failed_in_merged_batches == (
        [(1, task) for task in EXPECTED_BATCH_1] + [(6, task) for task in EXPECTED_BATCH_6]
        + [(4, "TASK-0040"), (5, "TASK-0050")])


def test_no_annotation_means_not_counted(tmp_path):
    text = CORPUS.replace("> Failed:", "> Note:").replace("> **FAILED**:", "> Note:")
    text = text.replace("> failed :", "> Note:").replace("> _Failed_:", "> Note:")
    batches = {b["number"]: b for b in _write(tmp_path, text)}
    assert batches[1]["failed_open"] == []


def _close_awk() -> str:
    m = re.search(r"^readonly CLOSE_AWK='\n(.*?)^'\n", CLOSE_BATCH.read_text(), re.S | re.M)
    assert m, "close_batch.sh no longer defines CLOSE_AWK in the shape this test extracts"
    return m.group(1)


@pytest.mark.skipif(shutil.which("awk") is None or shutil.which("git") is None,
                    reason="awk or git not on PATH")
def test_parity_with_close_batch_held_tasks(tmp_path):
    """The tasks named are exactly the ones `close_batch.sh`'s count pass HOLDS, over
    the range `close_batch.sh` itself takes: `review_index.py --range`, not the
    survey's own (round, lens B: handing awk the survey's range could not see the two
    disagree)."""
    repo = tmp_path / "repo"
    (repo / "sysop" / "scripts").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "core" / "companion" / "scripts" / "review_index.py",
                 repo / "sysop" / "scripts" / "review_index.py")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    path = repo / "review_tasks.md"
    path.write_text(CORPUS, encoding="utf-8")
    batches = {b["number"]: b for b in ss._read_review_batches(repo)}
    lines = CORPUS.split("\n")
    fenced = ss._fenced_mask(lines)
    fenced_list = ",".join(str(i + 1) for i, f in enumerate(fenced) if f)
    merged = sorted(n for n, b in batches.items() if b["status"] == "Merged")
    assert merged == [1, 6]
    for n in merged:
        rng = subprocess.run([sys.executable, "sysop/scripts/review_index.py", "--range", str(n)],
                             cwd=repo, capture_output=True, text=True, check=True).stdout.split("\t")
        s, e = int(rng[0]), int(rng[1])
        assert (s, e) == (batches[n]["line_start"] + 1, batches[n]["line_end"])
        r = subprocess.run(
            ["awk", "-v", f"s={s}", "-v", f"e={e}", "-v", "mode=count",
             "-v", f"fenced={fenced_list}", _close_awk(), str(path)],
            capture_output=True, text=True, check=True,
        )
        held = []
        for diag in r.stderr.splitlines():
            if diag.startswith("HELD "):
                m = ss._OPEN_TASK_LABEL_RE.match(diag.split(" ", 2)[2])
                held.append((m.group("bold") or m.group("plain")).strip()[:60])
        assert held == batches[n]["failed_open"]
        assert held == {1: EXPECTED_BATCH_1, 6: EXPECTED_BATCH_6}[n]


def _survey(failed, open_ids=()):
    from datetime import datetime, timezone
    return ss.Survey(
        timestamp=datetime.now(timezone.utc), main_root=Path("/x"), head_short="abc",
        tasks=[], review_batches=[], discrepancies=[], stale_days=7,
        open_roadmap_ids=list(open_ids), failed_in_merged_batches=failed,
    )


def test_text_report_names_each_failed_task():
    out = ss.render_text(_survey([(1, "TASK-0002"), (3, "unbolded task")]))
    assert "FAILED IN MERGED BATCHES (2)" in out
    assert "Batch 1      TASK-0002" in out
    assert "Batch 3      unbolded task" in out
    assert "no other reader routes these back" in out


def test_text_report_is_silent_when_there_are_none():
    assert "FAILED IN MERGED BATCHES" not in ss.render_text(_survey([]))


def test_json_carries_the_failed_tasks():
    import json
    payload = json.loads(ss.render_json(_survey([(1, "TASK-0002")])))
    assert payload["failed_in_merged_batches"] == [{"batch_number": 1, "task": "TASK-0002"}]


@pytest.mark.parametrize("open_ids", [(), ("FEAT-1", "FEAT-2")])
def test_the_counter_never_routes(open_ids):
    """Wade ruled a counter: the recommendation and the suggested order are the same with
    or without one. The non-idle case matters: idle returns None on both sides (lens B)."""
    a, b = _survey([], open_ids), _survey([(1, "TASK-0002")], open_ids)
    ra, rb = ss._recommended_next(a), ss._recommended_next(b)
    assert (ra and (ra.command, ra.reason)) == (rb and (rb.command, rb.reason))
    assert ss._suggested_order(a) == ss._suggested_order(b)


# A header the strict pattern rejects is still closed by close_batch.sh, through
# its `find_batch_range` fallback (lens A of Phase 357's round). The survey must
# name what it held there too, so this runs the real script and compares.
NEAR_MISS_HEADERS = [
    "### Batch 1 - ASCII hyphen `Pending`",
    "### Batch 1 — trailing space after the status `Pending` ",
]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
@pytest.mark.parametrize("header", NEAR_MISS_HEADERS)
def test_a_near_miss_header_closed_by_close_batch_is_reported(tmp_path, header):
    repo = tmp_path / "repo"
    (repo / "sysop" / "scripts").mkdir(parents=True)
    for f in (REPO_ROOT / "core" / "companion" / "scripts").iterdir():
        if f.is_file():
            shutil.copy2(f, repo / "sysop" / "scripts" / f.name)
    (repo / "review_tasks.md").write_text(
        "# Review tasks\n\n" + header + "\n\n"
        "- [ ] **TASK-0001**: fine\n"
        "- [ ] **TASK-0002**: failed\n"
        "> Failed: still broken\n"
        "\n## Deferred\n\n- [ ] **TASK-0009**: outside\n> Failed: not in a batch\n",
        encoding="utf-8")
    (repo / ".gitignore").write_text("sysop/runtime/\n", encoding="utf-8")
    git = ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    subprocess.run(git + ["add", "-A"], cwd=repo, check=True)
    subprocess.run(git + ["commit", "-qm", "init"], cwd=repo, check=True)
    r = subprocess.run(["bash", "sysop/scripts/close_batch.sh", "1"], cwd=repo,
                       capture_output=True, text=True)
    assert "held open" in r.stdout + r.stderr, r.stdout + r.stderr
    assert ss._read_near_miss_failed(repo) == [(1, "TASK-0002")]
    assert all(b["failed_open"] == [] for b in ss._read_review_batches(repo))


def test_near_miss_reader_skips_fences_and_stops_at_any_heading():
    """`find_batch_range`'s fallback ends the range at the next unfenced line starting
    `##`, a `###` included, and a fenced header is an example, not a batch."""
    lines = [
        "```markdown",
        "### Batch 7 - an example `Merged`",
        "- [ ] **TASK-0070**: example",
        "> Failed: example",
        "```",
        "- [ ] **TASK-0071**: under the fenced example header, so in no batch",
        "> Failed: not counted",
        "### Batch 8 - a real one `Merged`",
        "- [ ] **TASK-0080**: failed",
        "> Failed: real",
        "### Notes",
        "- [ ] **TASK-0081**: after a heading, outside the batch",
        "> Failed: not batch 8's",
    ]
    assert ss._near_miss_failed(lines, ss._fenced_mask(lines)) == [(8, "TASK-0080")]
