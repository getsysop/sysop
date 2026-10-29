"""`resolve_append_conflict.py` (`Q-629`, Phase 425): Step 4a's shared-append resolver, run
against real stopped rebases and merges.

`tests/test_step4a_shared_file_behaviour.py` pins the facts the recipe rests on (the marker-strip
union corrupts, the stage numbers, the removal gaps). This module runs the shipped resolver over
the same shapes and the ones the recipe told a person to handle: a same-id add, a both-sides
edit, a both-sides status move, a change outside `tasks:`, a conflicted body file, the
published arm's `--since`, and `tasks/notes.md`'s promotion-against-append.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.test_step4a_shared_file_behaviour import (
    _entry,
    _file_a_followup,
    _git,
    _init,
    _validate,
)

SCRIPT = Path(__file__).resolve().parents[1] / "core" / "companion" / "scripts" / \
    "resolve_append_conflict.py"


def resolve(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=repo, capture_output=True,
                          text=True, stdin=subprocess.DEVNULL, timeout=60)


def ids(repo: Path) -> list[str]:
    return [t["id"] for t in yaml.safe_load((repo / "tasks/index.yml").read_text())["tasks"]]


def entry(repo: Path, tid: str) -> dict:
    doc = yaml.safe_load((repo / "tasks/index.yml").read_text())
    return next(t for t in doc["tasks"] if t["id"] == tid)


def commit_all(repo: Path, msg: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", msg)


def rebase_stops(repo: Path, branch: str) -> None:
    _git(repo, "checkout", "-q", branch)
    assert _git(repo, "rebase", "main").returncode != 0
    assert "tasks/index.yml" in _git(repo, "ls-files", "-u").stdout


def edit_seed(repo: Path, old: str, new: str) -> None:
    idx = repo / "tasks/index.yml"
    text = idx.read_text()
    seed = text[text.index("  - id: FEAT-SEED"):text.index("body: open/FEAT-SEED.md")]
    assert old in seed
    idx.write_text(text.replace(seed, seed.replace(old, new)))


def cont(repo: Path) -> subprocess.CompletedProcess:
    _git(repo, "add", "tasks/index.yml")
    return subprocess.run(["git", "-c", "core.editor=true", "rebase", "--continue"], cwd=repo,
                          capture_output=True, text=True)


# --- the shapes the recipe resolved by hand ---------------------------------------------------

@pytest.fixture
def two_filings(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    _init(repo)
    for tid, title in (("FEAT-AAAA", "Alpha follow-up"), ("FEAT-BBBB", "Beta follow-up")):
        _git(repo, "checkout", "-q", "-b", f"feat/{tid}", "main")
        _file_a_followup(repo, tid, title)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/FEAT-BBBB")
    rebase_stops(repo, "feat/FEAT-AAAA")
    return repo


def test_two_filings_resolve_validate_and_continue(two_filings: Path) -> None:
    repo = two_filings
    target = _git(repo, "show", ":2:tasks/index.yml").stdout
    r = resolve(repo, "index")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "APPENDED: FEAT-AAAA (the branch filed it)" in r.stdout
    assert r.stdout.splitlines()[-1].startswith("RESOLVED: tasks/index.yml written from stage 2 with 1")
    text = (repo / "tasks/index.yml").read_text()
    assert text.startswith(target.rstrip("\n")), "the target's file is kept byte for byte"
    assert "<<<<<<<" not in text and _validate(repo).returncode == 0
    assert cont(repo).returncode == 0
    assert ids(repo) == ["FEAT-SEED", "FEAT-BBBB", "FEAT-AAAA"]


def test_it_never_stages(two_filings: Path) -> None:
    assert resolve(two_filings, "index").returncode == 0
    assert "tasks/index.yml" in _git(two_filings, "ls-files", "-u").stdout


def test_a_branch_removal_is_applied(tmp_path: Path) -> None:
    """Internal tracker #766: the replayed commit withdraws FEAT-OLD beside its filing."""
    repo = tmp_path / "r"
    _init(repo)
    _file_a_followup(repo, "FEAT-OLD", "To be withdrawn")
    _git(repo, "checkout", "-q", "-b", "feat/FEAT-BBBB", "main")
    _file_a_followup(repo, "FEAT-BBBB", "Beta follow-up")
    _git(repo, "checkout", "-q", "-b", "feat/FEAT-AAAA", "main")
    idx = repo / "tasks/index.yml"
    idx.write_text(idx.read_text().replace(_entry("FEAT-OLD", "To be withdrawn"), "")
                   + _entry("FEAT-AAAA", "Alpha follow-up"))
    (repo / "tasks/open/FEAT-OLD.md").unlink()
    (repo / "tasks/open/FEAT-AAAA.md").write_text("# FEAT-AAAA\n")
    commit_all(repo, "file FEAT-AAAA, withdraw FEAT-OLD")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/FEAT-BBBB")
    rebase_stops(repo, "feat/FEAT-AAAA")
    r = resolve(repo, "index")
    assert r.returncode == 0, r.stdout
    assert "REMOVED: FEAT-OLD (the branch removed it)" in r.stdout
    assert ids(repo) == ["FEAT-SEED", "FEAT-BBBB", "FEAT-AAAA"]
    assert _validate(repo).returncode == 0


def test_a_target_removal_stays_out(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init(repo)
    _file_a_followup(repo, "FEAT-OLD", "To be withdrawn")
    _git(repo, "checkout", "-q", "-b", "feat/FEAT-AAAA", "main")
    _file_a_followup(repo, "FEAT-AAAA", "Alpha follow-up")
    _git(repo, "checkout", "-q", "-b", "feat/FEAT-BBBB", "main")
    idx = repo / "tasks/index.yml"
    idx.write_text(idx.read_text().replace(_entry("FEAT-OLD", "To be withdrawn"), "")
                   + _entry("FEAT-BBBB", "Beta follow-up"))
    (repo / "tasks/open/FEAT-OLD.md").unlink()
    (repo / "tasks/open/FEAT-BBBB.md").write_text("# FEAT-BBBB\n")
    commit_all(repo, "file FEAT-BBBB, withdraw FEAT-OLD")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/FEAT-BBBB")
    rebase_stops(repo, "feat/FEAT-AAAA")
    r = resolve(repo, "index")
    assert r.returncode == 0, r.stdout
    assert "KEPT OUT: FEAT-OLD (the target removed it)" in r.stdout
    assert ids(repo) == ["FEAT-SEED", "FEAT-BBBB", "FEAT-AAAA"]


def test_a_branch_edit_of_an_untouched_entry_is_applied(tmp_path: Path) -> None:
    """Union-by-id discarded this edit wholesale, with the validator green."""
    repo = tmp_path / "r"
    _init(repo)
    _git(repo, "checkout", "-q", "-b", "feat/FEAT-BBBB", "main")
    _file_a_followup(repo, "FEAT-BBBB", "Beta follow-up")
    _git(repo, "checkout", "-q", "-b", "feat/FEAT-AAAA", "main")
    edit_seed(repo, "effort: Low", "effort: High")
    (repo / "tasks/index.yml").write_text((repo / "tasks/index.yml").read_text()
                                          + _entry("FEAT-AAAA", "Alpha follow-up"))
    (repo / "tasks/open/FEAT-AAAA.md").write_text("# FEAT-AAAA\n")
    commit_all(repo, "retriage FEAT-SEED, file FEAT-AAAA")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/FEAT-BBBB")
    rebase_stops(repo, "feat/FEAT-AAAA")
    r = resolve(repo, "index")
    assert r.returncode == 0, r.stdout
    assert "APPENDED: FEAT-AAAA" in r.stdout
    assert entry(repo, "FEAT-SEED")["effort"] == "High"
    assert _validate(repo).returncode == 0


# --- the shapes it refuses ---------------------------------------------------------------------

def _both_edit(tmp_path: Path, target_edit: tuple[str, str], branch_edit: tuple[str, str]) -> Path:
    repo = tmp_path / "r"
    _init(repo)
    _git(repo, "checkout", "-q", "-b", "feat/FEAT-BBBB", "main")
    edit_seed(repo, *target_edit)
    _file_a_followup(repo, "FEAT-BBBB", "Beta follow-up")
    _git(repo, "checkout", "-q", "-b", "feat/FEAT-AAAA", "main")
    edit_seed(repo, *branch_edit)
    _file_a_followup(repo, "FEAT-AAAA", "Alpha follow-up")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/FEAT-BBBB")
    rebase_stops(repo, "feat/FEAT-AAAA")
    return repo


def test_a_both_sides_status_move_stops_with_both_values(tmp_path: Path) -> None:
    repo = _both_edit(tmp_path, ("status: open", "status: done"), ("status: open", "status: in_progress"))
    before = (repo / "tasks/index.yml").read_text()
    r = resolve(repo, "index")
    assert r.returncode == 4, r.stdout
    assert "STATUS: FEAT-SEED target done, branch in_progress" in r.stdout
    assert r.stdout.splitlines()[-1] == "STOP: two actors moved a task's status; nothing was written"
    assert (repo / "tasks/index.yml").read_text() == before


def test_a_both_sides_field_edit_is_refused(tmp_path: Path) -> None:
    repo = _both_edit(tmp_path, ("effort: Low", "effort: Medium"), ("effort: Low", "effort: High"))
    before = (repo / "tasks/index.yml").read_text()
    r = resolve(repo, "index")
    assert r.returncode == 1, r.stdout
    assert "REFUSED: both sides edited FEAT-SEED: the target changed effort, the branch effort" in r.stdout
    assert r.stdout.splitlines()[-1] == "REFUSED: nothing was written; abort and 4a-SKIP the branch"
    assert (repo / "tasks/index.yml").read_text() == before


def test_a_same_id_added_differently_is_refused(tmp_path: Path) -> None:
    """`Q-547`: two branches auto-numbering one id, or a replay of an older copy; no conflict-local
    fact separates them, so it is not renumbered."""
    repo = tmp_path / "r"
    _init(repo)
    _git(repo, "checkout", "-q", "-b", "feat/b", "main")
    _file_a_followup(repo, "FEAT-0001", "Beta's task")
    _git(repo, "checkout", "-q", "-b", "feat/a", "main")
    _file_a_followup(repo, "FEAT-0001", "Alpha's task")
    (repo / "tasks/open/FEAT-0001.md").write_text("# FEAT-0001\n\nAlpha's body.\n")
    commit_all(repo, "alpha body")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/b")
    rebase_stops(repo, "feat/a")
    r = resolve(repo, "index")
    assert r.returncode == 1, r.stdout
    assert "REFUSED: both sides added FEAT-0001, differently" in r.stdout


def test_a_branch_change_outside_tasks_is_refused(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init(repo)
    _git(repo, "checkout", "-q", "-b", "feat/FEAT-BBBB", "main")
    _file_a_followup(repo, "FEAT-BBBB", "Beta follow-up")
    _git(repo, "checkout", "-q", "-b", "feat/FEAT-AAAA", "main")
    idx = repo / "tasks/index.yml"
    idx.write_text(idx.read_text().replace("    current_focus: true\n",
                                           "    current_focus: true\n  - number: 7\n    title: \"Next\"\n"
                                           "    status: planned\n"))
    _file_a_followup(repo, "FEAT-AAAA", "Alpha follow-up")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/FEAT-BBBB")
    rebase_stops(repo, "feat/FEAT-AAAA")
    r = resolve(repo, "index")
    assert r.returncode == 1, r.stdout
    assert "REFUSED: the branch changed phases: outside tasks:" in r.stdout


def test_a_conflicted_body_file_is_refused(tmp_path: Path) -> None:
    """Phase 350's case: a body both sides changed is the both-sides edit, index or no index."""
    repo = tmp_path / "r"
    _init(repo)
    _git(repo, "checkout", "-q", "-b", "feat/FEAT-BBBB", "main")
    (repo / "tasks/open/FEAT-SEED.md").write_text("# FEAT-SEED\n\nTarget's plan.\n")
    _file_a_followup(repo, "FEAT-BBBB", "Beta follow-up")
    _git(repo, "checkout", "-q", "-b", "feat/FEAT-AAAA", "main")
    (repo / "tasks/open/FEAT-SEED.md").write_text("# FEAT-SEED\n\nBranch's plan.\n")
    _file_a_followup(repo, "FEAT-AAAA", "Alpha follow-up")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/FEAT-BBBB")
    rebase_stops(repo, "feat/FEAT-AAAA")
    r = resolve(repo, "index")
    assert r.returncode == 1, r.stdout
    assert "REFUSED: tasks/open/FEAT-SEED.md is conflicted too" in r.stdout


# --- the published arm's `--since` -------------------------------------------------------------

def test_since_resolves_a_claim_commits_status_to_the_target(tmp_path: Path) -> None:
    """Step 4a item 2's published arm: the recorded PR head holds the branch's claim commit, so
    its status is the target's to keep, and Step 8 needs the line."""
    repo = tmp_path / "r"
    _init(repo)
    _git(repo, "checkout", "-q", "-b", "feat/FEAT-AAAA", "main")
    edit_seed(repo, "status: open", "status: in_progress")
    commit_all(repo, "claim FEAT-SEED")
    _git(repo, "update-ref", "refs/sysop/merged-pr-heads/7", "HEAD")
    _file_a_followup(repo, "FEAT-AAAA", "Alpha follow-up")
    _git(repo, "checkout", "-q", "main")
    edit_seed(repo, "status: open", "status: done\n    completed_date: 2026-10-27")
    idx = repo / "tasks/index.yml"
    idx.write_text(idx.read_text().replace("body: open/FEAT-SEED.md", "body: archive/FEAT-SEED.md"))
    _git(repo, "mv", "tasks/open/FEAT-SEED.md", "tasks/archive/FEAT-SEED.md")   # Step 4c's flip
    _file_a_followup(repo, "FEAT-BBBB", "Beta follow-up")
    assert _git(repo, "merge", "--no-ff", "-m", "merge", "refs/heads/feat/FEAT-AAAA").returncode != 0
    assert "tasks/index.yml" in _git(repo, "ls-files", "-u").stdout
    assert resolve(repo, "index").returncode == 4, "from stage 1 it reads as two actors"
    r = resolve(repo, "index", "--since", "refs/sysop/merged-pr-heads/7", "feat/FEAT-AAAA")
    assert r.returncode == 0, r.stdout
    assert "TARGET SIDE: FEAT-SEED status done (the branch's in_progress predates " \
           "refs/sysop/merged-pr-heads/7)" in r.stdout
    assert "APPENDED: FEAT-AAAA" in r.stdout
    assert entry(repo, "FEAT-SEED")["status"] == "done"
    assert set(ids(repo)) == {"FEAT-SEED", "FEAT-BBBB", "FEAT-AAAA"}
    assert _validate(repo).returncode == 0


# --- refusals of the call itself ---------------------------------------------------------------

def test_a_file_that_is_not_conflicted_is_exit_2(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init(repo)
    r = resolve(repo, "index")
    assert r.returncode == 2 and "is not conflicted here" in r.stdout


def test_a_placeholder_operand_is_exit_3(two_filings: Path) -> None:
    r = resolve(two_filings, "index", "--since", "<ref>", "feat/FEAT-AAAA")
    assert r.returncode == 3, r.stdout


def test_it_runs_only_from_the_top_level(two_filings: Path) -> None:
    r = resolve(two_filings / "tasks", "index")
    assert r.returncode == 2 and "top level" in r.stdout


def test_an_unknown_subcommand_is_exit_2(tmp_path: Path) -> None:
    assert resolve(tmp_path, "nope").returncode == 2


# --- style the splice keeps --------------------------------------------------------------------

def test_an_unindented_list_with_comments_keeps_its_style(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init(repo)
    idx = repo / "tasks/index.yml"
    text = idx.read_text().replace("\n  - id: FEAT-SEED", "\n# the backlog\n- id: FEAT-SEED")
    text = "\n".join(ln[2:] if ln.startswith("    ") and "tasks:" not in ln and
                     text.index("tasks:") < text.index(ln) else ln for ln in text.split("\n"))
    idx.write_text(text)
    commit_all(repo, "restyle")
    assert yaml.safe_load(idx.read_text())["tasks"][0]["id"] == "FEAT-SEED"

    def file_flat(tid: str) -> None:
        idx.write_text(idx.read_text() + f"\n- id: {tid}  # filed\n  title: \"{tid}\"\n  phase: 6\n"
                       "  status: open\n  effort: Low\n  blast_radius: single-file\n"
                       f"  user_action: false\n  depends_on: []\n  surfaced_by: []\n  body: open/{tid}.md\n")
        (repo / f"tasks/open/{tid}.md").write_text(f"# {tid}\n")
        commit_all(repo, tid)

    _git(repo, "checkout", "-q", "-b", "feat/b", "main")
    file_flat("FEAT-BBBB")
    _git(repo, "checkout", "-q", "-b", "feat/a", "main")
    file_flat("FEAT-AAAA")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/b")
    rebase_stops(repo, "feat/a")
    target = _git(repo, "show", ":2:tasks/index.yml").stdout
    r = resolve(repo, "index")
    assert r.returncode == 0, r.stdout + r.stderr
    out = idx.read_text()
    assert out.startswith(target.rstrip("\n")) and "# the backlog\n" in out
    assert "- id: FEAT-AAAA  # filed\n" in out
    assert ids(repo) == ["FEAT-SEED", "FEAT-BBBB", "FEAT-AAAA"]
    assert _validate(repo).returncode == 0


# --- tasks/notes.md ----------------------------------------------------------------------------

def _notes_conflict(tmp_path: Path, base: str, target: str, branch: str) -> Path:
    repo = tmp_path / "r"
    _init(repo)
    notes = repo / "tasks/notes.md"
    notes.write_text(base)
    commit_all(repo, "notes")
    _git(repo, "checkout", "-q", "-b", "feat/a", "main")
    notes.write_text(branch)
    commit_all(repo, "branch")
    _git(repo, "checkout", "-q", "main")
    notes.write_text(target)
    commit_all(repo, "target")
    _git(repo, "checkout", "-q", "feat/a")
    assert _git(repo, "rebase", "main").returncode != 0
    assert "tasks/notes.md" in _git(repo, "ls-files", "-u").stdout
    return repo


def test_a_branch_promotion_beside_a_target_append_stays_promoted(tmp_path: Path) -> None:
    """The recipe's fallback took the target's file and appended stage 3's additions, which
    brings back a line the branch deleted: the promoted note returned, duplicating its task."""
    repo = _notes_conflict(tmp_path, "- a\n- promoted\n", "- a\n- promoted\n- target's\n", "- a\n")
    r = resolve(repo, "notes")
    assert r.returncode == 0, r.stdout
    assert (repo / "tasks/notes.md").read_text() == "- a\n- target's\n"
    assert "1 line(s) it deleted taken out" in r.stdout


def test_two_appends_union_and_a_shared_line_lands_once(tmp_path: Path) -> None:
    repo = _notes_conflict(tmp_path, "- a\n", "- a\n- same\n- target's\n", "- a\n- branch's\n- same\n")
    assert resolve(repo, "notes").returncode == 0
    assert (repo / "tasks/notes.md").read_text() == "- a\n- same\n- target's\n- branch's\n"


def test_a_target_delete_survives(tmp_path: Path) -> None:
    repo = _notes_conflict(tmp_path, "- a\n- gone\n", "- a\n", "- a\n- gone\n- branch's\n")
    assert resolve(repo, "notes").returncode == 0
    assert (repo / "tasks/notes.md").read_text() == "- a\n- branch's\n"


def test_a_nested_ledger_is_refused(tmp_path: Path) -> None:
    repo = _notes_conflict(tmp_path, "- a\n", "- a\n  - nested\n", "- a\n- branch's\n")
    r = resolve(repo, "notes")
    assert r.returncode == 1 and "is not flat: line 2 is indented" in r.stdout
    assert "<<<<<<<" in (repo / "tasks/notes.md").read_text(), "nothing was written"


# --- Phase 425's battery survivors (C09, C10, P01) ---------------------------------------------

def _removal_vs_edit(tmp_path: Path, target_removes: bool) -> Path:
    """One side removes FEAT-OLD, the other edits it; both file a follow-up, so the index
    conflicts at the end."""
    repo = tmp_path / "r"
    _init(repo)
    _file_a_followup(repo, "FEAT-OLD", "Disputed")
    old = _entry("FEAT-OLD", "Disputed")

    def remove() -> None:
        idx = repo / "tasks/index.yml"
        idx.write_text(idx.read_text().replace(old, ""))
        (repo / "tasks/open/FEAT-OLD.md").unlink()

    def edit() -> None:
        idx = repo / "tasks/index.yml"
        idx.write_text(idx.read_text().replace(old, old.replace("effort: Low", "effort: High")))

    _git(repo, "checkout", "-q", "-b", "feat/b", "main")
    (remove if target_removes else edit)()
    _file_a_followup(repo, "FEAT-BBBB", "Beta follow-up")
    _git(repo, "checkout", "-q", "-b", "feat/a", "main")
    (edit if target_removes else remove)()
    _file_a_followup(repo, "FEAT-AAAA", "Alpha follow-up")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/b")
    rebase_stops(repo, "feat/a")
    return repo


def test_an_edit_to_an_entry_the_target_removed_is_refused(tmp_path: Path) -> None:
    repo = _removal_vs_edit(tmp_path, target_removes=True)
    before = (repo / "tasks/index.yml").read_text()
    r = resolve(repo, "index")
    assert r.returncode == 1, r.stdout
    assert "REFUSED: the target removed FEAT-OLD and the branch edited it" in r.stdout
    assert (repo / "tasks/index.yml").read_text() == before


def test_a_removal_of_an_entry_the_target_edited_is_refused(tmp_path: Path) -> None:
    repo = _removal_vs_edit(tmp_path, target_removes=False)
    before = (repo / "tasks/index.yml").read_text()
    r = resolve(repo, "index")
    assert r.returncode == 1, r.stdout
    assert "REFUSED: the branch removed FEAT-OLD and the target edited it" in r.stdout
    assert (repo / "tasks/index.yml").read_text() == before


def test_the_template_seeds_the_resolvers_rule_and_the_plugin_cache_read() -> None:
    """The arm runs the resolver under `dontAsk`, where a call no rule covers is denied, and a
    plugin install reads its step files from the cache (Phase 425's probes)."""
    import json
    allow = json.loads((SCRIPT.parents[1] / ".claude" / "settings.json").read_text())["permissions"]["allow"]
    assert "Bash(python3 sysop/scripts/resolve_append_conflict.py:*)" in allow
    assert "Read(~/.claude/plugins/cache/sysop/**)" in allow


# --- the author-side pass's hostile corpus (rule 4): text the consumer writes -----------------

def _module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("resolve_append_conflict", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _e(i: str, extra: str = "") -> str:
    return f"  - id: {i}\n    title: \"{i}\"\n    status: open\n{extra}"


_SCALAR = "    notes: |\n      - id: FAKE\n      - more\n"
HOSTILE = {
    "a block scalar holding '- id:'": ("tasks:\n" + _e("A", _SCALAR), "tasks:\n" + _e("A", _SCALAR) + _e("B")),
    "CRLF line ends": (("tasks:\n" + _e("A")).replace("\n", "\r\n"),
                       ("tasks:\n" + _e("A") + _e("B")).replace("\n", "\r\n")),
    "no trailing newline": (("tasks:\n" + _e("A")).rstrip("\n"), "tasks:\n" + _e("A") + _e("B")),
    "tasks: before another key": ("tasks:\n" + _e("A") + "phases:\n  - number: 1\n",
                                  "tasks:\n" + _e("A") + _e("B") + "phases:\n  - number: 1\n"),
    "a trailing comment block": ("tasks:\n" + _e("A") + "\n# end\n", "tasks:\n" + _e("A") + _e("B") + "\n# end\n"),
    "a document marker": ("---\ntasks:\n" + _e("A"), "---\ntasks:\n" + _e("A") + _e("B")),
}


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_the_splice_holds_on_hostile_text(name: str) -> None:
    r = _module()
    ours_text, theirs_text = HOSTILE[name]
    ours, theirs, base = r.Index(ours_text, "o"), r.Index(theirs_text, "t"), r.Index(ours_text, "b")
    ops, refused, status, _ = r.classify(base, ours, theirs)
    assert ops == [("append", "B")] and not refused and not status
    got = r.Index(r.splice(ours, theirs, ops), "got")
    assert r.normal(got.doc) == r.normal(r.expected(ours, theirs, ops))
    assert got.ids == ["A", "B"]


def test_the_installers_empty_seed_has_no_entries_and_a_flow_list_with_entries_is_refused() -> None:
    """Phase 425's round (lens A): `tasks: []` is `install.sh`'s seed and `safe_dump`'s empty list,
    and refusing it 4a-SKIPped every branch filing a first task, on every close."""
    r = _module()
    seed = r.Index("schema_version: 2\ntasks: []\n", "o")
    assert seed.ids == [] and seed.flow_empty == 1
    with pytest.raises(r.Refused):
        r.Index("tasks: [{id: A, title: a}]\n", "o")
    with pytest.raises(r.Unmappable):
        r.Index("tasks:\n  - id: A\n    deps: &d [X]\n  - id: C\n    deps: *d\n", "o")


# --- Phase 425's round, lens A ----------------------------------------------------------------

def _seed_conflict(tmp_path: Path, seed: str, a: str, b: str, name: str = "tasks/index.yml") -> Path:
    """`main` at `seed`; branch `feat/b` writes `b` and lands; `feat/a` writes `a` and rebases."""
    repo = tmp_path / "r"
    repo.mkdir()
    for args in (("init", "-q", "."), ("symbolic-ref", "HEAD", "refs/heads/main"),
                 ("config", "user.email", "t@t"), ("config", "user.name", "T"),
                 ("config", "core.autocrlf", "false")):
        _git(repo, *args)
    (repo / "tasks").mkdir()
    f = repo / name
    f.write_bytes(seed.encode())
    commit_all(repo, "seed")
    for br, text in (("feat/b", b), ("feat/a", a)):
        _git(repo, "checkout", "-q", "-b", br, "main")
        f.write_bytes(text.encode())
        commit_all(repo, br)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/b")
    _git(repo, "checkout", "-q", "feat/a")
    assert _git(repo, "rebase", "main").returncode != 0
    return repo


def test_the_installers_seed_resolves_end_to_end(tmp_path: Path) -> None:
    head = "schema_version: 2\nphases: []\n"
    repo = _seed_conflict(tmp_path, head + "tasks: []\n", head + "tasks:\n- id: A\n  title: a\n",
                          head + "tasks:\n- id: B\n  title: b\n")
    r = resolve(repo, "index")
    assert r.returncode == 0, r.stdout
    assert ids(repo) == ["B", "A"]


def test_a_crlf_index_keeps_its_line_ends_through_git(tmp_path: Path) -> None:
    """Lens A: `git show` read with universal newlines rewrote every line to LF."""
    crlf = lambda s: s.replace("\n", "\r\n")
    base = "tasks:\n  - id: S\n    title: s\n"
    repo = _seed_conflict(tmp_path, crlf(base), crlf(base + "  - id: A\n    title: a\n"),
                          crlf(base + "  - id: B\n    title: b\n"))
    assert resolve(repo, "index").returncode == 0
    raw = (repo / "tasks/index.yml").read_bytes()
    assert raw == crlf(base + "  - id: B\n    title: b\n  - id: A\n    title: a\n").encode(), raw


def test_a_block_scalar_ending_in_a_hash_line_maps(tmp_path: Path) -> None:
    """Lens A: a scalar's last content line starting with `#` was trimmed off its entry (exit 2)."""
    base = "tasks:\n  - id: S\n    notes: |\n      first\n      # not a comment\n"
    repo = _seed_conflict(tmp_path, base, base + "  - id: A\n    title: a\n",
                          base + "  - id: B\n    title: b\n")
    r = resolve(repo, "index")
    assert r.returncode == 0, r.stdout
    assert entry(repo, "S")["notes"] == "first\n# not a comment\n"


def test_notes_keeps_a_line_holding_a_unicode_line_separator(tmp_path: Path) -> None:
    """Lens A: `str.splitlines` split `- y\u2028z` into two lines."""
    repo = _notes_conflict(tmp_path, "- a\n", "- a\n- t\n", "- a\n- y\u2028z\n")
    assert resolve(repo, "notes").returncode == 0
    assert (repo / "tasks/notes.md").read_text() == "- a\n- t\n- y\u2028z\n"


def test_notes_keeps_crlf(tmp_path: Path) -> None:
    repo = _seed_conflict(tmp_path, "- a\r\n", "- a\r\n- x\r\n", "- a\r\n- t\r\n", "tasks/notes.md")
    assert resolve(repo, "notes").returncode == 0
    assert (repo / "tasks/notes.md").read_bytes() == b"- a\r\n- t\r\n- x\r\n"


def test_since_refuses_a_ref_that_already_holds_the_branch(tmp_path: Path) -> None:
    """Lens A: with the ref at the branch tip, reading from it dropped the branch's edit, exit 0."""
    repo = tmp_path / "r"
    _init(repo)
    _git(repo, "checkout", "-q", "-b", "feat/b", "main")
    _file_a_followup(repo, "FEAT-BBBB", "Beta follow-up")
    _git(repo, "checkout", "-q", "-b", "feat/a", "main")
    edit_seed(repo, "effort: Low", "effort: High")
    _file_a_followup(repo, "FEAT-AAAA", "Alpha follow-up")
    _git(repo, "update-ref", "refs/sysop/merged-pr-heads/9", "HEAD")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/b")
    assert _git(repo, "merge", "--no-ff", "-m", "m", "refs/heads/feat/a").returncode != 0
    before = (repo / "tasks/index.yml").read_text()
    r = resolve(repo, "index", "--since", "refs/sysop/merged-pr-heads/9", "feat/a")
    assert r.returncode == 2 and "already contains refs/heads/feat/a" in r.stdout, r.stdout
    assert (repo / "tasks/index.yml").read_text() == before


def test_the_post_splice_check_stops_a_wrong_splice(two_filings: Path, monkeypatch) -> None:
    """Lens A: disabling the parse-equals-expected check left the module green."""
    r = _module()
    monkeypatch.chdir(two_filings)
    before = (two_filings / "tasks/index.yml").read_text()
    monkeypatch.setattr(r, "splice", lambda ours, theirs, ops: "".join(ours.lines))
    with pytest.raises(SystemExit) as ex:
        r.cmd_index([])
    assert ex.value.code == 2
    assert (two_filings / "tasks/index.yml").read_text() == before


def test_since_reads_the_branch_not_a_tag_of_its_name(tmp_path: Path) -> None:
    """Lens A: no test held `refs/heads/` qualification (`Q-703`)."""
    repo = tmp_path / "r"
    _init(repo)
    seed = _git(repo, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "checkout", "-q", "-b", "feat/FEAT-AAAA", "main")
    edit_seed(repo, "status: open", "status: in_progress")
    commit_all(repo, "claim FEAT-SEED")
    _git(repo, "update-ref", "refs/sysop/merged-pr-heads/7", "HEAD")
    _file_a_followup(repo, "FEAT-AAAA", "Alpha follow-up")
    _git(repo, "tag", "feat/FEAT-AAAA", seed)            # a tag of the branch's name, at the seed
    _git(repo, "checkout", "-q", "main")
    edit_seed(repo, "status: open", "status: done\n    completed_date: 2026-10-27")
    idx = repo / "tasks/index.yml"
    idx.write_text(idx.read_text().replace("body: open/FEAT-SEED.md", "body: archive/FEAT-SEED.md"))
    _git(repo, "mv", "tasks/open/FEAT-SEED.md", "tasks/archive/FEAT-SEED.md")
    _file_a_followup(repo, "FEAT-BBBB", "Beta follow-up")
    assert _git(repo, "merge", "--no-ff", "-m", "m", "refs/heads/feat/FEAT-AAAA").returncode != 0
    r = resolve(repo, "index", "--since", "refs/sysop/merged-pr-heads/7", "feat/FEAT-AAAA")
    assert r.returncode == 0, r.stdout


def test_notes_refuses_a_section_a_nested_base_and_a_deleted_ledger(tmp_path: Path) -> None:
    repo = _notes_conflict(tmp_path / "h", "- a\n", "- a\n## Later\n- t\n", "- a\n- b\n")
    r = resolve(repo, "notes")
    assert r.returncode == 1 and "is a heading below the first line" in r.stdout
    repo = _notes_conflict(tmp_path / "n", "- a\n  - sub\n", "- a\n- t\n", "- a\n- b\n")
    r = resolve(repo, "notes")
    assert r.returncode == 1 and "at stage 1 is not flat" in r.stdout
    repo = tmp_path / "d"
    _init(repo)
    (repo / "tasks/notes.md").write_text("- a\n")
    commit_all(repo, "notes")
    _git(repo, "checkout", "-q", "-b", "feat/a", "main")
    (repo / "tasks/notes.md").write_text("- a\n- b\n")
    commit_all(repo, "branch")
    _git(repo, "checkout", "-q", "main")
    (repo / "tasks/notes.md").unlink()
    commit_all(repo, "cleared")
    _git(repo, "checkout", "-q", "feat/a")
    assert _git(repo, "rebase", "main").returncode != 0
    r = resolve(repo, "notes")
    assert r.returncode == 1 and "one side deleted tasks/notes.md" in r.stdout


def test_a_conflicted_ledger_beside_the_index_is_not_a_body_conflict(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    _init(repo)
    (repo / "tasks/notes.md").write_text("- a\n")
    commit_all(repo, "notes")
    for br, tid in (("feat/b", "FEAT-BBBB"), ("feat/a", "FEAT-AAAA")):
        _git(repo, "checkout", "-q", "-b", br, "main")
        (repo / "tasks/notes.md").write_text(f"- a\n- {tid}\n")
        _file_a_followup(repo, tid, tid)
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/b")
    rebase_stops(repo, "feat/a")
    assert "tasks/notes.md" in _git(repo, "ls-files", "-u").stdout
    assert resolve(repo, "index").returncode == 0
    assert resolve(repo, "notes").returncode == 0


def test_a_duplicate_id_is_refused_and_the_write_keeps_the_files_mode(tmp_path: Path) -> None:
    r = _module()
    with pytest.raises(r.Refused):
        r.Index("tasks:\n  - id: A\n  - id: A\n", "o")
    f = tmp_path / "index.yml"
    f.write_text("x\n")
    f.chmod(0o640)              # not mkstemp's own 0600, which a skipped chmod would leave
    r.write_atomic(f, "y\n")
    assert f.read_text() == "y\n" and (f.stat().st_mode & 0o777) == 0o640


def test_a_status_stop_wins_over_another_refusal(tmp_path: Path) -> None:
    """Phase 425's round (lens B, B07): a both-sides status move beside another refusal is still
    the STOP (exit 4), not a 4a-SKIP."""
    repo = tmp_path / "r"
    _init(repo)
    _git(repo, "checkout", "-q", "-b", "feat/b", "main")
    edit_seed(repo, "status: open", "status: done")
    _file_a_followup(repo, "FEAT-0001", "Beta's task")
    _git(repo, "checkout", "-q", "-b", "feat/a", "main")
    edit_seed(repo, "status: open", "status: in_progress")
    _file_a_followup(repo, "FEAT-0001", "Alpha's task")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--ff-only", "feat/b")
    rebase_stops(repo, "feat/a")
    r = resolve(repo, "index")
    assert r.returncode == 4, r.stdout
    assert "STATUS: FEAT-SEED target done, branch in_progress" in r.stdout
    assert "REFUSED: both sides added FEAT-0001, differently" in r.stdout
