"""`/review-close` Step 4c item 5's post-write check, run exactly as the skill writes it.

`Q-569` (internal tracker #707): the Rotation check never said where §6's entries end,
so on a consumer whose §6 is the file's last section a rotation took the section's
trailing furniture as the tail of the last entry, deleted it from `PROJECT_STATUS.md`
and joined it onto a rotated changelog bullet, in one write. `Q-578` (#689): a close
that did not find a class heading near the top of `## [Unreleased]` created a second
one. Item 5 now runs a check before the pending-docs are deleted; these tests run that heredoc, extracted
by the shared extractor, against fixture repositories.

Every arm has a fixture that trips it and nothing else, because a control that moves
two arms at once cannot tell which one reported (the Phase 327 lesson).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _heredoc_population import heredoc_containing  # noqa: E402
import test_project_status_rotation as R  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL = REPO_ROOT / "core" / "skills" / "review-close" / "SKILL.md"
CHECK = heredoc_containing(SKILL, "KEEP, TRIGGER = ")

FURNITURE = [
    "(Older entries rotated to changelog.md)",
    "Note to Agents:",
    "Read vision.md for aesthetic constraints before modifying UI.",
    "Record completion in Recent Major Updates and move older history to changelog.md.",
]


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return env


def _entry(i: int, lead: str = "") -> str:
    return f"{lead}2026-09-{30 - i:02d}: TASK-{i:03d} Complete: summary number {i}"


def _new(lead: str = "") -> str:
    return f"{lead}2026-09-30: TASK-900 Complete: the entry this close wrote"


def _numbered_status(n: int) -> str:
    """The terminal-§6 shape of the report: plain numbered sections, blank-separated
    entries, then a rotated-to marker and a note to agents."""
    body = "".join(_entry(i) + "\n\n" for i in range(1, n + 1))
    return ("1. Project Overview\n\nstuff\n\n5. Current State\n\n## Status Tracking\n\nrows\n\n"
            "6. Recent Major Updates\n\n" + body + "\n" + "\n\n".join(FURNITURE) + "\n")


def _repo(tmp_path: Path, files: dict) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    for name, text in files.items():
        (repo / name).write_bytes(text if isinstance(text, bytes) else text.encode())
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True, env=_env())
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=_env())
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True, env=_env())
    return repo


def _run(repo: Path, cwd: Optional[Path] = None, **extra: str) -> tuple[int, str]:
    r = subprocess.run([sys.executable, "-"], input=CHECK, cwd=cwd or repo, capture_output=True,
                       text=True, env={**_env(), **extra})
    assert "Traceback" not in r.stderr, r.stderr
    return r.returncode, r.stdout


def _entry_lines(text: str) -> list[int]:
    return [i for i, l in enumerate(text.splitlines())
            if re.match(r"\s{0,3}(?:-\s+)?\d{4}-\d{2}-\d{2}:", l)]


def _rotate(text: str, new: str, keep_old: int) -> tuple[str, list[str]]:
    """The correct write: `new` above the first entry, the oldest leave from the bottom."""
    lines = text.splitlines()
    ents = _entry_lines(text)
    gone = [lines[i] for i in ents[keep_old:]]
    for i in reversed(ents[keep_old:]):
        del lines[i:i + 2]
    lines[ents[0]:ents[0]] = [new, ""]
    return "\n".join(lines) + "\n", gone


CHANGELOG = "# Project Changelog\n\n## [Unreleased]\n\n### Fixed\n- **X**: y (2026-09-01)\n"


def _problems(out: str) -> list[str]:
    return [l for l in out.splitlines() if l.startswith("PROBLEM: ")]


# ── the extraction itself ───────────────────────────────────────────────────


def test_the_check_is_extracted_from_the_skill():
    assert "def split6" in CHECK and CHECK.rstrip().endswith("sys.exit(1 if problems else 0)")


# ── §6: the write that must pass ────────────────────────────────────────────


def test_a_correct_rotation_on_the_terminal_section_shape_passes(tmp_path):
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(8), "changelog.md": CHANGELOG})
    text, gone = _rotate((repo / "PROJECT_STATUS.md").read_text(), _new(), keep_old=5)
    (repo / "PROJECT_STATUS.md").write_text(text)
    (repo / "changelog.md").write_text(
        CHANGELOG + "\n### Changed\n" + "".join(f"- {g[12:]} ({g[:10]})\n" for g in gone))
    code, out = _run(repo)
    assert code == 0, out
    assert "S6_ENTRIES: before 8 · added 1 · after 6 · expected 6" in out
    assert "ROTATED: 3" in out and "CHANGELOG: changelog.md" in out


def test_a_rotated_bullet_that_keeps_the_entrys_date_is_not_furniture(tmp_path):
    """Only non-entry lines are furniture. A rotated bullet that carries the whole §6 line,
    date included, is a format slip, not a loss, and must not stop the close as one."""
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(8), "changelog.md": CHANGELOG})
    text, gone = _rotate((repo / "PROJECT_STATUS.md").read_text(), _new(), keep_old=5)
    (repo / "PROJECT_STATUS.md").write_text(text)
    (repo / "changelog.md").write_text(CHANGELOG + "\n### Changed\n" + "".join(f"- {g}\n" for g in gone))
    code, out = _run(repo)
    assert code == 0 and not _problems(out), out


def test_a_list_shaped_section_under_the_threshold_passes(tmp_path):
    status = ("# Status\n\n> Living snapshot.\n\n## 6. Recent Major Updates\n\n"
              + "".join(_entry(i, "- ") + "\n" for i in range(1, 8)))
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text(status.replace(
        _entry(1, "- "), _new("- ") + "\n" + _entry(1, "- "), 1))
    code, out = _run(repo)
    assert code == 0, out
    assert "expected 8" in out and "ROTATED: 0" in out and "CHANGELOG: absent" in out


def test_a_new_entry_below_a_lead_in_line_passes(tmp_path):
    status = "## 6. Recent Major Updates\n\nNewest first.\n\n" + "".join(
        _entry(i, "- ") + "\n" for i in range(1, 4))
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text(status.replace(
        "Newest first.\n\n", "Newest first.\n\n" + _new("- ") + "\n", 1))
    code, out = _run(repo)
    assert code == 0, out


def test_neither_file_present_is_nothing_to_check(tmp_path):
    repo = _repo(tmp_path, {"README.md": "x\n"})
    code, out = _run(repo)
    assert code == 0 and "PROJECT_STATUS.md absent" in out and "CHANGELOG: absent" in out, out


# ── §6: each arm alone ──────────────────────────────────────────────────────


def test_the_reported_write_stops_the_close(tmp_path):
    """The #707 write: every blank-separated chunk after the heading taken as an entry,
    so the furniture rides the last one out of `PROJECT_STATUS.md` and into the changelog."""
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(8), "changelog.md": CHANGELOG})
    t = (repo / "PROJECT_STATUS.md").read_text()
    head, body = t.split("6. Recent Major Updates\n", 1)
    chunks = [c for c in body.split("\n\n") if c.strip()]
    ents = chunks[:8]
    ents[-1] += " " + " ".join(c.replace("\n", " ") for c in chunks[8:])
    new = [_new()] + ents
    (repo / "PROJECT_STATUS.md").write_text(
        head + "6. Recent Major Updates\n\n" + "\n\n".join(new[:6]) + "\n")
    (repo / "changelog.md").write_text(
        CHANGELOG + "".join(f"- {r[12:]} ({r[:10]})\n" for r in new[6:]))
    code, out = _run(repo)
    assert code == 1 and "RESULT: STOP" in out, out
    probs = "\n".join(_problems(out))
    for f in FURNITURE:
        assert f"removed {f[:80]!r}" in probs, out
    assert "changelog.md gained a line of §6's furniture" in probs, out


def test_furniture_lost_from_the_status_file_alone_stops(tmp_path):
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(3)})
    t = (repo / "PROJECT_STATUS.md").read_text()
    (repo / "PROJECT_STATUS.md").write_text(t.replace(FURNITURE[1] + "\n\n", "", 1))
    code, out = _run(repo)
    assert code == 1, out
    assert _problems(out) == [
        "PROBLEM: PROJECT_STATUS.md changed outside §6's entries: removed 'Note to Agents:'"], out


def test_furniture_copied_into_the_changelog_alone_stops(tmp_path):
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(3), "changelog.md": CHANGELOG})
    (repo / "changelog.md").write_text(CHANGELOG + f"- summary number 3 {FURNITURE[2]} (2026-09-27)\n")
    code, out = _run(repo)
    assert code == 1, out
    assert _problems(out) == [
        f"PROBLEM: changelog.md gained a line of §6's furniture: {FURNITURE[2]!r}"], out


def test_rotating_from_the_wrong_end_stops(tmp_path):
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(8)})
    lines = (repo / "PROJECT_STATUS.md").read_text().splitlines()
    ents = _entry_lines("\n".join(lines))
    for i in reversed(ents[:3]):
        del lines[i:i + 2]
    lines[ents[0]:ents[0]] = [_new(), ""]
    (repo / "PROJECT_STATUS.md").write_text("\n".join(lines) + "\n")
    code, out = _run(repo)
    assert code == 1, out
    assert _problems(out) == [
        "PROBLEM: §6's entries are not the new ones above the newest old ones, in order"], out


def test_a_rotation_that_leaves_the_wrong_count_stops(tmp_path):
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(8)})
    t = (repo / "PROJECT_STATUS.md").read_text()
    (repo / "PROJECT_STATUS.md").write_text(t.replace(_entry(1), _new() + "\n\n" + _entry(1), 1))
    code, out = _run(repo)
    assert code == 1, out
    assert _problems(out) == ["PROBLEM: §6 holds 9 entries; the Rotation check leaves 6"], out


def test_a_new_entry_above_a_lead_in_line_stops(tmp_path):
    status = "## 6. Recent Major Updates\n\nNewest first.\n\n" + "".join(
        _entry(i, "- ") + "\n" for i in range(1, 4))
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text(status.replace(
        "Updates\n\n", "Updates\n\n" + _new("- ") + "\n", 1))
    code, out = _run(repo)
    assert code == 1 and "changed outside §6's entries" in out, out


# ── the changelog's class headings ──────────────────────────────────────────


def test_a_heading_this_close_forked_stops(tmp_path):
    repo = _repo(tmp_path, {"changelog.md": CHANGELOG + "\n### Changed\n- b (2)\n"})
    (repo / "changelog.md").write_text(
        CHANGELOG + "\n### Changed\n- b (2)\n\n### Fixed\n- **NEW**: x (2026-09-30)\n")
    code, out = _run(repo)
    assert code == 1, out
    assert _problems(out) == [
        "PROBLEM: '### Fixed' appears 2 times under [Unreleased] (lines 5, 11)"], out


def test_a_fork_the_file_already_had_only_warns(tmp_path):
    forked = ("# Project Changelog\n\n## [Unreleased]\n\n### Fixed\n- a (1)\n\n### Changed\n- b (2)\n"
              "\n### Changed\n- d (4)\n\n## August 2026\n\n### Changed\n- e\n")
    repo = _repo(tmp_path, {"changelog.md": forked})
    (repo / "changelog.md").write_text(forked.replace("### Fixed\n", "### Fixed\n- **NEW**: x (9)\n", 1))
    code, out = _run(repo)
    assert code == 0 and not _problems(out), out
    assert ("WARN: '### Changed' appears 2 times under [Unreleased] (lines 9, 12) — the file "
            "already had this; report it, do not fix it here") in out, out
    assert "August" not in out, "a heading below the next `## ` is not under [Unreleased]"


def test_a_second_unreleased_section_this_close_made_stops(tmp_path):
    repo = _repo(tmp_path, {"CHANGELOG.md": CHANGELOG})
    (repo / "CHANGELOG.md").write_text(CHANGELOG + "\n## [Unreleased]\n\n### Added\n- n (1)\n")
    code, out = _run(repo)
    assert code == 1, out
    assert _problems(out) == ["PROBLEM: CHANGELOG.md has 2 '## [Unreleased]' sections"], out


def test_a_changelog_created_this_close_is_checked(tmp_path):
    repo = _repo(tmp_path, {"README.md": "x\n"})
    (repo / "CHANGELOG.md").write_text(CHANGELOG + "\n### Fixed\n- again (2)\n")
    code, out = _run(repo)
    assert code == 1 and "'### Fixed' appears 2 times" in out, out


# ── what the check cannot judge ─────────────────────────────────────────────


def test_an_undecodable_file_is_unchecked_not_passed(tmp_path):
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(2)})
    with open(repo / "PROJECT_STATUS.md", "ab") as f:
        f.write(b"\xff\n")
    code, out = _run(repo)
    assert code == 2 and out.startswith("RESULT: UNCHECKED — PROJECT_STATUS.md could not be read"), out


def test_a_section_the_check_cannot_find_is_unchecked(tmp_path):
    status = _numbered_status(2).replace("Recent Major Updates", "Recent Updates")
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    code, out = _run(repo)
    assert code == 2 and "0 'Recent Major Updates' headings" in out, out


def test_a_prose_mention_of_the_section_is_not_its_heading(tmp_path):
    """The note-to-agents line names the section; only a heading-shaped line is §6. A
    lead-in that OPENS with the section's name is prose too, which the end-of-line anchor
    is for: without it the file has two headings and the check gives up."""
    status = _numbered_status(2).replace(
        "6. Recent Major Updates\n\n", "6. Recent Major Updates\n\nRecent Major Updates are listed newest first.\n\n")
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    code, out = _run(repo)
    assert code == 0 and "S6_ENTRIES: before 2" in out, out


def test_an_empty_section_does_not_borrow_a_later_sections_dated_lines(tmp_path):
    """§6's first entry is looked for only up to the next section. Past it, a dated line
    belongs to another section, and taking it as §6's first entry would turn the close's
    first real entry into a change outside §6."""
    status = "6. Recent Major Updates\n\n7. Releases\n\n2026-08-01: v1 shipped\n"
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text(status.replace(
        "Updates\n\n", "Updates\n\n" + _new() + "\n\n", 1))
    code, out = _run(repo)
    assert code == 0 and "S6_ENTRIES: before 0 · added 1 · after 1 · expected 1" in out, out


def test_a_status_file_this_close_created_is_checked_without_a_before(tmp_path):
    repo = _repo(tmp_path, {"README.md": "x\n"})
    (repo / "PROJECT_STATUS.md").write_text("## 6. Recent Major Updates\n\n" + _new("- ") + "\n")
    code, out = _run(repo)
    assert code == 0 and "S6_ENTRIES: before 0 · added 1 · after 1 · expected 1" in out, out


# ── the hostile corpus (author-side rule 4): what other writers leave in these files ──


def test_line_endings_and_trailing_spaces_an_editor_changes_are_not_losses(tmp_path):
    """A consumer file committed with CRLF and trailing spaces, rewritten by an editor that
    writes LF and trims: every line is still there, so nothing is lost."""
    crlf = _numbered_status(3).replace(FURNITURE[1], FURNITURE[1] + "   ").replace("\n", "\r\n")
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": crlf.encode()})
    lf = crlf.replace("\r\n", "\n").replace(FURNITURE[1] + "   ", FURNITURE[1])
    (repo / "PROJECT_STATUS.md").write_text(lf.replace(_entry(1), _new() + "\n\n" + _entry(1), 1))
    code, out = _run(repo)
    assert code == 0 and not _problems(out), out


def _wrapped_status() -> str:
    """Eight list entries; the oldest-but-one is wrapped onto an indented second line."""
    lines = []
    for i in range(1, 9):
        lines.append(_entry(i, "- "))
        if i == 7:
            lines.append("  wrapped tail of entry 7")
    return "## 6. Recent Major Updates\n\n" + "\n".join(lines) + "\n\nNote to Agents: keep it short.\n"


@pytest.mark.parametrize("indent", ["  ", "\t"])
@pytest.mark.parametrize("state", ["at HEAD", "on disk"])
def test_an_indented_line_under_an_entry_is_unchecked(tmp_path, indent, state):
    """Wade's decision after round 3 (2026-09-27). Round 1's rule ended an entry at its first
    line, and round 2 found a wrapped entry split by the prescribed rotation, with the check
    passing it. Round 2's rule carried an indented line with its entry, and round 3 found
    indented furniture under the last entry riding out with it, the lossy write the only one that
    passed. The check cannot tell the two apart, so it says so, in either version of the file."""
    status = _wrapped_status().replace("  wrapped tail", indent + "wrapped tail")
    plain = status.replace("\n" + indent + "wrapped tail of entry 7", "")
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status if state == "at HEAD" else plain})
    (repo / "PROJECT_STATUS.md").write_text(status if state == "on disk" else plain)
    code, out = _run(repo)
    assert code == 2 and f"PROJECT_STATUS.md {state}, line" in out and "indented directly under" in out, out


def test_indented_furniture_under_the_last_entry_is_unchecked(tmp_path):
    """Round 3's shape: a marker indented under the last entry. Under round 2's rule the only
    write that passed deleted it."""
    status = "## 6. Recent Major Updates\n\n" + "".join(_entry(i, "- ") + "\n" for i in range(1, 9)) + "  " + FURNITURE[0] + "\n"
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    kept = [_new("- ")] + [_entry(i, "- ") for i in range(1, 6)]
    (repo / "PROJECT_STATUS.md").write_text("## 6. Recent Major Updates\n\n" + "\n".join(kept) + "\n")
    assert _run(repo)[0] == 2


def test_an_indented_line_after_a_blank_is_furniture(tmp_path):
    """Only a line DIRECTLY under an entry is ambiguous; after a blank line it is a block of its own."""
    status = "## 6. Recent Major Updates\n\n" + "".join(_entry(i, "- ") + "\n" for i in range(1, 4)) + "\n  (an indented note)\n"
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text(status.replace(_entry(1, "- "), _new("- ") + "\n" + _entry(1, "- "), 1))
    code, out = _run(repo)
    assert code == 0 and "before 3 · added 1 · after 4" in out, out


def test_an_unindented_line_under_the_last_entry_ends_the_run(tmp_path):
    """The shape the reported defect needs: a marker written straight after the last entry,
    with no blank line and no indent, is furniture and never rides out with the entry."""
    status = "## 6. Recent Major Updates\n\n" + "".join(_entry(i, "- ") + "\n" for i in range(1, 9)) + FURNITURE[0] + "\n"
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    kept = [_new("- ")] + [_entry(i, "- ") for i in range(1, 6)]
    (repo / "PROJECT_STATUS.md").write_text("## 6. Recent Major Updates\n\n" + "\n".join(kept) + "\n")
    code, out = _run(repo)
    assert code == 1 and f"removed {FURNITURE[0]!r}" in out, out


def test_a_heading_inside_a_code_fence_is_not_a_heading(tmp_path):
    """Round 1 (lens 3): with the fenced `### Fixed` the only one under [Unreleased], a correct
    bugfix close creates the real heading, and a fence-blind count stopped it as a fork."""
    log = ("# C\n\n## [Unreleased]\n\n### Changed\n- **Y**: example below (2026-09-02)\n\n"
           "```markdown\n### Fixed\n```\n")
    repo = _repo(tmp_path, {"changelog.md": log})
    (repo / "changelog.md").write_text(log + "\n### Fixed\n- **N**: new (2026-09-30)\n")
    code, out = _run(repo)
    assert code == 0 and not _problems(out) and "WARN" not in out, out


# ── round 1's survivors: one fixture per arm the first tests did not reach ──────────


def _write_rotated(repo: Path, n_old: int, keep_old: int, lead: str = "") -> None:
    text, _ = _rotate((repo / "PROJECT_STATUS.md").read_text(), _new(lead), keep_old=keep_old)
    (repo / "PROJECT_STATUS.md").write_text(text)


def test_star_bullets_are_entries(tmp_path):
    status = "## 6. Recent Major Updates\n\n" + "".join(_entry(i, "* ") + "\n" for i in range(1, 4))
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text(status.replace(_entry(1, "* "), _new("* ") + "\n" + _entry(1, "* "), 1))
    assert _run(repo)[0] == 0


def test_a_dated_line_with_no_colon_is_furniture(tmp_path):
    """Directly after the last entry, where the run would take it as the oldest entry and
    rotate it, if the colon were not part of an entry's shape."""
    status = _numbered_status(8).replace(FURNITURE[0], "2026-09-01 release notes live in docs/.")
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    _write_rotated(repo, 8, keep_old=5)
    code, out = _run(repo)
    assert code == 0 and "before 8 · added 1 · after 6" in out, out


def test_the_heading_is_found_in_any_case(tmp_path):
    status = _numbered_status(3).replace("Recent Major Updates", "Recent major updates", 1)
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text(status.replace(FURNITURE[1] + "\n", "", 1))
    assert _run(repo)[0] == 1


def test_two_section_headings_are_unchecked(tmp_path):
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(2) + "\n## 6. Recent Major Updates\n"})
    code, out = _run(repo)
    assert code == 2 and "2 'Recent Major Updates' headings" in out, out


@pytest.mark.parametrize("inner", ["### September 2026", "1. Newest first; older ones live in the changelog."])
def test_a_subheading_or_numbered_lead_in_above_the_entries_stays_inside_the_section(tmp_path, inner):
    """Round 1 (lens 1): the first cut stopped looking for §6's first entry at ANY heading or
    numbered line, took every entry as furniture, and reported the close's own entry as `added`."""
    status = f"## 6. Recent Major Updates\n\n{inner}\n\n" + "".join(_entry(i, "- ") + "\n" for i in range(1, 4))
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text(status.replace(_entry(1, "- "), _new("- ") + "\n" + _entry(1, "- "), 1))
    code, out = _run(repo)
    assert code == 0 and "before 3 · added 1 · after 4" in out, out


def test_a_higher_heading_after_an_empty_section_ends_it(tmp_path):
    status = "## 6. Recent Major Updates\n\n# Appendix\n\n2026-08-01: not an update\n"
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text(status.replace("Updates\n\n", "Updates\n\n" + _new() + "\n\n", 1))
    code, out = _run(repo)
    assert code == 0 and "before 0 · added 1 · after 1" in out, out


@pytest.mark.parametrize("gone", ["Newest first.", "stuff"])
def test_a_line_lost_before_the_entries_stops(tmp_path, gone):
    """A lead-in inside §6, or a line in another section: both are before the entry run."""
    status = _numbered_status(3).replace("6. Recent Major Updates\n\n", "6. Recent Major Updates\n\nNewest first.\n\n")
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text(status.replace(gone + "\n", "", 1))
    code, out = _run(repo)
    assert code == 1 and f"removed {gone!r}" in out, out


def test_a_lead_in_lost_from_an_empty_section_stops(tmp_path):
    status = "## 6. Recent Major Updates\n\nNewest first.\n"
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text("## 6. Recent Major Updates\n\n" + _new("- ") + "\n")
    assert _run(repo)[0] == 1


def test_reordered_furniture_stops(tmp_path):
    status = _numbered_status(3)
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    swapped = status.replace(FURNITURE[2], "\x00").replace(FURNITURE[3], FURNITURE[2]).replace("\x00", FURNITURE[3])
    (repo / "PROJECT_STATUS.md").write_text(swapped)
    code, out = _run(repo)
    assert code == 1 and "lines reordered" in out, out


def test_swapped_old_entries_stop(tmp_path):
    status = _numbered_status(3)
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text(
        status.replace(_entry(2), "\x00").replace(_entry(3), _entry(2)).replace("\x00", _entry(3)))
    assert _run(repo)[0] == 1


@pytest.mark.parametrize("n,keep_old,why", [
    (8, 4, "over-rotated to 5"),
    (3, 2, "oldest deleted below the threshold"),
    (10, 10, "already over the threshold at HEAD, not rotated"),
])
def test_every_wrong_count_stops(tmp_path, n, keep_old, why):
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(n)})
    _write_rotated(repo, n, keep_old)
    code, out = _run(repo)
    assert code == 1 and "the Rotation check leaves" in out, f"{why}: {out}"


@pytest.mark.parametrize("which", range(len(FURNITURE)))
def test_any_furniture_line_copied_onto_the_first_rotated_bullet_stops(tmp_path, which):
    """Each line, the 39-character marker included, and on the FIRST new bullet, with the
    furniture still present in `PROJECT_STATUS.md`: only the changelog arm can see it."""
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(3), "changelog.md": CHANGELOG})
    (repo / "changelog.md").write_text(
        CHANGELOG + f"- summary number 3 {FURNITURE[which]} (2026-09-27)\n- summary number 2 (2026-09-28)\n")
    code, out = _run(repo)
    assert code == 1 and "gained a line of §6's furniture" in out, out


def test_damage_the_changelog_already_had_is_not_this_closes(tmp_path):
    log = CHANGELOG + f"- old {FURNITURE[2]} (2026-08-01)\n"
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(3), "changelog.md": log})
    (repo / "changelog.md").write_text(log + "- **N**: new (2026-09-30)\n")
    assert _run(repo)[0] == 0


def test_a_changelog_that_lost_lines_stops(tmp_path):
    """Round 1 (lens 1): only gained lines were read, so deleting bullets passed."""
    log = CHANGELOG + "- **Z**: z (2026-09-03)\n"
    repo = _repo(tmp_path, {"changelog.md": log})
    (repo / "changelog.md").write_text(CHANGELOG.replace("- **X**: y (2026-09-01)\n", "") + "- **N**: n (9)\n")
    code, out = _run(repo)
    assert code == 1 and "changelog.md lost 2 line(s)" in out, out


@pytest.mark.parametrize("name", ["fixed", "Security"])
def test_a_fork_of_any_class_in_any_case_stops(tmp_path, name):
    log = f"# C\n\n## [Unreleased]\n\n### {name}\n- a (1)\n"
    repo = _repo(tmp_path, {"CHANGELOG.md": log})
    (repo / "CHANGELOG.md").write_text(log + f"\n### {name.title()}\n- b (2)\n")
    assert _run(repo)[0] == 1


def test_an_unreleased_heading_with_trailing_text_is_still_it(tmp_path):
    log = "# C\n\n## [Unreleased] <!-- next -->\n\n### Fixed\n- a (1)\n"
    repo = _repo(tmp_path, {"CHANGELOG.md": log})
    (repo / "CHANGELOG.md").write_text(log + "\n### Fixed\n- b (2)\n")
    assert _run(repo)[0] == 1


def test_a_duplicate_unreleased_the_file_already_had_warns(tmp_path):
    log = CHANGELOG + "\n## [Unreleased]\n\n### Added\n- n (1)\n"
    repo = _repo(tmp_path, {"CHANGELOG.md": log})
    (repo / "CHANGELOG.md").write_text(log.replace("- **X**", "- **N**: new (9)\n- **X**", 1))
    code, out = _run(repo)
    assert code == 0 and "WARN: CHANGELOG.md has 2 '## [Unreleased]' sections" in out, out


def test_the_fork_is_judged_in_the_first_unreleased(tmp_path):
    log = CHANGELOG + "\n## [Unreleased]\n\n### Added\n- n (1)\n"
    repo = _repo(tmp_path, {"CHANGELOG.md": log})
    (repo / "CHANGELOG.md").write_text(log.replace("- **X**: y (2026-09-01)\n",
                                                   "- **X**: y (2026-09-01)\n\n### Fixed\n- b (2)\n", 1))
    code, out = _run(repo)
    assert code == 1 and "'### Fixed' appears 2 times" in out, out


def test_two_tracked_changelogs_are_unchecked(tmp_path):
    repo = _repo(tmp_path, {"CHANGELOG.md": CHANGELOG})
    blob = subprocess.run(["git", "hash-object", "-w", "CHANGELOG.md"], cwd=repo, capture_output=True,
                          text=True, env=_env(), check=True).stdout.strip()
    subprocess.run(["git", "update-index", "--add", "--cacheinfo", f"100644,{blob},changelog.md"],
                   cwd=repo, check=True, env=_env())
    code, out = _run(repo)
    assert code == 2 and "more than one tracked changelog" in out, out


def test_non_ascii_text_is_read_as_utf8(tmp_path):
    status = _numbered_status(3).replace(FURNITURE[1], "Note to Agents — see § 4:")
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text(status.replace(_entry(1), _new() + "\n\n" + _entry(1), 1))
    assert _run(repo)[0] == 0


# ── where the check runs from, and what it is handed ──────────────────────────


def _lossy(tmp_path: Path) -> Path:
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(3), "changelog.md": CHANGELOG})
    (repo / "PROJECT_STATUS.md").write_text(_numbered_status(3).replace(FURNITURE[1] + "\n", "", 1))
    return repo


def test_a_run_from_a_subdirectory_still_sees_the_loss(tmp_path):
    repo = _lossy(tmp_path)
    (repo / "sub").mkdir()
    assert _run(repo, cwd=repo / "sub")[0] == 1


def test_an_inherited_git_dir_is_not_read(tmp_path):
    repo = _lossy(tmp_path / "a")
    other = _repo(tmp_path / "b", {"README.md": "x\n"})
    assert _run(repo, GIT_DIR=str(other / ".git"))[0] == 1


def test_a_git_read_that_fails_is_unchecked_not_passed(tmp_path):
    """Round 1 (lens 2): any failed `git show` read as 'not at HEAD', skipped the comparison
    and passed over the loss. HEAD's tree object is removed, so the repository still resolves
    and only the read of HEAD fails: a bogus object directory fails `--show-toplevel` first and
    never reaches the read, which is how this test's first version passed a mutant."""
    repo = _lossy(tmp_path)
    tree = subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=repo, capture_output=True,
                          text=True, env=_env(), check=True).stdout.strip()
    (repo / ".git" / "objects" / tree[:2] / tree[2:]).unlink()
    code, out = _run(repo)
    assert code == 2 and "git could not list HEAD" in out, out


@pytest.mark.parametrize("name", ["PROJECT_STATUS.md", "changelog.md"])
def test_a_deleted_file_stops(tmp_path, name):
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(3), "changelog.md": CHANGELOG})
    (repo / name).unlink()
    code, out = _run(repo)
    assert code == 1 and f"{name} was deleted" in out, out


def test_a_non_utf8_locale_does_not_crash_the_report(tmp_path):
    """Round 1 (lens 1): `·`, `—` and `§` raised on an ASCII stdout, and the traceback's exit 1
    read as STOP."""
    repo = _lossy(tmp_path)
    r = subprocess.run([sys.executable, "-"], input=CHECK.encode(), cwd=repo, capture_output=True,
                       env={**_env(), "LC_ALL": "en_US.US-ASCII", "LANG": "en_US.US-ASCII",
                            "PYTHONIOENCODING": "ascii", "PYTHONUTF8": "0"})
    assert b"Traceback" not in r.stderr, r.stderr
    assert r.returncode == 1 and b"RESULT: STOP" in r.stdout, r.stdout


# ── round 2's survivors (lens 4's independent mutations, one fixture each) ─────────


def test_a_failed_show_after_a_good_listing_is_unchecked(tmp_path):
    """A6: HEAD's tree lists the file but its blob is gone, so `ls-tree` passes and only `git
    show` fails. The earlier git-failure test removed the tree, which fails first."""
    repo = _lossy(tmp_path)
    blob = subprocess.run(["git", "rev-parse", "HEAD:PROJECT_STATUS.md"], cwd=repo, capture_output=True,
                          text=True, env=_env(), check=True).stdout.strip()
    (repo / ".git" / "objects" / blob[:2] / blob[2:]).unlink()
    code, out = _run(repo)
    assert code == 2 and "git could not read HEAD:PROJECT_STATUS.md" in out, out


def test_outside_a_repository_is_unchecked(tmp_path):
    """A5: no repository at all is exit 2, not a traceback."""
    d = tmp_path / "plain"
    d.mkdir()
    code, out = _run(d, GIT_CEILING_DIRECTORIES=str(tmp_path))
    assert code == 2 and "not inside a git work tree" in out, out


@pytest.mark.parametrize("var", ["GIT_WORK_TREE", "GIT_INDEX_FILE"])
def test_every_inherited_git_location_is_ignored(tmp_path, var):
    """A4: only GIT_DIR was tested; the other discovery variables are stripped too."""
    repo = _lossy(tmp_path / "a")
    other = _repo(tmp_path / "b", {"README.md": "x\n"})
    value = str(other) if var == "GIT_WORK_TREE" else str(other / ".git" / "index")
    assert _run(repo, **{var: value})[0] == 1


def test_one_lost_changelog_line_stops(tmp_path):
    """A27: the commonest loss is one dropped bullet."""
    log = CHANGELOG + "- **Z**: z (2026-09-03)\n"
    repo = _repo(tmp_path, {"changelog.md": log})
    (repo / "changelog.md").write_text(CHANGELOG)
    code, out = _run(repo)
    assert code == 1 and "lost 1 line(s)" in out, out


def test_trimmed_trailing_spaces_in_the_changelog_are_not_a_loss(tmp_path):
    """A17."""
    log = CHANGELOG.replace("(2026-09-01)", "(2026-09-01)   ")
    repo = _repo(tmp_path, {"changelog.md": log})
    (repo / "changelog.md").write_text(CHANGELOG + "- **N**: n (9)\n")
    assert _run(repo)[0] == 0


def test_an_entry_deleted_with_nothing_added_stops(tmp_path):
    """A31: a close that adds nothing to §6 and still removes an entry."""
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(4)})
    (repo / "PROJECT_STATUS.md").write_text(_numbered_status(4).replace(_entry(4) + "\n\n", "", 1))
    assert _run(repo)[0] == 1


@pytest.mark.parametrize("n,keep_old,want", [(10, 5, 0), (20, 20, 1)])
def test_the_count_rule_holds_far_from_the_threshold(tmp_path, n, keep_old, want):
    """A13 and A14: 10 + 1 rotated to 6 is right; 20 + 1 left unrotated is not."""
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(n)})
    _write_rotated(repo, n, keep_old)
    assert _run(repo)[0] == want


def test_an_entry_identical_to_an_old_one_counts_as_added(tmp_path):
    """A12: the same text twice is two entries."""
    status = _numbered_status(3)
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text(status.replace(_entry(1), _entry(1) + "\n\n" + _entry(1), 1))
    code, out = _run(repo)
    assert code == 0 and "before 3 · added 1 · after 4" in out, out


def test_a_fork_far_down_a_long_unreleased_stops(tmp_path):
    """A20: the reported shape is a heading made hundreds of lines below `[Unreleased]`."""
    bullets = "".join(f"- **T{i}**: t (2026-08-01)\n" for i in range(300))
    log = "# C\n\n## [Unreleased]\n\n### Added\n" + bullets + "\n## [1.0.0] - 2026-01-01\n"
    repo = _repo(tmp_path, {"CHANGELOG.md": log})
    (repo / "CHANGELOG.md").write_text(log.replace("\n## [1.0.0]", "\n### Added\n- **N**: n (9)\n\n## [1.0.0]", 1))
    assert _run(repo)[0] == 1


@pytest.mark.parametrize("fence,closer", [("```", "```"), ("~~~", "~~~"), ("````", "````")])
def test_a_fork_after_a_closed_fence_still_stops(tmp_path, fence, closer):
    """A15, A2: a closed fence of either character hides nothing after it."""
    log = CHANGELOG + f"\n{fence}text\n### Fixed\n{closer}\n"
    repo = _repo(tmp_path, {"CHANGELOG.md": log})
    (repo / "CHANGELOG.md").write_text(log + "\n### Fixed\n- again (2)\n")
    code, out = _run(repo)
    assert code == 1 and "'### Fixed' appears 2 times" in out, out


def test_a_fence_closes_only_on_its_own_kind(tmp_path):
    """Round 2 (lens 4): a ```` fence holding a ``` example, then a `### Fixed` inside it. The
    inner ``` does not close the outer fence, so the example's heading stays fenced and the
    close's real `### Fixed` is the only one."""
    log = ("# C\n\n## [Unreleased]\n\n### Changed\n- **Y**: example (1)\n\n````markdown\n```\n### Fixed\n```\n"
           "### Fixed\n````\n")
    repo = _repo(tmp_path, {"CHANGELOG.md": log})
    (repo / "CHANGELOG.md").write_text(log + "\n### Fixed\n- **N**: new (9)\n")
    code, out = _run(repo)
    assert code == 0 and "WARN" not in out, out


@pytest.mark.parametrize("where", ["above", "inside"])
def test_fenced_level_two_headings_do_not_move_unreleased(tmp_path, where):
    """A16, A21: a fenced `## [Unreleased]` example above the real one, or a fenced `## x`
    inside it, is neither the section nor its end."""
    example = "```\n## [Unreleased]\n```\n" if where == "above" else ""
    inside = "```\n## x\n```\n" if where == "inside" else ""
    log = f"# C\n\n{example}## [Unreleased]\n\n### Fixed\n- a (1)\n{inside}\n### Changed\n- b (2)\n"
    repo = _repo(tmp_path, {"CHANGELOG.md": log})
    (repo / "CHANGELOG.md").write_text(log + "\n### Fixed\n- again (3)\n")
    code, out = _run(repo)
    assert code == 1 and "'### Fixed' appears 2 times" in out, out


@pytest.mark.parametrize("heading,successor", [
    ("## 6. Recent Major Updates", "## Releases"),       # A8: a same-level heading ends it
    ("6. Recent Major Updates", "## Appendix"),          # A7: a plain §6 ends at level 2
    ("### 6. Recent Major Updates", "### Releases"),     # A29, A30: a level-3 §6
])
def test_an_empty_section_ends_at_its_successor(tmp_path, heading, successor):
    status = f"{heading}\n\n{successor}\n\n2026-08-01: not an update\n"
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text(status.replace(heading + "\n\n", heading + "\n\n" + _new() + "\n\n", 1))
    code, out = _run(repo)
    assert code == 0 and "before 0 · added 1 · after 1" in out, out


def test_a_level_three_section_is_found(tmp_path):
    """A29: `### 6.` is a heading like any other."""
    status = "### 6. Recent Major Updates\n\n" + _entry(1, "- ") + "\n\nNote to Agents: short.\n"
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    (repo / "PROJECT_STATUS.md").write_text(status.replace("Note to Agents: short.\n", ""))
    assert _run(repo)[0] == 1


def test_a_later_sections_line_in_a_new_bullet_is_not_s6_furniture(tmp_path):
    """A10: only §6's own lines count as furniture for the changelog arm."""
    status = _numbered_status(3) + "\n7. Releases\n\nThe release train leaves on Fridays.\n"
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status, "changelog.md": CHANGELOG})
    (repo / "changelog.md").write_text(CHANGELOG + "- **N**: The release train leaves on Fridays. (9)\n")
    assert _run(repo)[0] == 0


def test_a_lead_in_joined_onto_a_bullet_stops(tmp_path):
    """A11: a lead-in above the entries is §6 furniture too."""
    status = _numbered_status(3).replace("6. Recent Major Updates\n\n", "6. Recent Major Updates\n\nNewest first, one line per close.\n\n")
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status, "changelog.md": CHANGELOG})
    (repo / "changelog.md").write_text(CHANGELOG + "- **N**: n Newest first, one line per close. (9)\n")
    assert _run(repo)[0] == 1


def test_a_four_space_dated_line_is_not_an_entry(tmp_path):
    """A1: past three spaces a line is code, not an entry, even when it starts with a date."""
    status = _numbered_status(8).replace(FURNITURE[0], "    2026-01-01: an example in a code block")
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": status})
    _write_rotated(repo, 8, keep_old=5)
    code, out = _run(repo)
    assert code == 0 and "before 8 · added 1 · after 6" in out, out


def test_furniture_on_a_star_bullet_stops(tmp_path):
    """A32."""
    repo = _repo(tmp_path, {"PROJECT_STATUS.md": _numbered_status(3), "changelog.md": CHANGELOG})
    (repo / "changelog.md").write_text(CHANGELOG + f"* summary {FURNITURE[2]} (9)\n")
    assert _run(repo)[0] == 1


# ── round 3: the fence rules, each half on its own ───────────────────────────────


_TOP = "# C\n\n## [Unreleased]\n\n### Changed\n- a (1)\n\n"
_NEW_FIXED = "\n### Fixed\n- n (9)\n"


@pytest.mark.parametrize("why,fenced,want", [
    # The example's `### Fixed` stays fenced, so the close's real one is the first: exit 0.
    ("a closer of the other character does not close", "```text\n~~~\n### Fixed\n```\n", 0),
    ("a closer with an info string does not close", "```\n```text\n### Fixed\n```\n", 0),
    ("an opener indented up to three spaces is a fence", "   ```\n### Fixed\n   ```\n", 0),
    # The fence closes, or never opens, so the `### Fixed` below is live: the close forks it.
    ("a longer closer closes", "```\n### x\n````\n\n### Fixed\n- b (2)\n", 1),
    ("a closer with trailing spaces closes", "```\n### x\n```   \n\n### Fixed\n- b (2)\n", 1),
    ("two backticks are not a fence", "``\n### Fixed\n``\n", 1),
    ("a backtick opener whose info string has a backtick is not a fence", "```x``` is the new name\n### Fixed\n", 1),
    ("a tab-indented opener is code, not a fence", "\t```\n### Fixed\n\t```\n", 1),
])
def test_each_commonmark_fence_rule(tmp_path, why, fenced, want):
    """The close's heading goes ABOVE the fenced block: appended below it, a mutant whose fence
    closed early reopens one on the block's last marker line and swallows the new heading, which
    is how this test's first version passed two mutants of the closer."""
    log = _TOP + fenced
    repo = _repo(tmp_path, {"CHANGELOG.md": log})
    (repo / "CHANGELOG.md").write_text(_TOP + _NEW_FIXED.lstrip("\n") + "\n" + fenced)
    code, out = _run(repo)
    assert code == want, f"{why}: {out}"


# ── the check agrees with the prose it enforces ─────────────────────────────


def _prose_numbers() -> tuple[int, int]:
    lines = R._lines()
    lo, hi = R._step_4c_bounds(lines)
    rot = R._logical_clause(lines, lo, hi, R.ROTATION_ANCHOR)
    trigger = R._only_number(rot, R._MORE_THAN + r" entries", "rotation trigger")
    keep = R._only_number(rot, r"only " + R._NUM + r" remain", "retained count")
    return keep, trigger


def test_the_check_enforces_the_rotation_checks_numbers(tmp_path):
    """Behaviour, not a line of text (round 1, lens 2: a second `KEEP, TRIGGER` line, or numbers
    hard-coded where they are used, kept a text comparison green while the check enforced others).
    The prose's own numbers build three writes; the check must pass the two the prose prescribes
    and stop the one it forbids."""
    keep, trigger = _prose_numbers()
    cases = [
        (trigger, keep - 1, 0),       # over the trigger, rotated down to `keep`: correct
        (trigger - 1, trigger - 1, 0),  # reaches the trigger exactly: no rotation, correct
        (trigger, trigger, 1),        # over the trigger and not rotated: forbidden
    ]
    for i, (n, keep_old, want) in enumerate(cases):
        repo = _repo(tmp_path / str(i), {"PROJECT_STATUS.md": _numbered_status(n)})
        text, _ = _rotate((repo / "PROJECT_STATUS.md").read_text(), _new(), keep_old=keep_old)
        (repo / "PROJECT_STATUS.md").write_text(text)
        code, out = _run(repo)
        assert code == want, f"n={n} kept={keep_old}: {out}"


def _only_line_with(lines, phrase, lo, hi):
    hits = [i for i in range(lo, hi) if phrase in lines[i]]
    assert len(hits) == 1, f"{phrase!r} found on lines {hits} inside Step 4c"
    return hits[0]


def test_the_check_runs_after_every_write_and_before_cleanup_and_staging():
    """Where the CODE sits, not its lead-in (round 1, lens 2 moved the heredoc and left the
    paragraph), and keyed to no item number (a renumber is a legal edit)."""
    lines = R._lines()
    lo, hi = R._step_4c_bounds(lines)
    code = _only_line_with(lines, "KEEP, TRIGGER = ", lo, hi)
    for writer in ("**Rotation check**:", "**CHANGELOG.md** (bugfix type only",
                   "**UI_Iterations.md** (ui-iteration type only)", "python3 sysop/scripts/validate_tasks.py ||"):
        assert _only_line_with(lines, writer, lo, hi) < code, f"{writer} runs after the check"
    assert code < _only_line_with(lines, "**Clean up pending-docs**", lo, hi), (
        "the check must run before the pending-docs are deleted: a doc is its entry's only other copy")
    assert code < _only_line_with(lines, "git add PROJECT_STATUS.md                 # every type", lo, hi)
