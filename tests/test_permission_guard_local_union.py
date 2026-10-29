"""Every skill's permission guard reads `settings.local.json` too.

`_shared/permission-guard.md` § Algorithm step 2 unions `permissions.allow` across
`.claude/settings.json` and `.claude/settings.local.json`: allow-rules are additive, and a
rule a consumer keeps only in the local file is in force. A guard sentence that reads the
shared file alone reports that rule missing and hard-stops a run that would have worked.
Phase 326 found the class at twelve skills, not the three its note named, and missed
`/release` on its own first sweep because that guard sentence sits mid-paragraph — so the
population here is every occurrence in the text, not every line that starts with one.

Round 2 widened it: the first cut matched only a capitalised `Read`, and its window ran to
the next `confirm`, which false-killed a union named later in the same sentence. The
window is now the sentence, and the verb set is the four a guard sentence uses.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS = REPO_ROOT / "core" / "skills"
GUARD = re.compile(r"(?i)\b(?:read|check|verify|inspect)\b[^.\n]{0,40}\.claude/settings\.json")
# 22 at Phase 326: fifteen `Read … and confirm` sentences plus seven `verify … carries`
# intros. Exact, so a guard that joins or leaves the population is a visible edit here.
POPULATION = 22


def sentence_from(text: str, start: int) -> str:
    """From `start` to the end of its sentence: a full stop, a colon ending a line, or a
    blank line, whichever comes first."""
    rest = text[start:]
    ends = [i for i in (rest.find(". "), rest.find(".\n"), rest.find(":\n"), rest.find("\n\n"))
            if i != -1]
    return rest[:min(ends)] if ends else rest


def guard_reads(text: str) -> list[str]:
    return [sentence_from(text, m.start()) for m in GUARD.finditer(text)]


def all_guard_reads() -> list[tuple[str, str]]:
    return [(p.relative_to(REPO_ROOT).as_posix(), s)
            for p in sorted(SKILLS.rglob("*.md"))
            for s in guard_reads(p.read_text(encoding="utf-8"))]


def test_the_population_is_every_guard() -> None:
    assert len(all_guard_reads()) == POPULATION, (
        f"{len(all_guard_reads())} guard sentences name `.claude/settings.json`, expected "
        f"{POPULATION}. If a skill gained or lost a permission guard, re-derive the number."
    )


def test_every_guard_read_unions_the_local_file() -> None:
    missing = [f for f, s in all_guard_reads() if "settings.local.json" not in s]
    assert not missing, (
        f"these permission guards read `.claude/settings.json` without "
        f"`.claude/settings.local.json`: {missing}. Allow-rules union across the two "
        "(`_shared/permission-guard.md` § Algorithm step 2)."
    )


def test_the_check_sees_a_shared_file_only_guard() -> None:
    # Controls, through the same extraction the population uses.
    def unions(sentence: str) -> list[bool]:
        return ["settings.local.json" in s for s in guard_reads(sentence)]
    for bad in ["Read `.claude/settings.json` and confirm `permissions.allow` contains:\n",
                "Before anything else, read `.claude/settings.json` and confirm it.",
                "Check `.claude/settings.json` for the rules.",
                "Verify `.claude/settings.json` carries the allow-rules. Also `.claude/settings.local.json` exists."]:
        assert unions(bad) == [False], bad
    for good in ["Read `.claude/settings.json` (and `.claude/settings.local.json` if present) and confirm x:\n",
                 "Read `.claude/settings.json` and confirm `permissions.allow` (unioned with `.claude/settings.local.json`) contains:\n"]:
        assert unions(good) == [True], good
