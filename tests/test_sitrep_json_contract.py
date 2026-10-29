"""`sitrep_survey.py --json` is a contract a script may key on (Phase 361).

`/roadmap` consumes the payload, and GDP's planned autopilot router keys on
`tasks[].state`, while the flag's help text called it "reserved". The module
docstring now names every key and the versioning rule. These tests hold:

* the emitted keys and the docstring's lists equal, both ways, per section;
* the version-1 key set frozen here, so a rename made in the payload AND the
  docstring together, with no version bump, still fails;
* each value's type, since the rule says a type change bumps the version;
* the rule paragraph itself, by hash, so it cannot be reversed in place.

The `state` VALUES are pinned elsewhere: `test_sitrep_survey.py` compares the
states `_classify_task` emits with `/sitrep`'s state table as sets, and
`test_roadmap_batch_survey.py` does the same for the batch states and `/roadmap`
Step 2a.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import sitrep_survey as ss

ROOT = Path(__file__).resolve().parents[1]
SURVEY = ROOT / "core/companion/scripts/sitrep_survey.py"

# The version-1 contract, frozen. Keys may be ADDED without a version change, so
# each section must CONTAIN these; removing or renaming one is a version bump,
# and a bump means a new frozen set here.
FROZEN_V1 = {
    "top level": {
        "schema_version", "timestamp", "main_root", "head_short", "stale_days",
        "tasks", "review_batches", "discrepancies", "open_roadmap_ids",
        "failed_in_merged_batches", "recommended_next", "suggested_order",
    },
    "tasks[]": {
        "task_id", "state", "state_marker", "branch", "worktree",
        "commits_ahead", "unpushed", "has_lock", "has_index_entry",
        "index_status", "dirty", "doc_work_ids", "pending_doc", "next_action",
        "notes", "agent",
    },
    "review_batches[]": {
        "batch_number", "title", "md_status", "branch", "has_lock",
        "has_branch", "has_flag", "flag_reason", "has_triage_record",
        "triaged_verdict", "triaged_tasks", "total_tasks", "doc_worked_tasks",
        "state", "next_action", "notes",
    },
    "discrepancies[]": {"kind", "detail", "suggestion"},
    "failed_in_merged_batches[]": {"batch_number", "task"},
    "recommended_next": {"command", "reason", "clear_nudge", "detail_lines"},
}

S, I, B, L = str, int, bool, list
TYPES_V1 = {
    "top level": {
        "schema_version": I, "timestamp": S, "main_root": S, "head_short": S,
        "stale_days": I, "tasks": L, "review_batches": L, "discrepancies": L,
        "open_roadmap_ids": L, "failed_in_merged_batches": L,
        "suggested_order": L,
    },
    "tasks[]": {
        "task_id": S, "state": S, "state_marker": S, "branch": S, "worktree": S,
        "commits_ahead": I, "unpushed": I, "has_lock": B, "has_index_entry": B,
        "index_status": S, "dirty": B, "doc_work_ids": L, "pending_doc": B,
        "next_action": S, "notes": L, "agent": S,
    },
    "review_batches[]": {
        "batch_number": I, "title": S, "md_status": S, "branch": S,
        "has_lock": B, "has_branch": B, "has_flag": B, "flag_reason": S,
        "has_triage_record": B, "triaged_verdict": S, "triaged_tasks": L,
        "total_tasks": I, "doc_worked_tasks": I, "state": S, "next_action": S,
        "notes": L,
    },
    "discrepancies[]": {"kind": S, "detail": S, "suggestion": S},
    "failed_in_merged_batches[]": {"batch_number": I, "task": S},
    "recommended_next": {"command": S, "reason": S, "clear_nudge": B,
                         "detail_lines": L},
}

# sha256[:16] of the rule paragraph (from "`tasks[].state` takes" to the end of
# the docstring), whitespace collapsed so a re-wrap keeps it. A deliberate change
# to the rule updates this in the same commit and says so in the phase record.
RULES_HASH = "76d22509874ec0b8"


def _documented() -> dict[str, set[str]]:
    """The key lists the module docstring states, by section label.

    Strict between the preamble and the rule paragraph: a line there that is
    neither a section label nor a continuation fails, so a sentence slipped
    into the key block cannot be read past (round 2, guards lens)."""
    doc = ss.__doc__ or ""
    start = doc.index(PREAMBLE) + len(PREAMBLE)
    block = doc[start:doc.index("`tasks[].state` takes")]
    sections: dict[str, set[str]] = {}
    label = None
    for line in block.splitlines():
        m = re.match(r"^    (\S+(?: level)?|\S+\[\])\s{2,}(.*)$", line)
        if m:
            label, rest = m.group(1), m.group(2)
            sections[label] = set()
        elif label and re.match(r"^\s{10,}\S", line):
            rest = line
        else:
            assert not line.strip(), f"an unrecognised line in the key block: {line!r}"
            label = None
            continue
        if label == "recommended_next":
            rest = rest.replace("null, or:", "")
        sections[label] |= {k.strip() for k in rest.split(",") if k.strip()}
    return sections


PREAMBLE = "JSON contract (`--json`, `schema_version` 1). A consumer may rely on these keys:"


def _rules_text() -> str:
    doc = ss.__doc__ or ""
    return " ".join(doc[doc.index("`tasks[].state` takes"):].split())


def test_the_preamble_is_exact():
    """The sentence that grants reliance sits outside the rule hash."""
    assert PREAMBLE in " ".join((ss.__doc__ or "").split())


def _survey(**kw) -> ss.Survey:
    base = dict(
        timestamp=datetime(2026, 10, 6, tzinfo=timezone.utc),
        main_root=Path("/tmp/repo"), head_short="abc1234", tasks=[],
        review_batches=[], discrepancies=[], stale_days=7, open_roadmap_ids=[],
    )
    base.update(kw)
    return ss.Survey(**base)


def _payload() -> dict:
    task = ss.TaskState(
        task_id="FEAT-1", state="ready for /review-close", branch="feat/feat-1",
        commits_ahead=1, has_lock=True, has_index_entry=True,
        index_status="in_progress", pending_doc=True, agent="autopilot",
        notes=["a note"], doc_work_ids=["FEAT-1"],
    )
    batch = ss.ReviewBatchState(
        batch_number=3, title="t", md_status="Pending", branch="", has_lock=False,
        has_branch=False, has_flag=False, flag_reason="", total_tasks=2,
        doc_worked_tasks=0, state="pending (not claimed)", next_action="x",
        notes=["a batch note"],
    )
    orphan = ss.TaskState(task_id="", state="in progress", branch="feat/orphan")
    # Every string field empty, so `x or None` cannot hide behind a value.
    branchless = ss.TaskState(task_id="FEAT-2", state="claimed, no branch", has_lock=True)
    survey = _survey(
        tasks=[task, orphan, branchless], review_batches=[batch], open_roadmap_ids=["FEAT-9"],
        discrepancies=[ss.Discrepancy(kind="k", detail="d", suggestion="s")],
        failed_in_merged_batches=[(4, "fix the thing")],
    )
    return json.loads(ss.render_json(survey))


def _sections(p: dict, task: int = 0) -> dict[str, dict]:
    return {
        "top level": p,
        "tasks[]": p["tasks"][task],
        "review_batches[]": p["review_batches"][0],
        "discrepancies[]": p["discrepancies"][0],
        "failed_in_merged_batches[]": p["failed_in_merged_batches"][0],
        "recommended_next": p["recommended_next"],
    }


def test_the_docstring_parse_is_not_vacuous():
    doc = _documented()
    assert set(doc) == set(FROZEN_V1), sorted(doc)
    assert len(doc["tasks[]"]) >= 16 and len(doc["top level"]) >= 12


def test_the_payload_emits_exactly_the_documented_keys():
    doc = _documented()
    p = _payload()
    assert p["recommended_next"] is not None, "the fixture no longer reaches a recommendation"
    for task in range(len(p["tasks"])):
        for label, obj in _sections(p, task).items():
            assert set(obj) == doc[label], (label, task)


def test_no_version_1_key_was_removed_or_renamed():
    """Equality with the docstring cannot see a rename made in both places."""
    assert ss.JSON_SCHEMA_VERSION == 1, "a new version needs its own frozen set here"
    p = _payload()
    for label, obj in _sections(p).items():
        missing = FROZEN_V1[label] - set(obj)
        assert not missing, f"{label}: removed or renamed without a version bump: {sorted(missing)}"


def test_each_value_keeps_its_version_1_type():
    p = _payload()
    assert len(p["tasks"]) == 3 and p["tasks"][1]["has_lock"] is False
    assert p["tasks"][2]["branch"] == "" and p["tasks"][2]["worktree"] == ""
    for label, obj in [kv for t in range(3) for kv in _sections(p, t).items()]:
        for key, want in TYPES_V1[label].items():
            assert type(obj[key]) is want, (
                f"{label}.{key} is {type(obj[key]).__name__}, not {want.__name__}"
            )
    for key in ("notes", "doc_work_ids"):
        items = p["tasks"][0][key]
        assert items and all(type(x) is str for x in items), key
    assert p["review_batches"][0]["notes"] == ["a batch note"]
    assert all(type(x) is str for x in p["recommended_next"]["detail_lines"])
    assert all(type(x) is str for x in p["suggested_order"])


def test_an_idle_survey_still_emits_recommended_next_as_null():
    p = json.loads(ss.render_json(_survey()))
    assert "recommended_next" in p and p["recommended_next"] is None
    assert set(p) == _documented()["top level"]


def test_the_version_is_emitted_and_matches_the_docstring():
    p = _payload()
    assert p["schema_version"] == ss.JSON_SCHEMA_VERSION
    assert f"`schema_version` {ss.JSON_SCHEMA_VERSION})" in (ss.__doc__ or "")


def test_the_versioning_rules_are_pinned():
    got = hashlib.sha256(_rules_text().encode("utf-8")).hexdigest()[:16]
    assert got == RULES_HASH, (
        f"the --json versioning rules changed (hash {got}, pinned {RULES_HASH}); "
        "if deliberate, update RULES_HASH in the same commit and say so in the phase record"
    )


def test_the_flag_help_states_the_contract():
    out = subprocess.run(
        [sys.executable, str(SURVEY), "--help"], capture_output=True, text=True, check=True,
    ).stdout
    flat = " ".join(out.split())
    want = "--json Emit JSON instead of the text report (a stable contract; see the module docstring)"
    assert want in flat, flat
    usage = next(l for l in (ss.__doc__ or "").splitlines() if "sitrep_survey.py --json" in l)
    assert usage.rstrip().endswith("# JSON output (contract below)"), usage


def test_the_sitrep_skill_flag_line_states_the_contract():
    text = (ROOT / "core/skills/sitrep/SKILL.md").read_text()
    start = text.index("- **`--json`**")
    end = text.index("\n- ", start)
    line = " ".join(text[start:end].split())
    assert line == (
        "- **`--json`** — emit the structured classification as JSON to stdout (default is "
        "the human-readable text report). The shape is a stable contract for scripts; its "
        "key list and versioning rule are in `sitrep_survey.py`'s module docstring."
    )


def test_a_yaml_typed_agent_is_read_as_its_text():
    """A router compares `agent` for equality, so the lock reader must keep the
    line's text: `No` must not arrive as `false`."""
    p = _payload()
    assert p["tasks"][0]["agent"] == "autopilot" and p["tasks"][1]["agent"] == ""
    lock_text = "task_id: FEAT-1\nstatus: in_progress\nagent: No\nbranch: feat/feat-1\n"
    assert ss.load_lock_text(lock_text)["agent"] == "No"


def _env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
               GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    return env


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, env=_env())


def test_the_lock_agent_reaches_the_json_end_to_end(tmp_path):
    """Round 2 (guards lens): every agent test used a hand-built `TaskState`, so
    reading the wrong lock field, defaulting to `anonymous`, or dropping the key
    passed. Claim through `claim_task.sh --lock ... autopilot`, break a second
    lock, drop the halt marker, and read `--json` as a router would."""
    root = tmp_path / "proj" / "main"
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    (root / ".gitignore").write_text("sysop/runtime/\n", encoding="utf-8")
    scripts = root / "sysop" / "scripts"
    scripts.mkdir(parents=True)
    for p in list(SURVEY.parent.glob("*.py")) + list(SURVEY.parent.glob("*.sh")):
        (scripts / p.name).write_bytes(p.read_bytes())
    (root / "tasks" / "open").mkdir(parents=True)
    row = ("  - {{id: {0}, title: T, phase: 6, status: open, effort: Low, "
           "blast_radius: single-module, user_action: false, body: open/{0}.md}}\n")
    (root / "tasks" / "index.yml").write_text(
        "schema_version: 2\nphases:\n"
        "  - {number: 6, title: P, status: in_progress, current_focus: true}\n"
        "tasks:\n" + row.format("FEAT-AAA") + row.format("FEAT-CCC"), encoding="utf-8")
    for tid in ("FEAT-AAA", "FEAT-CCC"):
        (root / "tasks" / "open" / f"{tid}.md").write_text(f"# {tid}\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    for tid in ("FEAT-AAA", "FEAT-CCC"):
        r = subprocess.run(["bash", "sysop/scripts/claim_task.sh", "--lock", tid,
                            f"feat/{tid.lower()}", "autopilot"],
                           cwd=root, capture_output=True, text=True, env=_env())
        assert r.returncode == 0, r.stdout + r.stderr
    broken = root / "sysop" / "runtime" / "locks" / "FEAT-CCC.lock"
    broken.write_text(broken.read_text(encoding="utf-8") + "bad: [\n", encoding="utf-8")
    (root / "sysop" / "runtime" / "auto-build-halt.md").write_text("halted\n", encoding="utf-8")

    out = subprocess.run([sys.executable, "sysop/scripts/sitrep_survey.py", "--json"],
                         cwd=root, capture_output=True, text=True, env=_env())
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    by_id = {t["task_id"]: t for t in got["tasks"]}
    assert by_id["FEAT-AAA"]["has_lock"] is True and by_id["FEAT-AAA"]["agent"] == "autopilot"
    assert by_id["FEAT-CCC"]["state"] == "lock unreadable" and by_id["FEAT-CCC"]["agent"] == ""
    assert "unattended auto-build halted" in [d["kind"] for d in got["discrepancies"]]


def test_the_halt_marker_is_a_discrepancy(tmp_path):
    """`/auto-build --unattended` stops every later unattended run while its
    halt marker exists; the router reads `discrepancies[]`, so the marker must
    appear there, and not when it is absent."""
    # A live claim beside the marker is the case it exists for (round 2: a
    # guard reading `and not locks` walked through an empty-input test).
    lock = ss.Lock(task_id="FEAT-1", path=tmp_path / "x.lock", branch="feat/feat-1",
                   workspace=str(tmp_path / "w"), agent="autopilot")
    wt = ss.Worktree(path=tmp_path / "w", branch="feat/feat-1", head="abc")

    def found():
        return [d for d in ss._find_discrepancies([lock], [wt], {}, tmp_path, [])
                if d.kind == "unattended auto-build halted"]
    assert found() == []
    marker = tmp_path / "sysop" / "runtime" / "auto-build-halt.md"
    marker.parent.mkdir(parents=True)
    marker.write_text("halted\n")
    (d,) = found()
    assert d.detail == (
        "sysop/runtime/auto-build-halt.md: an unattended /auto-build left a claim it "
        "could not verify, and every later unattended run stops until the file is gone"
    )
    assert d.suggestion == (
        "read it, reconcile the tasks it names (finish the claim, or claim_task.sh "
        "--release <TASK_ID>), then delete it"
    )
    marker.unlink()
    marker.mkdir()  # Step 0 stops on a marker that exists, whatever it is
    assert len(found()) == 1
