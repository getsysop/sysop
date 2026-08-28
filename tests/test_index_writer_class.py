"""Phase 201 — the `tasks/index.yml` writer class.

Five code paths rewrite `tasks/index.yml` whole through `yaml.safe_dump`. That
class was described in a filing and reasoned about in three phases, and **nothing
in the suite pinned it**: `git grep "width=120" -- tests/` returned zero hits
before this file existed.

**This module was rewritten by the phase's own review round, which found the
first version largely decorative: an independent battery ran 36 defect mutations
against it and 30 survived, while 9 of 11 negative controls false-killed.** The
comments below record what each guard is shaped that way *for*, because the
shapes that failed are the ones a later author will reach for again.

Four structural lessons, each now built in:

1. **Scope code assertions to the code.** The first version grepped the whole
   1200-line `review-close/SKILL.md`, so `os.replace(tmp, p)` written in a
   *comment* satisfied the atomicity check while the code below it truncated in
   place. Everything about Step 4c now runs against the extracted heredoc body.
2. **Pin load-bearing prose verbatim; do not token-check it.** A window check for
   the words "comment" and "read" passes on a sentence asserting the exact
   opposite — and negation, not deletion, is the shape that ships. The clauses in
   `PINS` are whitespace-normalised verbatim; rewording one is meant to be a
   deliberate act that updates the pin.
3. **Derive populations, then check the derivation reaches.** A file count is not
   a line count: the first title scan read 52 files and inspected 6 `title:`
   lines, while certifying breadth it did not have.
4. **Membership is not equality.** `"width=120" in "width=1200"` is true, so the
   identical-kwargs invariant missed the one drift that reads as a typo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

CANONICAL_KWARGS = {
    "sort_keys": "False",
    "default_flow_style": "False",
    "allow_unicode": "True",
    "width": "120",
}

INDEX_WRITERS = {
    "core/skills/claim-task/SKILL.md",       # Step 4a: open -> in_progress
    "core/skills/auto-build/SKILL.md",       # Step 5.1: open -> in_progress
    "core/companion/scripts/claim_task.sh",  # --release: in_progress -> open
    "core/skills/review-close/SKILL.md",     # Step 4c: -> done + completed_date + body
    "core/companion/scripts/backfill_completed_dates.py",
    "core/companion/scripts/clear_user_action.py",  # Q-314: user_action true -> false
}

# `safe_dump` sites in the shipped tree that do NOT write the task index.
NON_INDEX_DUMP_SITES = {"install.sh"}

SHIPPED_ROOTS = ("core", "packs")

# The quoting rule's population, as a PARTITION of a derived universe rather than
# a hand roster. See § "The authoring class" below for why it is shaped this way.
#
# Phase 204: the constant that used to sit here (`AUTHORING_SKILLS`, three files)
# was DEAD — Phase 201's own review round deleted both of its consumers and
# re-added the definition, so for three phases it read as coverage while binding
# nothing, and `/document-work` sat outside it unnoticed. A roster that no test
# reads is worse than no roster: it answers the question "is this guarded?" wrong.
TITLE_AUTHORING = {
    "core/skills/add-task/SKILL.md",
    "core/skills/intake/SKILL.md",
    "core/skills/onboard/SKILL.md",
    "core/skills/document-work/SKILL.md",  # Step 3b — added Phase 204
    "core/companion/tasks/README.md",
    "core/companion/tasks/schema.md",  # the `title` row — added Phase 204
}

# The rest of the universe: they name the index but never ask a reader to compose
# an entry. `install.sh` is here on purpose — it *writes* a seed, but the seed is
# a fixed template already covered by `test_every_shipped_title_template_is_quoted`,
# and no human authors a title from it.
INDEX_READERS = {
    "core/companion/.claude/settings.json",
    "core/companion/docs/WORKFLOW.md",
    "core/companion/docs/WORKFLOW_GUIDE.md",
    "core/companion/git-hooks/examples/pre-commit-tasks-validate.example",
    "core/companion/scripts/backfill_completed_dates.py",
    "core/companion/scripts/claim_task.sh",
    "core/companion/scripts/clear_user_action.py",
    "core/companion/scripts/next_task.py",
    "core/companion/scripts/scope_overlap.py",
    "core/companion/scripts/sitrep_survey.py",
    "core/companion/scripts/validate_tasks.py",
    "core/skills/_shared/adversarial-review.md",
    "core/skills/auto-build/SKILL.md",
    "core/skills/claim-task/SKILL.md",
    "core/skills/codebase-review/SKILL.md",
    "core/skills/daily-summary/SKILL.md",
    "core/skills/release/SKILL.md",
    "core/skills/review-close/SKILL.md",
    "core/skills/roadmap/SKILL.md",
    "core/skills/security-audit/SKILL.md",
    "core/skills/sitrep/SKILL.md",
    "install.sh",
    "packs/python/companion/checks.yml.fragment",
    "packs/python/companion/convention_map.md",
}

TASKS_README = "core/companion/tasks/README.md"


def _flat(text: str) -> str:
    """Whitespace-normalised, so a reflow never reds a pin but a reword does.

    `*` is stripped too (Phase 204). Without that, every pin below is keyed to
    where the author put bold and italic rather than to the claim: re-wrapping
    two words of a pinned clause in `**` silently disarms the guard, and it
    passes. That is the over-strict direction, and it reads as a green test.
    Phase 203 shipped a headline guard beaten by exactly one `*` between two
    words, and its round then found seven more separators doing the same.

    Only `*` — never `_`, which in this repo is overwhelmingly part of an
    identifier (`tasks/index.yml`'s siblings, `safe_dump`, `_sanitize_log`), so
    stripping it would make several pins unsatisfiable rather than robust. The
    cost of that choice, which the round measured: swapping a pinned clause's
    `*read*` to the equally-legal `_read_` reds the suite. Accepted — a pin is
    meant to make rewording deliberate — but it is a cost, not a free win.

    **HTML comments are removed before matching** (Phase 204, round finding). A
    pin is a membership check, so wrapping the rule in `<!-- … -->` satisfied
    every pin in this module while the reader saw nothing. This repo uses HTML
    comments routinely, and "temporarily" commenting out guidance is an ordinary
    edit — it was the cheapest full bypass the round found.
    """
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    return " ".join(text.replace("*", "").split())


def _shipped_files() -> list[Path]:
    files = [REPO_ROOT / "install.sh"]
    for root in SHIPPED_ROOTS:
        files.extend(p for p in (REPO_ROOT / root).rglob("*") if p.is_file())
    return files


# --------------------------------------------------------------------------
# The writer class
# --------------------------------------------------------------------------


def _balanced_call(text: str, open_idx: int) -> str:
    depth = 0
    for i in range(open_idx, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return " ".join(text[open_idx + 1 : i].split())
    raise AssertionError("unbalanced dump call")


# The paren is required, or PROSE mentions of `yaml.safe_dump` count as writer
# sites — the first draft counted tasks/README.md and claim-task's own doctrine
# sentence, then walked the paren-balancer onto whatever paren came next.
_DUMP_CALL = re.compile(r"\byaml\.safe_dump\s*\(")

# Spellings that are the same writer wearing a different name. The round added a
# whole-file writer four ways that `yaml.safe_dump(` cannot see — an aliased
# import, an aliased module, `yaml.dump(..., Dumper=yaml.SafeDumper)`, and a
# `getattr` — and the population test passed on all four.
_DUMP_ALIASES = (
    # `\bdump\b` does NOT match inside `safe_dump` — `_` is a word character, so
    # the boundary never falls there. That single missing alternation let the one
    # surviving smuggling route through on the re-run.
    re.compile(r"from\s+yaml\s+import\b[^\n]*(safe_)?dump\b"),
    re.compile(r"\byaml\.dump\s*\("),
    re.compile(r"getattr\s*\(\s*yaml\b"),
)
# `import yaml as X` is only a smuggling route if X is then used to dump.
# `scope_overlap.py` aliases yaml purely to probe that it imports, and an
# unconditional ban on the alias flagged that legitimate use — the
# over-strictness direction, caught by running the guard against the real tree.
_ALIASED_MODULE = re.compile(r"import\s+yaml\s+as\s+(\w+)")


def _fenced_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) offsets of ``` fenced code blocks. An unterminated fence runs
    to EOF rather than being dropped — a state machine's worst answer on input
    that never closes should be the conservative one."""
    spans, opened = [], None
    pos = 0
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            if opened is None:
                opened = pos + len(line)
            else:
                spans.append((opened, pos))
                opened = None
        pos += len(line)
    if opened is not None:
        spans.append((opened, len(text)))
    return spans


def _dump_sites() -> dict[str, list[str]]:
    sites: dict[str, list[str]] = {}
    for path in _shipped_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # In markdown, only a call inside a fenced code block is a writer. A prose
        # mention with parentheses (`WORKFLOW.md` has one) is documentation, and
        # counting it as a sixth writer is a false positive a control caught.
        fenced = _fenced_spans(text) if path.suffix == ".md" else None
        calls = [
            _balanced_call(text, m.end() - 1)
            for m in _DUMP_CALL.finditer(text)
            if fenced is None or any(a <= m.start() < b for a, b in fenced)
        ]
        if calls:
            sites[str(path.relative_to(REPO_ROOT))] = calls
    return sites


def test_the_index_writer_population_is_exactly_the_five_named_here():
    found = set(_dump_sites())
    assert found == INDEX_WRITERS | NON_INDEX_DUMP_SITES, (
        "the set of yaml.safe_dump sites in the shipped tree changed.\n"
        f"  expected: {sorted(INDEX_WRITERS | NON_INDEX_DUMP_SITES)}\n"
        f"  found:    {sorted(found)}"
    )


def test_no_shipped_file_dumps_yaml_under_another_name():
    """The population above is keyed to one spelling. This closes the aliases.

    Not exhaustive by construction — no pattern can be — but it covers the four
    forms an independent battery actually used to smuggle a sixth whole-file
    writer past the population test.
    """
    offenders: list[str] = []
    for path in _shipped_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = str(path.relative_to(REPO_ROOT))
        for pat in _DUMP_ALIASES:
            for m in pat.finditer(text):
                line = text[: m.start()].count("\n") + 1
                offenders.append(f"{rel}:{line}: {m.group(0)}")
        for m in _ALIASED_MODULE.finditer(text):
            alias = m.group(1)
            if re.search(rf"\b{re.escape(alias)}\.(safe_)?dump\s*\(", text):
                line = text[: m.start()].count("\n") + 1
                offenders.append(f"{rel}:{line}: {alias}.dump via aliased module")
    assert offenders == [], (
        "a shipped file reaches yaml's dumper under an alias, so the writer-"
        "population test above cannot see it:\n  " + "\n  ".join(offenders)
    )


def test_the_population_scan_is_not_vacuous():
    sites = _dump_sites()
    assert len(sites) >= 6, f"scan found only {len(sites)} files with safe_dump"
    assert sum(len(v) for v in sites.values()) >= 6
    for path, calls in sites.items():
        assert all(call.strip() for call in calls), f"empty call body in {path}"


def _kwargs_of(call: str) -> dict[str, str]:
    """Parse `k=v` pairs. Equality, not membership.

    `"width=120" in "width=1200"` is true, so a substring check misses the one
    kwargs drift that reads as a typo — which is exactly the mutation that
    survived the first version of this file.
    """
    out: dict[str, str] = {}
    for m in re.finditer(r"(\w+)\s*=\s*([^,()\s]+)", call):
        out[m.group(1)] = m.group(2)
    return out


@pytest.mark.parametrize("writer", sorted(INDEX_WRITERS))
def test_every_index_writer_carries_the_canonical_kwargs(writer: str):
    calls = _dump_sites()[writer]
    assert calls, f"no safe_dump call found in {writer}"
    for call in calls:
        kw = _kwargs_of(call)
        for key, value in CANONICAL_KWARGS.items():
            assert kw.get(key) == value, (
                f"{writer}: safe_dump has {key}={kw.get(key)!r}, expected {value!r}"
            )
        extra = set(kw) - set(CANONICAL_KWARGS) - {"f", "data", "d"}
        assert not extra, f"{writer}: safe_dump grew kwargs {sorted(extra)}"


def test_the_kwargs_check_distinguishes_a_value_from_a_prefix_of_it():
    """Negative control for the equality fix above."""
    assert _kwargs_of("data, f, width=1200")["width"] == "1200"
    assert _kwargs_of("data, f, width=120")["width"] == "120"
    assert _kwargs_of("data, f, width=120, canonical=True").get("canonical") == "True"


# --------------------------------------------------------------------------
# The seed
# --------------------------------------------------------------------------


def _seed_body() -> str:
    text = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    start = text.index('cat > "$idx" <<\'EOF\'')
    body_start = text.index("\n", start) + 1
    return text[body_start : text.index("\nEOF\n", body_start)]


def _uncommented(line: str) -> str:
    """Strip quoted spans so a `#` inside a quoted scalar is not read as a comment.

    **An unterminated quote disables the stripping entirely**, which is the whole
    point: the first version treated the apostrophe in the seed's own plain scalar
    (`your first sprint's narrative`) as an opening quote that never closed, so
    everything after it — a real trailing comment included — was discarded before
    the predicate ran. A state machine written for well-formed input gives its
    worst answer on input that never closes, and gives it silently.
    """
    out, quote = [], None
    for ch in line:
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
            continue
        out.append(ch)
    if quote is not None:  # unterminated — the strip is not trustworthy
        return line
    return "".join(out)


def _comment_offenders(body: str | list[str]) -> list[str]:
    """Lines carrying a YAML comment.

    Lines inside a block scalar are skipped: their content is literal data, so a
    markdown `### heading` in a `sprint_note: |` is not a comment and flagging it
    is over-strictness — the direction that hides, caught by a negative control.
    """
    lines = body.splitlines() if isinstance(body, str) else list(body)
    out: list[str] = []
    block_indent: int | None = None
    for line in lines:
        indent = len(line) - len(line.lstrip())
        if block_indent is not None:
            if line.strip() == "" or indent > block_indent:
                continue  # still inside the block scalar's literal content
            block_indent = None
        if re.search(r":\s*[|>][-+0-9]*\s*$", line):
            block_indent = indent
            continue
        if "#" in _uncommented(line):
            out.append(line)
    return out


def test_the_seeded_index_carries_no_comments():
    """Reversion guard. The seed used to carry 22 comment lines, including a full
    reference block, and the first whole-file write reserialized every one away."""
    offenders = _comment_offenders(_seed_body())
    assert offenders == [], (
        "install.sh's tasks/index.yml seed grew a comment. Every writer of that "
        "file rewrites it whole via safe_dump, so a seeded comment is destroyed "
        "by the first write. Put the guidance in "
        "core/companion/tasks/README.md, which is a managed path.\n"
        f"  offending lines: {offenders}"
    )


def test_the_comment_strip_survives_an_apostrophe():
    """Non-vacuity + the specific hole the round found.

    The seed itself contains an apostrophe, so this is not a hypothetical.
    """
    assert "'" in _seed_body(), "seed no longer exercises the apostrophe path"
    # A trailing comment on a line containing an apostrophe must still be seen.
    assert _comment_offenders(["  note: don't do this  # seeded comment"]) != []
    # A `#` inside a properly quoted scalar must still be ignored.
    assert _comment_offenders(['  title: "Fix the widget #482"']) == []


def test_the_seed_guard_can_see_a_comment():
    body = _seed_body()
    assert "schema_version: 1" in body and "tasks: []" in body
    assert _comment_offenders((body + "\n# a helpful note").splitlines()) != []
    assert _comment_offenders((body + "\ntasks: []  # trailing").splitlines()) != []


def test_the_heredoc_is_the_only_route_that_seeds_the_index():
    """The seed guard reads one heredoc. An append after it is a second route,
    and the round used exactly that to put a comment back into `index.yml`."""
    text = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    writes = re.findall(r'>>?\s*"\$idx"', text)
    assert writes == ['> "$idx"'], (
        "install.sh writes tasks/index.yml by more than the one seeding heredoc "
        f"the guard above reads: {writes}"
    )


def test_the_seed_still_parses_and_carries_the_shape_a_consumer_needs():
    yaml = pytest.importorskip("yaml")
    d = yaml.safe_load(_seed_body())
    assert d["schema_version"] == 1
    assert d["tasks"] == []
    assert sum(1 for p in d["phases"] if p.get("current_focus")) == 1


def test_the_skill_authored_index_skeleton_carries_no_comments_either():
    """`/intake` Step 7 writes a whole `index.yml` on a fresh project — the other
    seeding route into a consumer's index, and one the installer guard cannot see."""
    text = (REPO_ROOT / "core/skills/intake/SKILL.md").read_text(encoding="utf-8")
    start = text.index("     schema_version: 1")
    end = text.index("     ```", start)
    offenders = _comment_offenders(text[start:end])
    assert offenders == [], (
        "/intake's index.yml skeleton grew a comment; it dies on the first "
        f"whole-file write exactly as a seeded one does: {offenders}"
    )


# --------------------------------------------------------------------------
# The authoring class — a derived universe, partitioned by a named roster
# --------------------------------------------------------------------------
#
# Phase 204. `Q-209` asked for `AUTHORING_SKILLS` to be "derived from the tree".
# It cannot be, and the attempt is the interesting part of this section.
#
# **No mechanical predicate separates authoring paths from readers.** Five were
# probed against the tree before this shape was chosen, by
# `tools/phase204_predicate_probe.py` — run it to reproduce these, and read its
# docstring first, because the counts move with the ground-truth set and the
# population and the numbers here are meaningless without both. Against ground
# truth = the 4 authoring SKILLS and population = the 25 git-tracked core/packs
# files naming the index: "says file/create an entry" (16 FP, 1 miss), "names id
# and title together" (3 FP, 1 miss), "says new entry" (3 FP, 2 misses), "carries
# a literal `title:` key" (4 FP, 3 misses), "names `tasks/open/`" (4/4 recall but
# 7 FP). Every one either misses a known authoring path or drags in files that
# only read the index. "This surface tells a reader to compose a task entry" is a
# judgement, and encoding a judgement as a regex produces a guard that is
# confidently wrong.
#
# So the derivation does not classify. It derives the UNIVERSE — every shipped
# file that names the task index, which is sound by construction, since you
# cannot instruct someone to author an index entry without naming the index —
# and asserts set-equality against the partition above. Membership is named;
# *drift* is detected. A new file entering or leaving the universe reds and a
# human decides which half it belongs in.
#
# This is the same shape as `test_the_index_writer_population_is_exactly_the_five
# _named_here` at the top of this module, and it is used here for the same
# reason: the alternative is a roster with a countdown on it.
#
# The soundness argument above is about the INDEX being named; the pattern below
# is the argument's encoding, and Phase 204's round filed it (`Q-214` leg 4) for
# being narrower than the argument it implements. It was anchored to the full
# path `tasks/index.yml`, so a new surface writing "the task index (`index.yml`)"
# never entered the universe and the tripwire never fired — the file owed the
# quoting rule and nothing said so. Verified before the widening: the bypass
# surface passed at 65 green; after it, the tripwire names the file.
#
# The widening costs nothing here, because on this tree the strict and loose
# universes are the SAME 29 files, verified by deriving both and diffing — so
# this is prophylaxis against a surface nobody has written yet, not a fix to a
# live gap. Read it that way before citing it as one.
#
# What it still does NOT reach, stated so the next reader does not have to
# rediscover it: the match is case-sensitive (`INDEX.yml` escapes), extension-
# bound (`index.yaml` escapes), and filename-bound — a surface naming the index
# in prose alone ("the task index under `tasks/`") never enters the universe.
# That residue is the blacklist-over-English problem `Q-214` legs (1)-(3) park;
# it is not fixable by widening this pattern further, and widening it toward
# prose is how the false-fire class gets minted. No shipped file uses any of
# those spellings today.

_NAMES_INDEX = re.compile(r"\bindex\.yml\b")


def _index_naming_files() -> set[str]:
    """Every shipped file that names `tasks/index.yml`. The universe, derived."""
    found = set()
    for path in _shipped_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if _NAMES_INDEX.search(text):
            found.add(str(path.relative_to(REPO_ROOT)))
    return found


def test_the_index_naming_universe_is_exactly_the_partition():
    """The tripwire. Drift reds; it does not silently re-scope the guard below.

    If this fails, a shipped file started or stopped naming the task index.
    Decide which half it belongs in and add it — do NOT widen the derivation to
    make the failure go away. A file that instructs an author belongs in
    `TITLE_AUTHORING` and then owes the quoting rule; one that only reads the
    index belongs in `INDEX_READERS`.
    """
    found = _index_naming_files()
    named = TITLE_AUTHORING | INDEX_READERS
    assert found == named, (
        "the set of shipped files naming `tasks/index.yml` changed.\n"
        f"  entered the universe (classify these): {sorted(found - named)}\n"
        f"  left the universe (drop these):        {sorted(named - found)}"
    )


def test_the_universe_pattern_reaches_more_than_the_full_path():
    """Reach control for the widening — without it, nothing detects a revert.

    On this tree the strict pattern (`tasks/index.yml`) and the widened one
    select the SAME 29 files, so re-narrowing it reds nothing: measured, the
    revert survived the whole module. The widening's entire value is against a
    surface nobody has written yet, which means the only thing that can hold it
    in place is a direct assertion about the pattern's reach.

    The spellings below are the ones the filed bypass actually used.
    """
    reached = "append an entry to the task index (`index.yml`)"
    assert _NAMES_INDEX.search(reached), (
        "the universe pattern no longer matches a bare `index.yml`, so a file "
        "naming the index that way is invisible to the tripwire and silently "
        "owes none of the authoring obligations. This is `Q-214` leg (4); do "
        "not re-anchor the pattern to the full path."
    )
    assert _NAMES_INDEX.search("see `tasks/index.yml` for the schema"), (
        "the universe pattern stopped matching the full path — the widening was "
        "supposed to ADD reach, not trade it."
    )
    # The two asserts above pin two LITERALS, and the round walked them by
    # OR-ing the pre-phase pattern with the control's own string — satisfying
    # both while a real new file writing `index.yml` bare still never entered
    # the universe. Delimiter-anchored narrowings (`[/`]index\.yml\b`) do the
    # same. So the reach has to be probed where no delimiter helps.
    assert _NAMES_INDEX.search("append an entry to index.yml today"), (
        "the universe pattern only matches `index.yml` when a delimiter sits "
        "beside it — a backtick, a slash, a parenthesis. A surface writing the "
        "filename bare in a sentence is then invisible to the tripwire, which "
        "is the leg-(4) bypass wearing a narrower mask. Match the filename, "
        "not the punctuation around it."
    )


def test_the_partition_is_a_partition():
    """The halves must not overlap, or a file could be 'authoring' and exempt."""
    both = TITLE_AUTHORING & INDEX_READERS
    assert both == set(), f"named in both halves of the partition: {sorted(both)}"


def test_the_universe_derivation_is_not_vacuous():
    """Vacuity + reach control.

    An empty derivation satisfies the equality above only if both roster halves
    are also empty — but a derivation that silently read nothing (a bad glob, an
    encoding bail) would then be certifying breadth it does not have. This pins
    that it reads a real corpus and reaches every kind of shipped surface the
    universe actually spans, not just markdown.
    """
    found = _index_naming_files()
    assert len(found) >= 25, f"universe is only {len(found)} files"
    assert TITLE_AUTHORING <= found, (
        "a named authoring surface does not name `tasks/index.yml` — the "
        f"derivation cannot see it: {sorted(TITLE_AUTHORING - found)}"
    )
    exts = {Path(f).suffix for f in found}
    assert {".md", ".py", ".sh"} <= exts, (
        f"the universe scan misses a shipped file kind: {sorted(exts)}"
    )


# The authoring half, pinned member-by-member. The round demonstrated why this
# is not redundant with the tripwire above: it collapsed `TITLE_AUTHORING` to one
# file, moved the other five into `INDEX_READERS`, dropped their `PINS` and
# `RULE_STATED` entries in the same edit, deleted the quoting rule outright from
# four shipped files — and the suite stayed GREEN, 3,704 passed.
#
# The union never changed, so `found == named` held; and tying the three
# constants together is satisfied by editing all three at once, which is a
# mechanical follow-through rather than an obstacle. **It is also precisely the
# edit that created `Q-209`** — Phase 201's round deleted the consumers.
#
# So the tripwire detects universe *drift*, not *reclassification*, and the
# record's "the alternative is a roster with a countdown on it" was too kind to
# this design: the countdown is still here. What this constant buys is that
# removing a member is now a visible, deliberate act in a file whose whole
# subject is that rosters rot.
EXPECTED_TITLE_AUTHORING = frozenset({
    "core/skills/add-task/SKILL.md",
    "core/skills/intake/SKILL.md",
    "core/skills/onboard/SKILL.md",
    "core/skills/document-work/SKILL.md",
    "core/companion/tasks/README.md",
    "core/companion/tasks/schema.md",
})


def test_the_authoring_half_is_exactly_these_six():
    """`Q-209` stated as an assertion rather than as a comment.

    A file may only leave this roster by editing this literal, which is the
    deliberate act the phase wants. Adding one is equally visible, and then
    `test_the_rule_population_is_the_authoring_roster_itself` forces a pattern
    and a pin for it in the same edit.
    """
    assert TITLE_AUTHORING == set(EXPECTED_TITLE_AUTHORING), (
        "the authoring roster changed.\n"
        f"  removed: {sorted(set(EXPECTED_TITLE_AUTHORING) - TITLE_AUTHORING)}\n"
        f"  added:   {sorted(TITLE_AUTHORING - set(EXPECTED_TITLE_AUTHORING))}\n"
        "Reclassifying a file out of the authoring half silently drops its "
        "quoting rule — that is the Q-209 regression, and it is the one edit "
        "the universe tripwire cannot see."
    )


@pytest.mark.parametrize("path", sorted(EXPECTED_TITLE_AUTHORING))
def test_no_authoring_surface_is_reclassified_as_a_reader(path: str):
    """The other direction, per-file so the failure names the file."""
    assert path not in INDEX_READERS, (
        f"{path} was moved into INDEX_READERS, which exempts it from the "
        "quoting rule entirely while leaving the derived universe unchanged"
    )


# --------------------------------------------------------------------------
# Prose that carries the fix — pinned verbatim, because negation is the shape
# --------------------------------------------------------------------------

# Each clause is load-bearing: remove or negate it and the fix stops being taught.
# Whitespace-normalised, so reflow and rewrap pass; a reword is meant to red.
#
# Two tiers, because one tier got the tradeoff wrong in both directions.
#
# `PINS` holds only clauses whose *negation* is the failure — short, and chosen so
# an inverted sentence cannot contain them. Pinning the whole rule sentence also
# worked, but it false-killed ordinary rewordings ("Always quote the `title:`",
# an emphasis change), which pressures the next author toward vaguer language.
PINS: dict[str, tuple[str, ...]] = {
    "core/skills/add-task/SKILL.md": (
        "YAML reads ` #` (space then hash) as the start of a comment",
        "lands on disk as `Fix the widget`",
    ),
    "core/skills/intake/SKILL.md": (
        "YAML reads ` #` (space then hash) as the start of a comment",
        "the loss happens at *read* time, before any writer touches the file",
    ),
    "core/skills/onboard/SKILL.md": (
        "YAML reads ` #` (space then hash) as the start of a comment",
        "with the rest gone the first time anything reads the file",
    ),
    TASKS_README: (
        "treats ` #` — space then hash — as the start of a comment",
        "Quoting is the whole defence",
        "### Comments in `index.yml` do not survive",
        "every comment is stripped, quoting is normalised, indentation is rewritten",
        # Inverting this re-seeds the defect the template was moved to escape.
        "Copy the fields, not the comments.",
    ),
    # Phase 204 — the fourth authoring path. The second clause is the one whose
    # negation is the whole defect: an author who believes a template exists
    # goes looking for one instead of applying the rule, and Step 3b ships none.
    "core/skills/document-work/SKILL.md": (
        "YAML reads ` #` (space then hash) as the start of a comment",
        "the title it asks for is composed here, by hand, with no template to copy",
        "an issue number, a PR number or a heading fragment in the title is the "
        "ordinary case rather than the edge one",
    ),
    # Phase 204 — the reference the other paths route an author to. Its negation
    # is the row saying nothing, which is the state Q-209 found it in.
    "core/companion/tasks/schema.md": (
        "YAML reads ` #` (space then hash) as the start of a comment",
        "the validator stays green because what survives is still a legal title",
    ),
}

# `RULE_STATED` holds the same requirement at the level of meaning, so the rule
# cannot simply be deleted while the reason clause survives. Loose on wording.
# The round found this pattern wrong in BOTH directions, which is the shape that
# reads as a working guard. It matched the substring inside "**Never** quote the
# `title:`" — a statement of the opposite rule — while rejecting five ordinary
# rewordings including "Every `title:` you write must be quoted". So it accepted
# the negation and false-killed the reword: exactly the failure the module
# docstring credits the two-tier scheme with fixing, alive inside the mechanism.
#
# Split in two. `_QUOTE_RULE` is deliberately generous about phrasing (a rule can
# be written imperative or passive), and `_QUOTE_NEGATORS` is the screen that
# stops generosity from swallowing the inversion.
_QUOTE_RULE = re.compile(
    r"quote (?:every|the|each|all)[^.]{0,30}`title:`"
    r"|`title:`[^.]{0,60}?(?:must|should|has to|needs? to)[^.]{0,30}?quoted"
    r"|quote[^.]{0,30}`title:`[^.]{0,30}(?:you write|values?)",
    re.I,
)

# Sentence-scoped, and required to be about a TITLE. Both constraints were bought
# with false fires the moment the first version ran against the real tree:
#
#   * "…don't overwrite. Quote every `title:` you write" — `/add-task`. A window
#     of N words crosses a sentence boundary, so a negator in the PREVIOUS
#     sentence suppressed a correct rule in the next one.
#   * "Don't quote an item count here" — `/onboard`. A different sense of the
#     word entirely, nothing to do with YAML titles.
#
# So: same sentence, and `title` must be in it. The pattern is deliberately not
# clever about which side the negator falls on — "quoting … is optional" and
# "never quote …" are both inversions, and word order is not the signal.
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_NEGATOR = re.compile(
    r"\b(?:never|do not|don't|does not|need not|no need|not required|"
    r"unnecessary|optional|a style preference|avoid|refrain from)\b",
    re.I,
)
_QUOTE_WORD = re.compile(r"\bquot(?:e|es|ed|ing)\b", re.I)


# Co-occurrence inside a sentence is NOT the signal — that was the second false
# fire, on `tasks/README.md`'s own correct line "…that is the unquoted-title case
# above, and quoting is its fix. What does not survive the dump is…", where a
# negator and a quote-word share a sentence while modifying different verbs. The
# negator has to actually ATTACH to the quote word, so proximity is bounded to a
# few words in either order.
_NEG_ATTACHED = re.compile(
    r"(?:{neg})(?:\W+\w+){{0,2}}\W+{q}"          # never quote / do not ever quote
    r"|{q}(?:\W+\w+){{0,3}}\W+(?:is|are)\W+(?:{neg})".format(  # quoting … is optional
        neg=r"never|do not|don't|does not|need not|no need(?: to)?|not required(?: to)?"
            r"|unnecessary|optional|a style preference|avoid|refrain from",
        q=r"quot(?:e|es|ed|ing)",
    ),
    re.I,
)


def _negated_quote_sentences(flat: str) -> list[str]:
    """Sentences that tell the reader NOT to quote a title.

    Three conditions, each bought with a measured false fire: same sentence (a
    window crosses `. `), `title` present (`/onboard`'s "Don't quote an item
    count" is a different sense), and the negator grammatically attached to the
    quote word (README's correct line pairs a negator with a different verb).
    """
    out = []
    for sentence in _SENTENCE_SPLIT.split(flat):
        if "title" in sentence.lower() and _NEG_ATTACHED.search(sentence):
            out.append(sentence.strip())
    return out

RULE_STATED: dict[str, re.Pattern[str]] = {
    "core/skills/add-task/SKILL.md": _QUOTE_RULE,
    "core/skills/intake/SKILL.md": _QUOTE_RULE,
    "core/skills/onboard/SKILL.md": _QUOTE_RULE,
    "core/skills/document-work/SKILL.md": _QUOTE_RULE,  # Phase 204
    "core/companion/tasks/schema.md": _QUOTE_RULE,  # Phase 204
    TASKS_README: re.compile(r"quote the title", re.I),
}


def test_the_rule_population_is_the_authoring_roster_itself():
    """The hole `AUTHORING_SKILLS` left, closed at the level that caused it.

    Both dicts below are parametrized over their own keys, so a file added to
    `TITLE_AUTHORING` without an entry here would simply never be checked — the
    roster would grow and the guard would not, which is exactly how a dead
    constant reads as coverage. Tying the populations together means adding an
    authoring path forces a rule pattern and a pin for it, in the same edit.
    """
    assert set(RULE_STATED) == TITLE_AUTHORING, (
        "RULE_STATED and TITLE_AUTHORING disagree.\n"
        f"  in the roster, unchecked: {sorted(TITLE_AUTHORING - set(RULE_STATED))}\n"
        f"  checked, not in roster:   {sorted(set(RULE_STATED) - TITLE_AUTHORING)}"
    )
    assert set(PINS) == TITLE_AUTHORING, (
        "PINS and TITLE_AUTHORING disagree.\n"
        f"  in the roster, unpinned: {sorted(TITLE_AUTHORING - set(PINS))}\n"
        f"  pinned, not in roster:   {sorted(set(PINS) - TITLE_AUTHORING)}"
    )


def _missing_pins(clauses: tuple[str, ...], flat: str) -> list[str]:
    """The pin predicate, hoisted so the guard and its control share it.

    `Q-214` leg (5): blanking `PINS[path]` to `()` left the whole suite green,
    and so did reducing the `RULE_STATED` search below to `is not None`. The
    roster cross-check above cannot see either — it compares KEY sets, and both
    mutations leave the keys intact.

    Hoisting alone does not fix it, and the shape that looks right does not
    work. A control that feeds this predicate its own synthetic clauses never
    touches `PINS`, so blanking `PINS` still survives — measured, at 66 green.
    That is the difference from `_states_the_subset_as_the_population` in
    `tests/test_roadmap_batch_survey.py`, which this was modelled on: that
    guard's data is DERIVED, so a control re-derives it and observes the real
    thing. A literal roster has to be observed directly.

    So the control below runs synthetic gutted INPUT through the REAL roster,
    and asserts the roster is non-empty in the same breath. Both halves are
    load-bearing: the emptiness assert catches blanked data, the gutted-document
    assert catches a weakened predicate.
    """
    return [clause for clause in clauses if _flat(clause) not in flat]


@pytest.mark.parametrize("path", sorted(PINS))
def test_the_negation_sensitive_clauses_are_present_verbatim(path: str):
    """A token check for "comment" and "read" passes on a sentence asserting the
    opposite — the round inverted the rule in all three skills and in the README
    and every one stayed green. These clauses are what catch negation."""
    flat = _flat((REPO_ROOT / path).read_text(encoding="utf-8"))
    missing = _missing_pins(PINS[path], flat)
    assert missing == [], (
        f"{path} no longer carries a clause whose negation is the defect. If you "
        "reworded it deliberately, update PINS in this file — that is the point "
        f"of the pin, not an obstacle to it.\n  missing: {missing}"
    )


# A pin is a MEMBERSHIP check, and membership is not uniqueness. The author-side
# battery negated `/document-work`'s reason clause in the prose and the pin stayed
# green, because the same clause also appears in Step 3b's error message — one
# copy satisfied the pin while the other told the reader the opposite. Pinning
# presence cannot see that; forbidding the inversion can.
# **This blacklist is not exhaustive, and cannot be — no pattern over English is.**
# Saying so is not a formality: the first version of this tuple had four entries,
# its docstring asserted the mechanism worked, and the round wrote NINE plausible
# inversions that all passed ("YAML treats ` #` as ordinary text", "the hash and
# everything after it is preserved", "No truncation occurs", "an unquoted title
# round-trips exactly", …). The nine are folded in below and the residual is now
# declared, matching `_BLOCK_SCALAR_FALSEHOODS`, which got this right first.
#
# What this tier IS: a cheap screen for the inversions people actually write.
# What it is NOT: a proof that the reason is stated correctly. The load-bearing
# guard is `PINS` — a verbatim clause whose *presence* is checked — and this
# catches the case where the clause survives and a contradiction is added beside it.
_REASON_INVERSIONS = (
    r"YAML (?:does not|doesn't|never) read",
    r"YAML (?:treats|reads) ` ?#`[^.]{0,40}(?:ordinary|literal|plain) text",
    r"YAML ignores the ` ?#`",
    r"is not the start of a comment",
    r"only applies at the start of a line",
    r"survives? unquoted",
    r"unquoted titles? (?:are|is) safe",
    # These two are TRUE of a quoted title — `tasks/README.md` says both, correctly
    # — so they are only inversions when predicated of an UNQUOTED one. The first
    # version omitted that and false-fired on the reference page itself.
    r"unquoted[^.]{0,60}round-trips exactly",
    r"(?:no|without) truncation[^.]{0,60}unquoted|unquoted[^.]{0,60}(?:no|without) truncation",
    r"nothing is lost[^.]{0,60}(?:unquoted|omit the quotes)",
    r"(?:the hash|everything after it) (?:and everything after it )?is preserved",
    r"quoting (?:is|are) (?:optional|unnecessary|not required|a style preference)",
)


@pytest.mark.parametrize("path", sorted(TITLE_AUTHORING))
def test_no_authoring_surface_states_the_reason_backwards(path: str):
    """Reversal canary across the whole authoring roster.

    Scoped to the roster rather than to the one file that failed: the defect is a
    property of "a surface that teaches this rule", and the next one to acquire a
    second copy of the clause will not be `/document-work`.

    **Known residual, declared rather than discovered later:** this is a
    blacklist over English and cannot be complete. See `_REASON_INVERSIONS`.
    """
    flat = _flat((REPO_ROOT / path).read_text(encoding="utf-8"))
    for inversion in _REASON_INVERSIONS:
        m = re.search(inversion, flat, re.I)
        assert not m, (
            f"{path} states the quoting rule's reason backwards: {m.group(0)!r}. "
            "A pinned clause elsewhere in the file will keep the presence check "
            "green while this sentence teaches the opposite."
        )


def test_the_reversal_canary_fires_on_the_shape_that_survived():
    """Control, both directions, on the shape the battery used.

    (An earlier docstring said "the exact text"; the battery's strings carry no
    `Unquoted, ` prefix. Substantively the same mutation, but not verbatim, and
    the round was right to say so.)
    """
    real = "Unquoted, YAML reads ` #` (space then hash) as the start of a comment"
    negated = "Unquoted, YAML does not read ` #` (space then hash) as the start of a comment"
    fires = lambda s: any(  # noqa: E731
        re.search(inv, _flat(s), re.I) for inv in _REASON_INVERSIONS
    )
    assert not fires(real), "the canary false-fires on the correct sentence"
    assert fires(negated), "the canary misses the negation the battery planted"


def test_flat_normalises_emphasis_so_a_pin_cannot_be_disarmed_by_bold():
    """The `_flat` hardening, guarded.

    Reverting it reds nothing on its own — every clause pinned today happens to
    be plain text — so the battery watched the revert survive. This is the test
    that makes the normalisation a decision rather than an accident: wrapping two
    words of a pinned clause in `**` must not disarm the pin.
    """
    clause = "still a legal title"
    assert _flat(clause) in _flat("what survives is **still a legal** title")
    assert _flat(clause) in _flat("what survives is *still a legal title*")
    assert _flat(clause) in _flat("what survives is still\n  a legal title")
    # …and `_` must survive, or identifiers stop matching.
    assert "safe_dump" in _flat("a `safe_dump` call")


def test_both_copies_of_step_3bs_hard_fail_carry_the_rule():
    """`/document-work` ships the Step 3b block TWICE and only one of them runs.

    The prose block is what a reader sees; the "Reference implementation" heredoc
    at the bottom is the copy-pasteable one an agent actually executes, and it
    prints its own error message. The round's execute lens ran the shipped
    heredoc against a scratch project and found its message carried neither the
    new quoting rule nor the pre-existing "Stub minimum" paragraph — so this
    phase's first cut stated the rule only on the path that does not run, while
    the record claimed it shipped "where the author reads it".

    Nothing had ever compared the two copies. This does, for the one clause that
    matters: both must teach the quoting rule.
    """
    text = (REPO_ROOT / "core/skills/document-work/SKILL.md").read_text(encoding="utf-8")
    marker = "Reference implementation"
    at = text.index(marker)
    prose, runnable = text[:at], text[at:]

    for half, label in ((prose, "the prose block"), (runnable, "the runnable heredoc")):
        assert re.search(r"quote the title", half, re.I), (
            f"{label} of /document-work's Step 3b hard fail no longer tells the "
            "author to quote the title. Both copies teach the same contract; a "
            "rule in only one of them reaches only half the authors, and the "
            "runnable copy is the half that executes."
        )
        assert "space then hash" in half, (
            f"{label} states the quoting rule without its reason — a bare "
            "instruction reads as a style preference and gets dropped."
        )


def _states_the_rule(path: str, flat: str) -> bool:
    """The rule-stated predicate, hoisted so the guard and its control share it.

    Reducing the call site to `RULE_STATED[path] is not None` used to leave the
    suite green (`Q-214` leg 5). Hoisted, that weakening happens HERE, where the
    control below observes it by feeding neutral prose and demanding a miss.
    """
    return RULE_STATED[path].search(flat) is not None


@pytest.mark.parametrize("path", sorted(RULE_STATED))
def test_the_quoting_rule_is_stated(path: str):
    flat = _flat((REPO_ROOT / path).read_text(encoding="utf-8"))
    assert _states_the_rule(path, flat), f"{path} no longer states the quoting rule"
    negated = _negated_quote_sentences(flat)
    assert not negated, (
        f"{path} states the quoting rule NEGATED: {negated!r}. The presence "
        "check above matches the substring inside 'never quote the `title:`', so "
        "without this screen an inverted rule reads as a stated one."
    )


def test_the_rule_pattern_is_wrong_in_neither_direction():
    """Both directions, because the round found this pattern failing both.

    The accepted list is ordinary rewordings a maintainer would actually write;
    the rejected list is the rule inverted. A pattern that fails either way is
    worse than none: it pressures the next author toward vaguer prose while
    certifying the opposite rule as compliant.
    """
    accepted = (
        "**Quote every `title:` you write**",
        "Always quote the `title:` you write",
        "Every `title:` you write must be quoted",
        "`title:` must always be quoted",
        "Quote all `title:` values",
        "Quote the title",
    )
    rejected = (
        "**Never quote the `title:` you write**",
        "**Do not quote the `title:` you write**",
        "You need not quote the `title:` you write",
        "There is no need to quote the `title:` here",
        "Quoting the `title:` is optional",
    )
    for s in accepted:
        flat = _flat(s)
        hit = _QUOTE_RULE.search(flat) or re.search(r"quote the title", flat, re.I)
        assert hit, f"a legitimate rewording is rejected: {s!r}"
        assert not _negated_quote_sentences(flat), f"a correct rule reads as negated: {s!r}"
    for s in rejected:
        assert _negated_quote_sentences(_flat(s)), f"an inverted rule passes: {s!r}"

    # The two false fires the round's over-strictness direction produced, as controls.
    assert not _negated_quote_sentences(
        _flat("don't overwrite. Quote every `title:` you write")
    ), "a negator in the previous sentence suppresses a correct rule"
    assert not _negated_quote_sentences(
        _flat("Don't quote an item count here")
    ), "an unrelated sense of 'quote' reads as an inverted title rule"


def test_a_commented_out_rule_does_not_satisfy_the_pins():
    """The cheapest full bypass the round found, closed in `_flat`."""
    live = "**Quote every `title:` you write** — YAML reads ` #` as a comment"
    hidden = f"<!-- {live} -->"
    assert _QUOTE_RULE.search(_flat(live))
    assert not _QUOTE_RULE.search(_flat(hidden)), (
        "a rule inside an HTML comment still satisfies the presence check — the "
        "reader sees nothing and the guard is green"
    )


def test_the_rule_check_accepts_a_reword_but_the_pin_rejects_an_inversion():
    """The tradeoff, both directions, as controls."""
    rule = RULE_STATED["core/skills/add-task/SKILL.md"]
    assert rule.search("**Quote every `title:` you write**")
    assert rule.search("Always quote the `title:` you write")  # reword must pass
    pinned = "YAML reads ` #` (space then hash) as the start of a comment"
    negated = "YAML does not read ` #` (space then hash) as the start of a comment"
    assert _flat(pinned) not in _flat(negated)


def test_the_readme_names_every_writer_it_warns_about():
    """Scoped to the section. File-wide, four of the five writer names have decoy
    mentions elsewhere in the README, so dropping three of them stayed green."""
    readme = (REPO_ROOT / TASKS_README).read_text(encoding="utf-8")
    start = readme.index("### Comments in `index.yml` do not survive")
    section = _flat(readme[start:])
    # One human-readable fragment per INDEX_WRITERS member, keyed off that
    # constant rather than hand-listed. A writer added there without a README
    # mention now reddens HERE, instead of silently leaving the warning section
    # one writer short — which is how the section came to say "Five" while the
    # population was six (Phase 237, found by its round).
    fragments = {
        "core/skills/claim-task/SKILL.md": "`/claim-task` Step 4a",
        "core/skills/auto-build/SKILL.md": "`/auto-build` Step 5.1",
        "core/companion/scripts/claim_task.sh": "`claim_task.sh --release`",
        "core/skills/review-close/SKILL.md": "`/review-close` Step 4c",
        "core/companion/scripts/backfill_completed_dates.py":
            "`backfill_completed_dates.py`",
        "core/companion/scripts/clear_user_action.py": "`clear_user_action.py`",
    }
    assert set(fragments) == INDEX_WRITERS, (
        "this roster and INDEX_WRITERS disagree — writers with no README "
        f"fragment: {sorted(INDEX_WRITERS - set(fragments))}; fragments for "
        f"non-writers: {sorted(set(fragments) - INDEX_WRITERS)}"
    )
    for fragment in fragments.values():
        assert _flat(fragment) in section, (
            f"the round-trip warning section omits {fragment}"
        )
    words = {4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight"}
    expected = f"{words[len(INDEX_WRITERS)]} code paths rewrite it whole"
    assert expected in section, (
        f"the warning section's count disagrees with INDEX_WRITERS "
        f"({len(INDEX_WRITERS)}): expected {expected!r}"
    )


def test_the_reference_entry_moved_into_the_managed_readme():
    readme = (REPO_ROOT / TASKS_README).read_text(encoding="utf-8")
    assert "Authoring an entry by hand" in readme
    # Quote STYLE is deliberately not pinned — single and double quotes defend
    # equally, and pinning the character false-killed a legal edit.
    assert re.search(r"""title:\s*["']Short human-readable title["']""", readme)
    # Scoped to the template block. File-wide, this forbade *documenting* the
    # non-canonical form the move corrected — a legal edit a control caught.
    template = next(
        readme[a:b] for a, b in _fenced_spans(readme) if "FEAT-EXAMPLE" in readme[a:b]
    )
    assert "body: open/FEAT-EXAMPLE.md" in template
    assert "body: tasks/open/FEAT-EXAMPLE.md" not in template


# --------------------------------------------------------------------------
# The quoting rule's population — every shipped `title:` an agent could copy
# --------------------------------------------------------------------------


def _title_template_files() -> list[Path]:
    """Every shipped surface that can carry a YAML `title:` an agent copies.

    `.md` alone was not enough: the round planted an unquoted title in a `.sh`
    script and in a `.yml` config and both survived. `.py` is handled by its own
    control below, because shipped Python carries ~30 quoted YAML examples plus
    two type annotations.

    `.fragment` and `.example` added Phase 204: `rglob("*.yml")` does NOT match
    `checks.yml.fragment`, and `pre-commit-tasks-validate.example` was reached by
    no glob at all — both sit in the derived index-naming universe, so the scan
    was blind to two files it had already classified as in scope.
    """
    files = [REPO_ROOT / "install.sh"]
    for root in SHIPPED_ROOTS:
        for ext in ("*.md", "*.sh", "*.yml", "*.yaml", "*.fragment", "*.example"):
            files.extend(sorted((REPO_ROOT / root).rglob(ext)))
    return files


# Marker class widened Phase 204. `[\s>#-]` covered `- ` and blockquotes but not
# `* `, `+ ` or an ordered `1. ` — all legal CommonMark bullets, and the round
# planted an unquoted title behind each inside `tasks/README.md`'s own template
# block, the one every authoring path routes the reader to. All three were invisible.
_TITLE_LINE = re.compile(r"^[\s>#*+-]*(?:\d+[.)]\s*)?title:\s*(?P<value>.*?)\s*$")


def _unquoted_titles(paths: list[Path]) -> list[str]:
    """Strip leading list markers, blockquote markers and comment hashes.

    A `title:` behind a `- ` sequence marker was invisible to the first version,
    which required the stripped line to *start with* `title:`. That let a legal
    key reorder put an unquoted title into the installer's own seed.
    """
    out: list[str] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        try:
            rel = path.relative_to(REPO_ROOT)
        except ValueError:
            rel = path  # a probe fixture outside the repo (the tests below)
        for i, line in enumerate(text.splitlines(), 1):
            m = _TITLE_LINE.match(line)
            if not m and line.lstrip().startswith("#"):
                # A commented-out template is still a template an agent copies —
                # `# entry shape: title: Fix the widget #482` survived the strip,
                # because `[\s>#-]*` only reaches a `title:` that comes first.
                m = re.search(r"title:\s*(?P<value>.*?)\s*$", line)
            if not m:
                continue
            value = m.group("value")
            if not value or value.startswith(('"', "'")):
                continue
            if re.fullmatch(r"[A-Za-z_][\w.\[\]| ]*", value):
                continue  # a type annotation, e.g. `title: str`
            out.append(f"{rel}:{i}: {line.strip()}")
    return out


def test_every_shipped_title_template_is_quoted():
    unquoted = _unquoted_titles(_title_template_files())
    assert unquoted == [], (
        "a shipped `title:` template is unquoted — an agent copying it will "
        "author an unquoted title, and ` #` in one is lost at read time:\n  "
        + "\n  ".join(unquoted)
    )


def test_the_title_scan_inspects_lines_not_just_files():
    """A file count is not a line count. The first version asserted `len(files) >
    50` while inspecting six `title:` lines, certifying breadth it did not have."""
    files = _title_template_files()
    assert len(files) > 50, f"title scan corpus is only {len(files)} files"
    inspected = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        inspected += sum(1 for ln in text.splitlines() if _TITLE_LINE.match(ln))
    assert inspected >= 6, f"scan matched only {inspected} title: lines"
    exts = {p.suffix for p in files}
    assert {".md", ".sh", ".yml"} <= exts, f"scan misses a shipped extension: {exts}"


def test_the_title_scan_sees_a_title_behind_a_sequence_marker(tmp_path):
    """The exact shape that let the defect into the installer seed."""
    probe = tmp_path / "probe.md"
    probe.write_text("  - title: Wade's initial phase #1\n    number: 1\n", encoding="utf-8")
    assert _unquoted_titles([probe]), "an unquoted title behind `- ` is invisible"
    probe.write_text('  - title: "Wade\'s initial phase #1"\n', encoding="utf-8")
    assert _unquoted_titles([probe]) == [], "a quoted title behind `- ` false-fires"


def test_shipped_python_titles_are_annotations_or_quoted():
    """The claim the `.py` exclusion rests on — not "there are no YAML templates
    in Python", which is false: validate_tasks.py embeds ~30 quoted ones."""
    offenders = []
    for root in SHIPPED_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            offenders.extend(_unquoted_titles([path]))
    assert offenders == [], (
        "shipped Python carries an unquoted `title:` that is not a type "
        "annotation:\n  " + "\n  ".join(offenders)
    )


def test_the_loss_this_phase_fixes_is_real_and_the_fix_works():
    """The mechanism, executed rather than described."""
    yaml = pytest.importorskip("yaml")
    src = (
        "tasks:\n"
        '  - id: FEAT-QUOTED\n'
        '    title: "Fix the widget #482"\n'
        "  - id: FEAT-PLAIN\n"
        "    title: Fix the widget #482\n"
    )
    loaded = {t["id"]: t["title"] for t in yaml.safe_load(src)["tasks"]}
    assert loaded["FEAT-QUOTED"] == "Fix the widget #482"
    assert loaded["FEAT-PLAIN"] == "Fix the widget"  # the defect, at read time

    dumped = yaml.safe_dump(
        yaml.safe_load(src), sort_keys=False, default_flow_style=False,
        allow_unicode=True, width=120,
    )
    assert dumped.count("#482") == 1


# --------------------------------------------------------------------------
# Step 4c — asserted against the CODE, not the file it lives in
# --------------------------------------------------------------------------


def _step4c_body() -> str:
    """The Step 4c heredoc's Python, extracted.

    Every assertion below runs against this and not against the enclosing
    SKILL.md. The first version grepped the whole file, so `os.replace(tmp, p)`
    written in a comment satisfied the atomicity check over code that truncated
    in place.
    """
    text = (REPO_ROOT / "core/skills/review-close/SKILL.md").read_text(encoding="utf-8")
    start = text.index('   ids = ["<ROADMAP_ID_1>"')
    end = text.index("\n   PY\n", start)
    lines = []
    for raw in text[start:end].splitlines():
        line = raw[3:] if raw.startswith("   ") else raw
        code = line.split("#", 1)[0] if not line.lstrip().startswith("#") else ""
        lines.append(code)
    return "\n".join(lines)


def test_step4c_writes_the_index_atomically():
    code = _flat(_step4c_body())
    assert "os.replace(" in code, "Step 4c no longer replaces atomically"
    assert re.search(r"tmp\s*=\s*target\.with_suffix", code), (
        "Step 4c's tempfile must be derived from the target, so the replace stays "
        "same-filesystem — a tmp in the system temp dir makes os.replace raise"
    )
    assert not re.search(r"(?<![\w.])(p|target)\.write_text\s*\(", code), (
        "Step 4c writes the index in place again"
    )
    assert not re.search(r"shutil\.(copyfile|copy|move)", code), (
        "Step 4c replaced its atomic rename with a copy"
    )


def test_step4c_preserves_what_write_text_gave_for_free():
    """Three properties the round found `os.replace` silently drops."""
    code = _flat(_step4c_body())
    assert "os.path.realpath(p)" in code, "Step 4c stopped writing through a symlink"
    assert "os.chmod(" in code, "Step 4c stopped preserving the index's mode"
    assert "tmp.unlink()" in code, "Step 4c stopped cleaning up its tempfile on failure"
    assert "read_text(encoding='utf-8')" in code, (
        "Step 4c's read half lost its encoding, leaving the pair locale-dependent "
        "in one direction while allow_unicode=True opts the write into non-ASCII"
    )


def test_step4c_imports_os():
    """Property, not spelling: the round false-killed on an import reorder."""
    text = (REPO_ROOT / "core/skills/review-close/SKILL.md").read_text(encoding="utf-8")
    header = text[text.index("python3 - <<'PY'") : text.index('   ids = ["<ROADMAP_ID_1>"')]
    assert re.search(r"^\s*import\s+(\w+,\s*)*os\b|^\s*import\s+os\b", header, re.M), (
        "Step 4c's heredoc must import os"
    )


def test_the_step4c_extractor_sees_code_and_drops_comments():
    """Non-vacuity: the extractor must return real code, and must NOT return the
    comment text that the whole-file version was fooled by."""
    code = _step4c_body()
    assert "yaml.safe_load" in code and "subprocess.run" in code
    assert len(code.splitlines()) > 40
    assert "Atomic rewrite (Phase 201)" not in code, "extractor kept comment text"


def test_the_atomic_shape_is_stated_where_the_class_is_not_yet_converted():
    """The three claim-side writers still truncate in place, and the record said
    otherwise. This pins the honest statement rather than the fix."""
    code_comment = (REPO_ROOT / "core/skills/review-close/SKILL.md").read_text(encoding="utf-8")
    assert "still truncate in place" in _flat(code_comment), (
        "Step 4c's comment no longer states that the sibling writers are unconverted"
    )


# --------------------------------------------------------------------------
# The retired falsehood
# --------------------------------------------------------------------------

# Broadened past the original wording after the round restated the same false
# claim four ways around a narrow pattern. Residual, stated rather than implied:
# a pattern cannot catch every paraphrase of "block scalars are preserved". The
# verbatim pin on claim-task's corrected sentence (PINS, above) is the other half
# — it reds if the correction is removed, whatever replaces it.
_BLOCK_SCALAR_FALSEHOODS = (
    re.compile(r"block scalars?\b(?:(?!\.).){0,120}?(round[- ]trips? fine|reproduces? (?:those|them) exactly|are preserved|survive intact|comes? back (?:the same|unchanged|a `\|`))", re.I | re.S),
    re.compile(r"sprint prose\b(?:(?!\.).){0,120}?(round[- ]trips? fine|exactly|preserved)", re.I | re.S),
    # The falsehood stated concretely, naming no banned vocabulary at all — the
    # form that survived the first re-run: "a `|` literal comes back a `|` literal".
    re.compile(r"(`\|`|`>-`|literal|folded)[^.\n]{0,60}?comes? back[^.\n]{0,20}?(`\|`|`>-`|the same|unchanged|a literal)", re.I),
)


def test_the_block_scalar_claim_does_not_come_back():
    offenders: list[str] = []
    for path in _shipped_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pat in _BLOCK_SCALAR_FALSEHOODS:
            for m in pat.finditer(text):
                line = text[: m.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line}")
    assert offenders == [], (
        "the retired block-scalar preservation claim reappeared at: "
        + ", ".join(offenders)
    )


def test_the_falsehood_guard_fires_on_paraphrase_but_not_on_the_correction():
    """The round's four restatements must red; the TRUE correction must not.

    An earlier pattern banned the accurate rewording along with the falsehood,
    which pressures the next author back toward vaguer language.
    """
    def hit(s: str) -> bool:
        return any(p.search(s) for p in _BLOCK_SCALAR_FALSEHOODS)

    assert hit("sprint prose lives in block scalars which round-trip fine")
    assert hit("sprint prose lives in block scalars, and the dump reproduces those exactly")
    assert hit("block scalars, the construct sprint prose is written in, round-trip fine")
    # True statements must pass.
    assert not hit("block scalars keep their value but not their style")
    assert not hit("block scalars do not round-trip their style")


def test_block_scalar_style_really_is_lost():
    yaml = pytest.importorskip("yaml")
    src = "a: |\n  one\n  two\nb: >-\n  folded\n  text\n"
    out = yaml.safe_dump(
        yaml.safe_load(src), sort_keys=False, default_flow_style=False,
        allow_unicode=True, width=120,
    )
    assert "|" not in out and ">-" not in out
    assert yaml.safe_load(out) == yaml.safe_load(src)


# ---------------------------------------------------------------------------
# Controls for the pin loops themselves — `Q-214` leg (5).
#
# Phase 204's round found five ways to disarm the guards in this module without
# reddening anything, and Phase 204 fixed the shape for ONE predicate
# (`_states_the_subset_as_the_population`, in `tests/test_roadmap_batch_survey.py`)
# by hoisting it so the guard and its control share it. That treatment never
# reached the rosters here.
#
# The brief for this phase prescribed the same hoist-and-share fix. It is
# DISQUALIFIED, and the disqualification is the transferable part: the roadmap
# predicate's data is DERIVED, so a control that re-derives it observes the real
# guard. `PINS`, `RULE_STATED` and `_DUMP_ALIASES` are LITERAL rosters, and a
# control that supplies its own literals never touches them — the prescribed
# shape was built and left every survivor alive at 66 green.
#
# What works: run synthetic gutted INPUT through the REAL roster, and assert the
# roster is non-empty in the same breath.
#
# Two control shapes were tried and rejected as dead-on-arrival, recorded so they
# are not re-attempted:
#   - "the pin fires when the FIRST occurrence is deleted" — `/document-work`
#     legally carries a pinned clause TWICE, and that duplication is itself
#     mandated by `test_both_copies_of_step_3bs_hard_fail_carry_the_rule`.
#   - "`RULE_STATED` rejects an INVERTED rule" — `_QUOTE_RULE` matches inside
#     "Never quote the `title:` you write" by documented design (see the comment
#     on `_negated_quote_sentences`). Use neutral prose, not an inversion.
#
# **Declared residual — and a correction to how it was first declared.**
#
# The first cut of this section named two surviving bypasses — rewriting the
# call `_missing_pins(PINS[path], flat)` to `_missing_pins((), flat)`, and
# swapping the neutral input at its call site — and generalized from them to a
# stopping rule: that the class is unclosable because detecting it means
# asserting over the guard's own source text.
#
# **That generalization was wrong, and the round proved it by walking 22 of 28
# bypasses through these controls.** It was true of the two cases named and
# false of nearly everything else, because the rest sit in ordinary DATA, not in
# source text. Non-emptiness is not substance: `PINS = {k: ("the",)}` passed
# every assertion here, and so did `("index.yml",)` — true by construction,
# since every roster member names the index by derivation — and with either in
# place a real clause could be deleted from a real shipped file at 79 green.
# `RULE_STATED = {k: re.compile("title")}` did the same, because neutral prose
# misses every pattern including a useless one. Three data assertions closed the
# bulk of it: a derived word floor, an on-topic near-miss input, and a reach
# probe on an undelimited mention. None of them looks at source text.
#
# What actually remains is narrower than the first claim and is stated as such:
# an edit *inside* a guard's own body — changing what it passes, or what it
# compares against — is not observable by that guard. That is true of any test
# in any suite, it is a code-review boundary rather than a test one, and it is
# NOT a licence to leave a data-level hole undescribed. **A survivor reachable
# through data is a defect wearing a residual's label**, which is the rule
# `_shared/adversarial-review.md` states and the one this section failed first
# time round.
#
# One further residual, found by the round and absent from the first list:
# **classification-by-fiat.** A new authoring surface that enters the universe
# forces a classification, and the cheaper branch discharges it — adding the
# path to `INDEX_READERS` is one line and carries no pin, no rule pattern and
# no obligation. The tripwire makes the choice visible; it cannot make it
# honest. That is a review boundary too, and unlike the first claim it is
# named here rather than generalized from.
# ---------------------------------------------------------------------------

# Prose that is about this repo and mentions none of the rule's terms. Feeding
# this to a pattern that is supposed to detect the quoting rule must MISS.
_NEUTRAL_PROSE = _flat(
    "The installer copies the companion tree into the vendor directory and "
    "records every managed path in the lock file so a later update can tell a "
    "consumer edit from a stale copy."
)

# The NEAR MISS, and this is the one that does the work. Neutral prose shares no
# vocabulary with the subject, so it misses *any* pattern — including a useless
# one. The round exploited exactly that: `RULE_STATED = {k: re.compile("title")}`
# passed the neutral-prose check and then let the quoting rule be deleted from
# two shipped skills with the suite green.
#
# This text is ON TOPIC — it names `title:`, `index.yml` and quoting — and
# states no rule about quoting the title. A pattern that matches it is matching
# the topic rather than the claim.
_NEAR_MISS_PROSE = _flat(
    "Each entry in `index.yml` carries a `title:` field alongside its id and "
    "status. The title is free prose and is shown by `/sitrep` when it lists "
    "open work; quoting conventions for YAML scalars are covered elsewhere in "
    "this document."
)


@pytest.mark.parametrize("path", sorted(PINS))
def test_the_pin_roster_is_not_silently_emptied(path: str):
    """Control for `PINS`. Blanking the values left the suite green.

    The roster cross-check compares KEY sets, so `{k: () for k in PINS}` passes
    it. This asserts the values carry weight and that the shared predicate
    actually reports them missing when they are gone from the document.
    """
    clauses = PINS[path]
    assert clauses, (
        f"PINS[{path!r}] is empty, so the presence guard for this file checks "
        "nothing. If the file genuinely has no negation-sensitive clause left, "
        "remove it from TITLE_AUTHORING rather than pinning it to nothing."
    )
    # Non-emptiness is not substance, and the round proved the gap is not
    # theoretical: `PINS = {k: ("the",)}` passed every assertion here at 79
    # green, and so did `("index.yml",)` — which is true *by construction*,
    # since every TITLE_AUTHORING member is in the index-naming universe by
    # derivation. With either in place a real pinned clause can be deleted from
    # a real shipped file and the suite reports clean, which is the filed
    # `Q-214` leg-(5) defect restored through the door built to close it.
    #
    # The floor is derived, not chosen: the shortest of the 16 real clauses is
    # "Quoting is the whole defence" at 5 words / 28 characters. A clause below
    # that cannot carry a negation-sensitive claim — which is what a pin is for.
    for clause in clauses:
        assert len(clause.split()) >= 5 and len(clause) >= 28, (
            f"PINS[{path!r}] carries {clause!r}, which is too short to be a "
            "negation-sensitive claim. A pin is a clause whose NEGATION is the "
            "defect; a fragment this small is satisfied by prose that says the "
            "opposite, and the guard then certifies the file while the rule is "
            "gone. Pin the clause, not a word inside it."
        )
    flat = _flat((REPO_ROOT / path).read_text(encoding="utf-8"))
    gutted = flat
    for clause in clauses:
        gutted = gutted.replace(_flat(clause), "")
    assert _missing_pins(clauses, gutted) == list(clauses), (
        "the pin predicate no longer reports pinned clauses as missing from a "
        f"document they were removed from — it cannot detect deletion in {path}."
    )


@pytest.mark.parametrize("path", sorted(RULE_STATED))
def test_the_rule_pattern_is_not_silently_widened(path: str):
    """Control for `RULE_STATED` and for its assertion site.

    Catches both mutations the round walked: a pattern widened to match anything
    (`re.compile("")`), and the call site reduced to a truthiness check on the
    pattern object instead of on its result.
    """
    # The miss below is satisfied by ANY input the pattern does not match,
    # including an empty string — measured: swapping `_NEUTRAL_PROSE` for
    # `_flat("")` left this control green. So the input's substance is asserted
    # first. A control whose input can be silently emptied is the vacuity this
    # whole section exists to close.
    assert len(_NEUTRAL_PROSE.split()) >= 20, (
        "_NEUTRAL_PROSE has been reduced to something too thin to be evidence — "
        "the miss below would then pass vacuously."
    )
    assert not _states_the_rule(path, _NEUTRAL_PROSE), (
        f"RULE_STATED[{path!r}] matches prose that does not state the quoting "
        "rule at all, so the guard for this file certifies nothing. Either the "
        "pattern was widened or the call site stopped testing the match."
    )
    assert not _states_the_rule(path, _NEAR_MISS_PROSE), (
        f"RULE_STATED[{path!r}] matches ON-TOPIC prose that states no rule — it "
        "names `title:` and `index.yml` and says nothing about quoting. A "
        "pattern that fires on this is detecting the SUBJECT, not the claim, "
        "so the rule can be deleted from the file while the guard stays green. "
        "The neutral-prose check above cannot see this: neutral text misses "
        "every pattern, including a useless one."
    )


def test_the_dump_alias_patterns_are_not_silently_emptied():
    """Control for `_DUMP_ALIASES`. Emptying the tuple left the suite green.

    The alias sweep exists because `yaml.safe_dump` can be reached through an
    import alias; a roster of zero patterns sweeps for nothing while still
    reporting a clean run.
    """
    assert _DUMP_ALIASES, (
        "_DUMP_ALIASES is empty — the aliased-writer sweep matches nothing and "
        "every aliased `safe_dump` call in the tree is invisible to it."
    )
    # One smuggling route per pattern, each the route the round actually used.
    # Matched set-wise, NOT positionally: the first cut `zip`ped these against
    # `_DUMP_ALIASES` in declaration order, so REORDERING the roster — a
    # behaviour-identical edit, since the sweep unions offenders across all
    # patterns — reddened the guard. The round caught that as a false kill, and
    # it is the over-strictness direction this control was supposed to avoid.
    # SEVERAL spellings per route, not one. A single literal per pattern is
    # satisfied by a pattern narrowed to exactly that literal — the round
    # narrowed `\byaml\.dump\s*\(` to the full text of its own control route,
    # passed every assertion here, and then smuggled a real writer into a
    # shipped file. A route is a *shape*, so it takes more than one instance to
    # pin, and the variants below differ in the places a narrowing would bite:
    # argument text, whitespace, quoting, import spelling.
    routes = (
        "from yaml import safe_dump",
        "from yaml import dump",
        "from yaml import safe_dump, safe_load",
        "yaml.dump(payload, Dumper=yaml.SafeDumper)",
        "yaml.dump(index, fh)",
        "yaml.dump (rows)",
        "getattr(yaml, 'safe_dump')(payload)",
        'getattr(yaml, "dump")(index, fh)',
        "getattr( yaml , 'safe_dump' )(x)",
    )
    for route in routes:
        assert any(pat.search(route) for pat in _DUMP_ALIASES), (
            f"no alias pattern matches the smuggling route {route!r} — that "
            "route is now invisible to the writer sweep. A pattern narrowed to "
            "one spelling of a route does not cover the route."
        )
    # And every pattern must earn its place, or a dead pattern pads the roster
    # and satisfies the non-emptiness check above while sweeping for nothing.
    for pat in _DUMP_ALIASES:
        assert any(pat.search(route) for route in routes), (
            f"alias pattern {pat.pattern!r} matches none of the known smuggling "
            "routes. Either it is dead, or a route it exists for is missing "
            "here — and a route missing here is a route nothing tests."
        )
