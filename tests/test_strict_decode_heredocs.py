"""`Q-612` — the strict-decode residue `Q-550`'s guard did not look at.

`tests/test_strict_decode_class.py` sweeps shipped `.py` scripts. The same class
lived in the Python the tree runs as heredocs: skill bodies, `claim_task.sh` and
`install.sh`. On a byte that is not UTF-8 each of those ended in a raw traceback,
and exit 1 is not the code several of them document (`/claim-task` Step 2's typed
contract says 2 means the index could not be used; Step 3b's 1 means "file the
missing stubs"). Each site now names the file and exits on the error path it
already had, before any write, and never with `errors="replace"`:

* a read-only step exits with its own error code and says which file;
* the round-marker clear refuses the removal (exit 0), as a nonce mismatch does;
* `claim_task.sh --release` reads the index BEFORE removing the worktree. It
  checked only that PyYAML imports, so an unreadable index surfaced at the flip,
  after the worktree was gone.

Two git readers had the same shape through `subprocess ... text=True`:
`sitrep_survey._git` (a raw commit message or a non-UTF-8 packed ref ended the
survey) and `scope_overlap`'s diff and status readers. `_git` now `os.fsdecode`s,
which round-trips a ref name back to git, and sitrep's stdout escapes the
surrogate that leaves. `scope_overlap` reads `-z`, since without it a valid
non-ASCII name came back as a quoted octal escape under git's default
`core.quotePath` and matched no task's key files, and decodes a name that is not
UTF-8 to a visible `\\xe9` escape: its evidence is printed by callers it does
not control, and a surrogate crashed two of them (Phase 334's round). Four
heredoc reads through `text=True` got the same treatment one site at a time;
the class guard below does not sweep that shape, as `Q-550`'s does not.

THE CLASS GUARD reuses `test_strict_decode_class.strict_reads` over every body
`tests/_heredoc_population.py` extracts, and refuses a body that does not parse:
skipping one would pass it silently.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import scope_overlap as so  # noqa: E402
import sitrep_survey as ss  # noqa: E402
from _heredoc_population import (  # noqa: E402
    OPENER,
    heredoc_containing,
    heredocs_in,
    shipped_heredocs,
)
from test_strict_decode_class import strict_reads  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "core" / "skills"
INSTALL = REPO_ROOT / "install.sh"
CLAIM_SH = REPO_ROOT / "core" / "companion" / "scripts" / "claim_task.sh"

BAD = b"tasks: []\n\xff\xfe not utf-8 \xe9\n"
_GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


# ---------------------------------------------------------------------------
# The class guard
# ---------------------------------------------------------------------------
def test_every_shipped_heredoc_parses():
    bad = []
    for f, ln, opener, body in shipped_heredocs():
        try:
            compile(body, f"{f.name}:{ln}", "exec")
        except SyntaxError as e:
            bad.append(f"{f.relative_to(REPO_ROOT)}:{ln} {opener[:60]!r}: {e.msg}")
    assert not bad, ("heredoc bodies that do not parse — the strict-decode guard cannot "
                     "see inside them:\n  " + "\n  ".join(bad))


def test_no_shipped_heredoc_reads_text_strictly_outside_a_value_error_handler():
    bad = []
    for f, ln, _, body in shipped_heredocs():
        for line, kind, call, guarded, seen in strict_reads(body):
            if not guarded:
                bad.append(f"{f.relative_to(REPO_ROOT)}:{ln + line} [{kind}] {call} — "
                           f"handlers {seen or 'none'}")
    assert not bad, (
        "strict text read(s) in a shipped heredoc that a byte which is not UTF-8 turns "
        "into a traceback. Catch UnicodeDecodeError beside OSError, name the file, and "
        "exit on the site's own error path before any write:\n  " + "\n  ".join(bad))


def test_every_opener_reaches_its_delimiter():
    """The extractor skips an opener with no delimiter line, so a heredoc whose
    closer was mangled would leave the guard's population without a word. Fail
    closed instead: every opener in the population must produce a body."""
    from _heredoc_population import population
    bad = []
    for f in population():
        text = f.read_text(encoding="utf-8")
        found = {ln for ln, _, _ in heredocs_in(text)}
        for m in OPENER.finditer(text):
            ln = text.count("\n", 0, m.start()) + 1
            if ln not in found:
                bad.append(f"{f.relative_to(REPO_ROOT)}:{ln} {m.group(0).strip()[:60]!r}")
    assert not bad, "heredoc openers with no delimiter line:\n  " + "\n  ".join(bad)


def test_the_population_holds_every_opener_shape_the_tree_uses():
    """A narrower extractor passes vacuously. Pin the count and each shape by a
    heredoc that only that shape reaches."""
    docs = shipped_heredocs()
    reads = sum(len(strict_reads(b)) for _, _, _, b in docs)
    # 47 heredocs and 33 strict reads at Phase 334, measured by this module.
    assert len(docs) >= 47, len(docs)
    assert reads >= 33, reads
    openers = {(f.name, o) for f, _, o, _ in docs}
    shapes = {
        "positional arg before <<": ("install.sh", 'python3 - "$manifest" <<\'PY\''),
        "variable command word": ("install.sh", 'if ! _keys="$("$_py" - "$subs_path" <<\'PY\''),
        "redirect before <<": ("claim_task.sh",
                               'ES_OUT=$(HAS_LOCK="$HAS_LOCK" TASK_ID="$TASK_ID" '
                               'INDEX_PATH="$INDEX" python3 - 2>"$ES_ERR" <<\'PY\''),
    }
    for shape, key in shapes.items():
        assert key in openers, (shape, key)
    # List-indented in markdown, read off the raw line: the stripped opener text
    # cannot tell an indented heredoc from a column-0 one.
    from _heredoc_population import population
    indented = [f for f in population() if f.suffix == ".md"
                for m in OPENER.finditer(f.read_text(encoding="utf-8")) if m.group(1)]
    assert indented, "no list-indented markdown heredoc in the population"


@pytest.mark.parametrize("text,expected", [
    ("python3 - <<'PY'\nx = 1\nPY\n", ["x = 1"]),
    ('python3 - "$a" "$b" <<\'EOF\'\nx = 1\nEOF\n', ["x = 1"]),
    ('if ! k="$("$_py" - "$f" <<\'PY\'\nx = 1\nPY\n)"; then', ["x = 1"]),
    ("   python3 - <<'PY'\n   x = 1\n   PY\n", ["x = 1"]),
    ('O=$(python3 - 2>"$E" <<PY\nx = 1\nPY\n)', ["x = 1"]),
    ("python3 <<'PY'\nx = 1\nPY\n", ["x = 1"]),
    # a script argument makes the heredoc that script's data, not a program
    ("python3 tool.py <<'EOF'\nnot python\nEOF\n", []),
    ("python3 -u - <<'PY'\nx = 1\nPY\n", ["x = 1"]),
    ('"$ROOT/.venv/bin/python3" - <<PY\nx = 1\nPY\n', ["x = 1"]),
    ('"${PYTHON:-python3}" - "$a" <<PY\nx = 1\nPY\n', ["x = 1"]),
    ("python3.12 - <<PY\nx = 1\nPY\n", ["x = 1"]),
    ('"$PY" -I - <<PY\nx = 1\nPY\n', ["x = 1"]),
    # data heredocs a variable or a word merely containing "py" must not become programs
    ('cat > "$pyproject" <<EOF\n[project]\nEOF\n', []),
    ('tee "$COPY_LOG" <<EOF\nlog line\nEOF\n', []),
    ("cat > run_python <<EOF\nnot python\nEOF\n", []),
    # prose quoting a command is not a command
    ("Run `python3 - <<'PY'` from the root.\nx = 1\nPY\n", []),
    # no delimiter line, no heredoc
    ("python3 - <<'PY'\nx = 1\n", []),
])
def test_the_opener_arms(text, expected):
    assert [b for _, _, b in heredocs_in(text)] == expected
    assert OPENER.pattern  # imported, not re-typed


# ---------------------------------------------------------------------------
# Behaviour — each fixed site, run verbatim against a byte that is not UTF-8
# ---------------------------------------------------------------------------
def _run_body(body: str, args, cwd: Path, env=None):
    script = cwd / "_heredoc_under_test.py"
    script.write_text(body, encoding="utf-8")
    try:
        return subprocess.run([sys.executable, str(script), *map(str, args)], cwd=cwd,
                              capture_output=True, text=True,
                              env={**os.environ, **_GIT_ISOLATION, **(env or {})})
    finally:
        script.unlink()


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True, env={**os.environ, **_GIT_ISOLATION})


def _repo(root: Path, index: bytes = BAD) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "-c", "init.defaultBranch=main", "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "tasks").mkdir()
    (root / "tasks" / "index.yml").write_bytes(index)
    return root


def _refused(r, code: int, name: str, stream: str = "stderr"):
    out = getattr(r, stream)
    assert r.returncode == code, (r.returncode, r.stdout, r.stderr)
    assert re.search(re.escape(name) + r":? could not be read \(UnicodeDecodeError", out), (
        r.stdout, r.stderr)
    assert "Traceback" not in r.stdout + r.stderr, r.stderr


def test_auto_build_pool_read_exits_2_naming_the_index(tmp_path):
    body = heredoc_containing(SKILLS / "auto-build/SKILL.md", "subset = set(sys.argv[1].split())")
    _refused(_run_body(body, [""], _repo(tmp_path / "r")), 2, "tasks/index.yml", "stdout")


def test_auto_build_flip_refuses_before_writing(tmp_path):
    repo = _repo(tmp_path / "r")
    body = heredoc_containing(SKILLS / "auto-build/SKILL.md", 't["status"] = "in_progress"')
    r = _run_body(body, ["FEAT-1"], repo)
    _refused(r, 1, "tasks/index.yml")
    assert "Nothing was changed" in r.stderr
    assert (repo / "tasks/index.yml").read_bytes() == BAD


def test_claim_task_step_2_exits_2_as_its_contract_says(tmp_path):
    body = heredoc_containing(SKILLS / "claim-task/SKILL.md", "print(f\"id={match['id']}\")")
    _refused(_run_body(body, ["FEAT-1"], _repo(tmp_path / "r")), 2, "tasks/index.yml")
    text = (SKILLS / "claim-task/SKILL.md").read_text(encoding="utf-8")
    assert re.search(r"^- `2` — `tasks/index\.yml` itself missing .*unreadable", text, re.M)


def test_claim_task_step_4a_refuses_before_writing(tmp_path):
    repo = _repo(tmp_path / "r")
    body = heredoc_containing(SKILLS / "claim-task/SKILL.md", "resumed = False")
    r = _run_body(body, ["FEAT-1"], repo)
    _refused(r, 1, "tasks/index.yml")
    assert (repo / "tasks/index.yml").read_bytes() == BAD


def _option_c(tmp_path, plan: bytes, body: bytes):
    repo = _repo(tmp_path / "r", index=b"tasks: []\n")
    run = repo / "sysop/runtime/claim/FEAT-1/run1"
    run.mkdir(parents=True)
    (run / "plan.md").write_bytes(plan)
    (repo / "tasks/open").mkdir()
    (repo / "tasks/open/FEAT-1.md").write_bytes(body)
    code = heredoc_containing(SKILLS / "claim-task/SKILL.md", "sealed_report")
    return repo, _run_body(code, ["FEAT-1", "run1", "open/FEAT-1.md", "test X proves Y"], repo)


def test_claim_task_option_c_plan_read_exits_4(tmp_path):
    repo, r = _option_c(tmp_path, BAD, b"# FEAT-1\n")
    _refused(r, 4, "plan.md")
    assert (repo / "tasks/open/FEAT-1.md").read_bytes() == b"# FEAT-1\n"


def test_claim_task_option_c_body_read_exits_5_and_writes_nothing(tmp_path):
    repo, r = _option_c(tmp_path, b"## Plan\nstep\n", BAD)
    _refused(r, 5, "FEAT-1.md")
    assert "nothing was written" in r.stderr
    assert (repo / "tasks/open/FEAT-1.md").read_bytes() == BAD


@pytest.mark.parametrize("skill", ["codebase-review", "security-audit"])
def test_round_marker_clear_refuses_an_unreadable_marker(tmp_path, skill):
    marker = tmp_path / "round.abc123.pending"
    marker.write_bytes(b"nonce: abc123\n" + BAD)
    body = heredoc_containing(SKILLS / f"{skill}/SKILL.md", "round-marker: REFUSING to remove")
    r = _run_body(body, [marker], tmp_path)
    assert r.returncode == 0, r.stderr
    assert "REFUSING to remove round.abc123.pending — it could not be read" in r.stdout
    assert "Traceback" not in r.stderr and marker.exists()


def test_the_two_marker_clears_stay_identical():
    a, b = (heredoc_containing(SKILLS / f"{s}/SKILL.md", "round-marker: REFUSING to remove")
            for s in ("codebase-review", "security-audit"))
    assert a == b


def _doc_work(tmp_path, pending: bytes, index: bytes):
    repo = _repo(tmp_path / "r", index=index)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "seed")
    _git(repo, "switch", "-qc", "feat/x")
    d = repo / "sysop/runtime/pending-docs"
    d.mkdir(parents=True)
    (d / "feat-x.md").write_bytes(pending)
    body = heredoc_containing(SKILLS / "document-work/SKILL.md",
                              "Follow-up check: skipped (no tasks/index.yml)")
    return _run_body(body, [], repo)


def test_document_work_3b_an_unreadable_pending_doc_is_exit_2_not_missing_stubs(tmp_path):
    r = _doc_work(tmp_path, BAD, b"tasks: []\n")
    _refused(r, 2, "sysop/runtime/pending-docs/feat-x.md")
    assert "blocked" not in r.stdout


def test_document_work_3b_an_unreadable_index_is_exit_2(tmp_path):
    _refused(_doc_work(tmp_path, b"---\nbranch: feat/x\n---\nbody\n", BAD), 2, "tasks/index.yml")


def test_review_close_section_measure_names_claude_md(tmp_path):
    (tmp_path / "CLAUDE.md").write_bytes(BAD)
    body = heredoc_containing(SKILLS / "review-close/SKILL.md",
                              'SECTIONS = ["Prevention Conventions", "Testing Patterns"]')
    _refused(_run_body(body, [], tmp_path), 1, "CLAUDE.md")


def test_review_close_4c_round_trip_refuses_before_writing(tmp_path):
    repo = _repo(tmp_path / "r")
    body = heredoc_containing(SKILLS / "review-close/SKILL.md", 'ids = ["<ROADMAP_ID_1>"')
    r = _run_body(body, [], repo)
    _refused(r, 1, "tasks/index.yml")
    assert "nothing was changed" in r.stderr
    assert (repo / "tasks/index.yml").read_bytes() == BAD


# -- install.sh --------------------------------------------------------------
def _install_case(tmp_path, needle, argv):
    """argv entries: "BAD" -> a file holding a non-UTF-8 byte, "OK:<text>" -> a
    file holding <text>, anything else passed through."""
    args, bad = [], None
    for i, a in enumerate(argv):
        if a == "BAD":
            bad = tmp_path / f"arg{i}"
            bad.write_bytes(BAD)
            args.append(bad)
        elif a.startswith("OK:"):
            p = tmp_path / f"arg{i}"
            p.write_text(a[3:], encoding="utf-8")
            args.append(p)
        else:
            args.append(a)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    r = _run_body(heredoc_containing(INSTALL, needle), args, tmp_path,
                  env={"_SYSOP_COLLISIONS": "x"})
    after = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    r.written = sorted(n for n in after if before.get(n) != after[n])
    return r, bad


_SUBS = "OK:substitutions:\n  '<api module>': app/api.py\n"
_CHECKS = "OK:checks:\n  - id: a\n"
_JSON = 'OK:{"permissions": {"allow": []}}\n'


@pytest.mark.parametrize("needle,argv", [
    ('for d in data.get("dependencies", []) or []:', ["BAD"]),
    ("top-level 'substitutions:' mapping missing or empty", ["BAD"]),
    ("PATHS_KEY = re.compile", ["BAD", "OK:x\n"]),
    ("PATHS_KEY = re.compile", [_SUBS, "BAD"]),
    ("seen_in_proj, dupes = set(), []", ["BAD", _CHECKS]),
    ("seen_in_proj, dupes = set(), []", [_CHECKS, "BAD"]),
    ("_SYSOP_COLLISIONS", ["BAD"]),
    ("base['checks'] = base_checks", ["BAD", _CHECKS]),
    ("base['checks'] = base_checks", [_CHECKS, "BAD"]),
    ("keep, dropped = [], []", ["BAD", "main"]),
    ("Rewrite by exact string, not by regex over the file", ["BAD", "out.json", "main"]),
    ('if r in LOOP_ALLOW]', ["BAD", "out.json"]),
    ("--- permissions.allow set-union ---", ["BAD", _JSON]),
    ("--- permissions.allow set-union ---", [_JSON, "BAD"]),
    ("HOOK_FILES = (", ["BAD", _JSON, "old"]),
    ("HOOK_FILES = (", [_JSON, "BAD", "old"]),
])
def test_install_heredocs_name_the_unreadable_file(tmp_path, needle, argv):
    r, bad = _install_case(tmp_path, needle, argv)
    _refused(r, 1, str(bad))
    assert not r.written, f"written before the refusal: {r.written}"



@pytest.mark.parametrize("needle,argv", [
    ('for d in data.get("dependencies", []) or []:', ['OK:{"dependencies": []}\n']),
    ("PATHS_KEY = re.compile", [_SUBS, "OK:x\n"]),
    ("seen_in_proj, dupes = set(), []", [_CHECKS, _CHECKS]),
    ("keep, dropped = [], []", [_JSON, "main"]),
    ("--- permissions.allow set-union ---", [_JSON, _JSON]),
])
def test_install_heredocs_read_a_readable_file_without_refusing(tmp_path, needle, argv):
    """Control: the handler refuses only what it cannot read."""
    r, _ = _install_case(tmp_path, needle, argv)
    assert "could not be read" not in r.stderr and "Traceback" not in r.stderr, r.stderr


# -- claim_task.sh -----------------------------------------------------------
def _sh(cwd, *args, env=None):
    e = {**os.environ, **_GIT_ISOLATION, **(env or {})}
    e["PATH"] = os.path.dirname(sys.executable) + os.pathsep + e["PATH"]
    return subprocess.run(["bash", str(CLAIM_SH), *args], cwd=cwd, capture_output=True,
                          text=True, env=e)


def _claimed(tmp_path) -> Path:
    repo = _repo(tmp_path / "r", index=b"tasks:\n  - id: FEAT-1\n    status: in_progress\n")
    (repo / "README.md").write_text("x\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    r = _sh(repo, "--lock", "FEAT-1", "feat/x", env={"WORKTREE_PREFIX": "wt"})
    assert r.returncode == 0, r.stderr
    return repo


def test_release_refuses_an_unreadable_index_before_removing_the_worktree(tmp_path):
    repo = _claimed(tmp_path)
    lock = repo / "sysop/runtime/locks/FEAT-1.lock"
    ws = next(ln.split(":", 1)[1].strip() for ln in lock.read_text().splitlines()
              if ln.startswith("workspace:"))
    (repo / "tasks/index.yml").write_bytes(b"tasks:\n  - id: FEAT-1\n" + BAD)
    r = _sh(repo, "--release", "FEAT-1")
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "tasks/index.yml could not be read" in r.stderr and "UnicodeDecodeError" in r.stderr
    assert "the claim is intact" in r.stderr and "Traceback" not in r.stderr
    assert Path(ws).is_dir(), "the worktree was removed before the index was read"
    assert lock.exists()


def test_release_still_releases_a_readable_claim(tmp_path):
    """Control: the probe refuses only what it cannot read."""
    repo = _claimed(tmp_path)
    r = _sh(repo, "--release", "FEAT-1")
    assert r.returncode == 0, (r.stdout, r.stderr)
    assert not (repo / "sysop/runtime/locks/FEAT-1.lock").exists()


def test_entry_state_names_the_unreadable_index(tmp_path):
    repo = _repo(tmp_path / "r", index=b"tasks:\n  - id: FEAT-1\n" + BAD)
    r = _sh(repo, "--entry-state", "FEAT-1")
    assert r.returncode == 4, (r.stdout, r.stderr)
    assert "Could not read" in r.stderr and "tasks/index.yml" in r.stderr, r.stderr
    assert "codec can't decode" in r.stderr, r.stderr
    assert "Traceback" not in r.stderr


def test_install_lock_write_says_so_when_it_resets_a_malformed_lock(tmp_path):
    """Phase 148 tolerates a malformed lock by resetting both timestamps. A byte that
    is not UTF-8 is malformed too, and the reset is now named on stderr."""
    lock = tmp_path / "sysop.lock"
    lock.write_bytes(b'{"installed_at": "2025-01-01T00:00:00Z", "x": "caf\xe9"}\n')
    body = heredoc_containing(INSTALL, "treating an unreadable lock as an")
    env = {"SYSOP_LOCK_PATH": str(lock), "SYSOP_LOCK_VERSION": "1", "SYSOP_COMMIT": "abc",
           "SYSOP_PACKS": "", "SYSOP_INSTALLED_AT": "2026-09-26T00:00:00Z",
           "SYSOP_UPDATED_AT": "2026-09-26T00:00:00Z", "SYSOP_MANAGED_PATHS": ""}
    r = _run_body(body, [], tmp_path, env=env)
    assert r.returncode == 0, r.stderr
    assert f"the existing lock at {lock} could not be parsed (UnicodeDecodeError" in r.stderr
    assert json.loads(lock.read_text())["installed_at"] == "2026-09-26T00:00:00Z"


def test_commit_claim_names_the_unreadable_index(tmp_path):
    repo = _repo(tmp_path / "r", index=b"tasks:\n  - id: FEAT-1\n    status: open\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    head = _git(repo, "rev-parse", "HEAD").stdout
    (repo / "tasks/index.yml").write_bytes(b"tasks:\n  - id: FEAT-1\n" + BAD)
    r = _sh(repo, "--commit-claim", "FEAT-1")
    assert r.returncode == 1, (r.stdout, r.stderr)
    assert "tasks/index.yml could not be read (UnicodeDecodeError" in r.stderr, r.stderr
    assert "Traceback" not in r.stderr
    assert _git(repo, "rev-parse", "HEAD").stdout == head


# ---------------------------------------------------------------------------
# The git readers
# ---------------------------------------------------------------------------
def _gb(repo, *args, inp=None):
    return subprocess.run([b"git", b"-C", os.fsencode(repo),
                           *[a if isinstance(a, bytes) else a.encode() for a in args]],
                          input=inp, capture_output=True, check=True,
                          env={**os.environ, **_GIT_ISOLATION}).stdout


@pytest.fixture
def raw_repo(tmp_path):
    """A repo holding a raw non-UTF-8 commit message (a commit object with no
    encoding header, as libgit2 or imported history writes) and a packed ref
    `refs/heads/caf\\xe9`, which macOS will not create as a loose file."""
    repo = tmp_path / "r"
    repo.mkdir()
    _gb(repo, "-c", "init.defaultBranch=main", "init", "-q")
    _gb(repo, "config", "user.email", "t@example.invalid")
    _gb(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a\n")
    _gb(repo, "add", "a.txt")
    _gb(repo, "commit", "-qm", "A")
    head = _gb(repo, "rev-parse", "HEAD").strip()
    tree = _gb(repo, "rev-parse", "HEAD^{tree}").strip()
    raw = (b"tree " + tree + b"\nparent " + head + b"\nauthor t <t@x> 1 +0000\n"
           b"committer t <t@x> 1 +0000\n\ncaf\xe9 raw message\n")
    c2 = _gb(repo, "hash-object", "-t", "commit", "-w", "--stdin", inp=raw).strip()
    _gb(repo, "branch", "feat-x", c2)
    with open(repo / ".git" / "packed-refs", "ab") as fh:
        fh.write(c2 + b" refs/heads/caf\xe9\n")
    return repo


def test_sitrep_git_reads_a_raw_commit_message_and_ref_name(raw_repo):
    msg = ss._git(["log", "--pretty=format:%B", "main..feat-x"], cwd=str(raw_repo))
    assert msg == "caf\udce9 raw message", repr(msg)
    refs = ss._git(["for-each-ref", "--format=%(refname)"], cwd=str(raw_repo)).splitlines()
    assert "refs/heads/caf\udce9" in refs, refs
    # The decode round-trips: the name handed back to git still names the ref.
    assert ss._git(["rev-parse", "--verify", "--quiet", "refs/heads/caf\udce9"],
                   cwd=str(raw_repo))


def test_sitrep_survey_runs_to_exit_0_over_a_worktree_on_a_non_utf8_ref(raw_repo, tmp_path):
    wt = tmp_path / "wt"
    _gb(raw_repo, "worktree", "add", "-q", "--detach", os.fsencode(wt), "feat-x")
    (raw_repo / ".git" / "worktrees" / "wt" / "HEAD").write_bytes(b"ref: refs/heads/caf\xe9\n")
    script = REPO_ROOT / "core/companion/scripts/sitrep_survey.py"
    for extra in ([], ["--json"]):
        r = subprocess.run([sys.executable, str(script), *extra], cwd=raw_repo,
                           capture_output=True, env={**os.environ, **_GIT_ISOLATION})
        assert r.returncode == 0, r.stderr.decode(errors="backslashreplace")
        assert b"Traceback" not in r.stderr
    assert b"caf\\udce9" in subprocess.run(
        [sys.executable, str(script)], cwd=raw_repo, capture_output=True,
        env={**os.environ, **_GIT_ISOLATION}).stdout


def test_permission_hook_reads_a_non_utf8_current_branch_as_unprotected(raw_repo):
    import permission_denied_hook as pdh
    (raw_repo / ".git" / "HEAD").write_bytes(b"ref: refs/heads/caf\xe9\n")
    assert pdh._current_branch(str(raw_repo)) == ""
    assert pdh._match_protected_commit('git commit -m "x"', str(raw_repo)) is None


@pytest.fixture
def overlap_ws(tmp_path):
    """A worktree whose branch commits a Latin-1 name and a valid non-ASCII one."""
    repo = tmp_path / "r"
    repo.mkdir()
    _gb(repo, "-c", "init.defaultBranch=main", "init", "-q")
    _gb(repo, "config", "user.email", "t@example.invalid")
    _gb(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a\n")
    _gb(repo, "add", "a.txt")
    _gb(repo, "commit", "-qm", "A")
    ws = tmp_path / "ws"
    _gb(repo, "worktree", "add", "-q", "-b", "feat-y", os.fsencode(ws), "main")
    blob = _gb(ws, "hash-object", "-w", "--stdin", inp=b"x\n").strip()
    _gb(ws, "update-index", "--add", "--cacheinfo", b"100644," + blob + b",caf\xe9.py")
    (ws / "né.py").write_text("y\n")
    _gb(ws, "add", "né.py")
    _gb(ws, "commit", "-qm", "B")
    return repo, ws


@pytest.mark.parametrize("quote_path", ["true", "false"])
def test_scope_overlap_committed_names_decode_raw_under_either_quote_path(overlap_ws, quote_path):
    repo, ws = overlap_ws
    _gb(repo, "config", "core.quotePath", quote_path)
    ok, paths = so._run_git_name_only(str(ws), "main")
    # Without -z the default config returned '"n\\303\\251.py"', which matched nothing.
    assert ok and sorted(paths) == ["caf\\xe9.py", "né.py"], paths


@pytest.mark.parametrize("quote_path", ["true", "false"])
def test_scope_overlap_uncommitted_names_decode_raw_under_either_quote_path(overlap_ws, quote_path):
    repo, ws = overlap_ws
    _gb(repo, "config", "core.quotePath", quote_path)
    (ws / "untré.txt").write_text("z")
    _gb(ws, "mv", "a.txt", "renamed.txt")
    got = so._run_git_porcelain(str(ws))
    # caf\xe9.py was never on disk, so it reads as deleted; the rename keeps its new path.
    assert sorted(got) == ["caf\\xe9.py", "renamed.txt", "untré.txt"], got


@pytest.mark.parametrize("json_mode", [False, True])
def test_sitrep_prints_a_surrogate_as_a_visible_escape(monkeypatch, capsys, json_mode):
    """`_git`'s `os.fsdecode` keeps a bad byte as a lone surrogate, because a ref
    name has to round-trip back to git. sitrep's stdout escapes it rather than
    dying at the last step."""
    line = "branch caf\udce9\n"
    monkeypatch.setattr(ss, "run_survey", lambda **k: None)
    monkeypatch.setattr(ss, "render_text", lambda _: line)
    monkeypatch.setattr(ss, "render_json", lambda _: line)
    monkeypatch.setattr(sys, "argv", ["sitrep_survey.py"] + (["--json"] if json_mode else []))
    assert ss.main() == 0
    assert capsys.readouterr().out == "branch caf\\udce9\n"


def test_scope_overlap_never_hands_a_caller_a_surrogate(overlap_ws, tmp_path):
    """Phase 334's round, HIGH: the first cut decoded with `os.fsdecode`, and the
    lone surrogate reached `assess().overlaps[].evidence`, which `/auto-build`'s pool
    read and `next_task --avoid-inflight` print to a strict stdout. Both crashed on
    stock git where base worked. The crash needs the `possible` arm, where the
    evidence lists the directory's paths, so this fixture shares a directory and no
    file with the in-flight worktree."""
    repo, ws = overlap_ws
    _gb(ws, "update-index", "--add", "--cacheinfo",
        b"100644," + _gb(ws, "hash-object", "-w", "--stdin", inp=b"z\n").strip() + b",src/caf\xe9.py")
    _gb(ws, "commit", "-qm", "C")
    for qp in ("true", "false"):
        _gb(repo, "config", "core.quotePath", qp)
        for p in so._worktree_changed_paths(str(ws)):
            p.encode("utf-8")  # a surrogate raises here, as a strict stdout would
    tasks = repo / "tasks"
    (tasks / "open").mkdir(parents=True)
    (tasks / "open" / "FEAT-1.md").write_text("# FEAT-1\n\n## Key files\n- `src/a.py`\n")
    (tasks / "index.yml").write_text(
        "tasks:\n  - id: FEAT-1\n    status: open\n    body: open/FEAT-1.md\n"
        "  - id: FEAT-2\n    status: in_progress\n", encoding="utf-8")
    locks = repo / "sysop/runtime/locks"
    locks.mkdir(parents=True)
    (locks / "FEAT-2.lock").write_text(f"task_id: FEAT-2\nbranch: feat-y\nworkspace: {ws}\n")
    a = so.assess("FEAT-1", index_path=tasks / "index.yml", base_tasks_dir=tasks,
                  project_root=repo)
    assert a.max_verdict == "possible", (a.max_verdict, a.overlaps, a.notes)
    shared = ", ".join(e for o in a.overlaps for e in o.evidence)
    shared.encode("utf-8")
    assert "caf\\xe9.py" in shared, shared
    so.render_text(a).encode("utf-8")
    so.render_json(a).encode("utf-8")


# -- the heredoc git reads the round found (text=True, which the class guard cannot see)
def _branch_with_body(tmp_path, body: bytes):
    repo = _repo(tmp_path / "r", index=b"tasks: []\n")
    (repo / "tasks/open").mkdir()
    (repo / "tasks/open/FEAT-1.md").write_bytes(b"# FEAT-1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    _git(repo, "switch", "-qc", "feat/first")
    (repo / "tasks/open/FEAT-1.md").write_bytes(body)
    _git(repo, "commit", "-qam", "body")
    _git(repo, "switch", "-q", "main")
    return repo


@pytest.mark.parametrize("skill", ["claim-task", "auto-build"])
def test_the_branch_tip_body_read_takes_its_unreadable_arm(tmp_path, skill):
    repo = _branch_with_body(tmp_path, b"# FEAT-1\n\n## Test decision\ncaf\xe9\n")
    body = heredoc_containing(SKILLS / f"{skill}/SKILL.md", "does not exist in")
    r = _run_body(body, ["FEAT-1", "feat/first", "tasks/open/FEAT-1.md"], repo)
    assert "Traceback" not in r.stderr, r.stderr
    assert "UNREADABLE -- feat/first:" in r.stdout and "not UTF-8" in r.stdout, r.stdout


def test_the_two_branch_tip_body_reads_stay_identical():
    a, b = (heredoc_containing(SKILLS / f"{s}/SKILL.md", "does not exist in")
            for s in ("claim-task", "auto-build"))
    cut = lambda t: t[t.index("try:\n    r = subprocess.run(["):t.index("    sys.exit(0)")]
    assert cut(a) == cut(b)


def test_document_work_3b_a_branch_name_that_is_not_utf8_is_exit_2(tmp_path):
    repo = _repo(tmp_path / "r", index=b"tasks: []\n")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "seed")
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    with open(repo / ".git" / "packed-refs", "ab") as fh:
        fh.write(head.encode() + b" refs/heads/caf\xe9\n")
    (repo / ".git" / "HEAD").write_bytes(b"ref: refs/heads/caf\xe9\n")
    body = heredoc_containing(SKILLS / "document-work/SKILL.md",
                              "Follow-up check: skipped (no tasks/index.yml)")
    r = _run_body(body, [], repo)
    assert r.returncode == 2, (r.returncode, r.stderr)
    assert "the current branch name is not UTF-8" in r.stderr and "Traceback" not in r.stderr


def _function_from_heredoc(skill, needle, name, **globs):
    """Exec one `def` out of a shipped heredoc, verbatim, with the globals it reads."""
    import ast as _ast
    body = heredoc_containing(SKILLS / f"{skill}/SKILL.md", needle)
    fn = next(n for n in _ast.walk(_ast.parse(body))
              if isinstance(n, _ast.FunctionDef) and n.name == name)
    ns = {"subprocess": subprocess, "os": os, **globs}
    exec(compile(_ast.Module([fn], []), f"{skill}:{name}", "exec"), ns)
    return ns[name]


def test_review_close_git_helpers_never_raise_on_a_raw_commit_subject(raw_repo):
    """Both docstrings say "never raises"; a raw commit subject made each raise."""
    git3c = _function_from_heredoc("review-close", "Never raises: the gate runs before the merge",
                                   "git", repo=raw_repo, _GIT_ENV=dict(os.environ))
    rc, out, err = git3c("log", "--format=%s", "main..feat-x")
    assert rc == 1 and "decode" in err, (rc, out, err)
    git3b = _function_from_heredoc("review-close", "it FAILS OPEN", "_git", wt=raw_repo)
    assert git3b("log", "--oneline", "main..feat-x") is None
    assert git3b("rev-parse", "HEAD")  # control: an ASCII answer still reads


def test_claim_task_stranded_probe_reads_a_non_utf8_task_path(tmp_path):
    repo = _repo(tmp_path / "r", index=b"tasks: []\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    _gb(repo, "config", "core.quotePath", "false")
    blob = _gb(repo, "hash-object", "-w", "--stdin", inp=b"x\n").strip()
    _gb(repo, "update-index", "--add", "--cacheinfo", b"100644," + blob + b",tasks/open/caf\xe9.md")
    _gb(repo, "commit", "-qm", "latin-1 body")  # absent on disk, so `diff HEAD` lists it as deleted
    body = heredoc_containing(SKILLS / "claim-task/SKILL.md", "STRANDED")
    r = _run_body(body, [], repo)
    assert "Traceback" not in r.stderr, r.stderr
    assert "STRANDED" in r.stdout and "caf" in r.stdout, r.stdout
