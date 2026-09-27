"""`/contribute-convention` names two sources, and each one is checked against the code.

**Step 2, the override check.** A `checks.project.yml` entry with the same `id` as a
check Sysop ships is local policy, not a new rule. The skill once told the runner to
find the Sysop clone through "the durable dependency recorded in the install lock".
The lock writer (`install.sh` `write_lock_file`) records no source path, so on every
stock install the check ended at "could not determine". The skill now points at
`$SYSOP_SRC` and prescribes one `grep`. These guards run the real installer and read
its lock, and run the prescribed `grep` against the shipped fragments.

**Step 3, provenance.** The skill searched only `review_tasks.md`, but
`archive_review_tasks.py` moves merged rounds into `review_tasks_archive.md`. It also
offered a `Promotion summary:` trailer as evidence, and that trailer holds only counts.
The skill now searches both files and reads the commit that added the overlay entry.
These guards run the real archiver and the prescribed `git` commands, and check the
promotion writers' commit subject and staging list against the shape the skill reads.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from _prose_guard_helpers import carries, section, states

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS = REPO_ROOT / "core" / "skills"
SKILL = SKILLS / "contribute-convention" / "SKILL.md"
SCRIPTS = REPO_ROOT / "core" / "companion" / "scripts"
STEP2 = "## Step 2: Parse the overlay into candidate conventions"
STEP3 = "## Step 3: Discover provenance for each candidate"
PROMOTION_WRITERS = ("codebase-review", "security-audit")

_GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}


def _git(cwd, *args) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True,
        env={**os.environ, **_GIT_ENV},
    ).stdout


def _fenced_line(text: str, starts: str, contains: str = "") -> str:
    """The ONE line inside a fence of `text` that starts with `starts` and carries
    `contains`, stripped."""
    hits, inside = [], False
    for line in text.splitlines():
        if line.strip().startswith(("```", "~~~")):
            inside = not inside
            continue
        if inside and line.strip().startswith(starts) and contains in line:
            hits.append(line.strip())
    assert len(hits) == 1, (
        f"expected one fenced line starting {starts!r} with {contains!r}, found {len(hits)}"
    )
    return hits[0]


# ── Step 2: the clone's path is not in the lock ─────────────────────────────


@pytest.fixture(scope="module")
def fresh_install(tmp_path_factory):
    """A real fresh install from this tree. Returns (lock dict, installer stdout)."""
    target = tmp_path_factory.mktemp("consumer")
    _git(target, "init", "-q")
    _git(target, "config", "user.email", "test@test")
    _git(target, "config", "user.name", "test")
    (target / "README.md").write_text("# scratch\n")
    _git(target, "add", "-A")
    _git(target, "commit", "-qm", "seed")
    env = {**os.environ, **_GIT_ENV}
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env["PATH"]
    r = subprocess.run(
        ["bash", str(REPO_ROOT / "install.sh"), str(target), "--packs", "",
         "--no-arm-hooks", "--yes"],
        capture_output=True, text=True, env=env, timeout=300,
    )
    assert r.returncode == 0, f"install failed\n{r.stdout}\n{r.stderr}"
    lock = json.loads((target / ".claude" / "sysop.lock").read_text())
    return lock, r.stdout


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)


def test_the_lock_records_no_source_path(fresh_install):
    """The skill says so; the installer's own lock is the proof."""
    lock, _ = fresh_install
    assert lock.get("sysop_commit"), "the lock under test is not a real lock"
    sources = {str(REPO_ROOT), str(REPO_ROOT.resolve()), os.path.realpath(REPO_ROOT)}
    leaked = [s for s in _strings(lock) if any(src in s for src in sources)]
    assert not leaked, (
        f"the lock now records the source clone's path ({leaked}). Step 2 of "
        "contribute-convention/SKILL.md tells the runner not to look for it there. "
        "Update that paragraph to read the path from the lock."
    )
    assert states(section(SKILL.read_text(encoding="utf-8"), STEP2), "the lock holds no source path")


def test_the_skill_names_where_the_path_actually_lives(fresh_install):
    """`$SYSOP_SRC`, which the fresh-install footer prints as an export line."""
    _, stdout = fresh_install
    assert 'export SYSOP_SRC="' in stdout
    step2 = section(SKILL.read_text(encoding="utf-8"), STEP2)
    assert carries(step2, 'prints the exact `export SYSOP_SRC="<path>"` line')
    assert "recorded in the install lock" not in step2


def _shipped_ids() -> set[str]:
    frags = [REPO_ROOT / "core" / "companion" / "checks.yml.fragment",
             *sorted((REPO_ROOT / "packs").glob("*/companion/checks.yml.fragment"))]
    ids = set()
    for f in frags:
        for c in (yaml.safe_load(f.read_text()) or {}).get("checks") or []:
            ids.add(c["id"])
    return ids


def _run_prescribed_grep(env_src: str | None) -> subprocess.CompletedProcess:
    cmd = _fenced_line(section(SKILL.read_text(encoding="utf-8"), STEP2), "grep ",
                       "checks.yml.fragment")
    env = {k: v for k, v in os.environ.items() if k != "SYSOP_SRC"}
    if env_src is not None:
        env["SYSOP_SRC"] = env_src
    return subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, env=env)


def test_the_prescribed_grep_lists_every_shipped_id():
    r = _run_prescribed_grep(str(REPO_ROOT))
    got = set(re.findall(r"^[^:\n]+:\d+:\s*-\s*id:\s*[\"']?([^\"'\s#]+)[\"']?\s*(?:#.*)?$",
                         r.stdout, re.M))
    want = _shipped_ids()
    assert want, "no shipped check ids found"
    assert got == want, (
        f"the Step 2 grep misses {sorted(want - got)} and invents {sorted(got - want)}"
    )


def test_the_prescribed_grep_prints_no_id_when_the_variable_is_unset():
    """The skill's fallback (ask the human for the path) keys on this."""
    r = _run_prescribed_grep(None)
    assert "id:" not in r.stdout
    assert r.returncode != 0


# ── Step 3: the archive, and the commit that added the entry ────────────────


def test_the_archive_name_and_place_match_the_archiver():
    sys.path.insert(0, str(SCRIPTS))
    try:
        import archive_review_tasks as art
    finally:
        sys.path.remove(str(SCRIPTS))
    assert os.path.dirname(art.ARCHIVE_FILE) == os.path.dirname(art.REVIEW_FILE)
    step3 = section(SKILL.read_text(encoding="utf-8"), STEP3)
    for name in (os.path.basename(art.REVIEW_FILE), os.path.basename(art.ARCHIVE_FILE)):
        assert f"`{name}`" in step3, f"Step 3 does not name {name}"
    assert carries(step3, "both at the consumer-repo root")


_TRACKER = """# Review Tasks

## Round 2 (2026-01-02) — Code Quality Review

### Batch 1 — logging `Merged`

> **Scope:** src/log.py
> **Branch:** fix/batch-1-logging
> **Verify:** pytest

- [x] **TASK-1**: Stop logging raw request bodies 🟡
  `src/log.py:10` `[verified]` — raw body logged.

---

## Round 3 (2026-02-02) — Code Quality Review

### Batch 2 — merged half `Merged`

> **Scope:** src/api.py
> **Branch:** fix/batch-2-merged
> **Verify:** pytest

- [x] **TASK-2**: Stop logging raw request bodies again 🟡
  `src/api.py:5` `[verified]` — raw body logged.

### Batch 3 — open half `Pending`

> **Scope:** src/db.py
> **Branch:** fix/batch-3-open
> **Verify:** pytest

- [ ] **TASK-3**: Stop logging raw request bodies a third time 🟡
  `src/db.py:7` `[verified]` — raw body logged.
"""

_ARCHIVE_SEED = (
    "# Review Tasks Archive\n\n## Grand Total (Archived)\n\n"
    "| Round | Total | Completed | Deferred | Status |\n|---|---|---|---|---|\n"
)


def test_the_archiver_moves_rounds_out_and_keeps_their_headings(tmp_path):
    """A rule's earlier round is only in the archive once the archiver has run."""
    (tmp_path / "sysop" / "scripts").mkdir(parents=True)
    for name in ("archive_review_tasks.py", "_log.py"):
        (tmp_path / "sysop" / "scripts" / name).write_bytes((SCRIPTS / name).read_bytes())
    (tmp_path / "review_tasks.md").write_text(_TRACKER, encoding="utf-8")
    (tmp_path / "review_tasks_archive.md").write_text(_ARCHIVE_SEED, encoding="utf-8")
    r = subprocess.run(
        [sys.executable, "sysop/scripts/archive_review_tasks.py"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60, input="y\n",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert r.returncode == 0, r.stdout + r.stderr
    live = (tmp_path / "review_tasks.md").read_text(encoding="utf-8")
    arch = (tmp_path / "review_tasks_archive.md").read_text(encoding="utf-8")
    heading = re.compile(r"^## Round (\d+)\b", re.M)
    # Round 2 left the live file entirely; its heading and its task are in the archive.
    assert "TASK-1" not in live and "TASK-1" in arch
    assert "2" not in heading.findall(live) and "2" in heading.findall(arch)
    # Round 3 was partly archived, so its heading is in BOTH files. Counting headings
    # instead of round numbers would count Round 3 twice.
    assert "3" in heading.findall(live) and "3" in heading.findall(arch)
    step3 = section(SKILL.read_text(encoding="utf-8"), STEP3)
    assert carries(step3, "each under its round's `## Round N` heading")
    assert carries(step3, "a partly archived round has its `## Round N` heading in both files")


def _promotion_fence(writer: str) -> list[str]:
    """The ONE fenced block in `writer`'s SKILL.md that commits a promotion."""
    lines = (SKILLS / writer / "SKILL.md").read_text(encoding="utf-8").splitlines()
    blocks, cur = [], None
    for line in lines:
        if line.strip().startswith(("```", "~~~")):
            if cur is None:
                cur = []
            else:
                blocks.append(cur)
                cur = None
            continue
        if cur is not None:
            cur.append(line.strip())
    hits = [b for b in blocks if any(ln.startswith('git commit -m "docs: promote') for ln in b)]
    assert len(hits) == 1, f"{writer}: expected one promotion commit block, found {len(hits)}"
    return hits[0]


def _writer_subject(writer: str) -> str:
    line = next(ln for ln in _promotion_fence(writer)
                if ln.startswith('git commit -m "docs: promote'))
    return line.split('"', 1)[1]


def _shape(subject: str) -> str:
    """A subject template with every `<placeholder>` folded to one token."""
    return re.sub(r"<[^>]+>", "<X>", subject.replace("…", "<X>")).strip()


@pytest.mark.parametrize("writer", PROMOTION_WRITERS)
def test_the_promotion_subject_the_skill_reads_is_the_one_the_writers_emit(writer):
    step3 = section(SKILL.read_text(encoding="utf-8"), STEP3)
    m = re.search(r"under the subject\s+`([^`]+)`", step3)
    assert m, "Step 3 no longer states the promotion commit's subject"
    assert _shape(m.group(1)) == _shape(_writer_subject(writer)), (
        f"{writer} Step 9 commits under {_writer_subject(writer)!r}; "
        f"contribute-convention Step 3 looks for {m.group(1)!r}"
    )


@pytest.mark.parametrize("writer", PROMOTION_WRITERS)
def test_the_promotion_commit_stages_both_overlays(writer):
    """In the same block as the commit, or the commit that ADDS the overlay entry is
    some later, unrelated one."""
    block = _promotion_fence(writer)
    for overlay in (".claude/checks.project.yml", ".claude/convention_map.project.md"):
        assert f"git add -A -- {overlay}" in block, f"{writer} does not stage {overlay}"


def _commit(repo, rel, text, subject, *, replace=False):
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if replace:
        p.write_text(text, encoding="utf-8")
    else:
        with open(p, "a", encoding="utf-8") as f:
            f.write(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", subject)


def _adds(line: str, string: str, overlay: str) -> bool:
    """What the skill tells the runner to look for on a `+` line."""
    if overlay.endswith(".yml"):
        m = re.fullmatch(r"-\s*id:\s*[\"']?([^\"'\s#]+)[\"']?\s*(#.*)?", line)
        return bool(m) and m.group(1) == string
    return string in line


def _prescribed(repo, string, overlay):
    step3 = section(SKILL.read_text(encoding="utf-8"), STEP3)
    log_cmd = _fenced_line(step3, "git log ")
    show_cmd = _fenced_line(step3, "git show ")
    log_cmd = log_cmd.replace("<string>", string).replace("<overlay file>", overlay)
    env = {**os.environ, **_GIT_ENV}
    out = subprocess.run(["bash", "-c", log_cmd], cwd=repo, capture_output=True,
                         text=True, check=True, env=env).stdout
    for row in out.splitlines():
        if not row.strip():
            continue
        sha, subject = row.split(" ", 1)
        cmd = show_cmd.replace("<short sha>", sha).replace("<overlay file>", overlay)
        diff = subprocess.run(["bash", "-c", cmd], cwd=repo, capture_output=True,
                              text=True, check=True, env=env).stdout
        added = [ln[1:].strip() for ln in diff.splitlines()
                 if ln.startswith("+") and not ln.startswith("+++")]
        if any(_adds(ln, string, overlay) for ln in added):
            return subject
    return None


def test_the_prescribed_git_commands_find_the_promotion_commit(tmp_path):
    """Run Step 3's `git log` and `git show` against a history built from what the
    writers emit, including the two cases the skill's wording exists for."""
    repo = tmp_path / "consumer"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    subject = _writer_subject("codebase-review")
    values = iter(("1", "4"))
    subject = re.sub(r"<[^>]+>", lambda _m: next(values, "4"), subject)
    checks, cmap = ".claude/checks.project.yml", ".claude/convention_map.project.md"
    head = "checks:\n  - id: no-bare-print-call\n    name: a\n"
    _commit(repo, checks, head, subject)
    _commit(repo, cmap, "## `src/**` — Backend\n\n- Never log raw request bodies\n", subject)
    _commit(repo, checks, "  - id: no-bare-print\n    name: b\n", "chore: hand-add a check")
    # Promoted, then dropped, then restored by hand: still the promoted rule.
    _commit(repo, checks, "  - id: no-raw-body\n    name: c\n", subject)
    body = (repo / checks).read_text(encoding="utf-8")
    _commit(repo, checks, body.replace("  - id: no-raw-body\n    name: c\n", ""),
            "chore: drop a check", replace=True)
    _commit(repo, checks, "  - id: no-raw-body\n    name: c\n", "chore: restore a check")

    promoted = re.compile(r"promote \d+ conventions from Round (\d+)")
    found = _prescribed(repo, "no-bare-print-call", checks)
    assert found and promoted.search(found).group(1) == "4"
    found = _prescribed(repo, "Never log raw request bodies", cmap)
    assert found and promoted.search(found)
    # The trap: `no-bare-print` first occurs in the promotion commit, inside the longer
    # id. The adding commit is the hand edit, which is not promotion evidence.
    assert _prescribed(repo, "no-bare-print", checks) == "chore: hand-add a check"
    # Oldest first: the restore is not where the rule came from.
    found = _prescribed(repo, "no-raw-body", checks)
    assert found and promoted.search(found), found
    assert _prescribed(repo, "never-added", checks) is None


def test_the_counts_only_trailer_is_no_longer_offered_as_provenance():
    """`Promotion summary:` holds counts and names no rule."""
    assert "Promotion summary" not in section(SKILL.read_text(encoding="utf-8"), STEP3)
    for writer in PROMOTION_WRITERS:
        text = (SKILLS / writer / "SKILL.md").read_text(encoding="utf-8")
        assert "Promotion summary: <N> total (<M> mechanical / <K> prose)" in text


def test_a_semgrep_stub_candidate_is_carried_with_its_rule():
    """Step 9 option (ii) writes a `semgrep-<id>` entry with no `pattern:` into
    `checks.project.yml` (the pre-scan drops a rule's findings without one). Read as a
    check, that entry has no rule in it, so Step 2 must send the reader to the rule."""
    for writer in PROMOTION_WRITERS:
        body = (SKILLS / writer / "SKILL.md").read_text(encoding="utf-8")
        assert "`semgrep-<id>` entry to `.claude/checks.yml`" in body, writer
    step2 = " ".join(section(SKILL.read_text(encoding="utf-8"), STEP2).split())
    assert "`semgrep-<rule>` and has no `pattern:` is a registry stub" in step2
    assert "`.claude/semgrep/*.yaml` rule whose `id:` is `<rule>`" in step2


def test_an_override_is_judged_against_the_installed_packs_only(fresh_install):
    """A consumer id that matches a check in a pack this project never installed is
    not an override; the lock's `packs:` says which packs count."""
    lock, _ = fresh_install
    assert isinstance(lock.get("packs"), list), lock
    step2 = " ".join(section(SKILL.read_text(encoding="utf-8"), STEP2).split())
    assert "the `packs` list of the JSON lock `.claude/sysop.lock`" in step2
    assert "A match only in a pack this project did not install is not an override." in step2
