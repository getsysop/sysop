"""close_gate.py — the signed gate for the unattended land (`Q-411`, Phase 374; spec § 10.3).

The gate runs in CI from the default branch's copy and decides, from the merge result GitHub's
squash would produce and from the base, whether a pull request may merge with no human. These
tests drive it against real git fixtures (merge-tree, the real Step 4c index writer) and a fake
GitHub for the parts that read the API.
"""
from __future__ import annotations

import datetime
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from test_review_close_close_heredoc import CLOSE_SCRIPT, _git_env

SCRIPTS = Path(__file__).resolve().parent.parent / "core" / "companion" / "scripts"
GATE = SCRIPTS / "close_gate.py"
sys.path.insert(0, str(SCRIPTS))
import close_gate  # noqa: E402
import close_run  # noqa: E402

OWNER = "owner1"
CLASS = textwrap.dedent(f"""\
    ## Unattended close class

    allow: src/** tasks/** docs/** CHANGELOG.md PROJECT_STATUS.md
    exclude: src/billing
    blast_radius: single-module
    code_owner: @{OWNER}
    gate_app: 4242
    """)
READER = textwrap.dedent("""\
    ## Second reader

    reviewer: reader-bot[bot]
    format: approval
    request: please review
    timeout: 20m
    """)
GOVERNING_LINES = ["CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "AGENTS.override.md", ".claude/",
                   ".agents/", ".codex/", ".mcp.json", ".gitmodules", ".gitattributes", "/sysop/",
                   "/.github/", "/CODEOWNERS", "/docs/CODEOWNERS"]
CODEOWNERS = "\n".join(
    [f"* @{OWNER}", "", "# the class: no owner", "/src/", "/tasks/", "/docs/", "/CHANGELOG.md",
     "/PROJECT_STATUS.md", "", "# re-owned last: the exclusions, then the governing set",
     f"/src/billing/ @{OWNER}"] + [f"{g} @{OWNER}" for g in GOVERNING_LINES]) + "\n"


def _dump(index: dict) -> str:
    # The shape Step 4c writes (and every consumer index measured at Phase 374 already has).
    return yaml.safe_dump(index, sort_keys=False, default_flow_style=False, allow_unicode=True, width=120)


INDEX = {"schema_version": 2, "tasks": [
    {"id": "T-1", "title": "in class", "status": "in_progress", "effort": "Low",
     "blast_radius": "single-file", "user_action": False, "body": "open/T-1.md"},
    {"id": "T-2", "title": "needs a smoke", "status": "in_progress", "effort": "Low",
     "blast_radius": "single-file", "manual_smoke": True, "user_action": False, "body": "open/T-2.md"},
    {"id": "T-3", "title": "neighbour", "status": "open", "effort": "Low",
     "blast_radius": "single-file", "user_action": False, "body": "open/T-3.md"},
]}


def g(root: Path, *args: str, check: bool = True) -> str:
    p = subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=str(root),
                       capture_output=True, text=True, env=_git_env())
    if check and p.returncode:
        raise AssertionError(f"git {args}: {p.stderr}")
    return p.stdout.strip()


def write(root: Path, files: dict) -> None:
    for rel, text in files.items():
        p = root / rel
        if text is None:
            p.unlink()
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def commit(root: Path, msg: str, files: dict | None = None) -> str:
    write(root, files or {})
    g(root, "add", "-A")
    g(root, "commit", "-qm", msg, "--allow-empty")
    return g(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    g(root, "init", "-q", "-b", "main")
    commit(root, "base", {
        "CLAUDE.md": "# p\n\n" + READER + "\n" + CLASS,
        ".github/CODEOWNERS": CODEOWNERS,
        "tasks/index.yml": _dump(INDEX),
        "tasks/open/T-1.md": "# T-1\n", "tasks/open/T-2.md": "# T-2\n", "tasks/open/T-3.md": "# T-3\n",
        "tasks/archive/.gitkeep": "",
        "src/a.py": "a = 1\n", "src/billing/pay.py": "p = 1\n", "docs/guide.md": "guide\n",
    })
    return root


def branch(root: Path, name: str, files: dict | None = None, close: list[str] | None = None,
           start: str = "main") -> str:
    g(root, "checkout", "-qb", name, start)
    if files:
        commit(root, f"work on {name}", files)
    if close:
        # Step 4c's own program (`close_index.py` since Phase 386), with the ids as arguments.
        r = subprocess.run([sys.executable, str(CLOSE_SCRIPT), *close], cwd=str(root), capture_output=True,
                           text=True, env=_git_env(), timeout=30)
        assert r.returncode == 0, r.stderr
        commit(root, f"close {close}")
    head = g(root, "rev-parse", "HEAD")
    g(root, "checkout", "-q", "main")
    return head


def evaluate(root: Path, head: str, tip: str = "main") -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(GATE), "evaluate", tip, head], cwd=str(root),
                          capture_output=True, text=True, env=_git_env())


def problems(r: subprocess.CompletedProcess) -> str:
    return "\n".join(line for line in r.stdout.splitlines() if line.startswith("PROBLEM:"))


# --- the whole path, with the real Step 4c writer -------------------------------------------------

def test_a_real_close_of_an_in_class_task_passes(repo: Path) -> None:
    head = branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"])
    r = evaluate(repo, head)
    assert r.returncode == 0 and "VERDICT: pass" in r.stdout, r.stdout + r.stderr
    assert "NOT READ:" in r.stdout


def test_closing_a_manual_smoke_task_fails_on_the_flag_read_at_the_base(repo: Path) -> None:
    head = branch(repo, "feat/t2", {"src/a.py": "a = 2\n"}, close=["T-2"])
    r = evaluate(repo, head)
    assert r.returncode == 4 and "at the base: T-2 is manual_smoke" in problems(r)


def test_a_merge_that_closes_no_task_fails(repo: Path) -> None:
    r = evaluate(repo, branch(repo, "feat/none", {"src/a.py": "a = 2\n"}))
    assert r.returncode == 4 and "closes no task" in problems(r)


# --- the merge result -----------------------------------------------------------------------------

@pytest.mark.parametrize("path", ["docs/CLAUDE.md", "docs/claude.md", "src/.claude/x.json",
                                  "src/AGENTS.override.md", "docs/.gitattributes", "ſysop/x.sh",
                                  "docs/ＣＬＡＵＤＥ.md",
                                  ".github/workflows/x.yml", "CODEOWNERS", "src/billing/new.py"])
def test_a_governing_or_excluded_path_in_the_merge_result_fails(repo: Path, path: str) -> None:
    head = branch(repo, "feat/x", {"src/a.py": "a = 2\n", path: "x\n"}, close=["T-1"])
    r = evaluate(repo, head)
    assert r.returncode == 4 and f"{path} (" in problems(r), r.stdout


def test_a_symlink_in_the_merge_result_fails(repo: Path) -> None:
    g(repo, "checkout", "-qb", "feat/link", "main")
    os.symlink("a.py", repo / "src" / "link.py")
    commit(repo, "link")
    branch(repo, "feat/link2", close=["T-1"], start="feat/link")
    r = evaluate(repo, "feat/link2")
    assert r.returncode == 4 and "src/link.py is a symlink or gitlink (mode 120000)" in problems(r)


def test_a_gitlink_in_the_merge_result_fails(repo: Path) -> None:
    branch(repo, "feat/sub", close=["T-1"])
    g(repo, "checkout", "-q", "feat/sub")
    g(repo, "update-index", "--add", "--cacheinfo", f"160000,{g(repo, 'rev-parse', 'main')},src/sub")
    g(repo, "commit", "-qm", "sub")  # not `add -A`, which would stage the gitlink's removal
    g(repo, "checkout", "-q", "main")
    r = evaluate(repo, "feat/sub")
    assert r.returncode == 4 and "src/sub is a symlink or gitlink (mode 160000)" in problems(r)


def test_a_directory_rename_does_not_carry_a_file_the_tip_added(repo: Path) -> None:
    """§ 10.7 (8): GitHub's squash leaves a file the tip added under a directory the head renamed
    where the tip put it. `merge.directoryRenames=false` reproduces that; git's default would
    conflict, and `true` would move the file into the head's new directory."""
    commit(repo, "seed docs/x", {"docs/x/a.md": "a\n"})
    g(repo, "checkout", "-qb", "feat/mv", "main")
    g(repo, "mv", "docs/x", "docs/y")
    g(repo, "commit", "-qm", "mv")
    head = g(repo, "rev-parse", "HEAD")
    g(repo, "checkout", "-q", "main")
    tip = commit(repo, "tip adds", {"docs/x/b.md": "b\n"})
    why, tree = close_run.merge_tree(repo, tip, head)
    assert why == "" and g(repo, "cat-file", "-t", f"{tree}:docs/x/b.md") == "blob"
    assert subprocess.run(["git", "cat-file", "-e", f"{tree}:docs/y/b.md"], cwd=repo,
                          capture_output=True).returncode != 0


def test_a_union_merge_driver_is_ignored_as_github_ignores_it(repo: Path) -> None:
    """§ 10.7 (8): GitHub reads `merge=union` as nothing, so both sides editing one line is a
    conflict there. The scratch `GIT_DIR`'s unborn HEAD makes it one here too: no tree's
    `.gitattributes` is read."""
    commit(repo, "attrs", {".gitattributes": "docs/u.md merge=union\n", "docs/u.md": "one\n"})
    head = branch(repo, "feat/u", {"docs/u.md": "head\n"})
    tip = commit(repo, "tip edits", {"docs/u.md": "tip\n"})
    why, _ = close_run.merge_tree(repo, tip, head)
    assert why.startswith("does not merge cleanly") and "conflicts" in why


def test_a_callers_attribute_source_cannot_make_a_conflict_clean(repo: Path, monkeypatch) -> None:
    """Phase 374's battery (R08, round 2): a caller's `GIT_ATTR_SOURCE` naming a tree whose
    `.gitattributes` says `merge=union` made this merge clean. The empty `--attr-source` overrode
    it then; since round 3 the allowlisted environment drops it first."""
    attrs = commit(repo, "attrs", {".gitattributes": "docs/u.md merge=union\n"})
    tip, head = _union_conflict(repo)
    monkeypatch.setenv("GIT_ATTR_SOURCE", g(repo, "rev-parse", f"{attrs}^{{tree}}"))
    why, _ = close_run.merge_tree(repo, tip, head)
    assert why.startswith("does not merge cleanly") and "conflicts" in why


@pytest.mark.parametrize("var", ["GIT_COMMON_DIR", "GIT_GRAFT_FILE"])
def test_the_merge_environment_is_an_allowlist(repo: Path, monkeypatch, var: str) -> None:
    """Round 3: a denylist let `GIT_COMMON_DIR` bring the repository's `info/attributes`
    (`merge=union`) back into the scratch `GIT_DIR`, and `GIT_GRAFT_FILE` rewrite history."""
    tip, head = _union_conflict(repo)
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("docs/u.md merge=union\n", encoding="utf-8")
    grafts = repo.parent / "grafts"
    grafts.write_text(f"{head}\n", encoding="utf-8")  # the head as a root: nothing in common
    monkeypatch.setenv(var, str(repo / ".git") if var == "GIT_COMMON_DIR" else str(grafts))
    why, _ = close_run.merge_tree(repo, tip, head)
    assert why.startswith("does not merge cleanly") and "conflicts" in why
    for k in ("GIT_COMMON_DIR", "GIT_GRAFT_FILE", "GIT_DIR", "GIT_OBJECT_DIRECTORY", "HOME"):
        assert k not in close_run.merge_env() or k in close_run.MERGE_ENV_KEEP


def _union_conflict(repo: Path) -> tuple[str, str]:
    """A tip and a head that both edit one line of `docs/u.md`: a conflict on GitHub."""
    commit(repo, "u", {"docs/u.md": "one\n"})
    head = branch(repo, "feat/u", {"docs/u.md": "head\n"})
    return commit(repo, "tip edits", {"docs/u.md": "tip\n"}), head


@pytest.mark.parametrize("where", ["xdg", "attributesFile", "system-config"])
def test_a_users_attributes_file_cannot_make_a_conflict_clean(repo: Path, tmp_path: Path, monkeypatch, where) -> None:
    """Measured at Phase 374: `--attr-source` replaces only the tree's `.gitattributes`, and a
    `merge=union` line in `~/.config/git/attributes` (or a global `core.attributesFile`) still
    made this merge clean. GitHub ignores merge drivers, so the gate must see the conflict."""
    tip, head = _union_conflict(repo)
    attrs = tmp_path / "attrs"
    attrs.write_text("docs/u.md merge=union\n", encoding="utf-8")
    if where == "xdg":
        (tmp_path / "xdg" / "git").mkdir(parents=True)
        (tmp_path / "xdg" / "git" / "attributes").write_text(attrs.read_text(), encoding="utf-8")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    else:
        cfg = tmp_path / "gitconfig"
        cfg.write_text(f"[core]\n\tattributesFile = {attrs}\n", encoding="utf-8")
        monkeypatch.setenv("GIT_CONFIG_GLOBAL" if where == "attributesFile" else "GIT_CONFIG_SYSTEM", str(cfg))
        monkeypatch.delenv("GIT_CONFIG_NOSYSTEM", raising=False)
    why, _ = close_run.merge_tree(repo, tip, head)
    assert why.startswith("does not merge cleanly") and "conflicts" in why


def test_repository_config_and_info_attributes_cannot_change_the_merge(repo: Path) -> None:
    """Round 2: `merge.renameLimit`, `core.autocrlf` with `merge.renormalize`, and
    `$GIT_DIR/info/attributes` each changed `merge-tree`'s answer. The merge now runs in an empty
    scratch `GIT_DIR` over the repository's object store, so none of them reaches it."""
    tip, head = _union_conflict(repo)
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("docs/u.md merge=union\n", encoding="utf-8")
    g(repo, "config", "merge.renormalize", "true")
    g(repo, "config", "core.autocrlf", "true")
    g(repo, "config", "merge.renameLimit", "1")
    why, _ = close_run.merge_tree(repo, tip, head)
    assert why.startswith("does not merge cleanly") and "conflicts" in why


def test_a_repository_rename_limit_cannot_turn_a_clean_merge_into_a_conflict(repo: Path) -> None:
    """Round 2's measured case: two inexact renames on the head, an edit on the tip; with a
    repository `merge.renameLimit = 1` the raw `merge-tree` reported a modify/delete conflict."""
    body = "".join(f"line {i}\n" for i in range(40))
    commit(repo, "two files", {"docs/r1.md": "r1\n" + body, "docs/r2.md": "r2\n" + body})
    g(repo, "checkout", "-qb", "feat/mv", "main")
    g(repo, "mv", "docs/r1.md", "docs/s1.md")
    g(repo, "mv", "docs/r2.md", "docs/s2.md")
    write(repo, {"docs/s1.md": "r1 renamed\n" + body, "docs/s2.md": "r2 renamed\n" + body})
    head = commit(repo, "inexact renames")
    g(repo, "checkout", "-q", "main")
    tip = commit(repo, "tip edits", {"docs/r1.md": "r1\n" + body + "tail\n"})
    assert close_run.merge_tree(repo, tip, head)[0] == ""
    g(repo, "config", "merge.renameLimit", "1")
    g(repo, "config", "diff.renameLimit", "1")
    assert close_run.merge_tree(repo, tip, head)[0] == ""


def test_git_below_the_floor_refuses_with_its_minimum(repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(close_run, "git_version", lambda root: (2, 39))
    with pytest.raises(close_run.Fail, match=r"git 2\.39 is older than 2\.40"):
        close_run.merge_tree(repo, "main", "main")


# --- tasks/index.yml ------------------------------------------------------------------------------

def _closed(index: dict, tid: str) -> dict:
    out = yaml.safe_load(_dump(index))
    for t in out["tasks"]:
        if t["id"] == tid:
            t["status"], t["completed_date"] = "done", "2026-10-10"
            t["body"] = t["body"].replace("open/", "archive/")
    return out


def test_an_index_closing_one_entry_passes() -> None:
    probs, closed = close_gate.index_problems(_dump(INDEX), _dump(_closed(INDEX, "T-1")))
    assert probs == [] and closed == ["T-1"]


@pytest.mark.parametrize("field,value", [("manual_smoke", False), ("blast_radius", "single-module"),
                                         ("user_action", True), ("solo", True)])
def test_a_gating_field_change_on_any_task_fails(field: str, value) -> None:
    new = _closed(INDEX, "T-1")
    new["tasks"][1][field] = value  # T-2, which this merge does not close
    probs, _ = close_gate.index_problems(_dump(INDEX), _dump(new))
    assert any(f"T-2 changes a gating field ({field})" in p for p in probs), probs


def test_clearing_a_flag_on_the_entry_being_closed_still_fails() -> None:
    new = _closed(INDEX, "T-2")
    del new["tasks"][1]["manual_smoke"]
    probs, _ = close_gate.index_problems(_dump(INDEX), _dump(new))
    assert any("T-2 changes a gating field (manual_smoke)" in p for p in probs)


def test_an_added_or_removed_entry_fails() -> None:
    added = _closed(INDEX, "T-1")
    added["tasks"].append({"id": "T-4", "status": "open", "blast_radius": "single-file"})
    assert any("T-4 is added" in p for p in close_gate.index_problems(_dump(INDEX), _dump(added))[0])
    removed = _closed(INDEX, "T-1")
    removed["tasks"].pop(2)
    assert any("T-3 is removed or renamed" in p
               for p in close_gate.index_problems(_dump(INDEX), _dump(removed))[0])


@pytest.mark.parametrize("text,why", [
    ("tasks:\n- &a {id: T-1, status: open}\n- *a\n", "anchor or alias"),
    ("tasks:\n- id: T-1\n  status: open\n  status: done\n", "given twice"),
    ("base: &b {blast_radius: single-file}\ntasks:\n- <<: *b\n  id: T-1\n", "anchor or alias"),
    ("tasks:\n- id: T-1\n- id: T-1\n", "given twice"),
    ("tasks: [\n", "does not parse"),
    ("tasks: " + "[" * 3000 + "]" * 3000 + "\n", "does not parse"),  # RecursionError, not a YAMLError
])
def test_an_index_that_a_lenient_reader_would_resolve_is_unreadable(text: str, why: str) -> None:
    with pytest.raises(close_gate.Unreadable, match=why):
        close_gate.strict_index(text)


def test_a_merge_key_without_an_anchor_is_refused() -> None:
    with pytest.raises(close_gate.Unreadable, match="merge key"):
        close_gate.strict_index("tasks:\n- <<: {blast_radius: single-file}\n  id: T-1\n")


def test_an_index_added_or_deleted_fails() -> None:
    assert close_gate.index_problems(None, "tasks: []\n")[0]
    assert close_gate.index_problems("tasks: []\n", None)[0]
    assert close_gate.index_problems(None, None) == ([], [])


# --- the base -------------------------------------------------------------------------------------

def test_a_governing_symlink_at_the_base_keeps_the_gate_red(repo: Path) -> None:
    os.symlink("docs/guide.md", repo / "CLAUDE.local.md")
    commit(repo, "link at base")
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert r.returncode == 4 and "CLAUDE.local.md at the base is a symlink" in problems(r)


def test_a_governing_file_importing_an_in_class_path_keeps_the_gate_red(repo: Path) -> None:
    text = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    commit(repo, "import", {"CLAUDE.md": text + "\n## Notes\n\nSee @docs/guide.md for more.\n"})
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert r.returncode == 4 and "CLAUDE.md imports docs/guide.md" in problems(r)


def test_the_raw_scan_reads_every_at_token() -> None:
    """Fail-closed (Wade, round 2): every `@` in the raw text yields candidates, inside code, HTML,
    comments and links included; `\\ ` unescaped and `#fragment` dropped."""
    toks = close_gate.import_tokens("request: @codex review\n`@docs/x.md`\n<!-- @docs/c.md -->\n"
                                    "[@docs/l.md](x) @docs/my\\ guide.md#sec \\.@docs/e.md.\n")
    for want in ("codex", "docs/x.md", "docs/c.md", "docs/l.md", "docs/my guide.md", "docs/e.md"):
        assert want in toks, (want, toks)


# --- CODEOWNERS -----------------------------------------------------------------------------------

@pytest.mark.parametrize("pat,path,hit", [
    ("*", "a/b.c", True), ("*.js", "a/b/c.js", True), ("/build/logs/", "build/logs/x", True),
    ("/build/logs/", "x/build/logs/y", False), ("docs/*", "docs/a.md", True),
    ("docs/*", "docs/a/b.md", False), ("apps/", "x/apps/y", True), ("apps/", "apps", False),
    ("/docs/", "docs/a/b.md", True), ("**/logs", "deep/er/logs/x", True), ("CLAUDE.md", "a/b/CLAUDE.md", True),
    ("CLAUDE.md", "a/claude.md", False), (".claude/", "src/.claude/x", True), ("/src/", "src/a.py", True),
    ("/apps/github", "apps/github/x", True), ("/CODEOWNERS", "docs/CODEOWNERS", False),
])
def test_codeowners_patterns_read_as_github_documents_them(pat: str, path: str, hit: bool) -> None:
    assert bool(close_gate.codeowners_regex(pat).match(path)) is hit


def test_the_last_matching_rule_wins_and_an_owner_list_can_be_empty() -> None:
    rules = close_gate.parse_codeowners("* @a\n/docs/\n/docs/x/ @b  # comment\n")
    assert close_gate.owners_of(rules, "src/z") == ["@a"]
    assert close_gate.owners_of(rules, "docs/y.md") == []
    assert close_gate.owners_of(rules, "docs/x/y.md") == ["@b"]


def _with_codeowners(repo: Path, text: str | None) -> str:
    files = {".github/CODEOWNERS": text}
    commit(repo, "codeowners", files)
    return branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"])


def test_no_codeowners_fails(repo: Path) -> None:
    r = evaluate(repo, _with_codeowners(repo, None))
    assert r.returncode == 4 and "no CODEOWNERS at the base" in problems(r)


def test_a_codeowners_without_default_deny_fails(repo: Path) -> None:
    r = evaluate(repo, _with_codeowners(repo, CODEOWNERS.replace(f"* @{OWNER}\n", "")))
    assert r.returncode == 4 and "its first rule must be `* @owner1`" in problems(r)


def test_an_allow_line_after_the_governing_lines_un_owns_them(repo: Path) -> None:
    text = CODEOWNERS.replace("/docs/\n", "") + "/docs/\n"
    r = evaluate(repo, _with_codeowners(repo, text))
    assert r.returncode == 4 and "does not give the code owner" in problems(r) and "docs/CLAUDE.md" in problems(r)


def test_an_exclusion_left_unowned_fails(repo: Path) -> None:
    r = evaluate(repo, _with_codeowners(repo, CODEOWNERS.replace(f"/src/billing/ @{OWNER}\n", "")))
    assert r.returncode == 4 and "src/billing" in problems(r)


def test_a_class_without_code_owner_or_gate_app_fails(repo: Path) -> None:
    text = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    commit(repo, "no keys", {"CLAUDE.md": text.replace(f"code_owner: @{OWNER}\n", "").replace("gate_app: 4242\n", "")})
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert "names no code_owner" in problems(r) and "names no gate_app" in problems(r)


# --- the API half ---------------------------------------------------------------------------------

def _graph(*items) -> dict:
    return {"data": {"repository": {"pullRequest": {
        "comments": {"pageInfo": {"hasNextPage": False}, "nodes": list(items)},
        "reviews": {"pageInfo": {"hasNextPage": False}, "nodes": []}}}}}


def _item(author: str, *editors) -> dict:
    return {"author": {"login": author},
            "userContentEdits": {"pageInfo": {"hasNextPage": False},
                                 "nodes": [{"editor": None if e is None else {"login": e}} for e in editors]}}


def test_the_reviewers_own_edits_pass_and_anyone_elses_fail() -> None:
    # The shape § 10.7 (7) read: the history includes the author's own entry, and an app's
    # GraphQL login drops the `[bot]` its REST login carries.
    assert close_gate.edit_problems("reader-bot[bot]", _graph(_item("reader-bot", "reader-bot"))) == []
    assert close_gate.edit_problems("reader-bot[bot]", _graph(_item("reader-bot", "machine", "reader-bot")))
    assert close_gate.edit_problems("reader-bot[bot]", _graph(_item("reader-bot", None)))
    assert close_gate.edit_problems("reader-bot[bot]", _graph(_item("someone", "machine"))) == []


def _review(user: str, head: str, state: str, at: str) -> dict:
    return {"user": {"login": user}, "commit_id": head, "state": state, "submitted_at": at}


def test_the_escape_hatch_needs_the_owners_latest_approval_of_this_head_after_the_base_change() -> None:
    t = close_run.parse_time
    ok = [_review("Owner1", "h", "APPROVED", "2026-10-10T10:00:00Z")]
    assert close_gate.owner_approved(OWNER, "h", ok, t("2026-10-10T09:00:00Z"))
    assert not close_gate.owner_approved(OWNER, "h", ok, t("2026-10-10T11:00:00Z"))
    assert not close_gate.owner_approved(OWNER, "other", ok, None)
    assert not close_gate.owner_approved(OWNER, "h", [_review("someone", "h", "APPROVED", "2026-10-10T10:00:00Z")], None)
    later = ok + [_review(OWNER, "h", "CHANGES_REQUESTED", "2026-10-10T10:30:00Z")]
    assert not close_gate.owner_approved(OWNER, "h", later, None)


def test_a_waiting_reader_is_pending_never_neutral_and_any_problem_fails() -> None:
    assert close_gate.verdict([], [], ("wait", ["x"]), False)[0] == "pending"
    assert close_gate.verdict([], [], ("merge", ["ok"]), False)[0] == "success"
    assert close_gate.verdict([], [], ("park", ["no"]), False)[0] == "failure"
    assert close_gate.verdict(["bad"], [], ("merge", []), False)[0] == "failure"
    assert close_gate.verdict(["bad"], ["worse"], ("park", []), True)[0] == "success"


def test_no_request_comment_means_the_reader_is_waiting() -> None:
    cfg = {"reviewer": "r", "request": "please review", "timeout": "20m", "format": "approval"}
    now = datetime.datetime(2026, 10, 10, tzinfo=datetime.timezone.utc)
    assert close_gate.reader_state(cfg, "h", [], [], [], [], now)[0] == "wait"
    asked = [{"body": "please review", "created_at": "2026-10-09T23:50:00Z"}]
    approved = [{"user": {"login": "r"}, "commit_id": "h", "state": "APPROVED",
                 "submitted_at": "2026-10-09T23:55:00Z"}]
    assert close_gate.reader_state(cfg, "h", approved, [], asked, [], now)[0] == "merge"


class FakeGitHub:
    def __init__(self, tip: str, head: str, moves: bool = False, newer: bool = False):
        self.tip, self.head, self.moves, self.posts, self.reads = tip, head, moves, [], 0
        self.newer, self.heads = newer, {}

    def get(self, path: str):
        if path == "":
            return {"default_branch": "main"}
        if path.startswith("git/ref/heads/"):
            self.reads += 1
            return {"object": {"sha": "f" * 40 if self.moves and self.reads > 1 else self.tip}}
        if path.startswith("pulls/"):
            return {"number": 7, "state": "open", "base": {"ref": "main"}, "head": {"sha": self.head}}
        if path.startswith("codeowners/errors"):
            return {"errors": []}
        raise AssertionError(path)

    def pages(self, path: str):
        if path.endswith("issues/7/comments"):
            return [{"body": "please review", "created_at": "2026-10-10T00:00:00Z"}]
        if path.endswith("pulls/7/reviews"):
            return [{"user": {"login": "reader-bot[bot]"}, "commit_id": self.head, "state": "APPROVED",
                     "submitted_at": "2026-10-10T00:01:00Z"}]
        # The gate app holds no Issues permission, so a reactions read is refused (live, Phase 374).
        assert not path.endswith("/reactions"), "the gate must not read reactions"
        return []

    def graph(self, n: int):
        return _graph()

    def post(self, head, status, conclusion, title, lines):
        self.posts.append((head, status, conclusion))
        self.heads[len(self.posts)] = head
        return len(self.posts), 4242

    def update(self, run_id, status, conclusion, title, lines):
        self.posts.append((self.heads[run_id], status, conclusion))

    def runs(self, head):
        ours = [(i, 4242) for i, h in self.heads.items() if h == head]
        # A forged run under another app's id never counts as newer; a later run of ours does.
        return ours + [(999, 1)] + ([(500, 4242)] if self.newer else [])


def _run_args(**kw):
    import argparse
    return argparse.Namespace(**{"repo": "o/r", "event": "pull_request_target", "pr": 7,
                                 "head_sha": "", "post": True, **kw})


def _gate_run(repo: Path, monkeypatch, fake: FakeGitHub) -> str:
    monkeypatch.setattr(close_gate, "GitHub", lambda repo_name: fake)
    monkeypatch.setattr(close_gate, "fetch_head", lambda root, n: fake.head)
    monkeypatch.setattr(close_run, "utcnow",
                        lambda: datetime.datetime(2026, 10, 10, 0, 5, tzinfo=datetime.timezone.utc))
    g(repo, "checkout", "-q", "main")
    return str(close_gate.cmd_run(repo, _run_args()))


def test_run_posts_in_progress_then_the_verdict_on_the_head_it_evaluated(repo: Path, monkeypatch, capsys) -> None:
    head = branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"])
    fake = FakeGitHub(g(repo, "rev-parse", "main"), head)
    _gate_run(repo, monkeypatch, fake)
    assert fake.posts == [(head, "in_progress", ""), (head, "completed", "success")], capsys.readouterr().out


def test_run_posts_nothing_from_a_checkout_that_is_not_the_live_tip(repo: Path, monkeypatch, capsys) -> None:
    head = branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"])
    fake = FakeGitHub("e" * 40, head)
    _gate_run(repo, monkeypatch, fake)
    assert fake.posts == [] and "STALE:" in capsys.readouterr().out


def test_run_leaves_in_progress_when_the_tip_moves_during_the_evaluation(repo: Path, monkeypatch, capsys) -> None:
    head = branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"])
    fake = FakeGitHub(g(repo, "rev-parse", "main"), head, moves=True)
    _gate_run(repo, monkeypatch, fake)
    assert fake.posts == [(head, "in_progress", "")] and "MOVED #7" in capsys.readouterr().out


def test_the_gate_refuses_a_pyyaml_from_outside_its_interpreter(tmp_path: Path) -> None:
    venv = tmp_path / "bare"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    r = subprocess.run([str(venv / "bin" / "python3"), "-I", str(GATE), "evaluate", "a", "b"],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert r.returncode == 1 and "PyYAML must be installed in this interpreter's own environment" in r.stderr


def test_the_documented_class_and_codeowners_pass_the_gates_own_check(tmp_path: Path) -> None:
    """WORKFLOW.md's `## Unattended close class` template and the `CODEOWNERS` it shows beside the
    close gate must satisfy `codeowners_problems`, or a consumer copying them is red on arrival."""
    doc = (SCRIPTS.parent / "docs" / "WORKFLOW.md").read_text(encoding="utf-8")
    cls_text = doc.split("```markdown\n## Unattended close class\n", 1)[1].split("```", 1)[0]
    owners = doc.split("A\n`CODEOWNERS` the gate accepts, for the class above:\n\n```text\n", 1)[1].split("```", 1)[0]
    root = tmp_path / "r"
    root.mkdir()
    g(root, "init", "-q", "-b", "main")
    commit(root, "base", {"CLAUDE.md": "## Unattended close class\n" + cls_text, ".github/CODEOWNERS": owners})
    cls = close_run.read_class(root, rev="HEAD")
    assert cls["code_owner"] == "your-login" and cls["gate_app"] == "123456"
    assert close_gate.codeowners_problems(root, "HEAD", cls, []) == []


class _NoErrorsList(FakeGitHub):
    def get(self, path: str):
        if path.startswith("codeowners/errors"):
            raise close_run.Fail("gh api repos/o/r/codeowners/errors failed: HTTP 403")
        return super().get(path)


class _Edited(FakeGitHub):
    def graph(self, n: int):
        return _graph(_item("reader-bot", "machine-user", "reader-bot"))


@pytest.mark.parametrize("fake_cls,why", [(_NoErrorsList, "cannot read GitHub's codeowners/errors"),
                                          (_Edited, "edited by machine-user")])
def test_run_fails_when_a_check_it_needs_cannot_pass(repo: Path, monkeypatch, capsys, fake_cls, why) -> None:
    """The gate fails closed: an unreadable `codeowners/errors` and an edited reviewer comment
    each turn an otherwise passing close red."""
    head = branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"])
    fake = fake_cls(g(repo, "rev-parse", "main"), head)
    _gate_run(repo, monkeypatch, fake)
    out = capsys.readouterr().out
    assert fake.posts[-1] == (head, "completed", "failure") and why in out, out


def _possible_nodes(query: str) -> int:
    """GitHub's worst case: each connection's `first:`/`last:` times every one above it, summed."""
    import re as _re
    total, stack, pending = 0, [1], 1
    for m in _re.finditer(r"\(([^()]*)\)|\{|\}", query):
        if m.group(0) == "{":
            stack.append(stack[-1] * pending)
            pending = 1
        elif m.group(0) == "}":
            stack.pop()
        else:
            n = _re.search(r"\b(?:first|last):(\d+)", m.group(1))
            pending = int(n.group(1)) if n else 1
            total += stack[-1] * pending if n else 0
    return total


def test_the_edit_history_query_fits_githubs_node_limit() -> None:
    """Phase 374's live run: GitHub refused the first query (100 x 100 x 100 edits, 1,000,000
    possible nodes, over its 500,000 limit), and the gate failed closed on every pull request."""
    assert _possible_nodes(close_gate.EDITS_QUERY) <= 500_000
    assert _possible_nodes("{a(first:100){nodes{b(first:100){nodes{c(first:100){x}}}}}}") > 500_000


# --- the author-side battery's six survivors, each closed ------------------------------------------

def test_a_symlink_replaced_by_a_regular_file_fails(repo: Path) -> None:
    """R12: either side of a change being a link refuses, not only the new side."""
    os.symlink("a.py", repo / "src" / "link.py")
    commit(repo, "a symlink at the base")
    head = branch(repo, "feat/unlink", {"src/link.py": None}, close=["T-1"])
    g(repo, "checkout", "-q", "feat/unlink")
    (repo / "src" / "link.py").write_text("now a file\n", encoding="utf-8")
    head = commit(repo, "a file where the link was")
    g(repo, "checkout", "-q", "main")
    r = evaluate(repo, head)
    assert r.returncode == 4 and "src/link.py is a symlink or gitlink (mode 120000)" in problems(r)


def test_moving_a_neighbours_status_is_not_closing_it() -> None:
    """G09: only a status moving to `done` is a close; any other status change is a line outside
    the closed entries."""
    new = _closed(INDEX, "T-1")
    new["tasks"][2]["status"] = "in_progress"
    probs, closed = close_gate.index_problems(_dump(INDEX), _dump(new))
    assert closed == ["T-1"] and any("does not close (T-3)" in p for p in probs), probs


def test_an_import_naming_a_missing_path_is_not_an_import(repo: Path) -> None:
    """G12: `@docs/missing.md` names nothing at the base, so it keeps nothing red."""
    text = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    commit(repo, "a dangling import", {"CLAUDE.md": text + "\n## Notes\n\nSee @docs/missing.md.\n"})
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert r.returncode == 0 and "imports" not in problems(r), r.stdout


def test_the_gate_refuses_a_pyyaml_found_outside_its_interpreter(tmp_path: Path) -> None:
    """G28: a `yaml` importable from somewhere other than the interpreter's own environment (here
    through PYTHONPATH, which `-I` would ignore) is refused, not used."""
    import yaml as _yaml
    venv = tmp_path / "bare"
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
    site = str(Path(_yaml.__file__).resolve().parent.parent)
    r = subprocess.run([str(venv / "bin" / "python3"), str(GATE), "evaluate", "a", "b"],
                       capture_output=True, text=True, cwd=str(tmp_path), env=dict(os.environ, PYTHONPATH=site))
    assert r.returncode == 1 and "PyYAML must be installed in this interpreter's own environment" in r.stderr


# --- Phase 374's round: the index findings ---------------------------------------------------------

_H1_BASE = """tasks:
- id: T-1
  status: in_progress
  blast_radius: single-file
- id: T-2
  status: in_progress
  blast_radius: single-file
  depends_on:
  - T-1
  body: open/T-2.md
- id: T-3
  status: in_progress
  blast_radius: single-file
"""


def test_a_neighbours_tail_cannot_be_moved_into_the_closed_entry() -> None:
    """H1: moving the closed entry's dash above the neighbour's last lines made a text-alignment
    rule call them unchanged, while the parse moved them into the closed entry; T-2 lost fields."""
    moved = _H1_BASE.replace("""  depends_on:
  - T-1
  body: open/T-2.md
- id: T-3
  status: in_progress""", """- id: T-3
  depends_on:
  - T-1
  body: open/T-2.md
  status: done""")
    old, _ = close_gate.strict_index(_H1_BASE)
    new, _ = close_gate.strict_index(moved)
    assert "depends_on" in old["T-2"] and "depends_on" not in new["T-2"]  # the fixture does what it says
    probs, closed = close_gate.index_problems(_H1_BASE, moved)
    assert closed == ["T-3"] and any("does not close (T-2)" in p for p in probs), probs


@pytest.mark.parametrize("edit", ["remove a field", "add a field"])
def test_a_neighbours_field_added_or_removed_fails(edit: str) -> None:
    new = _closed(INDEX, "T-1")
    if edit == "remove a field":
        del new["tasks"][2]["effort"]
    else:
        new["tasks"][2]["depends_on"] = ["T-1"]
    probs, _ = close_gate.index_problems(_dump(INDEX), _dump(new))
    assert any("does not close (T-3)" in p for p in probs), probs


def test_a_comment_outside_the_closed_entries_may_change() -> None:
    base, new = "# keep this\n" + _dump(INDEX), "# changed\n" + _dump(_closed(INDEX, "T-1"))
    assert close_gate.index_problems(base, new) == ([], ["T-1"])


def test_reformatting_outside_the_closed_entries_is_allowed_and_a_value_change_is_not() -> None:
    """Phase 367 round 2's HIGH-1 cleared a flag with two PRs that each moved a quote; each moved
    quote changes a neighbour's parsed value, which refuses. A quote that changes no value does
    not, because Step 4c's own writer re-serialises the whole file (Phase 374's round)."""
    same = _dump(_closed(INDEX, "T-1")).replace("title: neighbour", "title: 'neighbour'")
    assert close_gate.index_problems(_dump(INDEX), same) == ([], ["T-1"])
    other = _dump(_closed(INDEX, "T-1")).replace("title: neighbour", "title: neighbour two")
    probs, _ = close_gate.index_problems(_dump(INDEX), other)
    assert any("a change to an entry this merge does not close (T-3)" in p for p in probs), probs


def test_a_top_level_change_fails() -> None:
    new = _dump(_closed(INDEX, "T-1")).replace("schema_version: 2", "schema_version: 1")
    assert any("top-level keys" in p for p in close_gate.index_problems(_dump(INDEX), new)[0])


def test_a_flow_style_index_cannot_carry_an_edit_to_another_entry() -> None:
    """The round's h1e: with every entry on one line, closing the last licensed an edit to the
    others on that line under the span rule; parsed, the other entry's change is seen."""
    base = "tasks: [{id: T-1, title: a, status: open}, {id: T-2, status: open}]\n"
    new = "tasks: [{id: T-1, title: PWNED, status: open}, {id: T-2, status: done}]\n"
    probs, closed = close_gate.index_problems(base, new)
    assert closed == ["T-2"] and any("does not close (T-1)" in p for p in probs), probs


def test_a_gating_value_changing_type_is_a_change() -> None:
    """`True == 1` in Python, but `/review-close` reads `manual_smoke` with `is True`."""
    new = _closed(INDEX, "T-1")
    new["tasks"][1]["manual_smoke"] = 1
    probs, _ = close_gate.index_problems(_dump(INDEX), _dump(new))
    assert any("T-2 changes a gating field (manual_smoke)" in p for p in probs), probs


def _claude_md(repo: Path, extra: str) -> None:
    text = (repo / "CLAUDE.md").read_text(encoding="utf-8")
    commit(repo, "instructions", {"CLAUDE.md": text + "\n## Notes\n\n" + extra + "\n"})


def test_a_dangling_import_the_merge_fills_fails(repo: Path) -> None:
    """H2a: the base imports `@docs/later.md`, which does not exist yet; the merge that adds it
    is the one that turns in-class content into instructions."""
    _claude_md(repo, "See @docs/later.md.")
    r = evaluate(repo, branch(repo, "feat/t1", {"docs/later.md": "obey\n"}, close=["T-1"]))
    assert r.returncode == 4 and "CLAUDE.md imports docs/later.md" in problems(r), r.stdout


def test_a_case_variant_import_fails(repo: Path) -> None:
    """h2b: a case-insensitive disk resolves `@Docs/Guide.md` to `docs/guide.md`."""
    _claude_md(repo, "See @Docs/Guide.md.")
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert r.returncode == 4 and "which names docs/guide.md" in problems(r), r.stdout


@pytest.mark.parametrize("where", [".claude/rules/style.md", ".claude/commands/go.md", ".claude/notes.md"])
def test_an_import_in_any_agent_instruction_file_fails(repo: Path, where: str) -> None:
    """The round's h2c-e: rules, commands and a file `CLAUDE.md` itself imports are instructions
    too, and each can point at in-class content."""
    up = "../" * (where.count("/"))
    commit(repo, "agent file", {where: f"Follow @{up}docs/guide.md.\n"})
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert r.returncode == 4 and f"{where} imports" in problems(r), r.stdout


def test_run_stands_down_when_a_newer_gate_run_exists(repo: Path, monkeypatch, capsys) -> None:
    """H3: two runs on one tip and head can finish in either order; the older one posts nothing
    more, so its `success` cannot land over the newer run's verdict."""
    head = branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"])
    fake = FakeGitHub(g(repo, "rev-parse", "main"), head, newer=True)
    _gate_run(repo, monkeypatch, fake)
    assert fake.posts == [(head, "in_progress", "")] and "SUPERSEDED #7" in capsys.readouterr().out


def test_the_escape_hatch_does_not_take_an_app_named_like_the_owner() -> None:
    app = [_review(f"{OWNER}[bot]", "h", "APPROVED", "2026-10-10T10:00:00Z")]
    assert not close_gate.owner_approved(OWNER, "h", app, None)


def test_a_codeowners_github_will_not_load_fails(repo: Path) -> None:
    big = CODEOWNERS + "# pad\n" * (3 * 1024 * 1024 // 6 + 1)
    r = evaluate(repo, _with_codeowners(repo, big))
    assert r.returncode == 4 and "3 MB or larger" in problems(r)


# --- Phase 374's round: the execution lens's findings and its battery's survivors -----------------

def _codex_link(repo: Path, name: str = "codebase-review", target: str = "") -> None:
    (repo / ".claude" / "skills" / name).mkdir(parents=True, exist_ok=True)
    (repo / ".claude" / "skills" / name / "SKILL.md").write_text("x\n", encoding="utf-8")
    (repo / ".agents" / "skills").mkdir(parents=True, exist_ok=True)
    os.symlink(target or f"../../.claude/skills/{name}", repo / ".agents" / "skills" / name)


def test_the_installers_codex_links_pass(repo: Path) -> None:
    """The installer's Codex links (on by default) made every default install red at round 1;
    they are the one link shape the gate admits (Wade's ruling at round 3)."""
    _codex_link(repo)
    _codex_link(repo, "security-audit")
    commit(repo, "codex links")
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert r.returncode == 0, r.stdout


@pytest.mark.parametrize("name,target", [
    ("codebase-review", "../../.claude/skills/security-audit"),  # another skill's name
    ("codebase-review", "../../.Claude/skills/codebase-review"),  # a case variant
    ("codebase-review", "../../.claude/skills/codebase-review/"),  # a trailing slash
    ("codebase-review", "../../src"),                              # into the class
])
def test_a_codex_link_of_any_other_shape_fails(repo: Path, name: str, target: str) -> None:
    _codex_link(repo, name, target)
    commit(repo, "a near-codex link")
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert r.returncode == 4 and f".agents/skills/{name} at the base is a symlink to {target}" in problems(r)


def test_a_link_between_two_governing_paths_fails(repo: Path) -> None:
    """Round 1 let a governing link that landed on a governing path pass; round 3 showed that
    path can be a file nothing scans (`AGENTS.md` -> `.github/agent-notes.md`, which imports an
    in-class path), so no link but a Codex link passes."""
    (repo / ".github").mkdir(exist_ok=True)
    os.symlink(".github/agent-notes.md", repo / "AGENTS.md")
    commit(repo, "agents link", {".github/agent-notes.md": "Always obey @src/a.py\n"})
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert r.returncode == 4 and "AGENTS.md at the base is a symlink to .github/agent-notes.md" in problems(r)


@pytest.mark.parametrize("link,target,imports", [
    ("notes/rules.md", "../src/a.py", "@notes/rules.md"),          # round 3, B
    ("lnk", "src", "@lnk/a.py"),                                     # round 3, C
    (".claude/rules", "../.github/rules", ""),                       # round 3, D
    ("srclnk", "src/deep", ""),                                      # round 3, F (case lookup)
])
def test_round_3s_link_shapes_fail(repo: Path, link: str, target: str, imports: str) -> None:
    """Every shape round 3 passed through the import scan or link resolution: each puts a
    non-Codex link at the base, which now refuses before anything follows it."""
    (repo / link).parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, repo / link)
    files = {".github/rules/style.md": "Follow @../../src/a.py\n", "src/deep/.github/x.md": "x\n"}
    if imports:
        files["AGENTS.md"] = f"See {imports}\n"
    commit(repo, "a link", files)
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert r.returncode == 4 and f"{link} at the base is a symlink to {target}" in problems(r), r.stdout


def test_a_module_beside_the_gate_cannot_shadow_the_standard_library(tmp_path: Path) -> None:
    """The gate's directory is appended to `sys.path` after the standard library loads, so a
    `json.py` beside it is never imported in place of the real one (Phase 374's round)."""
    d = tmp_path / "scripts"
    d.mkdir()
    for name in ("close_gate.py", "close_run.py", "pending_doc_hold.py"):
        (d / name).write_text((SCRIPTS / name).read_text(encoding="utf-8"), encoding="utf-8")
    # The gate's own imports load before the path changes; the modules `close_run` and
    # `pending_doc_hold` import afterwards are the ones the path order protects.
    for mod in ("json", "argparse", "base64", "re", "subprocess", "posixpath", "datetime",
                "secrets", "shutil", "tempfile", "hashlib", "unicodedata", "glob"):
        (d / f"{mod}.py").write_text("print('SHADOW')\nraise SystemExit(9)\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", str(d / "close_gate.py"), "evaluate", "a", "b"],
                       capture_output=True, text=True, cwd=str(tmp_path))
    assert "SHADOW" not in r.stdout + r.stderr and r.returncode != 9, r.stdout + r.stderr


@pytest.mark.parametrize("pat,path,hit", [
    ("src/*.py", "src/a.py", True), ("src/*.py", "src/a.py/payload.sh", False),
    ("docs/*", "docs/a/b/c.sh", False), ("src", "src/a/b.py", True), ("src/billing", "src/billing/x.py", True),
])
def test_only_a_wildcard_free_last_segment_covers_what_is_under_it(pat: str, path: str, hit: bool) -> None:
    assert bool(close_run.glob_regex(pat).match(path)) is hit


@pytest.mark.parametrize("line,why", [
    ("code_owner: @org/team", "not a GitHub login"), ("code_owner: -bad", "not a GitHub login"),
    ("gate_app: 0", "not a GitHub App id"), ("gate_app: 0123", "not a GitHub App id"),
    ("gate_app: app", "not a GitHub App id"),
])
def test_the_gate_keys_refuse_malformed_values(tmp_path: Path, line: str, why: str) -> None:
    (tmp_path / "CLAUDE.md").write_text(
        f"## Unattended close class\n\nallow: src/**\nblast_radius: single-file\n{line}\n", encoding="utf-8")
    with pytest.raises(close_run.Refuse, match=why):
        close_run.read_class(tmp_path)


def test_an_agents_md_import_and_a_nested_files_relative_import_fail(repo: Path) -> None:
    commit(repo, "agents", {"AGENTS.md": "Follow @docs/guide.md.\n",
                            "docs/sub/CLAUDE.md": "See @local.md.\n", "docs/sub/local.md": "x\n"})
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert "AGENTS.md imports docs/guide.md" in problems(r)
    assert "docs/sub/CLAUDE.md imports local.md, which names docs/sub/local.md" in problems(r)


@pytest.mark.parametrize("change,why", [
    (lambda t: t.replace(f"* @{OWNER}\n", "* @someone-else\n", 1), "first rule must be"),
    # Deleting the line would leave the path to `* @owner`; the case the fixed probes exist for
    # is a line that names no owner.
    (lambda t: t.replace(f"/sysop/ @{OWNER}\n", "/sysop/\n"), "sysop/x"),
    (lambda t: t.replace(f"/.github/ @{OWNER}\n", "/.github/\n"), ".github/x"),
])
def test_a_codeowners_missing_the_owner_or_a_fixed_governing_line_fails(repo: Path, change, why: str) -> None:
    r = evaluate(repo, _with_codeowners(repo, change(CODEOWNERS)))
    assert r.returncode == 4 and why in problems(r), r.stdout


def test_the_owner_matches_without_regard_to_case(repo: Path) -> None:
    r = evaluate(repo, _with_codeowners(repo, CODEOWNERS.replace(f"@{OWNER}", f"@{OWNER.upper()}")))
    assert r.returncode == 0, r.stdout


def test_github_reads_the_first_codeowners_it_finds(repo: Path) -> None:
    """.github/ before the root: a root CODEOWNERS that would fail is never read while
    .github/CODEOWNERS exists, and is read once it is gone."""
    commit(repo, "a root codeowners", {"CODEOWNERS": "* @someone-else\n"})
    assert evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"])).returncode == 0
    commit(repo, "drop .github/CODEOWNERS", {".github/CODEOWNERS": None})
    r = evaluate(repo, branch(repo, "feat/t1b", {"src/a.py": "a = 3\n"}, close=["T-1"]))
    assert r.returncode == 4 and "CODEOWNERS: its first rule" in problems(r)


def test_a_class_glob_with_a_hash_fails_the_codeowners_check(repo: Path) -> None:
    text = (repo / "CLAUDE.md").read_text(encoding="utf-8").replace("allow: src/**", "allow: src/** docs/#x")
    commit(repo, "hash glob", {"CLAUDE.md": text})
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert "uses `#`, which CODEOWNERS cannot express" in problems(r)


def test_an_edit_history_that_does_not_fit_one_page_fails() -> None:
    graph = _graph(_item("reader-bot", "reader-bot"))
    graph["data"]["repository"]["pullRequest"]["comments"]["pageInfo"]["hasNextPage"] = True
    assert close_gate.edit_problems("reader-bot[bot]", graph)
    item = _item("reader-bot", "reader-bot")
    item["userContentEdits"]["pageInfo"]["hasNextPage"] = True
    assert close_gate.edit_problems("reader-bot[bot]", _graph(item))


def test_a_nested_value_changing_type_is_a_change() -> None:
    new = _closed(INDEX, "T-1")
    base = yaml.safe_load(_dump(INDEX))
    base["tasks"][2]["depends_on"] = [True]
    new["tasks"][2]["depends_on"] = [1]
    probs, _ = close_gate.index_problems(_dump(base), _dump(new))
    assert any("does not close (T-3)" in p for p in probs), probs


@pytest.mark.parametrize("target", ["../CLAUDE.md", "/etc/CLAUDE.md"])
def test_a_governing_link_out_of_the_repository_fails(repo: Path, target: str) -> None:
    os.symlink(target, repo / "CLAUDE.local.md")
    commit(repo, "a link out")
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert r.returncode == 4 and "CLAUDE.local.md at the base is a symlink to" in problems(r)


def test_a_governing_gitlink_at_the_base_fails(repo: Path) -> None:
    g(repo, "update-index", "--add", "--cacheinfo", f"160000,{g(repo, 'rev-parse', 'main')},.claude/vendored")
    g(repo, "commit", "-qm", "a gitlink at the base")
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert r.returncode == 4 and ".claude/vendored at the base is a gitlink" in problems(r)


# --- `run`, against the fake GitHub: the execution lens's battery survivors -------------------------

def test_run_skips_a_pull_request_into_another_base(repo: Path, monkeypatch, capsys) -> None:
    head = branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"])
    fake = FakeGitHub(g(repo, "rev-parse", "main"), head)
    orig = fake.get
    fake.get = lambda path: {**orig(path), "base": {"ref": "release"}} if path.startswith("pulls/") else orig(path)
    _gate_run(repo, monkeypatch, fake)
    assert fake.posts == [] and "SKIP #7: not an open pull request into main" in capsys.readouterr().out


def test_run_skips_a_head_that_moved_while_it_was_fetched(repo: Path, monkeypatch, capsys) -> None:
    head = branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"])
    fake = FakeGitHub(g(repo, "rev-parse", "main"), head)
    monkeypatch.setattr(close_gate, "GitHub", lambda repo_name: fake)
    monkeypatch.setattr(close_gate, "fetch_head", lambda root, n: "e" * 40)
    g(repo, "checkout", "-q", "main")
    close_gate.cmd_run(repo, _run_args())
    # The in-progress post comes before the fetch, so a skipped or failed fetch leaves the head
    # blocked rather than carrying an earlier verdict (round 2).
    assert fake.posts == [(head, "in_progress", "")] and "its head moved while it was fetched" in capsys.readouterr().out


def test_run_fails_on_a_codeowners_errors_reply_with_no_list(repo: Path, monkeypatch, capsys) -> None:
    head = branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"])
    fake = FakeGitHub(g(repo, "rev-parse", "main"), head)
    orig = fake.get
    fake.get = lambda path: {} if path.startswith("codeowners/errors") else orig(path)
    _gate_run(repo, monkeypatch, fake)
    assert fake.posts[-1] == (head, "completed", "failure") and "no error list" in capsys.readouterr().out


def test_run_posts_a_waiting_reader_as_in_progress(repo: Path, monkeypatch, capsys) -> None:
    head = branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"])
    fake = FakeGitHub(g(repo, "rev-parse", "main"), head)
    orig = fake.pages
    fake.pages = lambda path: [] if path.endswith("/reviews") else orig(path)
    _gate_run(repo, monkeypatch, fake)
    assert fake.posts == [(head, "in_progress", ""), (head, "in_progress", "pending")], fake.posts


def test_the_relay_filter_evaluates_only_the_pull_requests_at_that_head(repo: Path, monkeypatch, capsys) -> None:
    head = branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"])
    fake = FakeGitHub(g(repo, "rev-parse", "main"), head)
    orig = fake.pages
    listed = [{"number": 7, "head": {"sha": head}}, {"number": 8, "head": {"sha": "d" * 40}}]
    fake.pages = lambda path: listed if path.startswith("pulls?") else orig(path)
    monkeypatch.setattr(close_gate, "GitHub", lambda repo_name: fake)
    monkeypatch.setattr(close_gate, "fetch_head", lambda root, n: fake.head)
    monkeypatch.setattr(close_run, "utcnow", lambda: datetime.datetime(2026, 10, 10, 0, 5, tzinfo=datetime.timezone.utc))
    g(repo, "checkout", "-q", "main")
    close_gate.cmd_run(repo, _run_args(pr=None, event="workflow_run", head_sha=head))
    out = capsys.readouterr().out
    assert "#7" in out and "#8" not in out, out


def test_the_newest_request_comment_starts_the_readers_clock() -> None:
    cfg = {"reviewer": "r", "request": "please review", "timeout": "20m", "format": "approval"}
    now = datetime.datetime(2026, 10, 10, 1, 0, tzinfo=datetime.timezone.utc)
    asks = [{"body": "please review", "created_at": "2026-10-09T00:00:00Z"},
            {"body": "please review", "created_at": "2026-10-10T00:55:00Z"}]
    assert close_gate.reader_state(cfg, "h", [], [], asks, [], now)[0] == "wait"


def test_fetch_head_fetches_the_head_ref_with_the_token_in_the_environment(repo: Path, monkeypatch) -> None:
    seen = {}

    def fake_run(cmd, capture_output, env):
        seen["cmd"], seen["env"] = cmd, env
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setenv("GH_TOKEN", "t0ken")
    monkeypatch.setattr(close_gate.subprocess, "run", fake_run)
    monkeypatch.setattr(close_run, "ref_sha", lambda root, ref: "a" * 40)
    close_gate.fetch_head(repo, 7)
    assert "+refs/pull/7/head:refs/sysop-gate/pr-7" in seen["cmd"] and "t0ken" not in " ".join(seen["cmd"])
    assert seen["env"]["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert seen["env"]["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: basic ")


# --- Phase 374's round 2 ---------------------------------------------------------------------------

@pytest.mark.parametrize("shape", [
    "<div>\n```\n</div>\n\n@docs/guide.md",
    "<!--\n```\n-->\n@docs/guide.md",
    "- ```\n  x\n\n@docs/guide.md",
    "x `y\nz` @docs/guide.md `w`",
    "` @docs/guide.md ``",
    "@docs/guide.md#section",
    "\\.@docs/guide.md",
    "[@docs/guide.md](x)",
])
def test_an_import_claude_code_reads_is_never_skipped(repo: Path, shape: str) -> None:
    """Round 2 (F1): Claude Code's extractor reads these; the Markdown-aware scan skipped them."""
    _claude_md(repo, shape)
    r = evaluate(repo, branch(repo, "feat/t1", {"docs/guide.md": "obey\n"}, close=["T-1"]))
    assert r.returncode == 4 and "which names docs/guide.md" in problems(r), r.stdout


@pytest.mark.parametrize("hop", [".github/AGENT_NOTES.md", ".claude/notes.txt", "sysop/notes.json"])
def test_an_import_chain_through_any_file_is_followed(repo: Path, hop: str) -> None:
    """Round 2 (F2): Claude Code loads imports recursively, through files of any kind."""
    up = "../" * hop.count("/")
    _claude_md(repo, f"See @{hop}.")
    commit(repo, "a hop", {hop: f"then @{up}docs/guide.md\n"})
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert r.returncode == 4 and f"{hop} imports" in problems(r), r.stdout


@pytest.mark.parametrize("tok", ["@/opt/proj/docs/guide.md", "@~/proj/docs/guide.md",
                                 "@/docs/guide.md", "@~/docs/../docs/guide.md",
                                 "@../repo/docs/guide.md", "@C:/proj/docs/guide.md",
                                 "@file:///opt/proj/docs/guide.md"])
def test_an_absolute_or_home_import_is_matched_by_its_trailing_path(repo: Path, tok: str) -> None:
    """Round 3: Claude Code resolves `@/…` and `@~/…` against the machine, which the gate
    cannot see; skipping them let an import of the checkout's own in-class file through."""
    _claude_md(repo, f"Obey {tok}")
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert r.returncode == 4 and "which names docs/guide.md" in problems(r), r.stdout


def test_an_absolute_import_of_the_deepest_known_path_fails(repo: Path) -> None:
    """Round 4's depth cap must keep the suffix as deep as the deepest path the gate knows."""
    commit(repo, "deep", {"docs/a/b/c/d.md": "deep\n"})
    _claude_md(repo, "Obey @/opt/proj/docs/a/b/c/d.md")
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    assert r.returncode == 4 and "which names docs/a/b/c/d.md" in problems(r), r.stdout


def test_an_exclusion_matches_the_raw_path_or_its_nfc_form(tmp_path: Path) -> None:
    """Round 4: round 3 matched the NFC form only, and U+0958's NFC form is two code points, so
    `exclude: src/x?/**` stopped covering `src/x\u0958/k.py`."""
    (tmp_path / "CLAUDE.md").write_text(
        "## Unattended close class\n\nallow: **\nexclude: src/x?/**\nblast_radius: single-file\n",
        encoding="utf-8")
    assert "excluded" in close_run.path_problem(close_run.read_class(tmp_path), "src/x\u0958/k.py")


def test_import_targets() -> None:
    assert close_gate.import_targets("CLAUDE.md", "/opt/p/src/a.py") == [
        "opt/p/src/a.py", "p/src/a.py", "src/a.py", "a.py"]
    assert close_gate.import_targets("x/CLAUDE.md", "~/p/a.py") == ["p/a.py", "a.py"]
    assert close_gate.import_targets("x/CLAUDE.md", "../a.py") == ["a.py"]
    assert close_gate.import_targets("CLAUDE.md", ".") == []
    # Round 4: a relative token that climbs out of the repository, drive letters, `file:`,
    # and the depth cap.
    assert close_gate.import_targets("CLAUDE.md", "../repo/a.py") == ["repo/a.py", "a.py"]
    assert close_gate.import_targets("CLAUDE.md", "C:\\p\\a.py") == ["C:/p/a.py", "p/a.py", "a.py"]
    assert close_gate.import_targets("CLAUDE.md", "file:///opt/a.py")[-2:] == ["opt/a.py", "a.py"]
    assert close_gate.import_targets("CLAUDE.md", "/a/b/c/d", depth=2) == ["c/d", "d"]


def test_a_replace_ref_cannot_hide_an_import(repo: Path) -> None:
    """Round 3: `refs/replace/*` changed what the base reads return but not the merge; a
    replaced `AGENTS.md` blob read as harmless while the real one imports an in-class path."""
    commit(repo, "agents", {"AGENTS.md": "Obey @docs/guide.md\n"})
    real = g(repo, "rev-parse", "HEAD:AGENTS.md")
    fake = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=repo, input="harmless\n",
                          capture_output=True, text=True, env=_git_env()).stdout.strip()
    g(repo, "replace", real, fake)
    head = branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"])
    assert g(repo, "cat-file", "-p", "main:AGENTS.md") == "harmless"
    r = evaluate(repo, head)
    assert r.returncode == 4 and "AGENTS.md imports docs/guide.md" in problems(r), r.stdout


def test_close_runs_own_commands_ignore_replace_refs(monkeypatch, capsys) -> None:
    """Round 4: `merge_env` ignores `refs/replace/*`, so `eligible`'s base reads must too, or the
    client half reads one base and merges another (round 3's finding, on the client side). A
    wiring test: every git `close_run.main` starts inherits the variable."""
    monkeypatch.delenv("GIT_NO_REPLACE_OBJECTS", raising=False)
    close_run.main(["no-such-command"])
    assert os.environ.get("GIT_NO_REPLACE_OBJECTS") == "1"


def test_a_link_through_another_link_fails(repo: Path) -> None:
    """Round 2 (F3): `docs/lnk -> ../src/x` made `docs/lnk/../CODEOWNERS` land on
    `src/CODEOWNERS`, which the class admits. Round 3's ruling refuses both links outright."""
    (repo / "src" / "x").mkdir()
    os.symlink("../src/x", repo / "docs" / "lnk")
    os.symlink("docs/lnk/../CODEOWNERS", repo / "CLAUDE.local.md")
    commit(repo, "links", {"src/CODEOWNERS": "agent text\n", "src/x/keep": ""})
    r = evaluate(repo, branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"]))
    out = problems(r)
    assert r.returncode == 4 and "docs/lnk at the base is a symlink to ../src/x" in out, r.stdout
    assert "CLAUDE.local.md at the base is a symlink to docs/lnk/../CODEOWNERS" in out


def test_an_nfd_spelling_of_an_excluded_directory_is_excluded(tmp_path: Path) -> None:
    """Round 3: APFS and HFS+ read an NFC and an NFD name as one directory, so an exclusion
    must cover both spellings."""
    import unicodedata
    nfc, nfd = unicodedata.normalize("NFC", "café"), unicodedata.normalize("NFD", "café")
    assert nfc != nfd
    for pat, path in ((nfc, nfd), (nfd, nfc)):
        (tmp_path / "CLAUDE.md").write_text(
            f"## Unattended close class\n\nallow: **\nexclude: docs/{pat}\nblast_radius: single-file\n",
            encoding="utf-8")
        assert "excluded" in close_run.path_problem(close_run.read_class(tmp_path), f"docs/{path}/x.md")


@pytest.mark.parametrize("pat,path", [("secrets/*", "secrets/prod/key.pem"), ("infra/*", "infra/terraform/main.tf"),
                                      ("src/billing*", "src/billing/pay.py"), ("deploy/?", "deploy/k/x.yml")])
def test_an_exclusion_covers_what_is_under_what_it_matches(tmp_path: Path, pat: str, path: str) -> None:
    """Round 2 (F4): round 1 narrowed wildcard globs for `allow:` and, by sharing the code, for
    `exclude:` too, which is the unsafe direction."""
    (tmp_path / "CLAUDE.md").write_text(
        f"## Unattended close class\n\nallow: **\nexclude: {pat}\nblast_radius: single-file\n", encoding="utf-8")
    assert "excluded" in close_run.path_problem(close_run.read_class(tmp_path), path)


def test_a_flag_main_adds_after_the_branch_is_read_at_the_base(repo: Path) -> None:
    """Round 2 (Y27): the merge carries `main`'s new flag through, so `index_problems` sees no
    change; only reading the closed task's flags at the base refuses it."""
    head = branch(repo, "feat/t1", {"src/a.py": "a = 2\n"}, close=["T-1"])
    flagged = yaml.safe_load((repo / "tasks" / "index.yml").read_text(encoding="utf-8"))
    # The flag goes first in the entry, so an unchanged line separates it from the branch's
    # status edit and the merge is clean.
    flagged["tasks"][0] = {"manual_smoke": True, **flagged["tasks"][0]}
    commit(repo, "main flags T-1", {"tasks/index.yml": _dump(flagged)})
    r = evaluate(repo, head)
    assert r.returncode == 4 and "at the base: T-1 is manual_smoke" in problems(r), r.stdout
