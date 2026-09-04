"""No shipped file may claim the default branch is untouched by a claim (Phase 260).

`Q-400` filed ONE site. The phase's own sweep found a second, and the round's
claims lens found a third — `WORKFLOW.md:57`, item 4 of § 1 *Core principles*,
*"The main branch is never committed to directly."* That was the strongest
instance and the sweep that missed it was keyed to the word *untouched*, which
is why this guard is keyed to the PROPOSITION and carries both vocabularies.

The proposition is false for at least seven shipped writers: `/claim-task`
Step 4d, `batch_work.sh`'s batch claim, `close_batch.sh`, `/review-close`
Step 1b, `/codebase-review` Step 7, and `/auto-build`'s pre-claims.

DELIBERATELY NOT FORBIDDEN: the imperative. `WORKFLOW_GUIDE.md:79` says
*"Never commit to `main` directly"* inside a numbered list of things the
OPERATOR does. That is advice to a human and is the same advice `WORKFLOW.md`
§ 4.4 gives under *"The one thing to avoid: freehand work on `main`."* A guard
that cannot tell a description from an instruction would force that line out
and make the docs worse.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Maintainer-side files: mirror-excluded, and the two queue files plus the
# phase log legitimately QUOTE the falsehood while recording its correction.
_EXCLUDE_PREFIXES = ("tools/",)
_EXCLUDE_NAMES = {
    "CLAUDE.md",
    "PHASE_LOG.md",
    "REVIEW_CHECKLIST.md",
    "REVIEW_ARCHIVE.md",
}

# Each pattern is a DESCRIPTIVE assertion that the default branch is not
# written. Anchored on the subject so an imperative ("never commit to main")
# does not match: every arm requires a copula or a participle.
_CLAIMS = (
    re.compile(r"main\s+branch\s+is\s+never\s+committed\s+to", re.I),
    re.compile(r"default\s+branch\s+is\s+never\s+committed\s+to", re.I),
    re.compile(r"leav(?:ing|es)\s+`?(?:main|the\s+default\s+branch)`?\s+untouched", re.I),
    re.compile(
        r"`?(?:main|default\s+branch)`?(?:\s+\w+){0,2}\s+"
        r"(?:stays|is\s+left|remains)\s+(?:completely\s+|entirely\s+)?untouched",
        re.I,
    ),
    # Paraphrases found by this module's own battery. The proposition survives
    # a change of vocabulary, so the arms track the proposition, not one wording.
    re.compile(r"`?(?:main|the\s+default\s+branch)`?\s+is\s+not\s+written\s+to", re.I),
    re.compile(r"nothing\s+is\s+(?:ever\s+)?committed\s+to\s+`?main`?", re.I),
    re.compile(r"`?main`?\s+is\s+read-only", re.I),
)

# WHAT THIS GUARD CANNOT REACH, and why the survivors are residual rather than
# unattempted. The battery also tried *"The build never happens on `main`"* and
# *"your clone stays put"*. Both survive, and both MUST: they are live at
# `docs/workflow.html:1580` and they are TRUE — that sentence scopes itself to
# the *build* and then names the two coordination files by path. An arm broad
# enough to catch them false-fires on the most careful prose in the tree, which
# is the over-strictness direction the author-side pass warns about. Telling a
# true scoped claim from a false unscoped one needs a judgement no pattern
# encodes, so the general form stays a reader's job. The arms above are the
# concrete falsehoods; this is not a claim to have closed the class.


def _shipped_files() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "-z"],
        capture_output=True, text=True, check=True,
    ).stdout
    keep = []
    for rel in out.split("\0"):
        if not rel or rel.endswith(("/",)):
            continue
        if rel.startswith(_EXCLUDE_PREFIXES) or rel in _EXCLUDE_NAMES:
            continue
        if not rel.endswith((".md", ".html", ".txt")):
            continue
        keep.append(REPO / rel)
    return keep


def _hits(text: str) -> list[str]:
    return [m.group(0) for pat in _CLAIMS for m in pat.finditer(text)]


def test_no_shipped_file_claims_the_default_branch_is_untouched():
    population = _shipped_files()
    # Vacuity: a guard whose population is empty passes while testing nothing.
    assert len(population) > 20, f"population collapsed to {len(population)} files"

    offenders: list[str] = []
    for path in population:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for hit in _hits(text):
            offenders.append(f"{path.relative_to(REPO)}: {hit!r}")

    assert not offenders, (
        "A shipped file asserts the default branch is never written. It is: a claim "
        "commits `tasks/index.yml` (Step 4d), and closes and review rounds commit "
        "`review_tasks.md`, all in the primary checkout.\n  " + "\n  ".join(offenders)
    )


def test_the_guard_actually_matches_the_corrected_sentences():
    """Non-vacuity: the exact strings this phase removed must still be caught."""
    removed = (
        "The main branch is never committed to directly.",
        "Checks the lock first, then builds in a fresh worktree, leaving `main` untouched.",
        "Your main checkout stays untouched; you can keep working in it.",
    )
    for sentence in removed:
        assert _hits(sentence), f"guard no longer catches: {sentence!r}"


def test_the_guard_permits_the_imperative():
    """The operator instruction must survive — see the module docstring."""
    allowed = (
        "Work in the worktree on the feature branch. Never commit to `main` directly.",
        "The one thing to avoid: freehand work on `main`.",
        "Two tasks that touch the same file can't corrupt each other.",
    )
    for sentence in allowed:
        assert not _hits(sentence), f"guard false-fires on: {sentence!r}"
