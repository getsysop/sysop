"""`/review-close` Step 4c's index write — asserted by RUNNING it.

Phase 269, `Q-414`. Step 4c derived its temp name from the target
(`tmp = target.with_suffix(target.suffix + '.tmp')`), while the four siblings it
sits beside in the roster — `/claim-task` Step 4a, `/auto-build` Step 5.1, and
`claim_task.sh`'s `--release` and `--commit-claim` — all use `mkstemp` precisely
so two writers cannot collide on the temp NAME.

It is the last of those FOUR to convert, **not** the last writer of the file: an
earlier draft of this docstring said the latter and a review lens falsified it.
`backfill_completed_dates.py` still uses the fixed name (`Q-442`).
`os.replace` makes each writer's own swap atomic; it does nothing about two
writers agreeing on the same scratch path.

**Why this module exists at all.** The site had text pins and no execution test,
which is how it stayed the odd one out through the two phases that converted its
neighbours: every grep for `os.replace(` was green the whole time. The pins in
`test_index_writer_class.py` are re-pointed rather than dropped, but a pin can
only assert the spelling someone thought to pin — `test_the_fixed_name_would_
destroy_a_concurrent_writers_tempfile` below asserts the HARM, and it is the one
that would have caught the defect while the old form was still shipping.

The collision is tested DETERMINISTICALLY rather than by racing two processes: a
file is planted at the fixed name the old code would have chosen, and the assert
is that the shipped block leaves it alone. Under the old form that file is
opened, written, chmod'ed and renamed away — a second writer's in-flight temp
destroyed, and its `os.replace` then landing a half-written index or raising.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core/skills/review-close/SKILL.md"

ANCHOR = "   p = Path('tasks/index.yml')"
FIXED_NAME = "index.yml.tmp"  # what `target.with_suffix(suffix + '.tmp')` produced


def _step4c_body() -> str:
    """Step 4c's heredoc'd Python, verbatim and runnable (indent stripped)."""
    text = SKILL.read_text(encoding="utf-8")
    found = text.count(ANCHOR)
    assert found == 1, (
        f"Step 4c's index-write anchor matched {found} times, not once; this "
        f"extractor keys on {ANCHOR!r} and a second copy makes the slice ambiguous"
    )
    i = text.index(ANCHOR)
    start = text.index("\n", text.rindex("python3 - <<'PY'", 0, i)) + 1
    end = text.index("\n   PY\n", start)
    return "\n".join(
        line[3:] if line.startswith("   ") else line
        for line in text[start:end].splitlines()
    )


def _runnable(ids: list[str]) -> str:
    """The shipped block with its one hand-substituted literal filled in.

    `ids = ["<ROADMAP_ID_1>", "<ROADMAP_ID_2>"]` is a placeholder the operator
    replaces by hand — substituting it is running the block as documented, not
    modifying it. Nothing else is touched.
    """
    body = _step4c_body()
    placeholder = 'ids = ["<ROADMAP_ID_1>", "<ROADMAP_ID_2>"]'
    assert placeholder in body, "Step 4c's id placeholder changed shape"
    return body.replace(placeholder, f"ids = {ids!r}")


def _index(*task_ids: str) -> str:
    rows = "".join(
        "- id: {tid}\n"
        "  title: a task\n"
        "  status: in_progress\n"
        "  type: tech\n"
        "  effort: 1\n"
        "  priority: medium\n"
        "  user_action: false\n"
        "  body: open/{tid}.md\n".format(tid=tid)
        for tid in task_ids
    )
    return "schema_version: 1\ntasks:\n" + rows


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A checkout whose bodies are tracked, because Step 4c runs `git mv`."""
    root = tmp_path / "repo"
    (root / "tasks" / "open").mkdir(parents=True)
    (root / "tasks" / "archive").mkdir(parents=True)
    (root / "tasks" / "index.yml").write_text(_index("TECH-0001", "TECH-0002"),
                                              encoding="utf-8")
    for tid in ("TECH-0001", "TECH-0002"):
        (root / "tasks" / "open" / f"{tid}.md").write_text(
            f"---\nid: {tid}\n---\nbody\n", encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(root: Path, ids: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-"],
        input=_runnable(ids),
        cwd=str(root), capture_output=True, text=True, timeout=60,
    )


def _load(root: Path) -> dict:
    import yaml
    return yaml.safe_load((root / "tasks" / "index.yml").read_text(encoding="utf-8"))


def _entry(root: Path, tid: str) -> dict:
    return next(t for t in _load(root)["tasks"] if t["id"] == tid)


# ---------------------------------------------------------------- non-vacuity


def test_the_extractor_returns_the_real_block():
    body = _step4c_body()
    assert "yaml.safe_dump(" in body, "extractor missed Step 4c's write"
    assert "os.replace(" in body and "tempfile.mkstemp(" in body
    assert len(body.splitlines()) > 100, "extracted block is implausibly short"


def test_the_block_runs_at_all(repo: Path):
    """The floor every assertion below rests on. Until this module the shipped
    block had no execution test, so a `NameError` on the happy path — the class
    `Q-404`'s conversion was one line from shipping next door — was invisible."""
    r = _run(repo, ["TECH-0001"])
    assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    assert "CLOSED_IDS: TECH-0001" in r.stdout, r.stdout


# ------------------------------------------------------------------ `Q-414`


def test_the_fixed_name_would_destroy_a_concurrent_writers_tempfile(repo: Path):
    """`Q-414`'s harm, asserted directly.

    A file is planted at exactly the path the old `target.with_suffix(...)` form
    derived. Under that form this block opens it, writes the whole index into it,
    chmods it and renames it onto the target — silently destroying the in-flight
    scratch file of whatever else was mid-write, and leaving that writer's own
    `os.replace` to land a foreign payload or raise.

    Under `mkstemp` the planted file is untouched, because the name is never
    guessed. This is the assertion no string pin can make.
    """
    victim = repo / "tasks" / FIXED_NAME
    victim.write_text("another writer's in-flight temp\n", encoding="utf-8")
    r = _run(repo, ["TECH-0001"])
    assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    assert victim.exists(), (
        "Step 4c consumed the fixed-name tempfile — it is deriving its temp name "
        "from the target again, which is the collision `Q-414` removed"
    )
    assert victim.read_text(encoding="utf-8") == "another writer's in-flight temp\n", (
        "Step 4c overwrote a concurrent writer's tempfile"
    )
    # and its own write still landed
    assert _entry(repo, "TECH-0001")["status"] == "done"


def test_a_directory_at_the_fixed_name_does_not_block_the_write(repo: Path):
    """A writer that derives its name from the target cannot proceed when a
    DIRECTORY sits at that name (the open fails); one that calls `mkstemp` is
    unaffected.

    **Renamed after a review lens pointed out the old name overclaimed.** It was
    `test_two_sequential_runs_never_reuse_one_temp_path`, which named a
    comparison this test never makes — it runs once and compares no paths. The
    per-run uniqueness of the name is measured directly by
    `test_the_tempfile_is_created_in_the_targets_own_directory`, which records
    every `mkstemp` call; this one is the obstruction case, which is a different
    property and worth keeping under an honest name."""
    (repo / "tasks" / FIXED_NAME).mkdir()
    r = _run(repo, ["TECH-0001"])
    assert r.returncode == 0, (
        f"a directory at the fixed temp name blocked the write, so the temp name "
        f"is still derived from the target:\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    )
    assert _entry(repo, "TECH-0001")["status"] == "done"


def test_the_tempfile_is_created_in_the_targets_own_directory(repo: Path, tmp_path: Path):
    """The property the OLD guard's stated reason was protecting — `os.replace`
    raises `EXDEV` across filesystems — kept explicitly now that the fixed name
    is gone. `dir=` is what secures it; the fixed name only implied it.

    **This test's first version asserted the wrong thing and a review lens killed
    it.** It made `tasks/` mode `0555` and asserted the run failed, reasoning that
    "if the tempfile were being created anywhere else, the write would succeed."
    That is false: `os.replace` INTO a `0555` directory raises `PermissionError`
    regardless of where the tempfile lives, so the test went red for a reason
    unrelated to `dir=` and two mutations that moved the tempfile out of `tasks/`
    — into `tempfile.gettempdir()` and into the repo root — both passed it, and
    passed the substring pin in `test_index_writer_class.py` too.

    So the property is now MEASURED rather than inferred: `tempfile.mkstemp` is
    wrapped in a preamble that records the `dir=` it was called with. The shipped
    block itself is run verbatim and unmodified — the wrapper is installed before
    it, the way a `sitecustomize` would be — because the claim is about the
    argument the block passes, and that is observable at no other moment: on
    success the tempfile is renamed away, and on failure it is unlinked.
    """
    probe = tmp_path / "mkstemp-calls.txt"
    preamble = (
        "import tempfile as _t, os as _o\n"
        "_orig = _t.mkstemp\n"
        "def _spy(*a, **k):\n"
        f"    open({str(probe)!r}, 'a').write(repr(k.get('dir')) + '\\n')\n"
        "    return _orig(*a, **k)\n"
        "_t.mkstemp = _spy\n"
    )
    r = subprocess.run(
        [sys.executable, "-"], input=preamble + _runnable(["TECH-0001"]),
        cwd=str(repo), capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    assert probe.exists(), "Step 4c never called tempfile.mkstemp"
    dirs = [ln.strip() for ln in probe.read_text().splitlines() if ln.strip()]
    assert dirs, "mkstemp was called with no dir= recorded"
    expected = str((repo / "tasks").resolve())
    for got in dirs:
        assert got != "None", (
            "Step 4c called mkstemp with no dir=, so the tempfile lands in the "
            "system temp dir and os.replace can raise EXDEV"
        )
        assert Path(got.strip("'\"")).resolve() == Path(expected), (
            f"Step 4c created its tempfile in {got}, not the target's own "
            f"directory ({expected}) — the replace is no longer guaranteed "
            f"same-filesystem"
        )


# ------------------------------- properties `os.replace` does not give for free


def test_a_symlinked_index_is_written_through_not_replaced(tmp_path: Path, repo: Path):
    """`realpath` before the write. Without it `os.replace` swaps the SYMLINK for
    a regular file and the real index stops receiving updates."""
    real = tmp_path / "elsewhere.yml"
    real.write_text(_index("TECH-0001", "TECH-0002"), encoding="utf-8")
    link = repo / "tasks" / "index.yml"
    link.unlink()
    link.symlink_to(real)
    r = _run(repo, ["TECH-0001"])
    assert r.returncode == 0, f"stdout:\n{r.stdout}\nstderr:\n{r.stderr}"
    assert link.is_symlink(), "Step 4c replaced the symlink with a regular file"
    import yaml
    entry = next(t for t in yaml.safe_load(real.read_text())["tasks"]
                 if t["id"] == "TECH-0001")
    assert entry["status"] == "done", "the write did not reach the symlink's target"


def test_the_index_mode_survives_the_replace(repo: Path):
    """`mkstemp` creates at 0600 — stricter than the old `write_text` — so without
    the explicit `chmod` the close would silently tighten the index's permissions
    for every other reader on the machine."""
    idx = repo / "tasks" / "index.yml"
    idx.chmod(0o664)
    r = _run(repo, ["TECH-0001"])
    assert r.returncode == 0, r.stderr
    assert stat.S_IMODE(idx.stat().st_mode) == 0o664, (
        f"mode became {oct(stat.S_IMODE(idx.stat().st_mode))}; mkstemp's 0600 leaked "
        "through, so the chmod was dropped"
    )


def test_a_successful_run_leaves_no_tempfile_residue(repo: Path):
    """A surviving scratch file sits untracked beside a tracked path for the rest
    of the close — the residue hazard Step 2b's classifier reacts to.

    **Compares the whole directory, not names containing `.tmp`.** A review lens
    changed `suffix='.tmp'` to `'.part'` and disabled the cleanup in one mutation;
    both this test and the failure-arm one below filtered on `".tmp" in name` and
    went blind, while the text pins were satisfied by the surviving tokens. The
    property is "no file appeared", and the suffix is the mutable part of it."""
    before = {x.name for x in (repo / "tasks").iterdir()}
    r = _run(repo, ["TECH-0001"])
    assert r.returncode == 0, r.stderr
    after = {x.name for x in (repo / "tasks").iterdir()}
    assert after <= before, f"the run left new files in tasks/: {sorted(after - before)}"


def test_the_failure_arm_cleans_up_its_tempfile(repo: Path):
    """The `except BaseException` arm, driven by making the rename fail: a
    DIRECTORY at the target path makes `os.replace` raise, after the tempfile
    exists. Without the cleanup that tempfile is the residue above, left behind
    on exactly the path where the close already aborted."""
    idx = repo / "tasks" / "index.yml"
    idx.unlink()
    idx.mkdir()
    before = {x.name for x in (repo / "tasks").iterdir()}
    r = _run(repo, ["TECH-0001"])
    assert r.returncode != 0, "the run should have failed with a directory at the index"
    after = {x.name for x in (repo / "tasks").iterdir()}
    assert after <= before, (
        f"the failure arm left a scratch file behind: {sorted(after - before)}"
    )


# --------------------------------------------------------- unchanged behaviour


def test_the_conversion_did_not_change_what_gets_written(repo: Path):
    """`yaml.safe_dump` moved from returning a string to writing a stream, and the
    kwargs moved with it. Assert the OUTPUT, so a dropped kwarg cannot hide."""
    r = _run(repo, ["TECH-0001"])
    assert r.returncode == 0, r.stderr
    e = _entry(repo, "TECH-0001")
    assert e["status"] == "done" and e["completed_date"]
    assert e["body"] == "archive/TECH-0001.md"
    # the untouched task keeps everything
    other = _entry(repo, "TECH-0002")
    assert other["status"] == "in_progress" and other["body"] == "open/TECH-0002.md"


def test_a_held_task_is_still_withheld(repo: Path):
    """`Q-327`'s hold, re-asserted through the rewritten writer: the conversion
    touched the write, and a write that closed a held task would be worse than the
    collision it fixed."""
    idx = repo / "tasks" / "index.yml"
    idx.write_text(_index("TECH-0001").replace("user_action: false",
                                               "user_action: true"), encoding="utf-8")
    r = _run(repo, ["TECH-0001"])
    assert r.returncode == 0, r.stderr
    assert "HELD_USER_ACTION: TECH-0001" in r.stdout, r.stdout
    assert _entry(repo, "TECH-0001")["status"] == "in_progress"


def test_the_bodies_are_staged_by_the_code_that_moved_them(repo: Path):
    """Staging beside the write, which the conversion sits in the middle of."""
    r = _run(repo, ["TECH-0001"])
    assert r.returncode == 0, r.stderr
    staged = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--name-only"],
                            capture_output=True, text=True, check=True).stdout.split()
    assert "tasks/index.yml" in staged, staged
    assert "tasks/archive/TECH-0001.md" in staged, staged
