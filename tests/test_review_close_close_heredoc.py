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
    """Drift guard for the gdp cb8f3840 backport: the Step 3b collect command must
    create main's pending-docs dir before the silently-failing-when-dest-missing cp."""
    text = SKILL.read_text(encoding="utf-8")
    assert (
        "`mkdir -p sysop/runtime/pending-docs && "
        "cp <worktree>/sysop/runtime/pending-docs/*.md sysop/runtime/pending-docs/ 2>/dev/null`"
    ) in text


def test_final_report_template_carries_parked_markers_row():
    text = SKILL.read_text(encoding="utf-8")
    assert 'Parked markers: <removed TASK-ID list> (or "none")' in text
