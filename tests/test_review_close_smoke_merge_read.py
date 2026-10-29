"""Phase 359 — `/review-close` Step 3c reads a task body as it will merge (`Q-638`), and a
`#` line inside a fenced code block is not a procedure heading (`Q-639`).

Both defects were reproduced by Phase 351's round, and both are executed here against the
heredoc extracted from `core/skills/review-close/SKILL.md`:

* `Q-638`: source 3 read a linked body at the approved branch's tip. When the default
  branch changed that body after the fork, the tip is not the text that merges, so a
  procedure heading the default branch added then was never read for an undeclared task.
  The body is now the tip three-way merged with the merge target by `git merge-file`
  (Wade, 2026-10-06: no git version floor), and a conflicted body scans both sides.
* `Q-639`: heading detection was fence-blind, so a `# manual check: …` shell comment read
  as an H1 procedure, and a `# comment` inside a real procedure's code block cut the section
  the human was shown. Fenced lines now neither start nor end a section (Wade, 2026-10-06).

Fixtures are real git repos with local-only history. A remote, where one is needed, is a
local bare repo under `tmp_path`, never a URL.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _prose_guard_helpers import _fence_state  # noqa: E402
from test_review_close_smoke_gate import SMOKE_SRC, _run, _signals, _sources  # noqa: E402
from test_review_close_smoke_held_and_tip import (  # noqa: E402
    LOCK, _field, _git, _index, _task, _tree,
)

SMOKE = "## Manual smoke required\n1. Rotate the staging key (MAIN-ADDED).\n"


def _forked(tmp_path: Path, *, base: str, main: str | None, branch: str | None,
            smoke: bool = False, **kw) -> Path:
    """`main` and `feat/x` fork from a commit whose FEAT-X body is `base`; each side then
    commits its own body (None leaves that side's body alone). FEAT-X is lock-linked."""
    repo = _tree(tmp_path, bodies={"FEAT-X.md": base}, index=_index(_task("FEAT-X", smoke=smoke)),
                 locks={"FEAT-X.lock": LOCK}, **kw)
    body = repo / "tasks/open/FEAT-X.md"
    _git(repo, "checkout", "-q", "-b", "feat/x")
    if branch is not None:
        body.write_text(branch, encoding="utf-8")
        _git(repo, "commit", "-qam", "branch edits the body")
    _git(repo, "checkout", "-q", "main")
    if main is not None:
        body.write_text(main, encoding="utf-8")
        _git(repo, "commit", "-qam", "main edits the body after the fork")
    return repo


BASE = "# X\n\nSummary.\n\n## Plan\n1. step one\n"
BRANCH_EDIT = "# X\n\nSummary.\n\n## Plan\n1. step one, done\n"
MAIN_ADDS = "# X\n\nSummary.\n\n" + SMOKE + "\n## Plan\n1. step one\n"


# ── Q-638: the body is read as it will merge ──

def test_a_heading_main_added_after_the_fork_is_read_for_an_undeclared_task(tmp_path):
    """Lens C's reproduction: an undeclared task, main adds the procedure after the fork,
    the branch edits elsewhere. The tip lacks the heading; the merge carries it."""
    repo = _forked(tmp_path, base=BASE, main=MAIN_ADDS, branch=BRANCH_EDIT)
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1, out
    assert "MAIN-ADDED" in out, out
    (read,) = _field(out, "READ")
    tip = _git(repo, "rev-parse", "feat/x")[:12]
    head = _git(repo, "rev-parse", "main")[:12]
    assert read == (f"feat/x@{tip} merged with main@{head} — the text that is merging; "
                    "the merge target changed this body"), read


def test_a_branch_that_never_touched_the_body_merges_mains_text(tmp_path):
    repo = _forked(tmp_path, base=BASE, main=MAIN_ADDS, branch=None)
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "MAIN-ADDED" in out, out


def test_a_heading_the_branch_retired_is_not_re_asked_when_main_edits_elsewhere(tmp_path):
    """The `Q-568` bound the entry warned a union read would break: the branch removed the
    procedure, main changed an unrelated line. The merge has no heading, so nothing asks."""
    base = "# X\n\nSummary.\n\n" + SMOKE.replace("MAIN-ADDED", "RETIRED") + "\n## Plan\n1. step one\n"
    branch = "# X\n\nSummary.\n\n## Plan\n1. step one\n"
    main = base.replace("Summary.", "Summary, reworded.")
    repo = _forked(tmp_path, base=base, main=main, branch=branch)
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 0, out


def test_a_body_main_left_alone_keeps_the_tip_label(tmp_path):
    repo = _forked(tmp_path, base=BASE, main=None, branch=BRANCH_EDIT + "\n" + SMOKE)
    out = _run(repo, [], branches=["feat/x"])
    tip = _git(repo, "rev-parse", "feat/x")[:12]
    assert _field(out, "READ") == [f"feat/x@{tip} — the branch tip, the text that is merging"], out


def test_a_conflicted_body_scans_both_sides_and_says_so(tmp_path):
    """Wade's ruling: a conflict scans both versions, the gate's loud direction."""
    base = "# X\n\n## Notes\nshared line\n"
    main = "# X\n\n" + SMOKE.replace("1. ", "1. main: ")
    branch = "# X\n\n## Notes\nbranch rewrote the shared line\n"
    repo = _forked(tmp_path, base=base, main=main, branch=branch)
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "main: Rotate" in out, out
    (read,) = _field(out, "READ")
    head = _git(repo, "rev-parse", "main")[:12]
    assert read.endswith(f"this body CONFLICTS with main@{head} (1 hunk(s)); each side's version is scanned"), read
    assert "=======" not in out and ">>>>>>>" not in out, out


def test_a_conflict_still_shows_a_heading_only_the_branch_wrote(tmp_path):
    base = "# X\n\n## Notes\nshared line\n"
    main = "# X\n\n## Notes\nmain rewrote the shared line\n"
    branch = "# X\n\n" + SMOKE.replace("MAIN-ADDED", "BRANCH-WROTE")
    repo = _forked(tmp_path, base=base, main=main, branch=branch)
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "BRANCH-WROTE" in out, out


def _origin_adds(tmp_path: Path, repo: Path, body: str = MAIN_ADDS) -> None:
    """A local bare origin holding main, then a second clone pushes `body` to it."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "main")
    other = tmp_path / "other"
    # `-b main`: a bare repo's HEAD follows `init.defaultBranch`, which is `master` on CI.
    subprocess.run(["git", "clone", "-q", "-b", "main", str(bare), str(other)], check=True, capture_output=True)
    _git(other, "config", "user.email", "t@example.invalid")
    _git(other, "config", "user.name", "t")
    (other / "tasks/open/FEAT-X.md").write_text(body, encoding="utf-8")
    _git(other, "commit", "-qam", "origin adds the procedure")
    _git(other, "push", "-q", "origin", "main")


def test_origin_ahead_of_head_is_the_merge_target(tmp_path):
    """The entry's `pr` case: origin's default branch gained the procedure and local main
    has not pulled it. The push lands on origin's text, so that is what merges."""
    repo = _forked(tmp_path, base=BASE, main=None, branch=BRANCH_EDIT)
    _origin_adds(tmp_path, repo)
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "MAIN-ADDED" in out, out
    (read,) = _field(out, "READ")
    org = _git(repo, "rev-parse", "origin/main")[:12]
    assert f"merged with origin/main@{org} —" in read and "merged with main@" not in read, read


def test_origin_diverged_from_main_is_also_a_target(tmp_path):
    """Round lens B, F1: local main carries an unpushed claim flip, so it has diverged from
    origin, which gained the procedure. Step 4-pre merges origin into the integration branch,
    and Rule B rebases onto it, so origin's text lands. Replayed here to prove it."""
    repo = _forked(tmp_path, base=BASE, main=None, branch=BRANCH_EDIT)
    _origin_adds(tmp_path, repo)
    (repo / "claimflip.txt").write_text("flip\n", encoding="utf-8")
    _git(repo, "add", "claimflip.txt")
    _git(repo, "commit", "-qm", "claim flip, unpushed")
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "MAIN-ADDED" in out, out
    (read,) = _field(out, "READ")
    assert "merged with origin/main@" in read, read
    _git(repo, "checkout", "-q", "-b", "merge/review-close-1", "main")
    _git(repo, "merge", "-q", "--no-edit", "origin/main")
    _git(repo, "merge", "-q", "--no-ff", "--no-edit", "feat/x")
    assert "MAIN-ADDED" in (repo / "tasks/open/FEAT-X.md").read_text(encoding="utf-8")


def test_the_target_is_the_default_branch_not_head(tmp_path):
    """Round lens A, 6: HEAD on another branch; Step 4-pre checks the default branch out
    before it merges, so local main is the target."""
    repo = _forked(tmp_path, base=BASE, main=MAIN_ADDS, branch=BRANCH_EDIT)
    _git(repo, "checkout", "-q", "-b", "scratch", "main~1")
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "MAIN-ADDED" in out, out
    (read,) = _field(out, "READ")
    assert f"merged with main@{_git(repo, 'rev-parse', 'main')[:12]} —" in read, read


def test_origin_behind_head_leaves_head_the_merge_target(tmp_path):
    """Local main carries an unpushed procedure; origin is the older base. HEAD is not behind
    origin, so HEAD stays the target and the procedure is read."""
    repo = _forked(tmp_path, base=BASE, main=None, branch=BRANCH_EDIT)
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "main")
    (repo / "tasks/open/FEAT-X.md").write_text(MAIN_ADDS, encoding="utf-8")
    _git(repo, "commit", "-qam", "main adds the procedure, unpushed")
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "MAIN-ADDED" in out, out
    (read,) = _field(out, "READ")
    assert f"merged with main@{_git(repo, 'rev-parse', 'main')[:12]} —" in read, read


def _clone_ws(tmp_path: Path, repo: Path) -> Path:
    ws = tmp_path / "main-feat-x"
    subprocess.run(["git", "clone", "-q", str(repo), str(ws)], check=True, capture_output=True)
    _git(ws, "config", "user.email", "t@example.invalid")
    _git(ws, "config", "user.name", "t")
    _git(ws, "checkout", "-q", "-b", "feat/x")
    (ws / "tasks/open/FEAT-X.md").write_text(BRANCH_EDIT + "\n" + SMOKE, encoding="utf-8")
    _git(ws, "commit", "-qam", "branch")
    (repo / "tasks/open/FEAT-X.md").write_text(MAIN_ADDS.replace("MAIN-ADDED", "LATE"), encoding="utf-8")
    _git(repo, "commit", "-qam", "main moves after the clone")
    (repo / "sysop/runtime/locks").mkdir(parents=True)
    (repo / "sysop/runtime/locks/FEAT-X.lock").write_text(
        f"task_id: FEAT-X\nbranch: feat/x\nmode: clone\nworkspace: {ws}\n", encoding="utf-8")
    return ws


def test_a_clone_workspace_that_has_the_target_reads_the_merge_there(tmp_path):
    """The clone fetched main's new commit, so the merge base is computable in the clone's
    own store, where the tip lives. Main's store cannot see the tip."""
    repo = _tree(tmp_path, bodies={"FEAT-X.md": BASE}, index=_index(_task("FEAT-X")))
    ws = _clone_ws(tmp_path, repo)
    _git(ws, "fetch", "-q", "origin")
    out = _run(repo, [], branches=["feat/x"])
    assert "LATE" in out and "MAIN-ADDED" in out, out
    reads = set(_field(out, "READ"))
    assert len(reads) == 1 and f"merged with main@{_git(repo, 'rev-parse', 'main')[:12]} —" in reads.pop(), out


def test_a_clone_workspace_without_the_target_reads_the_tip_and_says_so(tmp_path):
    """A `--clone` workspace has its own objects. When main moved after the clone, the
    merge base is not computable there, so the tip is read and the line says why."""
    repo = _tree(tmp_path, bodies={"FEAT-X.md": BASE}, index=_index(_task("FEAT-X")))
    _clone_ws(tmp_path, repo)
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "MAIN-ADDED" in out and "LATE" not in out, out
    (read,) = _field(out, "READ")
    assert "the branch tip, read as is: its merge with main@" in read and "could not be read" in read, read
    assert "BODY NOT READ" not in out, out
    (note,) = [ln for ln in out.splitlines() if ln.startswith("MERGE NOT READ: ")]
    assert note.startswith("MERGE NOT READ: tasks/index.yml § FEAT-X at `feat/x`: its merge with main@"), note
    assert "fatal:" in note, "the reason git gave must reach the note"


def _merge_note(out: str) -> str:
    (note,) = [ln for ln in out.splitlines() if ln.startswith("MERGE NOT READ: ")]
    return note


def test_an_unread_merge_is_named_even_for_an_undeclared_task_with_no_signal(tmp_path):
    """Round lens A, 4: the `READ:` line prints only with a signal, so an undeclared task
    whose merge could not be read needs a header line, or the fallback is silent."""
    repo = _tree(tmp_path, bodies={"FEAT-X.md": BASE}, index=_index(_task("FEAT-X", smoke=False)))
    ws = _clone_ws(tmp_path, repo)
    (ws / "tasks/open/FEAT-X.md").write_text(BRANCH_EDIT, encoding="utf-8")
    _git(ws, "commit", "-qam", "branch drops its own heading")
    out = _run(repo, [], branches=["feat/x"])
    assert out.splitlines()[0] == "NO_SMOKE_REQUIRED", out
    assert "could not be read" in _merge_note(out), out


def test_a_target_blob_that_does_not_decode_still_merges(tmp_path):
    """Round 2, lens E: a strict decode turned one non-UTF-8 byte on main into a tip read, so
    the procedure main added went unseen. Blobs decode with replacement, as pending docs do."""
    repo = _forked(tmp_path, base=BASE, main=None, branch=BRANCH_EDIT)
    (repo / "tasks/open/FEAT-X.md").write_bytes(MAIN_ADDS.encode() + b"\xff\n")
    _git(repo, "commit", "-qam", "main writes a non-UTF-8 byte")
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "MAIN-ADDED" in out and "MERGE NOT READ" not in out, out


def test_a_merge_file_error_is_named_without_a_temp_path(tmp_path):
    repo = _forked(tmp_path, base=BASE, main=MAIN_ADDS + "\x00\n", branch=BRANCH_EDIT)
    out = _run(repo, [], branches=["feat/x"])
    note = _merge_note(out)
    head = _git(repo, "rev-parse", "main")[:12]
    assert note.startswith(f"MERGE NOT READ: tasks/index.yml § FEAT-X at `feat/x`: merging it with main@{head} "
                           "failed (error: Cannot merge binary files: "), note
    assert note.endswith("; a procedure heading the merge target added is not seen"), note
    assert str(tmp_path) not in note, note


def test_no_resolvable_target_is_named(tmp_path):
    repo = _forked(tmp_path, base=BASE, main=None, branch=BRANCH_EDIT)
    _git(repo, "checkout", "-q", "--orphan", "fresh")
    out = _run(repo, [], branches=["feat/x"], default_branch="trunk")
    assert _merge_note(out) == ("MERGE NOT READ: tasks/index.yml § FEAT-X at `feat/x`: `trunk` does not "
                                "resolve here, so neither does HEAD; no merge target resolves; a procedure "
                                "heading the merge target added is not seen"), out


def test_a_body_the_target_moved_is_read_at_the_tip_and_named(tmp_path):
    """Round lens A, 3: Step 4c's archive move on the target is a rename, which a per-path
    read cannot follow; reading it as a deletion emptied the body. The tip is read instead."""
    repo = _forked(tmp_path, base=BASE + "\n" + SMOKE.replace("MAIN-ADDED", "TIP-KEPT"),
                   main=None, branch=None)
    (repo / "tasks/archive").mkdir()
    _git(repo, "mv", "tasks/open/FEAT-X.md", "tasks/archive/FEAT-X.md")
    _git(repo, "commit", "-qm", "archive move")
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "TIP-KEPT" in out, out
    assert "moved or deleted" in _merge_note(out), out


def test_a_heading_next_to_a_conflicting_fence_edit_still_signals(tmp_path):
    """Round lens A, 1 (HIGH): marker text is not markdown, so a fence opener from one side
    paired with a closer after the hunk and hid the other side's heading. Each side is now
    resolved on its own."""
    base = "# X\n\nIntro.\n```\nold code\n```\n\n## Plan\n1. one\n"
    main = "# X\n\nIntro.\n```bash\nnew code\n```\n\n## Plan\n1. one\n"
    branch = ("# X\n\nIntro.\n## Manual smoke required\n1. Rotate the key (BRANCH-WROTE).\n"
              "```sh\nold code\n```\n\n## Plan\n1. one\n")
    repo = _forked(tmp_path, base=base, main=main, branch=branch)
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "BRANCH-WROTE" in out, out


def test_diff3_conflict_style_does_not_resurrect_the_base(tmp_path):
    """Round lens A, 5: under `merge.conflictStyle=diff3` the marker text carries the base,
    so a procedure both sides removed was asked again."""
    base = "# X\n\n## Manual smoke required\n1. BASE-PROC.\n"
    main = "# X\n\n## Notes\nmain's note\n"
    branch = "# X\n\n## Notes\nbranch's note\n"
    repo = _forked(tmp_path, base=base, main=main, branch=branch)
    for style in ("diff3", "zdiff3"):
        _git(repo, "config", "merge.conflictStyle", style)
        out = _run(repo, [], branches=["feat/x"])
        assert out.splitlines()[0] == "NO_SMOKE_REQUIRED", (style, out)


# ── Q-639: a fenced `#` line no longer ends a section (Wade, 2026-10-06, after round 2) ──
#
# Round 1 built a rule that skipped fenced headings; two rounds each found real CommonMark
# headings it hid. So fences only decide where a section ENDS: a misread fence can lengthen a
# section and never hide a heading. A fenced line matching a phrase still signals, the cost
# Wade accepted.

def _doc(body: str) -> dict:
    return {"a.md": "---\nbranch: feat/a\n---\n# Summary\n\n" + body}


def test_a_fenced_shell_comment_still_signals_and_runs_to_the_next_real_heading(tmp_path):
    """Lens A's original fixture. The accepted cost: it is asked, once."""
    body = ("# X\n\n## Plan\n```bash\n# manual check: the export runs\nmake export\n```\n\n"
            "## Test decision\nunit tests.\n")
    repo = _forked(tmp_path, base=BASE, main=None, branch=body)
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "make export" in out, out


def test_a_fenced_comment_does_not_cut_the_procedure_shown(tmp_path):
    main = _tree(tmp_path, index=_index(), pending=_doc(
        "## Manual smoke required\n1. Start it:\n```bash\n# start the server\nmake run\n```\n"
        "2. Open the page and check the banner.\n"))
    out = _run(main, [])
    assert "2. Open the page and check the banner." in out, out
    assert "# start the server\nmake run" in out, "the section shown must be the text, not the mask"


def test_tilde_and_longer_fences_end_no_section(tmp_path):
    main = _tree(tmp_path, index=_index(), pending=_doc(
        "## Manual smoke required\n1. one\n~~~\n# a\n~~~\n````md\n```\n# b\n```\n````\n2. TAIL-STEP\n"))
    out = _run(main, [])
    assert "2. TAIL-STEP" in out, out


def test_an_unclosed_fence_ends_sections_as_before(tmp_path):
    main = _tree(tmp_path, index=_index(), pending=_doc(
        "## Manual smoke required\n1. Go.\n```\n# Next\nafter\n"))
    out = _run(main, [])
    assert _signals(out) == 1 and "after" not in out, out


def test_a_backtick_info_string_with_a_backtick_opens_no_fence(tmp_path):
    main = _tree(tmp_path, index=_index(), pending=_doc(
        "## Manual smoke required\n1. Go.\n```a`b\n# Next\nafter\n```\n"))
    out = _run(main, [])
    assert "after" not in out, out


def test_a_declared_task_whose_only_heading_is_fenced_signals_that_heading(tmp_path):
    body = "# X\n\n```md\n## Manual smoke required\n```\n"
    repo = _forked(tmp_path, base=BASE, main=None, branch=body, smoke=True)
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "no procedure heading matched" not in out, out


# ── the fence rule keeps one home: `_fence_state`'s, plus one stated divergence ──

def _gate_unfenced():
    ns: dict = {"re": re}
    src = SMOKE_SRC[SMOKE_SRC.index("_fence_line = re.compile("):SMOKE_SRC.index("def extract_sections")]
    exec(compile(src, "<gate>", "exec"), ns)
    return ns["unfenced"]


# Every fence in these is closed, so `_fence_state`'s verdict is the whole expectation.
FENCE_CORPUS = [
    "a\n```\n# x\n```\nb",
    "```bash\n# x\n```\n# y\n",
    "~~~\n```\n# x\n~~~\n",
    "````\n```\n# x\n```\n````\n",
    "```\n# x\n~~~\n```\n",
    "  ```\n# x\n  ```\n",
    "    ```\n# x\n    ```\n",
    "\t```\n# x\n\t```\n",
    "```\r\n# x\r\n```\r\n# y\r\n",
    "```\n```  \n# y\n",
    "```\n```x\n# x\n```\n",
    "```\n# a\n```\n```\n# b\n```\n",
    "```a`b\n# x\n",
    "~~~a`b\n# x\n~~~\n",
    "```\n# x\n```\t\n",
    "```a`b\n# x\n```\n# y\n```\n",
    "```\n# x\n````\n# y\n```\nz\n```\n",
    "text\n",
    "",
]

# The one stated divergence from `_fence_state`: a fence open at the end of the text fences
# nothing, so a stray fence cannot run every later section to the end. (text, output)
UNCLOSED = [
    ("```\n# open to the end\n", "```\n# open to the end\n"),
    ("a\n```\n# x\n```\n```\n# y\n", "a\n   \n   \n   \n```\n# y\n"),
    ("~~~\n# x\n```\n", "~~~\n# x\n```\n"),
]


def test_the_gate_masks_exactly_the_lines_fence_state_fences():
    gate = _gate_unfenced()
    masked_any = False
    for text in FENCE_CORPUS:
        lines = text.split("\n")
        state = dict(_fence_state([ln.rstrip("\r") for ln in lines]))
        want = [" " * len(ln) if state[i] else ln for i, ln in enumerate(lines)]
        masked_any |= any(state.values())
        assert gate(text).split("\n") == want, (text, gate(text))
    assert masked_any, "the corpus fences nothing, so agreement over it proves nothing"
    for text, want in UNCLOSED:
        assert any(f for _, f in _fence_state(text.split("\n"))), text
        assert gate(text) == want, (text, gate(text))


def test_no_fence_shape_hides_a_heading(tmp_path):
    """The ruling's whole point, over every shape two rounds used to hide one: starts are
    matched on the raw text, so each heading signals whatever the fences around it do."""
    shapes = {
        "indented-top-level": "1. Run:\n  ```bash\n# comment\ncmd\n```\n\n",
        "mid-line-comment": "Never leave a stray `<!--` in the template.\n\n```html\n<!-- TODO -->\n```\n\n",
        "thematic-break": "---\n```bash\necho\n---\n```\n",
        "html-block": "<details>\n```\n</details>\n\n",
        "html-comment": "<!--\n```\n-->\n",
    }
    for name, lead in shapes.items():
        body = lead + "## Manual smoke required\n1. Go (REAL).\n\n```\nx\n```\n"
        main = _tree(tmp_path / name, index=_index(), pending=_doc(body))
        out = _run(main, [])
        assert "REAL" in out and _signals(out) >= 1, (name, out)


# ── round 1, lens A 2 and 8: what no fence may hide, and what a bare `#` must not invent ──

REAL = "## Manual smoke required\n1. Go (REAL).\n"


def test_a_real_heading_between_look_alike_fences_still_signals(tmp_path):
    """Each shape renders the heading under CommonMark; a fence rule that paired the two
    look-alikes blanked it, the gate's silent direction."""
    shapes = {
        "indented-code": "    ```\n" + REAL + "    ```\n",
        "tab": "\t```\n" + REAL + "\t```\n",
        "html-comment": "<!--\n```\n-->\n" + REAL + "<!--\n```\n-->\n",
        "list-item": "1. step\n   ```\n   code\n" + REAL + "```\necho\n```\n",
    }
    for name, body in shapes.items():
        main = _tree(tmp_path / name, index=_index(), pending=_doc(body))
        out = _run(main, [])
        assert _signals(out) == 1 and "REAL" in out, (name, out)


def test_a_fence_shaped_line_in_frontmatter_opens_no_fence(tmp_path):
    doc = {"a.md": "---\nbranch: feat/a\nnote: |\n  ```\n---\n# S\n\n" + REAL + "```\nc\n```\n"}
    main = _tree(tmp_path, index=_index(), pending=doc)
    assert _signals(_run(main, [])) == 1


def test_a_bare_hash_line_does_not_reach_across_lines(tmp_path):
    """`#` alone is an empty heading; `\\s+` let it reach the next line's prose, and across a
    blanked fence too."""
    for name, body in {"bare": "#\nRun this before merge.\n",
                       "over-fence": "#\n```\nx\n```\nRun this before merge.\n"}.items():
        main = _tree(tmp_path / name, index=_index(), pending=_doc(body))
        assert _signals(_run(main, [])) == 0, name


# ── round lens C: survivors the first suite let through ──

def test_a_clone_tip_main_can_see_merges_in_main_when_the_clone_lacks_the_target(tmp_path):
    """Phase 355 fetches a clone's tip into main, while the clone still lacks main's new
    commit: the merge base is found in main's store, the second place looked."""
    repo = _tree(tmp_path, bodies={"FEAT-X.md": BASE}, index=_index(_task("FEAT-X")))
    ws = _clone_ws(tmp_path, repo)
    _git(repo, "fetch", "-q", str(ws), "feat/x:feat/x")
    out = _run(repo, [], branches=["feat/x"])
    assert "LATE" in out and "MERGE NOT READ" not in out, out


def test_a_target_that_made_the_branchs_own_change_keeps_the_tip_label(tmp_path):
    repo = _forked(tmp_path, base=BASE, main=BRANCH_EDIT + "\n" + SMOKE,
                   branch=BRANCH_EDIT + "\n" + SMOKE)
    out = _run(repo, [], branches=["feat/x"])
    tip = _git(repo, "rev-parse", "feat/x")[:12]
    assert _field(out, "READ") == [f"feat/x@{tip} — the branch tip, the text that is merging"], out


def test_an_origin_equal_to_main_is_not_a_second_target(tmp_path):
    repo = _forked(tmp_path, base=BASE, main=MAIN_ADDS, branch=BRANCH_EDIT)
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "origin", "main")
    out = _run(repo, [], branches=["feat/x"])
    (read,) = _field(out, "READ")
    assert f"merged with main@{_git(repo, 'rev-parse', 'main')[:12]} —" in read and "origin/" not in read, read


def test_head_is_the_target_when_the_default_branch_does_not_resolve(tmp_path):
    repo = _forked(tmp_path, base=BASE, main=MAIN_ADDS, branch=BRANCH_EDIT)
    out = _run(repo, [], branches=["feat/x"], default_branch="trunk")
    (read,) = _field(out, "READ")
    head = _git(repo, "rev-parse", "--short=12", "HEAD")
    assert f"merged with main@{head} —" in read, read
    assert _merge_note(out) == (f"MERGE NOT READ: tasks/index.yml § FEAT-X at `feat/x`: `trunk` does not "
                                f"resolve here, so HEAD (main@{head}) stands in for it"), out


def test_origin_ahead_of_a_changed_main_is_the_only_target(tmp_path):
    """Local main changed the body and pushed it; origin went further. Origin holds all of
    main's work, so it is the one target, and the label names only it."""
    repo = _forked(tmp_path, base=BASE, main=MAIN_ADDS, branch=BRANCH_EDIT)
    _origin_adds(tmp_path, repo, MAIN_ADDS + "\n## Notes\norigin went further\n")
    out = _run(repo, [], branches=["feat/x"])
    (read,) = _field(out, "READ")
    org = _git(repo, "rev-parse", "origin/main")[:12]
    local = _git(repo, "rev-parse", "main")[:12]
    assert f"origin/main@{org}" in read and f"main@{local}" not in read, read


def test_a_section_both_sides_of_a_conflict_carry_is_asked_once(tmp_path):
    base = "# X\n\n" + SMOKE + "\n## Notes\nshared line\n"
    main = "# X\n\n" + SMOKE + "\n## Notes\nmain rewrote it\n"
    branch = "# X\n\n" + SMOKE + "\n## Notes\nbranch rewrote it\n"
    repo = _forked(tmp_path, base=base, main=main, branch=branch)
    out = _run(repo, [], branches=["feat/x"])
    assert "CONFLICTS" in _field(out, "READ")[0], out
    assert _signals(out) == 1, out


def test_the_validator_does_not_read_a_bare_hash_as_a_heading(tmp_path):
    import validate_tasks as vt

    body = tmp_path / "FEAT-X.md"
    body.write_text("# FEAT-X\n\n#\nmanual smoke is described elsewhere\n", encoding="utf-8")
    report = vt.Report()
    vt._check_manual_smoke({"manual_smoke": True}, body, "FEAT-X", report)
    assert len(report.warnings) == 1, report.warnings


# ── round 2: the merge read's survivors and the regex edges ──

def test_a_failed_target_keeps_the_other_targets_merge_and_names_only_itself(tmp_path):
    """Round 2, lens E F1 and lens D 3: local main archive-moved the body (unpushed) while a
    diverged origin added the procedure. Origin's merge is read and signals; the label and the
    note name main as the target whose heading is not seen, not origin."""
    repo = _forked(tmp_path, base=BASE, main=None, branch=BRANCH_EDIT)
    _origin_adds(tmp_path, repo)
    (repo / "tasks/archive").mkdir()
    _git(repo, "mv", "tasks/open/FEAT-X.md", "tasks/archive/FEAT-X.md")
    _git(repo, "commit", "-qm", "archive move, unpushed")
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "MAIN-ADDED" in out, out
    (read,) = _field(out, "READ")
    loc, org = _git(repo, "rev-parse", "main")[:12], _git(repo, "rev-parse", "origin/main")[:12]
    tip = _git(repo, "rev-parse", "feat/x")[:12]
    assert read == (f"feat/x@{tip} merged with origin/main@{org} — and the branch tip, read as is: "
                    f"main@{loc} moved or deleted `tasks/open/FEAT-X.md`; a heading main@{loc} added "
                    "is not seen"), read
    assert _merge_note(out).endswith(f"; a procedure heading main@{loc} added is not seen"), out


def test_a_clean_target_and_a_conflicting_target_are_both_named(tmp_path):
    repo = _forked(tmp_path, base=BASE, main=None, branch=BRANCH_EDIT)
    _origin_adds(tmp_path, repo, BASE.replace("1. step one", "1. step one, origin's way") + "\n" + SMOKE)
    (repo / "tasks/open/FEAT-X.md").write_text(MAIN_ADDS.replace("MAIN-ADDED", "LOCAL"), encoding="utf-8")
    _git(repo, "commit", "-qam", "local adds its own procedure, unpushed")
    out = _run(repo, [], branches=["feat/x"])
    (read,) = set(_field(out, "READ"))
    loc, org = _git(repo, "rev-parse", "main")[:12], _git(repo, "rev-parse", "origin/main")[:12]
    assert read.endswith(f"merged with main@{loc} — and this body CONFLICTS with origin/main@{org} "
                         "(1 hunk(s)); each side's version is scanned"), read


def test_two_linked_tasks_each_read_against_the_same_targets(tmp_path):
    repo = _tree(tmp_path, bodies={"FEAT-X.md": BASE, "FEAT-Y.md": BASE},
                 index=_index(_task("FEAT-X", smoke=False), _task("FEAT-Y", smoke=False)),
                 locks={"FEAT-X.lock": LOCK, "FEAT-Y.lock": LOCK.replace("FEAT-X", "FEAT-Y")})
    _git(repo, "checkout", "-q", "-b", "feat/x")
    for t in ("X", "Y"):
        (repo / f"tasks/open/FEAT-{t}.md").write_text(BRANCH_EDIT, encoding="utf-8")
    _git(repo, "commit", "-qam", "branch")
    _git(repo, "checkout", "-q", "main")
    for t in ("X", "Y"):
        (repo / f"tasks/open/FEAT-{t}.md").write_text(MAIN_ADDS.replace("MAIN-ADDED", f"ADDED-{t}"),
                                                       encoding="utf-8")
    _git(repo, "commit", "-qam", "main adds both")
    out = _run(repo, [], branches=["feat/x"])
    head = _git(repo, "rev-parse", "main")[:12]
    reads = _field(out, "READ")
    assert len(reads) == 2 and all(r.endswith(f"merged with main@{head} — the text that is merging; "
                                              "the merge target changed this body") for r in reads), out


def test_a_body_only_the_branch_has_is_read_at_the_tip_with_no_note(tmp_path):
    repo = _tree(tmp_path, index=_index(_task("FEAT-X", smoke=False)), locks={"FEAT-X.lock": LOCK})
    _git(repo, "checkout", "-q", "-b", "feat/x")
    (repo / "tasks/open/FEAT-X.md").write_text("# X\n\n" + SMOKE, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "branch creates the body")
    _git(repo, "checkout", "-q", "main")
    out = _run(repo, [], branches=["feat/x"])
    tip = _git(repo, "rev-parse", "feat/x")[:12]
    assert _field(out, "READ") == [f"feat/x@{tip} — the branch tip, the text that is merging"], out
    assert "MERGE NOT READ" not in out, out


def test_a_section_ends_at_a_tabbed_heading_and_not_at_a_hash_word(tmp_path):
    main = _tree(tmp_path, index=_index(), pending=_doc(
        "## Manual smoke required\n1. one\n#notes are inline\n2. KEPT\n##\tNext\nCUT\n"))
    out = _run(main, [])
    assert "2. KEPT" in out and "CUT" not in out, out


def test_the_validator_regex_takes_a_tab_and_refuses_no_space(tmp_path):
    import validate_tasks as vt

    body = tmp_path / "FEAT-X.md"
    for text, warns in (("# FEAT-X\n\n##\tManual smoke required\n", 0),
                        ("# FEAT-X\n\n#manual smoke check\n", 1)):
        body.write_text(text, encoding="utf-8")
        report = vt.Report()
        vt._check_manual_smoke({"manual_smoke": True}, body, "FEAT-X", report)
        assert len(report.warnings) == warns, (text, report.warnings)


def test_a_heading_indented_up_to_three_spaces_signals_and_ends_a_section(tmp_path):
    """Round 2, lens D (latent): CommonMark renders a heading indented 0-3 spaces; the gate
    anchored at column 0 and never saw one. Four spaces is indented code, not a heading."""
    main = _tree(tmp_path, index=_index(), pending=_doc(
        "   ## Manual smoke required\n1. Go (INDENTED).\n  ## Next\nCUT\n    ## Operator action\n"))
    out = _run(main, [])
    assert _signals(out) == 1 and "INDENTED" in out and "CUT" not in out, out
    import validate_tasks as vt

    body = tmp_path / "FEAT-X.md"
    for text, warns in (("# FEAT-X\n\n   ## Manual smoke required\n", 0),
                        ("# FEAT-X\n\n    ## Manual smoke required\n", 1)):
        body.write_text(text, encoding="utf-8")
        report = vt.Report()
        vt._check_manual_smoke({"manual_smoke": True}, body, "FEAT-X", report)
        assert len(report.warnings) == warns, (text, report.warnings)



def test_a_target_that_left_the_body_alone_adds_no_stale_copy(tmp_path):
    """Local main left the body alone; a diverged origin changed the procedure. The text that
    lands is origin's merge, so the tip's older procedure is not asked beside it."""
    base = "# X\n\n" + SMOKE.replace("MAIN-ADDED", "OLD-STEP") + "\n## Plan\n1. step one\n"
    repo = _forked(tmp_path, base=base, main=None, branch=base.replace("step one", "step one, done"))
    _origin_adds(tmp_path, repo, base.replace("OLD-STEP", "NEW-STEP"))
    (repo / "claimflip.txt").write_text("flip\n", encoding="utf-8")
    _git(repo, "add", "claimflip.txt")
    _git(repo, "commit", "-qm", "claim flip, unpushed")
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "NEW-STEP" in out and "OLD-STEP" not in out, out


def test_a_failed_target_keeps_the_tip_even_when_the_other_merge_drops_the_heading(tmp_path):
    """Local main moved the body (unreadable as a merge); origin removed the procedure. What
    local does to it is unknown, so the tip is still read, and its heading signals."""
    base = "# X\n\n" + SMOKE.replace("MAIN-ADDED", "TIP-PROC") + "\n## Plan\n1. step one\n"
    repo = _forked(tmp_path, base=base, main=None, branch=base.replace("step one", "step one, done"))
    _origin_adds(tmp_path, repo, "# X\n\n## Plan\n1. step one\n")
    (repo / "tasks/archive").mkdir()
    _git(repo, "mv", "tasks/open/FEAT-X.md", "tasks/archive/FEAT-X.md")
    _git(repo, "commit", "-qm", "archive move, unpushed")
    out = _run(repo, [], branches=["feat/x"])
    assert _signals(out) == 1 and "TIP-PROC" in out, out
    assert "moved or deleted" in _merge_note(out), out
