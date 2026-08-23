"""Regression coverage for the Phase 134 gdp backports into `/review-close`.

Two same-day gdp fixes (2026-07-19), both silent-failure classes:

- **Step 3b `mkdir -p` before the pending-docs cp** (gdp `cb8f3840`): main's
  `sysop/runtime/pending-docs/` is gitignored (absent from any fresh clone) and
  authored lazily in the *worktree*, so a bare `cp <file> <missing-dir>/` fails
  with its error masked by `2>/dev/null` — and the very next `git worktree remove`
  destroys the doc for good. Guarded here as a prose drift-check on the command.

- **Step 4c parked-marker removal at close** (gdp `5f6a74b5`): the close heredoc
  flipped status + dropped the lock but never touched
  `sysop/runtime/parked/<TASK_ID>__*.md`, so markers for done tasks
  accumulated as stale drift. Exercised here by extracting the heredoc's Python
  body from SKILL.md and running it against a fixture repo (same pattern as
  test_review_close_smoke_gate.py), so the fix has CI coverage.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"

PLACEHOLDER_IDS = 'ids = ["<ROADMAP_ID_1>", "<ROADMAP_ID_2>"]'


def _extract_close_heredoc() -> str:
    """Pull the Step 4c tasks/index.yml close heredoc's Python body out of SKILL.md.

    Anchor on the body's unique placeholder-ids line and walk back to the nearest
    `python3 - <<'PY'` opener (robust to future heredocs being added or blocks
    reordered — the Step 3c smoke gate uses a different `<<'EOF'` opener); the body
    runs to the terminating `PY` line. The block sits inside a numbered markdown
    list, so every line carries a 3-space indent — dedent before returning.
    """
    text = SKILL.read_text(encoding="utf-8")
    ids_at = text.find(PLACEHOLDER_IDS)
    assert ids_at != -1, "could not locate the Step 4c placeholder-ids anchor in SKILL.md"
    opener = "python3 - <<'PY'\n"
    opener_at = text.rfind(opener, 0, ids_at)
    assert opener_at != -1, "could not locate the Step 4c heredoc opener above the ids anchor"
    start = opener_at + len(opener)
    end = text.find("\n   PY\n", start)
    assert end != -1, "could not locate the Step 4c heredoc terminator"
    return textwrap.dedent(text[start:end])


CLOSE_SRC = _extract_close_heredoc()


def _seed_repo(tmp_path: Path) -> Path:
    """A minimal consumer repo: two open tasks (tracked), locks + parked markers
    (gitignored working-tree artifacts, deliberately NOT committed)."""
    repo = tmp_path / "consumer"
    (repo / "tasks" / "open").mkdir(parents=True)
    (repo / "tasks" / "archive").mkdir(parents=True)
    (repo / "tasks" / "archive" / ".gitkeep").write_text("", encoding="utf-8")
    index = {
        "schema_version": 1,
        "tasks": [
            {"id": "TASK-0001", "status": "in_progress", "body": "open/TASK-0001.md"},
            {"id": "TASK-0002", "status": "in_progress", "body": "open/TASK-0002.md"},
        ],
    }
    (repo / "tasks" / "index.yml").write_text(yaml.safe_dump(index, sort_keys=False), encoding="utf-8")
    (repo / "tasks" / "open" / "TASK-0001.md").write_text("# TASK-0001\n", encoding="utf-8")
    (repo / "tasks" / "open" / "TASK-0002.md").write_text("# TASK-0002\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=_git_env())
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=_git_env())
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "seed"],
        cwd=repo, check=True, env=_git_env(),
    )
    # Gitignored runtime artifacts (working-tree-only, like a real consumer).
    (repo / "sysop" / "runtime" / "locks").mkdir(parents=True)
    (repo / "sysop" / "runtime" / "locks" / "TASK-0001.lock").write_text("x", encoding="utf-8")
    parked = repo / "sysop" / "runtime" / "parked"
    parked.mkdir(parents=True)
    (parked / "TASK-0001__20260719T000000Z.md").write_text("park 1", encoding="utf-8")
    (parked / "TASK-0001__20260719T010000Z.md").write_text("park 2", encoding="utf-8")
    (parked / "TASK-0002__20260719T000001Z.md").write_text("other task", encoding="utf-8")
    return repo


def _git_env() -> dict:
    """Ambient-config isolation. Every git subprocess in this module passes this env.

    Phase 150 shipped a regression test that passed with the bug fully restored on
    any machine carrying a global `core.hooksPath` — including the reporter's. The
    heredoc under test shells out to `git mv` / `git add`, and the fixtures commit,
    so a developer's global config (hooks path, `core.excludesFile`, `add.*`) can
    silently change what these assertions observe. Pin it to nothing.
    """
    env = dict(os.environ)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    # GIT_CONFIG_COUNT/KEY_n/VALUE_n override config even with the files pinned to
    # /dev/null, and GIT_TEMPLATE_DIR can plant hooks at `git init` — drop both.
    for leak in [k for k in env if k.startswith(("GIT_CONFIG_KEY", "GIT_CONFIG_VALUE"))]:
        del env[leak]
    env.pop("GIT_CONFIG_COUNT", None)
    env.pop("GIT_TEMPLATE_DIR", None)
    return env


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=str(repo), capture_output=True, text=True, check=check, env=_git_env(),
    )


def _run_close(repo: Path, ids: list[str]) -> None:
    src = CLOSE_SRC.replace(PLACEHOLDER_IDS, f"ids = {ids!r}")
    assert src != CLOSE_SRC, "placeholder ids line not found in the extracted heredoc"
    r = subprocess.run(
        [sys.executable, "-c", src], capture_output=True, text=True, cwd=str(repo),
        timeout=30, env=_git_env(),
    )
    assert r.returncode == 0, f"close heredoc errored ({r.returncode}):\n{r.stderr}"


def test_close_drops_lock_and_parked_markers_for_closed_task_only(tmp_path):
    repo = _seed_repo(tmp_path)
    before = datetime.date.today().isoformat()
    _run_close(repo, ["TASK-0001"])
    after = datetime.date.today().isoformat()

    d = yaml.safe_load((repo / "tasks" / "index.yml").read_text(encoding="utf-8"))
    by_id = {t["id"]: t for t in d["tasks"]}
    assert by_id["TASK-0001"]["status"] == "done"
    assert by_id["TASK-0001"]["completed_date"] in (before, after)
    assert by_id["TASK-0001"]["body"] == "archive/TASK-0001.md"
    assert (repo / "tasks" / "archive" / "TASK-0001.md").exists()
    assert not (repo / "tasks" / "open" / "TASK-0001.md").exists()

    # The Phase 134 assertions: lock AND both parked markers for the closed task
    # are gone; the other task's marker (and its open state) are untouched.
    assert not (repo / "sysop" / "runtime" / "locks" / "TASK-0001.lock").exists()
    parked = repo / "sysop" / "runtime" / "parked"
    assert sorted(p.name for p in parked.glob("*.md")) == ["TASK-0002__20260719T000001Z.md"]
    assert by_id["TASK-0002"]["status"] == "in_progress"


def test_close_noops_cleanly_when_never_parked(tmp_path):
    repo = _seed_repo(tmp_path)
    # Simulate a consumer that has never parked anything: no parked dir at all.
    # (Phase 159b: the dir is sysop/runtime/parked/, no longer nested under
    # auto-build/ — removing the wrong dir would leave the real one in place
    # and quietly stop testing the missing-dir path.)
    parked = repo / "sysop" / "runtime" / "parked"
    for p in sorted(parked.rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    parked.rmdir()
    assert not parked.exists()
    _run_close(repo, ["TASK-0001"])
    d = yaml.safe_load((repo / "tasks" / "index.yml").read_text(encoding="utf-8"))
    assert {t["id"]: t["status"] for t in d["tasks"]}["TASK-0001"] == "done"


def test_close_cleanup_runs_for_archive_summary_and_flat_layout_bodies(tmp_path):
    """The cleanup is keyed on the task id, not the body shape (Phase 134 review
    finding): an `archive_summary` close (no `body:`) and a flat-layout body (no
    open/deferred segment) both `continue` past the git-mv logic — their lock and
    parked markers must still be dropped."""
    repo = tmp_path / "consumer"
    (repo / "tasks").mkdir(parents=True)
    (repo / "tasks" / "TASK-0003.md").write_text("# TASK-0003\n", encoding="utf-8")
    index = {
        "schema_version": 1,
        "tasks": [
            {"id": "TASK-0003", "status": "in_progress", "body": "TASK-0003.md"},
            {"id": "TASK-0004", "status": "in_progress", "archive_summary": "done inline"},
        ],
    }
    (repo / "tasks" / "index.yml").write_text(yaml.safe_dump(index, sort_keys=False), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=_git_env())
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=_git_env())
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "seed"],
        cwd=repo, check=True, env=_git_env(),
    )
    (repo / "sysop" / "runtime" / "locks").mkdir(parents=True)
    parked = repo / "sysop" / "runtime" / "parked"
    parked.mkdir(parents=True)
    for tid in ("TASK-0003", "TASK-0004"):
        (repo / "sysop" / "runtime" / "locks" / f"{tid}.lock").write_text("x", encoding="utf-8")
        (parked / f"{tid}__20260719T000000Z.md").write_text("park", encoding="utf-8")

    _run_close(repo, ["TASK-0003", "TASK-0004"])

    d = yaml.safe_load((repo / "tasks" / "index.yml").read_text(encoding="utf-8"))
    assert all(t["status"] == "done" for t in d["tasks"])
    assert list((repo / "sysop" / "runtime" / "locks").glob("*.lock")) == []
    assert list(parked.glob("*.md")) == []


def test_close_heredoc_stages_the_index_it_rewrote(tmp_path):
    """Phase 151 / upstream #203.

    `git mv` stages; `Path.write_text` does not. Before the fix the heredoc left
    `tasks/index.yml` MODIFIED-but-unstaged while the body rename sat staged — a
    half-staged index. The heredoc now stages the file in the same code that wrote
    it, so nothing downstream has to remember to.
    """
    repo = _seed_repo(tmp_path)
    _run_close(repo, ["TASK-0001"])

    staged = _git(repo, "diff", "--cached", "--name-only").stdout.split()
    unstaged = _git(repo, "diff", "--name-only").stdout.split()

    assert "tasks/index.yml" in staged, (
        "the heredoc rewrote tasks/index.yml but left it unstaged — Step 7's commit "
        f"would silently drop the status flip (staged={staged}, unstaged={unstaged})"
    )
    # The body rename came along too — staged by `git mv`, and reported as one rename
    # entry (`--name-only` collapses a rename to its destination, hence --name-status).
    rename = _git(repo, "diff", "--cached", "--name-status", "-M").stdout
    assert "tasks/open/TASK-0001.md\ttasks/archive/TASK-0001.md" in rename, rename
    assert unstaged == [], f"unstaged leftovers after the heredoc: {unstaged}"


def test_step4c_commit_carries_the_index_flip_not_just_the_rename(tmp_path):
    """The #203 failure end-to-end: run the heredoc, then Step 7's literal commit.

    Before the fix this produced `1 file changed, 0 insertions(+), 0 deletions(-)` —
    the rename alone — under a subject claiming the consolidation happened, and on a
    `pr` consumer that half-commit is what gets squash-merged. Asserts on the commit
    contents rather than on the index, so it fails for the reason a human would care
    about.
    """
    repo = _seed_repo(tmp_path)
    _run_close(repo, ["TASK-0001"])
    _git(repo, "commit", "-q", "-m", "docs: consolidate documentation for 1 merged branch")

    files = _git(repo, "show", "--stat", "--name-only", "--pretty=format:", "HEAD").stdout.split()
    assert "tasks/index.yml" in files, (
        f"the consolidation commit dropped the status flip; it carried only {files}"
    )

    # And the committed index really says `done` — not just that the file was touched.
    committed = yaml.safe_load(_git(repo, "show", "HEAD:tasks/index.yml").stdout)
    by_id = {t["id"]: t for t in committed["tasks"]}
    assert by_id["TASK-0001"]["status"] == "done"
    assert by_id["TASK-0001"]["body"] == "archive/TASK-0001.md"

    # Step 7's own post-commit gate must now hold: nothing left unstaged or staged.
    assert _git(repo, "diff", "--quiet", check=False).returncode == 0
    assert _git(repo, "diff", "--cached", "--quiet", check=False).returncode == 0


def test_close_heredoc_leaves_the_index_alone_when_nothing_closed(tmp_path):
    """Phase 151 review finding: the write+stage must be guarded on `closed`.

    With no matching ids, `d` is unchanged — but reserializing and staging it anyway would
    commit a whole-file yaml reformat (comments stripped) under the consolidation subject,
    on exactly the run where Step 7 says `tasks/index.yml` is legitimately absent from the
    commit.
    """
    repo = _seed_repo(tmp_path)
    # Hand-formatted, with a comment — the fixture's own safe_dump output would survive a
    # reserialization byte-identically, which would make this test a false negative.
    hand_written = (
        "# Task index — hand maintained; comments here are load-bearing to a human.\n"
        "schema_version: 1\n"
        "tasks:\n"
        "  - id: TASK-0001          # the one under test\n"
        "    status: in_progress\n"
        "    body: open/TASK-0001.md\n"
    )
    (repo / "tasks" / "index.yml").write_text(hand_written, encoding="utf-8")
    _git(repo, "commit", "-q", "-a", "-m", "hand-format the index")
    original = (repo / "tasks" / "index.yml").read_text(encoding="utf-8")
    assert "#" in original

    _run_close(repo, ["TASK-NOT-IN-THIS-INDEX"])

    assert (repo / "tasks" / "index.yml").read_text(encoding="utf-8") == original, (
        "the index was rewritten despite nothing closing"
    )
    assert _git(repo, "diff", "--cached", "--name-only").stdout.split() == []
    assert _git(repo, "diff", "--name-only").stdout.split() == []


def test_close_heredoc_creates_a_missing_archive_directory(tmp_path):
    """Phase 151 review finding: `git mv` into a missing dir is fatal, and `check=True`
    would abort the loop AFTER earlier renames staged and BEFORE the index write — the
    half-staged commit of #203, via a route the staging fix does not cover."""
    repo = _seed_repo(tmp_path)
    archive = repo / "tasks" / "archive"
    (archive / ".gitkeep").unlink()
    _git(repo, "commit", "-q", "-a", "-m", "drop the archive .gitkeep")
    archive.rmdir()
    assert not archive.exists()

    _run_close(repo, ["TASK-0001"])

    assert (archive / "TASK-0001.md").exists()
    d = yaml.safe_load((repo / "tasks" / "index.yml").read_text(encoding="utf-8"))
    assert {x["id"]: x["status"] for x in d["tasks"]}["TASK-0001"] == "done"
    assert "tasks/index.yml" in _git(repo, "diff", "--cached", "--name-only").stdout.split()


def test_step3b_collect_has_loadbearing_mkdir():
    """Drift guard for the gdp cb8f3840 backport, re-pointed by Phase 210.

    The original asserted the literal bash `mkdir -p … && cp … 2>/dev/null`. Phase 210
    replaced that with a provenance-checking `python3 -` heredoc, so the guard now asserts
    the SURVIVING INVARIANT rather than the retired spelling: main's pending-docs dir is
    still created before anything is copied into it. That is the whole point of the
    backport — a copy into a missing destination fails, and the next `git worktree remove`
    then destroys the gitignored doc.

    An earlier version of this guard did `text.find(...)` on the markdown and compared
    byte offsets. A reviewer walked it by COMMENTING OUT the mkdir: the substring is still
    present, still ordered before the copy, and the collect then dies with
    FileNotFoundError on any repo whose pending-docs dir does not yet exist — which is
    every fresh clone. So this now EXECUTES the extracted heredoc against a destination
    that genuinely does not exist, which is the only form that can fail for the right
    reason.
    """
    import re as _re

    text = SKILL.read_text(encoding="utf-8")
    bodies = _re.findall(
        r"python3 - \"<worktree-path>\" \"<branch name>\" <<'PY'\n(.*?)\n      PY\n", text, _re.DOTALL
    )
    assert bodies, "Step 3b's collect heredoc is gone"
    collect_src = "\n".join(
        ln[6:] if ln.startswith("      ") else ln for ln in bodies[0].split("\n")
    )
    # The masking redirect that made the original failure silent must not come back.
    assert "cp <worktree>/sysop/runtime/pending-docs/*.md" not in text

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        main, wt = d / "main", d / "wt"
        main.mkdir()
        # Deliberately do NOT create main/sysop/runtime/pending-docs — that is the case.
        assert not (main / "sysop/runtime/pending-docs").exists()
        doc = wt / "sysop/runtime/pending-docs/feat-x.md"
        doc.parent.mkdir(parents=True)
        doc.write_text('---\nbranch: feat/x\nsummary: "s"\n---\n', encoding="utf-8")

        script = d / "collect.py"
        script.write_text(collect_src, encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(script), str(wt), "feat/x"],
            cwd=main, capture_output=True, text=True,
        )

        # Assert INSIDE the context manager — the tree is deleted on exit.
        assert r.returncode == 0, (
            "the collect failed against a missing destination — the load-bearing mkdir "
            f"is gone or inert:\n{r.stdout}\n{r.stderr}"
        )
        assert (main / "sysop/runtime/pending-docs/feat-x.md").exists(), (
            "the doc was not collected; a fresh clone would lose it at the next "
            "worktree remove"
        )


def test_final_report_template_carries_parked_markers_row():
    text = SKILL.read_text(encoding="utf-8")
    # Phase 219 (`Q-237`): the row is now sourced from what Step 4c PRINTED, rather than
    # naming a shape the agent had to fill from memory. Pin the sourcing, not the shape.
    assert 'Parked markers: <the `PARKED_MARKERS_REMOVED` filenames Step 4c printed>' in text
    assert 'Locks cleaned: <the `LOCKS_REMOVED` ids Step 4c printed>' in text
    assert "`CLOSED_IDS`" in text and "`NOT_IN_INDEX`" in text, (
        "Step 8's tasks/index.yml row must name both emitted sets — reporting only the "
        "closed ids hides every id this close was asked for and could not find")


# ---------------------------------------------------------------------------------------
# `Q-237` — the heredoc now REPORTS what it did. Step 8 asked it for three values and it
# printed nothing, so the agent answered from intent. Two of the three are not derivable
# after the fact at all: `missing_ok=True` erases whether a lock existed, and a removed
# marker is gone. These assert the VALUES, not the presence of a print.
# ---------------------------------------------------------------------------------------

def _run_close_capturing(repo: Path, ids: list[str]) -> str:
    src = CLOSE_SRC.replace(PLACEHOLDER_IDS, f"ids = {ids!r}")
    assert src != CLOSE_SRC, "placeholder ids line not found in the extracted heredoc"
    r = subprocess.run(
        [sys.executable, "-c", src], capture_output=True, text=True, cwd=str(repo),
        timeout=30, env=_git_env(),
    )
    assert r.returncode == 0, f"close heredoc errored ({r.returncode}):\n{r.stderr}"
    return r.stdout


def _row(out: str, key: str) -> list[str]:
    """The values on one emitted row, or [] for the literal `(none)`."""
    lines = [ln for ln in out.splitlines() if ln.startswith(key + ": ")]
    assert len(lines) == 1, f"expected exactly one {key!r} row, got {lines!r}"
    rest = lines[0][len(key) + 2:].strip()
    return [] if rest == "(none)" else rest.split()


def test_the_close_reports_the_locks_it_actually_removed_not_the_ones_it_tried(tmp_path):
    """The fixture gives TASK-0001 a lock and TASK-0002 none. Closing both must report
    one removed and one already-absent — the distinction `missing_ok=True` destroys, and
    the reason printing `closed` would have been confidently wrong rather than merely
    unhelpful."""
    repo = _seed_repo(tmp_path)
    out = _run_close_capturing(repo, ["TASK-0001", "TASK-0002"])
    assert _row(out, "LOCKS_REMOVED") == ["TASK-0001"], out
    assert _row(out, "LOCKS_ALREADY_ABSENT") == ["TASK-0002"], out
    # Direction, not presence: the two sets must be disjoint and together account for
    # every closed task. A swap of the two labels passes an `in` check and fails this.
    removed, absent = _row(out, "LOCKS_REMOVED"), _row(out, "LOCKS_ALREADY_ABSENT")
    assert not set(removed) & set(absent)
    assert sorted(removed + absent) == _row(out, "CLOSED_IDS")


def test_the_close_reports_the_parked_markers_by_name(tmp_path):
    """Both of TASK-0001's markers, and not TASK-0002's, when only TASK-0001 closes."""
    repo = _seed_repo(tmp_path)
    out = _run_close_capturing(repo, ["TASK-0001"])
    assert _row(out, "PARKED_MARKERS_REMOVED") == [
        "TASK-0001__20260719T000000Z.md", "TASK-0001__20260719T010000Z.md",
    ], out
    # …and the files really are gone, so the row is a receipt rather than a wish.
    assert not list((repo / "sysop" / "runtime" / "parked").glob("TASK-0001__*.md"))
    assert (repo / "sysop" / "runtime" / "parked" / "TASK-0002__20260719T000001Z.md").exists()


def test_an_id_with_no_index_entry_is_reported_rather_than_silently_dropped(tmp_path):
    """`closed` is a strict SUBSET of `ids`: the loop skips any id the index does not
    carry, silently. Reporting `ids` would over-claim and reporting `closed` alone would
    hide the drop, so the heredoc emits both and this asserts the arithmetic between
    them."""
    repo = _seed_repo(tmp_path)
    out = _run_close_capturing(repo, ["TASK-0001", "TASK-9999"])
    assert _row(out, "CLOSED_IDS") == ["TASK-0001"], out
    assert _row(out, "NOT_IN_INDEX") == ["TASK-9999"], out
    assert sorted(_row(out, "CLOSED_IDS") + _row(out, "NOT_IN_INDEX")) == [
        "TASK-0001", "TASK-9999",
    ], "every requested id must appear in exactly one of the two rows"


def test_every_row_is_present_even_when_empty(tmp_path):
    """A row that vanishes when its set is empty is worse than one that says `(none)`:
    Step 8 cannot tell an absent row from a forgotten one."""
    repo = _seed_repo(tmp_path)
    out = _run_close_capturing(repo, [])
    for key in ("CLOSED_IDS", "NOT_IN_INDEX", "LOCKS_REMOVED",
                "LOCKS_ALREADY_ABSENT", "PARKED_MARKERS_REMOVED"):
        assert _row(out, key) == [], f"{key} should be the literal `(none)` here: {out!r}"
