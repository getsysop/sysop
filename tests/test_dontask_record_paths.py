"""`Q-665` (Phase 420): every Sysop record path a skill names is either granted or accounted for.

Under `dontAsk` a `Write` or `Edit` of a path no `Edit(...)` rule covers is denied, in the project
too. Wade's answer of 2026-10-24: seed a rule per path the skills write with a file tool, not a
directory-wide grant, so that `sysop/runtime/locks/` stays ungranted in every mode. An
enumeration goes stale when a skill starts writing a new path, so this test makes each
top-level name under `sysop/runtime/` and `tasks/` that a shipped skill mentions take a side:
covered by a seeded rule, or listed below with what writes it instead; and the same for a loop
install's skills against `LOOP_ALLOW`. Records outside those two roots are not scanned: the
close's own are taken from `close_run.py`'s `CLOSE_WRITTEN` instead (Phase 420's round, lens A),
and the overlays and `CLAUDE.md` are out on Wade's answer.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "core" / "companion" / ".claude" / "settings.json"
SKILLS = REPO / "core" / "skills"
INSTALL = REPO / "install.sh"
CLOSE_RUN = REPO / "core" / "companion" / "scripts" / "close_run.py"
GUARD = SKILLS / "_shared" / "permission-guard.md"
WORKFLOW = REPO / "core" / "companion" / "docs" / "WORKFLOW.md"

# Written by a script, the shell or a hook, or only read; or written with a file tool but left
# unseeded on purpose (vision.md and decisions.md, which the guard's `dontAsk` note names, and
# a legacy notes.md). A name moves out of here, into the template, when it is seeded.
NOT_A_FILE_TOOL_WRITE = {
    "sysop/runtime/locks": "claim_task.sh and batch_work.sh; never granted (Phase 374's ruling)",
    "sysop/runtime/subagent-envelopes": "parse_subagent_envelope.py, the SubagentStop hook",
    "sysop/runtime/round-receipts": "round_receipt.py",
    "sysop/runtime/pending-rounds": "the review skills' Step 0 heredoc",
    "sysop/runtime/preserved": "ignored_refs.py --preserve",
    "sysop/runtime/tracker.write.lock": "the tracker writers' mutex, a script",
    # `/review-close` Step 2b's baselines and pinned checkouts: `review_pins.py` writes them
    # (Phase 421, `Q-665`); the step names the config baseline in its leak arm.
    "sysop/runtime/2b-config-baseline.txt": "review_pins.py baseline, in /review-close Step 2b",
    "sysop/runtime/pins": "review_pins.py add, in /review-close Step 2b and 4a-fix",
    "tasks/archive": "close_index.py and archive moves, scripts",
    "tasks/deferred": "read by /add-task's overlap search",
    "tasks/schema.md": "a managed file the skills read",
    "tasks/README.md": "a managed file the skills read",
    # Consumer-owned (`/intake` says so), written by /intake and /onboard with a human in the
    # loop; left out with the overlays on Wade's answer of 2026-10-24.
    "tasks/vision.md": "consumer-owned, /intake and /onboard",
    "tasks/decisions.md": "consumer-owned, /intake and /onboard",
    # Retired: nothing appends to it, but `/add-task` Step 2 deletes a promoted line from a legacy
    # one with a file tool (Phase 420's round, lens B); unseeded, like vision.md.
    "tasks/notes.md": "legacy; /add-task deletes a promoted line, unseeded",
    "tasks/in_progress": "named only to say no shipped layout has it",
}

# Named by a loop install's skills but never written there: a loop install has no `tasks/`.
LOOP_NOT_WRITTEN = {
    "tasks/index.yml": "_shared/adversarial-review.md, about full-mode callers",
    "tasks/open": "_shared/adversarial-review.md, about full-mode callers",
}

# `/review-close` Step 4c writes these project documents with a file tool (and `/release`
# `CHANGELOG.md`). Phase 421 seeds an `Edit` rule for each, on Wade's ruling of 2026-10-24.
PROJECT_DOCUMENTS = ("PROJECT_STATUS.md", "CHANGELOG.md", "UI_Iterations.md")
# The rest of `CLOSE_WRITTEN` that no seeded rule covers is written by a script.
CLOSE_BY_SCRIPT = {
    "tasks/archive/TASK-0001.md": "close_index.py moves the body",
    "review_tasks_archive.md": "archive_review_tasks.py",
}

# An optional `<PLACEHOLDER>/`, `$VAR/`, `${VAR}/` or `./` prefix is read through (Phase 420's
# round, lens A); any other leading path segment is not, so `foo/tasks/x` stays out.
_NAME = re.compile(r"(?<![\w/.-])(?:(?:<[^<>\s]+>|\$\{?\w+\}?|\.)/)?(sysop/runtime|tasks)/([A-Za-z0-9_][A-Za-z0-9_.-]*?)(?=[/`'\"\s)*:,;|]|\.?$|\.\s)")


def _edit_rules() -> list[str]:
    allow = json.loads(TEMPLATE.read_text(encoding="utf-8"))["permissions"]["allow"]
    return [r[len("Edit(/"):-1] for r in allow if r.startswith("Edit(/")]


def _loop_edit_rules() -> list[str]:
    block = re.search(r"^LOOP_ALLOW = \{(.*?)^\}", INSTALL.read_text(encoding="utf-8"), re.S | re.M)
    assert block, "LOOP_ALLOW not found in install.sh"
    return re.findall(r'^\s*"Edit\(/([^"]+)\)",', block.group(1), re.M)


def _loop_skill_files() -> list[Path]:
    text = INSTALL.read_text(encoding="utf-8")
    skills = set(re.search(r'^LOOP_EXCLUDE_SKILLS="([^"]*)"', text, re.M).group(1).split())
    shared = set(re.search(r'^LOOP_EXCLUDE_SHARED="([^"]*)"', text, re.M).group(1).split())
    out = []
    for path in sorted(SKILLS.rglob("*.md")):
        top = path.relative_to(SKILLS).parts[0]
        if top in skills or (top == "_shared" and path.stem in shared):
            continue
        out.append(path)
    return out


def _covered(name: str, rules: list[str]) -> bool:
    for rule in rules:
        if rule.endswith("/**") and (name == rule[:-3] or name.startswith(rule[:-2])):
            return True
        if rule == name:
            return True
    return False


def _named(paths=None) -> dict[str, str]:
    """Each top-level name a shipped skill file mentions, with one file that mentions it."""
    out: dict[str, str] = {}
    for path in (paths if paths is not None else sorted(SKILLS.rglob("*.md"))):
        for line in path.read_text(encoding="utf-8").splitlines():
            for root, leaf in _NAME.findall(line):
                if root == "tasks" and leaf == "tasks":
                    continue  # `tasks/tasks/open/…`, a doubled prefix quoted as a mistake
                out.setdefault(f"{root}/{leaf}", path.relative_to(REPO).as_posix())
    return out


def test_the_scan_finds_the_record_paths():
    named = _named()
    for must in ("tasks/index.yml", "tasks/open", "sysop/runtime/close",
                 "sysop/runtime/pending-docs", "sysop/runtime/locks"):
        assert must in named, f"the scan lost {must}"


def test_every_named_record_path_takes_a_side():
    rules = _edit_rules()
    undecided = {n: f for n, f in _named().items()
                 if not _covered(n, rules) and n not in NOT_A_FILE_TOOL_WRITE}
    assert not undecided, (
        "a skill names a Sysop record path that no seeded Edit rule covers and that is not "
        "listed as written some other way; under dontAsk a Write or Edit of it is denied. Seed "
        f"an Edit rule for it or list it in NOT_A_FILE_TOOL_WRITE: {undecided}"
    )


def test_no_listed_path_is_also_granted():
    rules = _edit_rules()
    both = [n for n in NOT_A_FILE_TOOL_WRITE if _covered(n, rules)]
    assert not both, f"listed as not a file-tool write, yet granted: {both}"


def test_the_list_has_no_stale_entries():
    named = _named()
    stale = [n for n in NOT_A_FILE_TOOL_WRITE if n not in named]
    assert not stale, f"no shipped skill names these any more: {stale}"


def test_the_scan_reads_through_a_placeholder_prefix():
    line = "write `<WORKTREE_PATH>/sysop/runtime/x.md`, `./tasks/y`, `$ROOT/tasks/z` and `${R}/tasks/w`"
    found = {f"{r}/{l}" for r, l in _NAME.findall(line)}
    assert found == {"sysop/runtime/x.md", "tasks/y", "tasks/z", "tasks/w"}, found
    assert not _NAME.findall("see `docs/tasks/x.md` and `a/sysop/runtime/y`")


def test_every_record_path_a_loop_skill_names_takes_a_side():
    files = _loop_skill_files()
    assert any(p.parent.name == "codebase-review" for p in files), "the loop skill set is empty"
    rules = _loop_edit_rules()
    undecided = {n: f for n, f in _named(files).items()
                 if not _covered(n, rules) and n not in NOT_A_FILE_TOOL_WRITE
                 and n not in LOOP_NOT_WRITTEN}
    assert not undecided, (
        "a loop-mode skill names a record path LOOP_ALLOW grants no Edit rule for; under "
        f"dontAsk a loop install's Write of it is denied: {undecided}"
    )


def test_the_close_written_paths_take_a_side():
    m = re.search(r"^CLOSE_WRITTEN = \((.*?)\)\n", CLOSE_RUN.read_text(encoding="utf-8"), re.S | re.M)
    assert m, "CLOSE_WRITTEN not found in close_run.py"
    written = re.findall(r'"([^"]+)"', m.group(1))
    assert "PROJECT_STATUS.md" in written
    rules = _edit_rules()
    undecided = [w for w in written
                 if not any(_covered(w, [r]) or w.startswith(r[:-2]) for r in rules if r)
                 and w not in CLOSE_BY_SCRIPT]
    assert not undecided, f"a path the close commits takes no side: {undecided}"
    for doc in PROJECT_DOCUMENTS:
        assert _covered(doc, rules), f"{doc} is no longer seeded; Wade ruled it seeded (Phase 421)"


def test_the_seeded_project_documents_are_no_longer_called_unsupported():
    """Phase 421 seeded them, so the runner's note and the reader's paragraph must stop saying a
    `dontAsk` run cannot write them, and the reader's must say they are seeded."""
    guard = " ".join(GUARD.read_text(encoding="utf-8").split())
    workflow = " ".join(WORKFLOW.read_text(encoding="utf-8").split())
    note = guard[guard.index("Not supported under dontAsk"):guard.index("Record-path rules missing")]
    for doc in PROJECT_DOCUMENTS:
        assert doc not in note, f"the guard's dontAsk note still calls {doc} unsupported"
    half_a = workflow[workflow.index("Under `dontAsk` every file write"):][:800]
    assert "and for the project documents Step 4c writes" in half_a
    for doc in PROJECT_DOCUMENTS:
        assert f"`{doc}`" in half_a, f"WORKFLOW.md's half-A paragraph omits {doc}"


def test_the_guards_record_path_list_is_the_templates():
    """Phase 420's round (lens B): step 3b's two lists are what the guard checks, and nothing tied
    them to what the installer seeds. Both modes = `LOOP_ALLOW`'s Edit rules; both lists = the
    template's."""
    text = GUARD.read_text(encoding="utf-8")
    step = text[text.index("**Detect `dontAsk`.**"):text.index("For each rule in the skill's *required* list")]
    both = step[step.index("Both install modes:"):step.index("Full installs:")]
    full = step[step.index("Full installs:"):]
    rule = re.compile(r"`Edit\(/([^`]+)\)`")
    assert set(rule.findall(both)) == set(_loop_edit_rules()), "step 3b's both-modes list is not LOOP_ALLOW's"
    assert set(rule.findall(both)) | set(rule.findall(full)) == set(_edit_rules()), (
        "step 3b's lists are not the template's Edit rules")
    n = len(rule.findall(both))
    words = {4: "four", 5: "five", 6: "six", 7: "seven"}
    assert f"check only the first {words.get(n, n)}" in " ".join(step.split()), (
        f"step 3b says how many a loop install checks, and it is {n}")
