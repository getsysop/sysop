"""Drift guards for Phase 173 — Phase-128 vendor-path drift in shipped content.

Phase 128 moved Sysop's whole consumer-side footprint under one `sysop/` vendor dir.
`install.sh`'s `_ns_old_to_new()` is the source of truth for what moved:

    scripts/*          → sysop/scripts/*
    WORKFLOW.md        → sysop/docs/WORKFLOW.md
    WORKFLOW_GUIDE.md  → sysop/docs/WORKFLOW_GUIDE.md
    SYSOP_ISSUES.md    → sysop/SYSOP_ISSUES.md

Content that still names an old spelling points at a directory no current install has.
The friction-log population is the bulk of this module (below); § Map headers at the end
guards the `scripts/` population, where the same point-fix-and-move-on failure recurred.

--------------------------------------------------------------------------------
## The friction log's path in shipped content

Ground truth: `install.sh`'s `seed_friction_log()` writes `$TARGET/sysop/SYSOP_ISSUES.md`,
and `_ns_move_issues_log()` migrates a pre-Phase-128 bare-root copy into that same place.
So on any current install the file is at `sysop/SYSOP_ISSUES.md`, never at the bare root.

**This path has now been point-fixed three times** (Phase 128 moved it, Phase 147's rider
caught `/report-issues` + `/share-wins` still reading the old root, Phase 173 swept the
class). Each earlier fix corrected the sites in front of it and left siblings, which is
exactly what a class sweep exists to stop — so the class gets a guard rather than a fourth
fix.

## What is checked, and what deliberately is not

A bare `SYSOP_ISSUES.md` is **not** a defect on its own — 20 of the 31 bare occurrences the
sweep found were correct and were left alone. Prefix-chasing every mention would be churn,
and one of them (`docs/workflow.html`'s ASCII tree) would be actively *broken* by a prefix.
Two properties are worth pinning instead:

1. **No bare reference may claim the file sits at a repo root** (`root_location_offenders`).
   That is the false-claim class: three sites asserted it, and `/review-close`'s was
   self-confirming — it looked at the bare root, missed the real file, and printed
   "not present — re-run bash install.sh to seed", a diagnosis that reads as coherent
   while friction capture silently no-ops for the cycle. Re-running the installer would
   then skip the existing file, confirming the false story.

2. **A skill file may not reference the log only in bare form** (`bare_only_skills`).
   `/review-close` and `/add-task` each named the log repeatedly and the correct path
   *nowhere in the file*, so an executing agent had nothing to resolve against. Scoped to
   `core/skills/**` on purpose: those are executed. `README.md`, `WORKFLOW.md`,
   `docs/install-and-update.md` and the monograph are read by humans, nominal mentions
   there are normal, and they are not in this population.

**The over-strictness this buys, stated rather than left implied:** property 2 reds if a
new skill mentions the log only nominally (`/auto-build`'s design-note trailer did). That
is a deliberate trade — the fix is to write the prefix once, which is the thing we want —
but it is a guard that constrains ordinary authoring, so it is named here rather than
discovered.

**Whitespace normalisation is load-bearing, not tidiness.** The scout that sized this class
first ran a line-scoped regex and found **2** root-location claims; a whitespace-tolerant
re-run found **5**, because `/onboard`'s phrase wraps as "at the repo\nroot". Every
predicate here collapses whitespace across the whole file before matching, and
`test_predicate_catches_the_wrapped_form` pins that specific case so the bug cannot return.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SKILLS = _ROOT / "core" / "skills"

#: The corpus Sysop ships or publishes: plugin content, companion docs, public docs,
#: and the two root-level public pages. Derived by walking the tree rather than from a
#: hand-maintained list, so a new file joins the population by existing.
#: `install.sh` is in the population deliberately, and its absence was a real miss.
#: The sweep that produced this module covered every *mention* of the log and not
#: the installer's **seed body** — the heredoc that writes the file's own header
#: into every consumer. That header asserted "This file lives at repo root by
#: design", wrapped across a line, in the single most authoritative place the
#: claim could appear: inside the artifact itself. A corpus derived from "where
#: does the documentation talk about this" could not see it.
_CORPUS_DIRS = ("core", "packs", "docs")
_CORPUS_FILES = ("README.md", "CONTRIBUTING.md", "install.sh")
#: Binary-ish suffixes to skip. Everything else in the corpus dirs is read, rather
#: than an allowlist of "text" suffixes being enumerated — an allowlist of
#: `.md/.html/.yml/.yaml/.json/.txt/.sh/.py` silently excluded the shipped
#: extensionless git hooks (`core/companion/git-hooks/pre-commit`,
#: `pre-merge-commit`) and the `.ts`/`.tsx` semgrep fixtures. Derive the population
#: from the tree and subtract, so a new file type joins by existing.
_SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".woff",
                  ".woff2", ".ttf", ".otf", ".svg"}

_TOKEN = "SYSOP_ISSUES.md"

#: An affirmative claim that something sits at the top of the consumer repo.
#:
#: **Structural, not an enumeration of phrasings.** The first draft matched a fixed
#: preposition-then-`repo root` shape and four ordinary rewordings walked straight
#: through it — `at the repo's root`, `in the root of the repository`, `at the top
#: level of the repo`, `at the project root`. None of those is adversarial; they are
#: how people write, which is rule 1's "what it matches on" failure exactly. This
#: form instead asks whether a repo-noun and a location-noun co-occur close together
#: in *either* order, so the phrasing is free.
_LOC_NOUN = (
    r"(?:root|top[-\s]level|top\s+(?:dir(?:ectory)?|folder)"
    r"|base|outermost(?:\s+(?:dir(?:ectory)?|folder|level))?)"
)
_REPO_NOUN = r"(?:repo(?:sitory)?|project|checkout|clone|working\s+tree)"
_ROOT_CLAIM = re.compile(
    # a repo-noun and a location-noun close together, in either order
    rf"\b{_REPO_NOUN}\b[^.]{{0,25}}\b{_LOC_NOUN}\b"
    rf"|\b{_LOC_NOUN}\b[^.]{{0,25}}\b{_REPO_NOUN}\b"
    # …or a location-noun that needs no repo-noun to be unambiguous. `root` alone
    # is deliberately NOT enough — "records the root cause of each issue" is
    # ordinary prose and a guard that reddens on it gets deleted.
    rf"|\broot\s+(?:dir(?:ectory)?|folder)\b"
    rf"|\btop\s+of\s+(?:the|your)\b",
    re.IGNORECASE,
)

#: **Polarity, the direction that gets a guard deleted.** `_ROOT_CLAIM` matches the
#: NOUNS of a location claim and is blind to its tense and polarity, so it reads
#: "no longer at the repo root" exactly like "at the repo root". Every correct
#: migration note in this repo is phrased the first way. An independent review
#: battery reddened **5 of 11** ordinary sentences on this — "used to live at the
#: repo root", "Phase 128 moved it out of the project root", "a pre-Phase-128
#: install may have left it at the repo root; migrate it" — all true, all the sort
#: of sentence this codebase writes constantly. A guard that punishes them is worse
#: than no guard, because it gets deleted rather than fixed.
_PAST_OR_NEGATED = re.compile(
    r"\b(?:no\s+longer|not\s+at|never\s+at|used\s+to|previously|formerly|legacy"
    r"|pre-Phase-\d+|before\s+Phase\s+\d+|moved\s+(?:\S+\s+){0,4}?(?:out\b|from\b)"
    r"|was\s+moved|migrat|older\s+install|left\s+it\s+at|still\s+(?:in|at))\b",
    re.IGNORECASE,
)

#: The correct location stated in the same breath also disambiguates: "Run
#: install.sh from the project root. The log is SYSOP_ISSUES.md under `sysop/`."
#: is a true sentence whose root-claim is about something else entirely.
_RESOLVED_NEARBY = re.compile(r"sysop/", re.IGNORECASE)

#: A *path expression* asserts a location with no prose at all, and this is the
#: half that can be checked structurally rather than by guessing at nouns. Capture
#: the maximal path-ish run before the token; an empty run is a bare mention (that
#: is `_ROOT_CLAIM`'s job), a non-empty one must resolve to exactly `sysop/`.
_PATH_REF = re.compile(r"([A-Za-z0-9_${}<>.\\/-]*)" + re.escape(_TOKEN))

#: Roots a path may legitimately be written against before `sysop/` — the installer
#: writes `$TARGET/sysop/…`, the docs write `<repo-root>/sysop/…`.
_ALLOWED_ROOT = re.compile(r"^(?:\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|<[^>]+>|~)?/?")


def corpus_files() -> list[Path]:
    """Every shipped/published text file. Population derived from the tree."""
    out: list[Path] = []
    for d in _CORPUS_DIRS:
        base = _ROOT / d
        if base.is_dir():
            out.extend(
                p
                for p in base.rglob("*")
                if p.is_file()
                and p.suffix.lower() not in _SKIP_SUFFIXES
                and "__pycache__" not in p.parts
            )
    out.extend(_ROOT / f for f in _CORPUS_FILES if (_ROOT / f).is_file())
    return sorted(out)


def skill_files() -> list[Path]:
    return sorted(_SKILLS.rglob("*.md"))


def normalise(text: str) -> str:
    """Collapse every whitespace run to a single space.

    This is what makes a wrapped `at the repo\\nroot` visible to `_ROOT_CLAIM`. A
    line-scoped scan of the same corpus undercounted this class by more than half.
    """
    return re.sub(r"\s+", " ", text)


#: `sysop/` counts as the prefix only at a path boundary. A plain `.endswith()`
#: test accepts `mysysop/SYSOP_ISSUES.md` — a wrong path scored as a correct one,
#: which is worse than a miss because it marks the reference compliant. Preceded
#: by `/` is fine (`$TARGET/sysop/…` is how the installer writes it).
_PREFIXED = re.compile(r"(?:^|[^A-Za-z0-9_-])sysop/$")


def bare_spans(normalised: str) -> list[tuple[int, int]]:
    """Offsets of every `SYSOP_ISSUES.md` NOT already carrying the `sysop/` prefix."""
    return [
        (m.start(), m.end())
        for m in re.finditer(re.escape(_TOKEN), normalised)
        if not _PREFIXED.search(normalised[: m.start()])
    ]


def root_location_offenders(text: str, window: int = 80) -> list[str]:
    """Bare references that sit next to an affirmative, present-tense root claim.

    `window` is measured in normalised characters on each side. It is symmetric on
    purpose: all three historical defects put the claim *after* the token, so a
    narrow look-behind was untested and a claim placed ahead of the reference
    walked through.

    A character window beats sentence-scoping here — a claim often lands in the
    *next* sentence ("The log is SYSOP_ISSUES.md. It sits at the repo root."),
    which a sentence-scoped window cuts off and misses.
    """
    norm = normalise(text)
    hits: list[str] = []
    for start, end in bare_spans(norm):
        near = norm[max(0, start - window) : end + window]
        if not _ROOT_CLAIM.search(near):
            continue
        # Past-tense / migration prose describes where it *used* to be. Flagging
        # that is the false-alarm direction, and it is the one that gets a guard
        # deleted rather than fixed.
        if _PAST_OR_NEGATED.search(near):
            continue
        # The correct location stated in the same breath disambiguates a root
        # claim that was about something else ("run install.sh from the project
        # root; the log is SYSOP_ISSUES.md under `sysop/`").
        if _RESOLVED_NEARBY.search(near):
            continue
        hits.append(near.strip())
    return hits


def path_expression_offenders(text: str) -> list[str]:
    """Path expressions for the log that do not resolve to `sysop/`.

    This is the structural half, and it is the half worth trusting. `_ROOT_CLAIM`
    guesses at nouns; this one just reads the path. It catches every wrong
    directory without knowing any English: `.claude/sysop/…`, `vendor/sysop/…`,
    `.sysop/…`, `sysop/docs/…`, `SYSOP/…`, `./…`, `/…`, `$REPO_ROOT/…`.

    A *bare* token (no path prefix at all) is not this function's business — that
    is `_ROOT_CLAIM`'s domain and, for skills, property 2's.
    """
    norm = normalise(text)
    hits: list[str] = []
    for m in _PATH_REF.finditer(norm):
        prefix = m.group(1)
        if not prefix:
            continue  # a bare mention, not a path expression
        # Strip one leading root token ($TARGET/, <repo-root>/, ~/, /) if present.
        remainder = _ALLOWED_ROOT.sub("", prefix, count=1)
        if remainder == "sysop/":
            continue
        if remainder == "" and prefix.endswith("/"):
            # A root token with nothing after it: "$TARGET/SYSOP_ISSUES.md" says
            # the log is at the root, which is exactly the claim under review.
            hits.append(m.group(0))
        elif remainder != "sysop/":
            hits.append(m.group(0))
    return hits


def bare_only_skills() -> list[str]:
    """Skill files that name the log but never once spell the resolvable path."""
    offenders: list[str] = []
    for path in skill_files():
        text = path.read_text(encoding="utf-8")
        if _TOKEN not in text:
            continue
        if "sysop/" + _TOKEN not in text:
            offenders.append(str(path.relative_to(_ROOT)))
    return offenders


# --- Property 1: no bare reference claims a root location ----------------------


def test_no_shipped_file_places_the_friction_log_at_a_repo_root():
    offenders: list[str] = []
    for path in corpus_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for excerpt in root_location_offenders(text):
            offenders.append(f"{path.relative_to(_ROOT)}: …{excerpt}…")
    assert offenders == [], (
        "A bare SYSOP_ISSUES.md reference claims the file sits at a repo root. "
        "Ground truth is sysop/SYSOP_ISSUES.md (install.sh seed_friction_log). "
        "Offenders:\n  " + "\n  ".join(offenders)
    )


# --- Property 2: an executed skill must resolve the path at least once ---------


def test_every_skill_naming_the_log_also_names_the_real_path():
    offenders = bare_only_skills()
    assert offenders == [], (
        "These skill files reference the friction log but never spell "
        "`sysop/SYSOP_ISSUES.md`, so an agent executing them has nothing to resolve "
        "the path against: " + ", ".join(offenders)
    )


#: Skills that operate on the friction log. **Derived, not counted.** An earlier
#: `>= 6` floor against an actual population of 7 let one skill drop out silently —
#: a magic number is always lowerable to the population that survives. This set is
#: the source of truth; adding a skill that names the log means adding it here,
#: which is the point.
_LOG_NAMING_SKILLS = {
    "add-task",
    "auto-build",
    "intake",
    "onboard",
    "report-issues",
    "review-close",
    "share-wins",
}


def skills_naming_the_log() -> set[str]:
    return {
        p.parent.name
        for p in skill_files()
        if _TOKEN in p.read_text(encoding="utf-8")
    }


def test_the_population_is_exactly_the_declared_set():
    """Vacuity floor, derived rather than counted.

    Property 2 passes trivially if the population collapses. Comparing the *set*
    rather than asserting a floor means a skill cannot leave silently and a new
    one cannot join unnoticed.
    """
    actual = skills_naming_the_log()
    assert actual == _LOG_NAMING_SKILLS, (
        f"the set of skills naming the friction log changed: "
        f"gone={sorted(_LOG_NAMING_SKILLS - actual)} "
        f"new={sorted(actual - _LOG_NAMING_SKILLS)}. If this is intended, update "
        "_LOG_NAMING_SKILLS — but check the newcomer names the resolvable path."
    )


# --- Property 0: ground truth, asserted rather than assumed --------------------
#
# The module's whole premise is "install.sh puts the log at sysop/SYSOP_ISSUES.md".
# An independent battery rewrote `seed_friction_log` to the bare root and undid the
# migration mapping, and every test here stayed green — the module asserted a
# premise it never checked. These three close that.


def _installer() -> str:
    return (_ROOT / "install.sh").read_text(encoding="utf-8")


def test_the_installer_seeds_into_the_vendor_dir():
    assert 'local dst="$TARGET/sysop/SYSOP_ISSUES.md"' in _installer(), (
        "seed_friction_log's destination is the ground truth every other assertion "
        "in this module rests on; it no longer writes into sysop/"
    )


def test_the_migration_maps_the_old_spelling_to_the_new():
    text = normalise(_installer())
    assert "SYSOP_ISSUES.md) printf 'sysop/SYSOP_ISSUES.md'" in text, (
        "_ns_old_to_new no longer migrates the friction log — a pre-Phase-128 "
        "consumer would keep a bare-root copy that nothing reads"
    )
    assert 'local old="SYSOP_ISSUES.md" new="sysop/SYSOP_ISSUES.md"' in text


def test_no_path_expression_resolves_outside_the_vendor_dir():
    """Structural: read the path, do not guess at the prose around it."""
    offenders: list[str] = []
    for path in corpus_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for hit in path_expression_offenders(text):
            offenders.append(f"{path.relative_to(_ROOT)}: {hit}")
    assert offenders == [], (
        "a path expression for the friction log resolves somewhere other than "
        "sysop/:\n  " + "\n  ".join(offenders)
    )


def test_path_predicate_catches_every_wrong_directory():
    """Detection floor for the structural half — no English required."""
    for wrong in (
        "`.claude/sysop/SYSOP_ISSUES.md`",
        "`vendor/sysop/SYSOP_ISSUES.md`",
        "`.sysop/SYSOP_ISSUES.md`",
        "`mysysop/SYSOP_ISSUES.md`",
        "`sysop/docs/SYSOP_ISSUES.md`",
        "`sysop/runtime/SYSOP_ISSUES.md`",
        "`SYSOP/SYSOP_ISSUES.md`",
        "./SYSOP_ISSUES.md",
        "/SYSOP_ISSUES.md",
        "$REPO_ROOT/SYSOP_ISSUES.md",
        "$(git rev-parse --show-toplevel)/SYSOP_ISSUES.md",
        "<repo-root>/SYSOP_ISSUES.md",
    ):
        assert path_expression_offenders(wrong), f"{wrong} not flagged"


def test_path_predicate_accepts_the_legitimate_forms():
    """Over-strictness control for the structural half."""
    for ok in (
        "`sysop/SYSOP_ISSUES.md`",
        'local dst="$TARGET/sysop/SYSOP_ISSUES.md"',
        "<repo-root>/sysop/SYSOP_ISSUES.md",
        "~/sysop/SYSOP_ISSUES.md",
        "a bare SYSOP_ISSUES.md mention",
    ):
        assert path_expression_offenders(ok) == [], f"{ok} false-flagged"


# --- Detection floor: the predicate catches each real historical defect --------
#
# Phase 172's lesson: a guard asserting today's tree is clean proves nothing about
# what it would catch. These are the three sentences that actually shipped, fed to
# the predicate directly.

_HISTORICAL_DEFECTS = {
    "intake": (
        "Hit any Sysop friction while planning (a confusing step, a rough edge)? "
        "Note it\nin SYSOP_ISSUES.md at the repo root — /report-issues sends the "
        "keepers upstream."
    ),
    "onboard": (
        "Hit any Sysop friction while onboarding? Note it in SYSOP_ISSUES.md at "
        "the repo\nroot — /report-issues sends the keepers upstream."
    ),
    "review-close": (
        "1. **Find the friction log:** `SYSOP_ISSUES.md` at the consumer-repo root "
        "(NOT under `.claude/`). If the file is missing (consumer pre-dates Phase 13 "
        "install), emit one line: `note: SYSOP_ISSUES.md not present — re-run bash "
        "install.sh to seed. Skipping friction capture.` and proceed to Step 8."
    ),
}


def test_predicate_catches_each_historical_defect_alone():
    for name, text in _HISTORICAL_DEFECTS.items():
        assert root_location_offenders(text), (
            f"the {name} sentence that actually shipped is not caught by the "
            "predicate — the guard would not have prevented this phase's own defect"
        )


#: Rewordings that walked through the first draft of `_ROOT_CLAIM`, found by the
#: author-side pass rather than by a reviewer. None is adversarial — they are how
#: people write — so each is pinned rather than left to be rediscovered.
_BYPASS_PHRASINGS = {
    "possessive": "Note it in SYSOP_ISSUES.md at the repo's root.",
    "root-of-the": "The root of the repository holds SYSOP_ISSUES.md.",
    "top-level-of": "SYSOP_ISSUES.md sits at the top level of the repo.",
    "project-root": "Create SYSOP_ISSUES.md at the project root.",
    "root-directory": "Put SYSOP_ISSUES.md in the root directory.",
    "root-folder": "Put SYSOP_ISSUES.md in the root folder.",
    "top-of-checkout": "SYSOP_ISSUES.md lives at the top of your checkout.",
    "next-sentence": "The log is SYSOP_ISSUES.md. It sits at the repo root.",
    "path-expression": "Read ./SYSOP_ISSUES.md to see the friction log.",
    # Found by an independent review battery, which walked six ordinary noun
    # choices through the "structural" first rewrite. Structural in the sense of
    # "not a fixed phrase list" still left the *nouns* enumerated.
    "base-of-repo": "SYSOP_ISSUES.md sits at the base of the repo.",
    "top-folder": "SYSOP_ISSUES.md is in the repository's top folder.",
    "outermost-dir": "Put SYSOP_ISSUES.md in the outermost directory of your project.",
    "top-directory": "SYSOP_ISSUES.md at the top directory of the checkout.",
    "claim-before-token": (
        "At the root of the repository you will find, among other things, the file "
        "SYSOP_ISSUES.md."
    ),
}


def test_predicate_catches_ordinary_rewordings():
    """Either predicate may catch it — prose claim or path expression.

    They are two halves of one question ("does this say the log is at the root?")
    and a caller should never have to know which half owns a given shape.
    """
    for name, text in _BYPASS_PHRASINGS.items():
        assert root_location_offenders(text) or path_expression_offenders(text), (
            f"'{name}' walks through both predicates — a fixed phrase list is not "
            "a guard, the check has to be phrasing-free"
        )


def test_root_cause_prose_is_not_a_location_claim():
    """Over-strictness control: `root` alone must not be enough.

    "SYSOP_ISSUES.md records the root cause of each issue" is ordinary prose. A
    guard that reddens on it punishes normal authoring and gets deleted.
    """
    assert root_location_offenders(
        "SYSOP_ISSUES.md records the root cause of each issue."
    ) == []


def test_the_residuals_this_guard_does_not_reach_are_named():
    """Stated, not hidden. Three shapes survive both predicates, on purpose.

    1. **Implied location.** "sits alongside `CLAUDE.md`" / "next to your
       `.gitignore`" asserts the bare root by implication and carries no location
       noun at all. Closing it needs a judgement about what other files imply,
       not a wider regex.
    2. **Exotic phrasings.** An independent battery got through with "head of the
       working tree" and "un-nested, directly in the repo". The ordinary nouns are
       closed (`base`, `top folder/directory`, `outermost`); the tail is genuinely
       open-ended, and widening it further trades false negatives for the false
       *positives* that get a guard deleted.
    3. **Behaviour vs. wording.** The verbatim pins constrain what the steps *say*.
       Prefixing a step with "SKIP this entire step" keeps every pinned byte and
       inverts what it does. That is a general limit of pinning prose, not specific
       to this class.

    Property 2 and the structural path check are the backstops: whatever the prose
    does, a skill that names the log must still spell the resolvable path, and no
    path expression may resolve outside `sysop/`.
    """
    for implied in (
        "SYSOP_ISSUES.md sits alongside CLAUDE.md.",
        "Put SYSOP_ISSUES.md next to your .gitignore.",
    ):
        assert not (
            root_location_offenders(implied) or path_expression_offenders(implied)
        ), (
            "this residual just became reachable — good; fold it into "
            "_BYPASS_PHRASINGS and shorten this docstring"
        )


def test_prefix_is_recognised_only_at_a_path_boundary():
    """A look-alike directory must not score as the correct prefix.

    `mysysop/SYSOP_ISSUES.md` ends with the literal `sysop/`, so a naive
    `.endswith()` marks it compliant — a wrong path scored as a right one, which
    is worse than a miss. `$TARGET/sysop/…` (a `/` boundary) must still pass.
    """
    assert bare_spans(normalise("`mysysop/SYSOP_ISSUES.md`")), (
        "a look-alike directory is being accepted as the sysop/ vendor dir"
    )
    assert bare_spans(normalise("`sysop-x/SYSOP_ISSUES.md`"))
    assert not bare_spans(normalise("`sysop/SYSOP_ISSUES.md`"))
    assert not bare_spans(normalise('"$TARGET/sysop/SYSOP_ISSUES.md"'))


def test_predicate_catches_the_wrapped_form():
    # The scout's own bug: line-scoped matching missed this and halved the count.
    wrapped = "Note it in SYSOP_ISSUES.md at the repo\nroot — see /report-issues."
    flat = "Note it in SYSOP_ISSUES.md at the repo root — see /report-issues."
    assert root_location_offenders(wrapped), "wrapped root claim not detected"
    assert root_location_offenders(flat), "flat root claim not detected"


# --- Negative controls: what the guard must NOT punish -------------------------


def test_the_monograph_directory_tree_is_left_bare_and_unflagged():
    """`docs/workflow.html` nests the log under a `sysop/` tree node.

    The bare filename is *correct* there — prefixing it would print the parent path
    twice and corrupt the rendering. This pins both halves: the line stays bare, and
    the root-location predicate does not flag it.
    """
    html = (_ROOT / "docs" / "workflow.html").read_text(encoding="utf-8")
    tree_lines = [
        ln
        for ln in html.splitlines()
        if _TOKEN in ln and ("└──" in ln or "├──" in ln)
    ]
    assert tree_lines, "the monograph's sysop/ tree no longer lists the friction log"
    for ln in tree_lines:
        assert "sysop/" + _TOKEN not in ln, (
            "the monograph's tree leaf was prefixed — the parent `sysop/` node already "
            "supplies the path, so this duplicates it and breaks the tree"
        )
    assert root_location_offenders(html) == []


def test_the_pre_128_fallback_prose_is_not_flagged():
    """The canonical form mentions the old root on purpose and must stay green.

    `/report-issues`, `/share-wins` and now `/review-close` all say the file is "no
    longer at the bare repo root" and that a pre-Phase-128 install may have left one
    there. That is correct migration guidance, not a false location claim.
    """
    for skill in ("report-issues", "share-wins", "review-close"):
        text = (_SKILLS / skill / "SKILL.md").read_text(encoding="utf-8")
        assert "no longer at the bare repo root" in normalise(text), (
            f"{skill}: lost the pre-Phase-128 disambiguation"
        )
        assert root_location_offenders(text) == [], (
            f"{skill}: the guard false-flags its own correct migration prose"
        )


#: Migration prose that is TRUE and must never redden the guard. An independent
#: battery reddened 5 of 11 sentences of this shape — the direction that gets a
#: guard deleted rather than fixed. The live-tree control above passes *incidentally*
#: (in those three skills the neighbouring token is `sysop/`-prefixed, so no bare
#: span exists), which is a vacuous control; these are synthetic and bare on purpose.
_TRUE_MIGRATION_PROSE = {
    "used-to": "SYSOP_ISSUES.md used to live at the repo root.",
    "moved-out": "Phase 128 moved SYSOP_ISSUES.md out of the project root.",
    "may-have-left": (
        "A pre-Phase-128 install may have left SYSOP_ISSUES.md at the repo root; "
        "migrate it."
    ),
    "still-in": "If SYSOP_ISSUES.md is still in the root directory, run --update.",
    "no-longer": "SYSOP_ISSUES.md is no longer at the bare repo root.",
    "root-is-elsewhere": (
        "Run install.sh from the project root. The log is SYSOP_ISSUES.md under "
        "`sysop/`."
    ),
}


def test_true_migration_prose_never_reddens_the_guard():
    for name, text in _TRUE_MIGRATION_PROSE.items():
        assert root_location_offenders(text) == [], (
            f"'{name}' is a true sentence and the guard reddens on it — this is the "
            "failure direction that gets a guard deleted instead of fixed"
        )


def test_the_polarity_suppression_is_not_a_blanket_escape():
    """The control above must not have opened a hole big enough to drive through.

    A past-tense marker anywhere in the window would let an author neutralise the
    guard by writing the word 'migrate' nearby. The suppression has to be tied to
    the claim, so an affirmative claim in the same window still reds.
    """
    assert root_location_offenders(
        "We moved fast on this. SYSOP_ISSUES.md is at the repo root."
    ), "an unrelated past-tense verb disarmed the guard"


def test_nominal_doc_mentions_are_not_flagged():
    """Human-facing docs name the file without a path, and that is fine.

    These are the sites the sweep deliberately left alone. If the guard reddens here
    it has become a prefix-chaser rather than a false-claim detector.
    """
    for rel in (
        "README.md",
        "docs/install-and-update.md",
        "core/companion/docs/WORKFLOW.md",
    ):
        text = (_ROOT / rel).read_text(encoding="utf-8")
        assert _TOKEN in text
        assert root_location_offenders(text) == [], (
            f"{rel}: nominal mention false-flagged"
        )


def test_a_reflow_of_a_fixed_sentence_stays_green():
    """Rewrapping must not red the guard — that is what normalisation is for."""
    reflowed = (
        "Hit any Sysop friction while planning?\nNote it in\nsysop/SYSOP_ISSUES.md\n"
        "— /report-issues sends the keepers upstream."
    )
    assert root_location_offenders(reflowed) == []


# --- Verbatim pins on the corrected sites --------------------------------------
#
# Whitespace-normalised so a reflow stays green, verbatim so a softening reds.


def _norm_skill(name: str) -> str:
    return normalise((_SKILLS / name / "SKILL.md").read_text(encoding="utf-8"))


def test_review_close_step7_pins_the_canonical_find_sentence():
    assert (
        "**Find the friction log:** `sysop/SYSOP_ISSUES.md` — inside the `sysop/` "
        "vendor dir at the consumer-repo root (Phase 128; NOT under `.claude/`, and "
        "no longer at the bare repo root). If a pre-Phase-128 install left it at the "
        "root, append there instead rather than treating it as missing."
    ) in _norm_skill("review-close")


def test_the_three_give_back_skills_share_one_fallback_clause():
    """Sibling parity, byte-for-byte in the shared half.

    `/review-close` adopted `/report-issues`' and `/share-wins`' wording but said
    "the **bare** root" where they say "the root" — same meaning, and a later grep
    for the canonical phrase would have missed one of the three. The verb still
    differs (append vs. read), because review-close writes and they read.
    """
    clause = "If a pre-Phase-128 install left it at the root,"
    for skill in ("report-issues", "share-wins", "review-close"):
        assert clause in _norm_skill(skill), (
            f"{skill}: drifted off the shared fallback clause"
        )


def test_review_close_absence_note_names_the_prefixed_path():
    text = _norm_skill("review-close")
    assert "`note: sysop/SYSOP_ISSUES.md not present — re-run bash install.sh" in text
    # The *parse-failure* note is reached only after step 1 resolved a file, which
    # may be either path — so it must report what step 1 resolved, not re-assert
    # one. Naming `sysop/` here would send a human to the wrong file on the
    # fallback path, and they are being told to file manually.
    assert (
        "could not determine next ISSUE number from <the path step 1 resolved>"
        in text
    )


def test_a_write_step_never_reasserts_a_path_the_read_step_may_not_have_used():
    """The regression the round caught, pinned so it cannot come back.

    Each of these skills has a read step that falls back to a pre-Phase-128
    bare-root copy. A later write step that *re-asserts* `sysop/SYSOP_ISSUES.md`
    contradicts that fallback: on the fallback path the `Edit` targets a file that
    does not exist — and in `/report-issues` and `/share-wins` it does so **after**
    the issue or comment has already been published, so the status flip that
    prevents double-posting is exactly what fails.

    The correct shape binds the write to what the read resolved *and* still names
    the canonical path for an agent that arrives mid-document.
    """
    assert (
        "edit **the same file Step 1 read** — `sysop/SYSOP_ISSUES.md`, or the "
        "bare-root copy if that is where Step 1 resolved it" in _norm_skill(
            "report-issues"
        )
    )
    assert (
        "edit **the same file Step 1 read** — `sysop/SYSOP_ISSUES.md`, or the "
        "bare-root copy if that is where Step 1 resolved it" in _norm_skill(
            "share-wins"
        )
    )
    assert (
        "positive-signal template in the log step 1 located "
        "(`sysop/SYSOP_ISSUES.md`, or the bare-root copy if step 1 resolved there)"
        in _norm_skill("review-close")
    )


def test_the_double_post_rationale_ships_with_the_binding():
    """The *reason* is pinned too — a bare rule reads as pedantry and gets undone."""
    for skill, artefact in (("report-issues", "issue"), ("share-wins", "comment")):
        assert (
            f"would fail *after* the {artefact} is already"
            in _norm_skill(skill)
        ), f"{skill}: lost the consequence that justifies binding the write step"


def test_closing_nudges_point_at_the_vendor_dir():
    assert "in sysop/SYSOP_ISSUES.md — /report-issues sends the keepers" in _norm_skill(
        "intake"
    )
    assert (
        "Note it in sysop/SYSOP_ISSUES.md — /report-issues sends the keepers"
        in _norm_skill("onboard")
    )


def test_add_task_routing_rule_names_the_path_at_both_ends():
    """Both the definition and the actionable instruction spell it out.

    A first draft made the terminal instruction anaphoric ("capture it *there*")
    to keep the occurrence count down. The round was right that this optimised the
    wrong thing: the bullet's other locative pro-form is "belongs *here*", meaning
    the task queue — the one destination the rule exists to steer away from.
    """
    text = _norm_skill("add-task")
    assert "**Friction with Sysop itself goes to `sysop/SYSOP_ISSUES.md`**" in text
    assert "capture it in `sysop/SYSOP_ISSUES.md` instead" in text


def test_the_installer_seed_body_states_the_vendor_dir():
    """The header written *into* every consumer's log — the H1 miss.

    This is the most authoritative place the location claim appears, because it
    ships inside the artefact rather than in documentation about it.
    """
    text = normalise((_ROOT / "install.sh").read_text(encoding="utf-8"))
    # The heredoc escapes its backticks (`\``) so bash does not command-substitute.
    assert "This file lives in the" in text and "vendor dir and is project-owned" in text
    assert "This file lives at repo root by design" not in text


# ================================================================================
# § Map headers — the `scripts/` population
# ================================================================================
#
# Both review skills derive their scan roots by parsing `## <glob list> — <Name>`
# headers out of the maps (`security-audit:235`/`:255`, `codebase-review:221`/`:241`).
# A header still keyed to the pre-Phase-128 `scripts/` therefore derives a root that
# does not exist on a current install: the section matches zero tracked files, the
# real `sysop/scripts/` surface attaches to no section, and Step 2a-0 reports `sysop/`
# as uninventoried.
#
# Phase 130 fixed exactly this in `convention_map.md` ("post-128 map-header
# regression — shell rules silently unmatched") and did not touch `security_map.md`,
# whose header carried the identical defect for 43 phases. That is the same
# fix-one-site-and-move-on failure this whole module exists to close, so the parity
# is a guard rather than a second point fix.

_MAP_FILES = sorted(
    [_ROOT / "core" / "companion" / "convention_map.md",
     _ROOT / "core" / "companion" / "security_map.md"]
    + list((_ROOT / "packs").glob("*/companion/*_map.md"))
)

#: Old→new prefixes from install.sh `_ns_old_to_new()`. A header naming the left
#: side must also name the right side.
_MIGRATED_PREFIXES = {"scripts/": "sysop/scripts/"}

_HEADER = re.compile(r"^## (.+?) — ", re.MULTILINE)
_GLOB = re.compile(r"`([^`]+)`")


def map_header_offenders() -> list[str]:
    """Headers naming a migrated path in its old spelling only.

    A *placeholder* glob (`<scripts dir>/*.py`) is the consumer's own directory, not
    Sysop's vendor dir, and is deliberately exempt — three pack maps use that form and
    none of them is drifted. The test below pins that exemption so the guard cannot be
    "fixed" into flagging them.
    """
    offenders: list[str] = []
    for path in _MAP_FILES:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for header in _HEADER.findall(text):
            globs = _GLOB.findall(header)
            for old, new in _MIGRATED_PREFIXES.items():
                names_old = any(
                    g.startswith(old) and not g.startswith("<") for g in globs
                )
                names_new = any(g.startswith(new) for g in globs)
                if names_old and not names_new:
                    offenders.append(
                        f"{path.relative_to(_ROOT)}: '{header}' names {old} "
                        f"but not {new}"
                    )
    return offenders


def test_no_map_header_names_only_the_pre_128_path():
    offenders = map_header_offenders()
    assert offenders == [], (
        "A map section header still derives a pre-Phase-128 scan root, so its "
        "conventions attach to nothing on a current install:\n  "
        + "\n  ".join(offenders)
    )


def test_both_core_maps_cover_the_vendor_script_surface():
    """Parity: the defect was one map fixed and its twin left behind."""
    for name in ("convention_map.md", "security_map.md"):
        text = (_ROOT / "core" / "companion" / name).read_text(encoding="utf-8")
        headers = _HEADER.findall(text)
        shell = [h for h in headers if "scripts/" in h]
        assert shell, f"{name}: lost its shell-scripts section entirely"
        assert any("sysop/scripts/" in h for h in shell), (
            f"{name}: the shell-scripts header does not cover sysop/scripts/, so "
            "Sysop's own vendor scripts are scanned under no section"
        )


def test_placeholder_script_globs_are_not_flagged():
    """Negative control: `<scripts dir>/` is the consumer's dir and must stay exempt.

    Three pack maps use it. A guard that reddened on them would punish the shipped
    placeholder vocabulary rather than catch drift.
    """
    placeholder_maps = [
        p for p in _MAP_FILES
        if "<scripts dir>/" in p.read_text(encoding="utf-8")
    ]
    assert len(placeholder_maps) >= 3, (
        "the placeholder population vanished — this control no longer controls "
        "anything"
    )
    offenders = map_header_offenders()
    for p in placeholder_maps:
        assert not any(str(p.relative_to(_ROOT)) in o for o in offenders), (
            f"{p}: placeholder glob false-flagged as Phase-128 drift"
        )


def test_predicate_catches_a_reverted_map_header():
    """Detection floor: the exact pre-fix header must be caught."""
    reverted = "## `scripts/*.sh`, `scripts/hooks/*` — Shell Scripts & Git Hooks\n"
    globs = _GLOB.findall(_HEADER.findall(reverted)[0])
    assert any(g.startswith("scripts/") for g in globs)
    assert not any(g.startswith("sysop/scripts/") for g in globs), (
        "the pre-fix header would not have been caught by map_header_offenders()"
    )


def test_workflow_pointer_template_names_the_installed_path():
    """§ 6.1's CLAUDE.md template is copied verbatim into consumer repos."""
    text = normalise(
        (_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md").read_text(
            encoding="utf-8"
        )
    )
    assert '"Follow the workflow in `sysop/docs/WORKFLOW.md`."' in text, (
        "the § 6.1 `## Task Workflow (pointer)` template row tells a consumer to "
        "follow a path that does not exist on a post-Phase-128 install"
    )


def test_workflow_md_names_no_bare_consumer_side_doc_path():
    """The `sysop/docs/` half of this module's own subject, finally guarded.

    This file's docstring has named `WORKFLOW.md → sysop/docs/WORKFLOW.md` as
    part of the Phase-128 class since it was written, and guarded only the
    `SYSOP_ISSUES.md` half. That gap is why § 8.2c and § 8.7 both still told a
    consumer to look for bare `WORKFLOW.md` five phases later, and why Phase 207
    found the § 8.2c site, fixed it, and left the § 8.7 sibling standing — the
    fix-the-site-in-front-of-you shape this module exists to end.

    Scoped to instruction-shaped references, which are the ones that assert a
    consumer-side location. A bare mention of the document by name (`see
    WORKFLOW.md § 4.2`) is a citation of the spec, not a path claim, and is left
    alone deliberately: widening this to every occurrence would false-fire on
    several hundred legitimate cross-references in this file.
    """
    text = (_ROOT / "core" / "companion" / "docs" / "WORKFLOW.md").read_text(
        encoding="utf-8"
    )
    # "Copy/open/edit/write <bare path>" — a verb that acts on the FILE.
    pattern = re.compile(
        r"(?:Copy|copy|Open|open|Edit|edit|Write|write|Create|create)\s+"
        r"`?WORKFLOW(?:_GUIDE)?\.md`?"
    )
    offenders = []
    for i, line in enumerate(text.splitlines(), 1):
        for m in pattern.finditer(line):
            # A correctly-qualified path is fine; only the bare form is a claim.
            if "sysop/docs/" not in line[max(0, m.start() - 20):m.end()]:
                offenders.append(f"  WORKFLOW.md:{i}: {m.group(0)!r} in {line.strip()[:90]!r}")

    assert offenders == [], (
        "WORKFLOW.md tells a reader to act on a bare `WORKFLOW.md` / "
        "`WORKFLOW_GUIDE.md` path. Phase 128 moved both under `sysop/docs/`, so "
        "the bare path does not exist in any consumer install and the "
        "instruction cannot be followed.\n" + "\n".join(offenders)
    )


def test_the_bare_doc_path_guard_is_not_vacuous():
    """Control: the guard must reject the shape it exists to catch, and accept
    the qualified form. Without this, a pattern that matches nothing reports a
    clean sweep — the vacuity class this repo keeps re-finding."""
    pattern = re.compile(
        r"(?:Copy|copy|Open|open|Edit|edit|Write|write|Create|create)\s+"
        r"`?WORKFLOW(?:_GUIDE)?\.md`?"
    )
    assert pattern.search("1. Copy WORKFLOW.md, WORKFLOW_GUIDE.md, and this manifest")
    assert pattern.search("Open `WORKFLOW_GUIDE.md` and read § 2")
    # A citation is not a path claim and must not be swept up.
    assert not pattern.search("see WORKFLOW.md § 4.2 for the full contract")
    assert not pattern.search("documented canonically in WORKFLOW.md § 8.2a")
