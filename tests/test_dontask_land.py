"""The unattended land under `dontAsk` (Phase 423, `Q-665`'s last mode).

Phase 423 measured the shipped land as one headless session with no denial, so nothing here
converts a wall. It pins what the phase added around that measurement, each by running it or by
reading its live line in the section that governs it:

- WORKFLOW.md's three night commands parse as flag sets `begin` accepts, the land's with
  `--headless` (a recipe `begin` refuses is a night that stops at its first command);
- the land's `--headless` rule sits in the unattended land's own section;
- `land-check` on `ALREADY MERGED` prints no `READER:` line, and the step file no longer says it
  prints one per thing it read;
- Step 6's HARD RULE lists the pending docs with the `find` a headless session can run (it has no
  Glob tool; the shipped land's night composed an `ls` chain for it).
"""
import re
import shlex
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "core" / "companion" / "scripts"))
import close_arms  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_runner_text import text_of  # noqa: E402

WORKFLOW = REPO / "core" / "companion" / "docs" / "WORKFLOW.md"
CORE = REPO / "core" / "skills" / "review-close" / "SKILL.md"
LAND = REPO / "core" / "skills" / "review-close" / "steps" / "request-review-land.md"


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    nxt = re.search(r"^#{1,3} ", text[start + len(heading):], re.M)
    return text[start:start + len(heading) + nxt.start()] if nxt else text[start:]


def _night_commands() -> list[str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    found = re.findall(r'claude -p --permission-mode dontAsk "/review-close ([^"]+)"', text)
    return [c.replace("$run", "20261027T004526Z-8fcb").replace("<name>", "bot") for c in found]


def test_workflow_s_three_night_commands_parse_as_begin_accepts_them():
    cmds = _night_commands()
    assert len(cmds) == 3, cmds
    sets = [frozenset(close_arms.parse_flags(" ".join(shlex.quote(w) for w in c.split())))
            for c in cmds]
    assert all("--headless" in s for s in sets), sets
    assert any({"--land", "--unattended", "--agent", "--headless"} == s for s in sets), sets


def test_the_land_s_launcher_names_the_awaiting_subcommand():
    text = WORKFLOW.read_text(encoding="utf-8")
    block = re.search(r"run=\$\(python3 sysop/scripts/close_run\.py awaiting --agent <name>\) &&\s*"
                      r'claude -p --permission-mode dontAsk "/review-close --land \$run --headless'
                      r' --unattended --agent <name>"', text)
    assert block, "WORKFLOW.md's half-B recipe lost its awaiting → --land chain"


def test_the_headless_rule_is_in_the_unattended_land_s_own_section():
    sect = _section(LAND.read_text(encoding="utf-8"),
                    "### Under `--land <run-id> --unattended --agent <name>`")
    assert "**Under `--headless`**, a denied command is a failed one." in sect
    assert "before `landed` has printed, report the command on Step 8 and end the run" in sect
    assert ("From `landed` on, put that command and every Step 6 command after it on Step 8's "
            "`Remaining:` row as owed") in sect


def test_the_step_file_does_not_promise_a_reader_line_per_read():
    text = LAND.read_text(encoding="utf-8")
    assert "one `READER:` line per thing it read" not in text
    sect = _section(text, "### Under `--land <run-id> --unattended --agent <name>`")
    assert "(none on `ALREADY MERGED`)" in sect


def _flat(text: str) -> str:
    """One space for each whitespace run, so a re-wrap is not a change (lens B's X13)."""
    return re.sub(r"\s+", " ", text)


def test_step_6_lists_the_pending_docs_with_a_runnable_find():
    sect = _flat(_section(text_of(CORE), "## Step 6: Clean Up"))
    line = sect[sect.index("So: before cleaning up"):][:600]
    assert ("`find sysop/runtime/pending-docs/ -maxdepth 1 -type f -name '*.md'` (no output, or no "
            "such directory, is none)") in line, line
    assert "read each one's `branch:`" in line and "**exclude those branches from both lists below**" in line


def test_the_pre_flight_checks_the_scripts_with_a_runnable_find():
    """The shipped land's nights composed `ls sysop/scripts/ .claude/` for this check; the
    baseline prepare's own `find sysop/scripts -maxdepth 1 -type f` was admitted."""
    sect = _flat(_section(text_of(CORE), "## Pre-flight: Permission Guard"))
    line = sect[sect.index("**The scripts arrive the same way, so check them too.**"):][:400]
    assert "with `find sysop/scripts/ -maxdepth 1 -type f`." in line, line


def test_the_land_s_digest_only_lines_are_read_live():
    """Lens B's K13 and K15: each of these was guarded only by the step file's digest, which an
    editor recomputes."""
    text = _flat(LAND.read_text(encoding="utf-8"))
    assert ("`ALREADY MERGED` reads no reviewer, so its only `READER:` line says when GitHub merged "
            "a head other than the recorded one.") in text
    unattended = _flat(_section(LAND.read_text(encoding="utf-8"),
                                "### Under `--land <run-id> --unattended --agent <name>`"))
    assert ("If the command fails otherwise or is denied, record the branch and the error for "
            "Step 8's `Remaining:` row, and go on.") in unattended


def test_section_8_4_names_awaiting():
    """Lens B's F13: the script reference row is how a consumer learns the subcommand exists."""
    rows = [l for l in WORKFLOW.read_text(encoding="utf-8").splitlines()
            if l.startswith("| `close_run.py begin")]
    assert len(rows) == 1 and "`awaiting [--agent <name>]`" in rows[0]
