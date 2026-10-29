"""Phase 433 — no shipped skill file cites the maintainer's private record.

WHAT THIS CLASS IS
------------------
`core/skills/**/*.md` ships to every consumer and is read on the public repository. Until
this phase those files carried 797 pointers into records that are not in the public tree:
development phase numbers (`Phase 363`), queue entry ids (`Q-644`) and the maintainer's
name attached to rulings. A reader who follows one finds nothing; a runner gains nothing
from it either, because a citation never changes what a step does. Phase 432 ruled the
scrub (mechanical, not the rationale migration) and Phase 433 ran it: 250 pure-citation
parentheticals by `tools/phase433_scrub.py`, the rest by hand.

WHY THE GUARD IS SHAPED THIS WAY
--------------------------------
1. **Zero-invariant over a derived population.** Every `.md` under `core/skills/` is
   scanned, so a skill or step file added later is covered without anyone remembering
   to add it. The CLAUDE.md phase table re-accreted to 95% of the file twice after
   being trimmed; a one-time scrub with no guard is the same shape.
2. **Not fence-scoped.** Citations sat in prose, in blockquotes, in table cells and in
   script comments inside fences; a scan that skipped fences would have reported a green
   zero over 62 sites.
3. **One named exception, pinned.** `/auto-build` names its own pipeline stages
   `Phase 6a`..`Phase 6e` and `Phase 7`, and other skills refer to them. Those are product
   vocabulary, not citations, and the allowlist is exactly that shape. A Sysop build
   numbered 6 or 7 would pass through it; none is cited in any skill today, and the
   scrub's inventory is the measurement (`PHASE_LOG.md` § Phase 433).
4. **A control pins the predicate.** The cheapest way to silence this guard is to narrow
   the regex, so a fixture carrying one of each token kind must still trip it.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests import shape_lib as S

SKILLS = S.REPO_ROOT / "core" / "skills"

# `Phases 376 and 380`, `pre-Phase-40` and `Phase\n360` (a citation split by a wrap) were found by the hand pass
# and were invisible to the single-line `Phase \d+` grep that measured the inventory.
CITATION = re.compile(r"\bPhases?[\s-]+\d+[a-z]?\b|\bQ-\d{3,4}\b|\bWade\b")
PIPELINE_STAGE = re.compile(r"\APhases? (?:6[a-e]|7)\Z")


def _canon(tok: str) -> str:
    """`Phase-40` and `Phase\n40` read as `Phase 40`; a queue id is left as written."""
    return re.sub(r"^(Phases?)[\s-]+", r"\1 ", tok)


def citations(text: str) -> list[str]:
    """Every citation token in `text`, with `/auto-build`'s stage names left out."""
    toks = [_canon(m.group()) for m in CITATION.finditer(text)]
    return [t for t in toks if not PIPELINE_STAGE.match(t)]


def _skill_files() -> list[Path]:
    files = sorted(SKILLS.rglob("*.md"))
    assert len(files) >= 30, f"population looks wrong: {len(files)} files under {SKILLS}"
    return files


def test_no_shipped_skill_cites_the_private_record():
    hits = []
    for path in _skill_files():
        text = path.read_text(encoding="utf-8")
        for m in CITATION.finditer(text):
            tok = _canon(m.group())
            if PIPELINE_STAGE.match(tok):
                continue
            n = text.count("\n", 0, m.start()) + 1
            hits.append(f"{path.relative_to(S.REPO_ROOT)}:{n}: {tok}")
    assert not hits, (
        f"{len(hits)} citation(s) of the private record in shipped skill text — a phase "
        f"number, a queue id or the maintainer's name tells a consumer nothing and points a "
        f"public reader at a file that is not there:\n  " + "\n  ".join(hits[:40]))


def test_the_predicate_still_sees_each_token_kind():
    """Control: the guard above is only as strong as this regex."""
    fixture = ("Fixed since Phase 363's round; see `Q-644` (Wade, 2026-10-06). "
               "Skip Phase 6e for it; Phase 7 recovers the envelope.")
    assert citations(fixture) == ["Phase 363", "Q-644", "Wade"]
    assert citations("Phase 6a, Phase 6e, Phase 7, Phase 70, Phase 6") == ["Phase 70", "Phase 6"]
    assert citations("Q-12 and Q-12345 and phase 400 and Wader") == []
    assert citations("Q-1000 is the queue's next thousand") == ["Q-1000"]
    assert citations("Phases 376 and 380; until Phase\n360 the") == ["Phases 376", "Phase 360"]
    assert citations("pre-Phase-40 commits; the Phase-6e agent; skip Phases 6b-6e") == ["Phase 40"]
