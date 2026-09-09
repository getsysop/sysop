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
    # --release: in_progress -> open, and --commit-claim: open -> in_progress
    # (Phase 261, `Q-397` — both now under the tracker write mutex).
    "core/companion/scripts/claim_task.sh",
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
    # A FILE may hold more than one writer, and since Phase 261 one does:
    # `claim_task.sh` writes the index from `--release` and again from
    # `--commit-claim`. The README sentence counts CODE PATHS, so counting
    # `len(INDEX_WRITERS)` — a set of paths — against it was a category error that
    # forced the README to say "Six" over a true seven. Phase 261's round found it
    # by deriving the population itself instead of trusting either number.
    fragments = {
        "core/skills/claim-task/SKILL.md": ["`/claim-task` Step 4a"],
        "core/skills/auto-build/SKILL.md": ["`/auto-build` Step 5.1"],
        "core/companion/scripts/claim_task.sh": [
            "`claim_task.sh --release`", "`claim_task.sh --commit-claim`"],
        "core/skills/review-close/SKILL.md": ["`/review-close` Step 4c"],
        "core/companion/scripts/backfill_completed_dates.py":
            ["`backfill_completed_dates.py`"],
        "core/companion/scripts/clear_user_action.py": ["`clear_user_action.py`"],
    }
    assert set(fragments) == INDEX_WRITERS, (
        "this roster and INDEX_WRITERS disagree — writers with no README "
        f"fragment: {sorted(INDEX_WRITERS - set(fragments))}; fragments for "
        f"non-writers: {sorted(set(fragments) - INDEX_WRITERS)}"
    )
    for group in fragments.values():
        for fragment in group:
            assert _flat(fragment) in section, (
                f"the round-trip warning section omits {fragment}"
            )
    code_paths = sum(len(g) for g in fragments.values())
    words = {4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight", 9: "Nine"}
    expected = f"{words[code_paths]} code paths rewrite it whole"
    assert expected in section, (
        f"the warning section's count disagrees with the code-path roster "
        f"({code_paths}): expected {expected!r}"
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


def _step4c_region() -> str:
    """Step 4c's heredoc, comments INCLUDED — the roster lives in a comment."""
    text = (REPO_ROOT / "core/skills/review-close/SKILL.md").read_text(encoding="utf-8")
    start = text.index('   ids = ["<ROADMAP_ID_1>"')
    return text[start:text.index("\n   PY\n", start)]


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
    # `Q-414` (Phase 269) replaced the fixed `<path>.tmp` with `mkstemp`. The old
    # assertion pinned `tmp = target.with_suffix(...)` and gave its reason as
    # "so the replace stays same-filesystem". That reason is REAL and is kept —
    # a tmp in the system temp dir makes os.replace raise EXDEV — but the fixed
    # name was never what secured it. `dir=` is, and it secures it without the
    # collision the fixed name creates. So the property is asserted directly
    # instead of through the weaker form that happened to imply it.
    assert re.search(r"tempfile\.mkstemp\s*\(", code), (
        "Step 4c's tempfile must come from mkstemp — a name derived from the target "
        "collides when two closes overlap (`Q-382`'s class, `Q-414`'s site)"
    )
    assert re.search(r"dir\s*=\s*os\.path\.dirname\(", code), (
        "Step 4c's tempfile left the target's own directory, so the replace is no "
        "longer guaranteed same-filesystem — a tmp elsewhere makes os.replace raise"
    )
    assert not re.search(r"tmp\s*=\s*\w+\.with_suffix", code), (
        "Step 4c derived its temp name from the target again — the fixed-name "
        "collision `Q-414` removed"
    )
    assert not re.search(r"(?<![\w.])(p|target|real)\.write_text\s*\(", code), (
        "Step 4c writes the index in place again"
    )
    assert not re.search(r"shutil\.(copyfile|copy|move)", code), (
        "Step 4c replaced its atomic rename with a copy"
    )


def test_step4c_preserves_what_write_text_gave_for_free():
    """Three properties the round found `os.replace` silently drops.

    The cleanup assertion moved from `tmp.unlink()` to `os.unlink(tmp)` at Phase
    269: `mkstemp` returns a `str`, not a `Path`, so the method form is no longer
    available. Same property, different spelling — the guard is re-pointed rather
    than dropped, because the failure arm is what keeps a surviving `.tmp` from
    sitting untracked beside a tracked path for the rest of the close.
    """
    code = _flat(_step4c_body())
    assert "os.path.realpath(p)" in code, "Step 4c stopped writing through a symlink"
    assert "os.chmod(" in code, "Step 4c stopped preserving the index's mode"
    assert re.search(r"os\.unlink\(\s*tmp\s*\)|tmp\.unlink\(\)", code), (
        "Step 4c stopped cleaning up its tempfile on failure"
    )
    assert re.search(r"os\.path\.exists\(\s*tmp\s*\)|tmp\.exists\(\)", code), (
        "Step 4c's cleanup lost its existence check and will raise from the except "
        "arm when the failure preceded the temp file"
    )
    assert "read_text(encoding='utf-8')" in code, (
        "Step 4c's read half lost its encoding, leaving the pair locale-dependent "
        "in one direction while allow_unicode=True opts the write into non-ASCII"
    )
    # Both found unguarded by a review lens, and both are properties the mkstemp
    # conversion INTRODUCED — `write_text` carried the first for free and the old
    # `stat()` line carried the second, so neither had ever needed a pin.
    assert re.search(r"os\.fdopen\([^)]*encoding\s*=\s*'utf-8'", code), (
        "Step 4c's WRITE half lost its encoding. The read half is pinned above; "
        "dropping it here leaves the pair locale-dependent in the other direction, "
        "while allow_unicode=True opts the dump into non-ASCII"
    )
    assert "0o7777" in code, (
        "Step 4c's mode mask narrowed (0o7777 -> 0o777?), so setgid/sticky bits on "
        "the index are dropped on every close — mkstemp creates 0600, so the chmod "
        "is the only thing carrying the old mode across"
    )


def test_step4c_joins_the_mkstemp_roster_rather_than_standing_apart():
    """`Q-414`'s actual subject: the roster of `tasks/index.yml` writers, and
    which of them still derive a temp name from the target.

    Asserted as a POPULATION rather than as one more site, so the next writer
    added to the roster cannot quietly reintroduce the fixed name — which is how
    Step 4c itself stayed the odd one out through two phases that converted its
    neighbours.

    **The population is the whole point, and this test's first version got it
    wrong twice.** It listed four files, and a review lens found a fifth writer
    of the same file still using the fixed name — so the roster is now split:
    `CONVERTED` is asserted, `STILL_FIXED_NAME` is asserted to be *exactly* the
    known remainder. A converted holdout must be MOVED between the two lists,
    which makes closing `Q-442` a visible edit rather than a silent one.

    **And membership is COUNTED, not tested with `in`** — a second lens found the
    first version scoring zero unique kills. `claim_task.sh` holds TWO index
    writers (`--commit-claim` and `--release`), so `"tempfile.mkstemp(" in body`
    stays true when one of them is reverted to a fixed name: measured, the whole
    module went 83 passed / 0 failed with `--release` reverted. A per-file count
    catches that; a membership check cannot, in any file with two writers — and
    both SKILL.md files are large enough that a mere *comment* mentioning
    `tempfile.mkstemp(` would satisfy `in` as well."""
    # (file, how many index writers it holds)
    CONVERTED = {
        # Step 4a (the index) + Step 7f (the task BODY, `Q-444`, Phase 271).
        "claim-task Step 4a + Step 7f": (REPO_ROOT / "core/skills/claim-task/SKILL.md", 2),
        "auto-build Step 5.1": (REPO_ROOT / "core/skills/auto-build/SKILL.md", 1),
        "claim_task.sh --commit-claim + --release":
            (REPO_ROOT / "core/companion/scripts/claim_task.sh", 2),
        "review-close Step 4c": (REPO_ROOT / "core/skills/review-close/SKILL.md", 1),
        "clear_user_action.py":
            (REPO_ROOT / "core/companion/scripts/clear_user_action.py", 1),
        # `Q-442`, Phase 271 — moved here out of `STILL_FIXED_NAME`.
        "backfill_completed_dates.py":
            (REPO_ROOT / "core/companion/scripts/backfill_completed_dates.py", 1),
    }
    # EMPTY BY DESIGN as of Phase 271, which closed `Q-442` (the last
    # `tasks/index.yml` writer deriving its temp name from its target) and
    # `Q-444` (the task-body writer). Kept rather than deleted, and asserted
    # empty rather than merely iterated: an empty dict makes the loop below
    # vacuous, so the emptiness itself has to be the assertion.
    STILL_FIXED_NAME: dict = {}
    # Deliberately INDEX-scoped, and that scoping is exactly why it needs the
    # companion detector in `test_no_new_fixed_name_temp_writers`. This pattern
    # sees ONE idiom on ONE variable-name family. The roster has now been wrong
    # about its own population three times: a fifth index writer found by a lens,
    # then `Q-444` on a different file, then Phase 271's sweep turning up seven
    # concat-shape writers (`tmp = path + ".tmp"`) that this regex cannot match
    # at all. The counts stay because they catch what a tree-wide detector
    # cannot — a commented-out writer, and one of two writers in a file reverted
    # — and the detector catches what the counts cannot: a writer in a file
    # nobody remembered to list.
    _FIXED_NAME = re.compile(
        r"\b(tmp|tmp_path|_tmp)\s*=\s*(target|real|_real|p|index_path)\.with_suffix"
    )
    def _live(text: str) -> str:
        """Comment lines dropped before counting.

        A count over raw text is satisfied by a COMMENTED-OUT call, which is
        exactly how a writer gets disabled: the mutation that first exposed this
        inserted a fixed-name assignment and commented the `mkstemp` out, leaving
        the raw count unchanged and the module green. Both `#`-comment languages
        here (shell, and Python inside markdown fences) use the same marker.
        """
        return "\n".join(
            "" if ln.lstrip().startswith("#") else ln for ln in text.splitlines()
        )

    for name, (path, expected) in CONVERTED.items():
        body = _live(path.read_text(encoding="utf-8"))
        # `mkstemp(` regardless of module spelling: `import tempfile as tf` is a
        # legal rewrite and the literal count reddened on it. The receiver is not
        # the property — the call is.
        got = len(re.findall(r"\bmkstemp\s*\(", body))
        assert got == expected, (
            f"{name} has {got} mkstemp call(s), expected {expected} — a writer of "
            f"tasks/index.yml was removed or added without updating this roster"
        )
        assert not _FIXED_NAME.search(body), (
            f"{name} derives a temp name from its target again — the collision class "
            f"`Q-382` closed for the claim paths and `Q-414` closed for the close path"
        )
    for name, path in STILL_FIXED_NAME.items():
        body = _live(path.read_text(encoding="utf-8"))
        assert _FIXED_NAME.search(body), (
            f"{name} was converted to mkstemp but is still listed as a holdout — move "
            f"it into CONVERTED and close its entry in the same commit"
        )
    assert not STILL_FIXED_NAME, (
        "STILL_FIXED_NAME is non-empty again. Re-opening the holdout list is legal, "
        "but it must be a deliberate edit here rather than a silent one — the loop "
        "above is vacuous while the dict is empty, so this line is what asserts the "
        "closure. Delete it in the same commit that adds the holdout."
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


def test_the_corrected_writer_rosters_stay_corrected():
    """Two `Records corrected` items this phase shipped with nothing pinning them.

    Round lens 3 reverted both and the suite stayed green — which is how the
    `clear_user_action.py` sentence survived being false from Phase 261 to Phase
    263 in the first place. Declining to guard a corrected sentence is how it
    un-corrects itself.
    """
    installer = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
    for name in ("claim_task.sh --commit-claim", "clear_user_action.py"):
        assert name in installer, (
            f"install.sh's tasks/index.yml writer roster stopped naming {name}; it "
            "listed five of a seven-path population until Phase 263"
        )

    cua = (REPO_ROOT / "core/companion/scripts/clear_user_action.py").read_text(encoding="utf-8")
    assert "Phase 261 converted" in _flat(cua), (
        "clear_user_action.py's comment stopped recording that `--release` was "
        "converted; it asserted the opposite, unpinned, for two phases"
    )


def test_the_auto_build_guard_module_actually_collects_its_tests():
    """Reachability, asserted from OUTSIDE the module it protects.

    `test_auto_build_index_write.py` carries its own collection guard, which
    counts `def test_...` lines in its source text. Round lens 3 put a
    module-level `pytest.skip(..., allow_module_level=True)` at the top: all its
    tests went dark, its own guard went dark with them, and the suite stayed
    green. A guard inside the thing it guards cannot see the thing being
    switched off. This one runs collection in a subprocess and asserts a floor —
    the shape `test_claim_commit_mutex.py` already documents for the same reason.
    """
    import subprocess
    import sys as _sys

    r = subprocess.run(
        [_sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
         "tests/test_auto_build_index_write.py"],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180,
    )
    assert r.returncode == 0, f"collection failed:\n{r.stdout}\n{r.stderr}"
    collected = [ln for ln in r.stdout.splitlines() if "::test_" in ln]
    assert len(collected) >= 17, (
        f"tests/test_auto_build_index_write.py collected {len(collected)} tests, "
        "expected at least 17 — a module-level skip or an import error switches the "
        "whole Q-404 guard off without reddening anything inside it"
    )


def test_the_roster_separates_the_closed_class_from_the_open_one():
    """Phase 263 closed the in-place-write class. The mutex class is still open.

    The predecessor pinned the sentence naming `/auto-build` Step 5.1 as the last
    writer that truncated in place, and that sentence went false the moment the
    conversion landed. Its replacement is pinned here **including the half that is
    not done**: an unqualified "converted" reads as coverage `Q-404` does not have,
    which is the exact shape the original guard was written to stop.
    """
    # Scoped to Step 4c's REGION, not the whole file. Round lens 3 restored the
    # pre-263 falsehood verbatim and this guard passed, because four of its five
    # substrings occur elsewhere in a 2,600-line skill — only `MUTEX, not
    # atomicity` was unique, and that is the one substring the author's own
    # battery row attacked, so the kill was self-selected. `_step4c_body()` is no
    # use here: it strips comments, and the roster IS a comment.
    comment = _flat(_step4c_region())
    assert "truncates in place" in comment and "any more" in comment, (
        "Step 4c's roster no longer states that the in-place-write class is closed"
    )
    assert "MUTEX, not atomicity" in comment, (
        "Step 4c's roster stopped distinguishing the closed class (atomicity) from "
        "the open one (the tracker mutex) — without it `Q-404` reads as resolved"
    )
    for still_unlocked in ("backfill_completed_dates.py", "clear_user_action.py"):
        assert still_unlocked in comment, (
            f"the roster stopped naming {still_unlocked} as an unserialized writer"
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


# ---------------------------------------------------------------------------
# `Q-447` / `Q-448`, Phase 271 — the class detector the roster above cannot be.
# ---------------------------------------------------------------------------

# The population is this module's EXISTING `_shipped_files()`, reused rather than
# re-derived, for the reason `_shared/adversarial-review.md` rule 1 gives: "derive
# the population from the source of truth, not from an index or summary of it".
# The roster above is such a summary and has been wrong about itself three times.
#
# Reusing it is also the fix for a self-inflicted regression this pass caught: the
# first draft defined its own `_shipped_files()` at module level, silently
# SHADOWING the one above, and because that copy scanned only `core/` it dropped
# `install.sh` from the population of two unrelated guards — which went red
# immediately. A second copy of a population is a second thing to get wrong.
# `.yml`/`.yaml`/`.fragment` carry shell (`checks.yml.fragment` run lines, the CI
# template) and were never opened — 41 of 153 shipped files (round 2, `P34`).
_SCANNED_SUFFIXES = (".py", ".sh", ".md", ".yml", ".yaml", ".fragment")
# Shipped executables with NO suffix. `core/companion/git-hooks/pre-commit` and
# its siblings are shell scripts that git requires to be extensionless, so a
# suffix filter never opens them — an independent battery planted a fixed-name
# temp in `pre-commit` and it survived every regex change, because the gap is in
# the POPULATION, not the pattern. Matched by shebang rather than by a filename
# list, so a new hook is covered on the day it is added.
# Python too: an extensionless `#!/usr/bin/env python3` script under
# `core/companion/scripts/` was a population gap an independent battery walked
# through (Phase 272's round, `D09`).
_SHEBANG = re.compile(rb"^#!.*\b(?:(?:ba)?sh|python3?)\b")
_PY_SHEBANG = re.compile(rb"^#!.*\bpython3?\b")


def _is_shipped_script_without_suffix(p) -> bool:
    # `.example` counts: `core/companion/git-hooks/examples/*.example` are shipped
    # hook bodies a consumer copies into place, and a suffix filter skipped all
    # four. The test is the SHEBANG, so what matters is whether it is a script.
    if p.suffix and p.suffix != ".example":
        return False
    try:
        return bool(_SHEBANG.match(p.read_bytes()[:120]))
    except OSError:
        return False

# Both shapes, because the filed one was never the population. `Q-442`/`Q-444`
# were `<path>.with_suffix(<path>.suffix + ".tmp")`; Phase 271's sweep found
# seven more writers spelled `<path> + ".tmp"`, which no `with_suffix` pattern
# can see. A third shape (shell `"${VAR}.tmp"`) is matched too.
# **Shape-GENERAL, after two rounds of the narrow version being wrong.**
# The first cut matched one idiom (`x.with_suffix(x.suffix + ".tmp")`); a review
# lens found two shipped sites it could not see. The second cut added a concat
# branch anchored at `=`; an independent battery then walked FOUR more spellings
# through it — `f"{real}.tmp"`, `str(real) + ".tmp"`, `"%s.tmp" % real`,
# `"{}.tmp".format(real)`. Enumerating spellings is losing this game, so the
# predicate no longer tries: it asks whether an ASSIGNMENT's right-hand side
# carries a string literal ending in a temp extension, whatever builds it.
#
# Two exclusions, both narrow and both necessary:
#   - a line containing `mkstemp` is the SANCTIONED shape, whose own
#     `suffix=".tmp"` argument would otherwise match;
#   - spaces are required around `=`, so a keyword argument (`suffix=".tmp"`) on
#     a continuation line is not read as an assignment. This tree is PEP8 and the
#     distinction holds; it is stated here so the next reader knows it is load
#     bearing rather than incidental.
# LHS may be dotted (`self.tmp`) or annotated (`tmp: str = …`) — both were
# walked through the first version by a review battery. Spaces around `=` are
# still required for the multi-space form, because that is what separates an
# assignment from a keyword argument on a wrapped call; the no-space form is
# accepted only when the line does NOT end in a comma, which is what a wrapped
# kwarg does.
_PY_ASSIGN = re.compile(
    r"^\s*(?P<lhs>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
    r"(?:\s*:\s*[A-Za-z_][A-Za-z0-9_\[\], .]*)?"
    r"(?:\s+=\s+|=(?!=))(?P<rhs>.*?)\s*$"
)
# Spaces REQUIRED. Used for markdown and shell, where the enclosing text is prose
# or shell and paren depth cannot be tracked, so a wrapped `prefix=...` keyword
# argument inside an embedded python heredoc would otherwise read as a writer.
_PY_ASSIGN_SPACED = re.compile(
    r"^\s*(?P<lhs>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
    r"(?:\s*:\s*[A-Za-z_][A-Za-z0-9_\[\], .]*)?"
    r"\s+=\s+(?P<rhs>.*?)\s*$"
)
# `.part` and `~` join the family: both are ordinary "work in progress" suffixes
# and both survived the first list.
_TEMP_EXT = r"(?:tmp|temp|new|bak|part|partial|swp)"
_TEMP_LITERAL = re.compile(r"""['"][^'"]*\.""" + _TEMP_EXT + r"""['"]|['"][^'"]*~['"]""", re.I)
# Shell: no spaces around `=`, and a `local`/`export`/`declare`/`readonly`
# prefix, all three of which the first version's start-anchor missed. Quoting is
# optional — `TMP=$HOME.tmp` is legal shell and was a survivor.
_SH_ASSIGN = re.compile(
    r"""^\s*(?:(?:local|export|declare|readonly|typeset)(?:\s+-[A-Za-z]+)*\s+)?"""
    r"""(?P<lhs>[A-Za-z_][A-Za-z0-9_]*)=["']?[^"'\s]*\.""" + _TEMP_EXT + r"""["']?\s*$""",
    re.I,
)
# A temp literal handed straight to a writing call, no assignment (`P28`):
# `open(path + ".tmp", "w")`. Reported under the call's name.
_WRITE_CALL = re.compile(
    r"""\b(?P<call>open|Path|os\.open|shutil\.copy\w*|shutil\.move)\(.*?['"][^'"]*\.""" + _TEMP_EXT + r"""['"]""",
    re.I,
)

# DECLARED DEBT — real fixed-name temp writers not yet converted, with an
# occurrence COUNT per (file, name). Counted rather than listed because
# `run_checks/baseline.py` once held two writers sharing the name `tmp_path`, and
# a set of pairs collapsed them, so reverting one would have passed unseen.
#
# EMPTY AS OF PHASE 272, which converted all nine — the seven Phase 271's sweep
# found plus the two its round found — to the four-element mkstemp shape
# (`Q-448`). Kept as a dict rather than deleted, and still asserted in both
# directions below: a writer this predicate can see that is in neither list
# reds as `new`, so the debt can only grow by a visible edit here, which is the
# review. The shell site, `install_hooks.sh`, moved to `ASSESSED_NOT_THE_CLASS`
# rather than leaving the population: its temp name now carries `$$`, the
# device `batch_work.sh` uses on the same premise — `mktemp` creates 0600, and
# `chmod +x` on that makes a 0711 hook (0700 under a 077 umask), where `cp` +
# `chmod +x` makes 0755. The vacuity control for the predicate itself is
# `test_the_fixed_name_detector_is_not_vacuous`, not this dict.
KNOWN_FIXED_NAME_TEMPS: dict = {}

# MATCHED BUT ASSESSED AS NOT THE CLASS. Listed rather than excluded by pattern,
# so the judgement is visible and reviewable instead of hidden in a regex. Each
# builds a temp name that carries the PROCESS ID — `"%s.%d.tmp" % (path,
# os.getpid())`, or shell `"${TASKS_FILE%.md}.$$.md.tmp"` — which makes it unique
# per process, the exact property the collision class is about. (Two THREADS in
# one process would still collide; these scripts are single-threaded.)
#
# **The PID is VERIFIED, not assumed, and the first version of this list did
# assume it.** Its comment claimed "if someone drops the PID, this list is wrong
# and the suite says so" — false: the key was `(file, lhs)`, the PID was never
# inspected, and a round dropped it at all three sites with the suite green. That
# made the carve-out an ignore list for precisely the edit it advertised catching.
# `_PID_TOKENS` below is what makes the claim true.
_PID_TOKENS = ("getpid", "$$", "os.getpid()")
ASSESSED_NOT_THE_CLASS = {
    # `"%s.%d.tmp" % (path, os.getpid())`
    ("core/companion/scripts/review_index.py", "tmp_path"): 1,
    # `"${TASKS_FILE%.md}.$$.md.tmp"` — `$$` is the shell's PID.
    ("core/companion/scripts/batch_work.sh", "REL_TMP"): 1,
    ("core/companion/scripts/close_batch.sh", "TMP_FILE"): 2,  # :1439 and :1517
    # `local tmp_file="${TASKS_FILE%.md}.$$.md.tmp"` — invisible to the first
    # predicate because of the `local` prefix, so it was in neither list.
    ("core/companion/scripts/batch_work.sh", "tmp_file"): 1,
    # `TMP="${DST}.$$.tmp"` — Phase 272 (`Q-448`); previously declared debt.
    # Not `mktemp`: it creates 0600, and `chmod +x` on that is 0711, not 0755.
    ("core/companion/scripts/install_hooks.sh", "TMP"): 1,
}


_MINTING_CALL = re.compile(r"\b(?:mkstemp|mkdtemp|NamedTemporaryFile|TemporaryDirectory)\s*\(")
_BARE_STRING = re.compile(r"""\s*['"][^'"]*['"]\s*""")


_COMMENT_START = re.compile(r"(?:^|(?<=\s))#")


def _strip_comment(ln: str) -> str:
    """Drop a comment — a `#` at the start of the line or preceded by whitespace.

    Comments are the documentation OF this class — every converted writer
    explains in-comment what it replaced, and counting those would make the
    detector fire on its own rationale. An independent battery reddened the
    first version with `real = os.path.realpath(index_path)  # was: tmp_path =
    index_path + ".tmp"` — a legal annotation, and exactly the kind a conversion
    leaves behind. ONLY a whitespace-preceded `#`: the first rewrite split at
    any `#`, so a markdown anchor `(#anchor)`, a `re.compile(r"(#…")` and a
    shell `grep -qE '(…str\\()'` each lost their closer and folded the lines after
    them (Phase 272's round 2). Still naive on quoting by design: a ` #` inside
    a string literal truncates the line early, which can only cause a MISS,
    never a false alarm — and since every physical line is also matched on its
    own (below), a miss here cannot hide a writer, only a closer.
    """
    m = _COMMENT_START.search(ln)
    return ln[:m.start()] if m else ln


def _paren_delta(ln: str) -> int:
    """Net `(` minus `)` OUTSIDE quoted spans, quoting tracked naively per line."""
    depth, quote = 0, None
    for ch in ln:
        if quote:
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
    return depth


def _logical_lines(text: str):
    """Yield (logical line, its stripped physical lines) with parens balanced ACROSS lines.

    Why joining rather than skipping: the first version tracked paren depth per
    physical line and SKIPPED every line inside parens, which is what separates
    `suffix=".tmp"` (a keyword argument of the sanctioned `mkstemp` call) from
    `tmp=".tmp"` (an assignment). Two defects, both found by Phase 272's round
    1: the depth was counted BEFORE comments were stripped and never reset, so
    a `(` in a comment, a docstring or a shell regex put the rest of the file
    behind the skip — 4,881 of 51,110 scanned lines, five files blind to their
    own tail; and a temp literal on a continuation line
    (`tmp = (str(real)\n    + ".tmp")`) was inside parens and so never seen.
    Joining answers both: the kwarg is folded into the call that contains
    `mkstemp(` and excluded with it, and the continuation is folded into its
    assignment and matched with it.

    Round 2 then measured the fold itself blind INSIDE files — 650 of 20,199
    sampled legal positions — wherever an unbalanced `(` survived the naive
    rules above. So the fold is no longer allowed to HIDE anything: `_scan_text`
    matches every physical line on its own as well as the logical line, and the
    fold's only remaining power is to attach a wrapped kwarg to the minting call
    that owns it. Two resets bound the fold regardless: an UNINDENTED physical
    line that does not open with a closer starts a new logical line whatever
    the depth, and a logical line is flushed after 40 physical lines.
    """
    buf, depth = [], 0
    for raw in text.splitlines():
        ln = _strip_comment(raw)
        unindented = bool(raw) and not raw[0].isspace() and not raw.lstrip().startswith((")", "]", "}"))
        if buf and (depth <= 0 or unindented or len(buf) >= 40):
            yield " ".join(x.strip() for x in buf), list(buf)
            buf, depth = [], 0
        if not ln.strip():
            continue
        buf.append(ln)
        depth += _paren_delta(ln)
    if buf:
        yield " ".join(x.strip() for x in buf), list(buf)


def _match_writer(line: str, kind: str):
    """The lhs of a fixed-name temp assignment on ONE line (logical or physical), or None.

    `kind` is "py", "sh" or "md". Shell grammar FIRST for shell and markdown
    (both carry shell), Python only for Python: `TMP="${DST}.tmp"` is a shell
    assignment whose RHS is one quoted string, and the Python path's bare-string
    exclusion swallowed it as a constant when it ran first — every PID-named
    shell site went `gone` at once. A `.py` file never gets the shell regex,
    because there `S=".tmp"` IS a constant. The Python regex is applied to all
    three kinds — markdown and shell both embed Python heredocs, and a no-space
    `tmp=str(p)+".tmp"` inside one was a survivor when markdown used the spaced
    form only. A line ending in a comma is a wrapped keyword argument, never an
    assignment.
    """
    if line.rstrip().endswith(","):
        return None
    if kind in ("sh", "md"):
        sh = _SH_ASSIGN.match(line)
        if sh:
            return sh.group("lhs")
    m = _PY_ASSIGN.match(line)
    if not m:
        w = _WRITE_CALL.search(line)
        return (w.group("call") + "(") if w else None
    # A bare string constant is not a temp PATH — `suffix = ".tmp"` passed to
    # `mkstemp` is the sanctioned idiom and reddened this guard. The cost is
    # real and recorded: a two-step construction (`S = ".tmp"` … `tmp = str(p)
    # + S`) is invisible, because neither line carries both a path reference
    # and the literal (`Q-451`).
    if _BARE_STRING.fullmatch(m.group("rhs")):
        return None
    return m.group("lhs") if _TEMP_LITERAL.search(m.group("rhs")) else None


_KWARG_SHAPE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*=(?!=)")
_MINTING_LOOKBACK = 6


def _scan_text(text: str, kind: str) -> dict:
    """{lhs: occurrences} of fixed-name temp writers in `text`.

    Every physical line is matched on its own, and the logical line only for a
    name no physical line produced (the continuation case) — so a fold that went
    wrong (an unbalanced `(` in prose, a docstring, a regex) can hide nothing.
    The sanctioned shape is excluded per PHYSICAL line: a keyword-argument-
    shaped line (`name=…`, no spaces) within a few lines after a MINTING call is
    that call's wrapped argument, and skipped. Not "a fold containing a minting
    call is skipped" — round 2 of Phase 272 measured that rule hiding 16
    legal positions, every one a line inside 40 of a `mkstemp(` where a
    docstring's stray `(` had folded the two together. The minting call is
    narrowed to a real call: `"mkstemp" in ln` let any line mentioning the word
    opt out (`… if not use_mkstemp else …`), which a battery used as a bypass;
    and every stdlib API that MINTS a unique name is sanctioned, not just
    `mkstemp` — `NamedTemporaryFile(suffix=".tmp")` reddened this guard and is
    the opposite of the defect. The stated cost: a no-space, keyword-shaped
    line (`tmp=path+".tmp"`) folded together with an UNCLOSED minting call —
    within six physical lines of it — is read as its argument; a spaced writer
    never is, and neither is anything after the call has closed.
    """
    found: dict = {}
    for logical, physicals in _logical_lines(text):
        phys = []
        for i, ph in enumerate(physicals):
            if _MINTING_CALL.search(ph):
                continue  # a line that mints on its own is the sanctioned shape
            if _KWARG_SHAPE.match(ph) and any(
                _MINTING_CALL.search(prev) for prev in physicals[max(0, i - _MINTING_LOOKBACK):i]
            ):
                continue
            h = _match_writer(ph, kind)
            if h:
                phys.append(h)
        for lhs in phys:
            found[lhs] = found.get(lhs, 0) + 1
        if not _MINTING_CALL.search(logical):
            lhs = _match_writer(logical, kind)
            if lhs and lhs not in phys:
                found[lhs] = found.get(lhs, 0) + 1
    return found


def _kind_for(p) -> str:
    """"py", "sh" or "md" — how the detector reads a file, or "" if it does not."""
    if p.suffix == ".py":
        return "py"
    if p.suffix == ".md":
        return "md"
    if p.suffix in _SCANNED_SUFFIXES:
        return "sh"
    if _is_shipped_script_without_suffix(p):
        try:
            head = p.read_bytes()[:120]
        except OSError:
            return ""
        return "py" if _PY_SHEBANG.match(head) else "sh"
    return ""


def _scanned_files():
    """(path, kind) for every shipped file the detector reads."""
    for p in sorted(_shipped_files()):
        kind = _kind_for(p)
        if kind:
            yield p, kind


def _scan_fixed_name_temps():
    """{(repo-relative path, lhs name): occurrences} for every derived-temp site."""
    found: dict = {}
    for p, kind in _scanned_files():
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lhs, n in _scan_text(text, kind).items():
            found[(str(p.relative_to(REPO_ROOT)), lhs)] = n
    return found


def test_no_new_fixed_name_temp_writers():
    """A temp path derived from its target is the collision class `Q-382`,
    `Q-414`, `Q-442` and `Q-444` closed writer by writer.

    **What this asserts, stated at the strength it was MEASURED at rather than
    the strength it was first written at.** It pins the population *its predicate
    can see*, exactly and in both directions — not "the population", which is a
    claim this guard has now failed four times and which two independent review
    batteries falsified again after each rewrite. Known reach limits, measured and
    filed as `Q-451`: a shell `local`/`export` prefix, a temp suffix outside
    `.tmp/.temp/.new/.bak`, an attribute target (`self.tmp = …`), an annotated
    assignment (`tmp: str = …`), a shell assignment with no spaces, and any line
    that happens to contain the token `mkstemp`.

    Why an exact set rather than a ceiling, which is the part that does hold:
    `Q-409` records that a count "could be widened to 400/400/300 with a green
    suite", so a count is the wrong primitive. A set cannot be widened without
    naming what was added, and naming it is the review.
    """
    found = _scan_fixed_name_temps()
    # The two lists together are the whole matched population. Anything outside
    # both is new — either a real writer, or a shape that needs assessing and
    # then recording in one of them. Neither list is an ignore list: both are
    # asserted exactly, in both directions, below.
    accounted = dict(KNOWN_FIXED_NAME_TEMPS)
    for k, n in ASSESSED_NOT_THE_CLASS.items():
        accounted[k] = accounted.get(k, 0) + n
    new = {k: n for k, n in found.items() if accounted.get(k, 0) < n}
    assert not new, (
        "new fixed-name temp writer(s) — a temp path derived from its target "
        "collides when two writers run at once (`Q-382`/`Q-414`/`Q-442`/`Q-444`). "
        "Use the shipped shape: realpath, carry the mode across (mkstemp creates "
        "0600), `tempfile.mkstemp(dir=<target's own dir>)` so os.replace cannot "
        "raise EXDEV, and a cleanup arm — a fixed-name leak self-heals on the next "
        "run, a mkstemp leak does not. Sites: " + ", ".join(sorted(map(str, new)))
    )
    gone = {k: n for k, n in accounted.items() if found.get(k, 0) < n}
    # Every ASSESSED site must still carry a PID token on the matched line. This
    # is the assertion the carve-out's own comment used to only claim.
    unpidded = []
    for (rel, lhs) in ASSESSED_NOT_THE_CLASS:
        body = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for ln, _n in _logical_lines(body):
            if _MINTING_CALL.search(ln):
                continue
            m = _PY_ASSIGN.match(ln)
            hit = (m and m.group("lhs") == lhs and _TEMP_LITERAL.search(m.group("rhs")))
            sh = _SH_ASSIGN.match(ln)
            hit = hit or (sh and sh.group("lhs") == lhs)
            if hit and not any(tok in ln for tok in _PID_TOKENS):
                unpidded.append(f"{rel}: {ln.strip()[:90]}")
    assert not unpidded, (
        "a site in ASSESSED_NOT_THE_CLASS no longer carries a PID in its temp name, so "
        "the judgement that put it there — unique per process, therefore not a collision "
        "hazard — no longer holds. Move it to KNOWN_FIXED_NAME_TEMPS or restore the PID:\n  "
        + "\n  ".join(unpidded)
    )
    assert not gone, (
        "declared-debt entr(ies) no longer present — converted, moved or renamed. "
        "Remove them from KNOWN_FIXED_NAME_TEMPS in the same commit, so the list "
        "keeps naming exactly the debt that is really there: " +
        ", ".join(sorted(map(str, gone)))
    )


def test_the_fixed_name_detector_is_not_vacuous():
    """Non-vacuity in the direction that actually fails.

    An exact-population assertion passes trivially if the predicate matches
    nothing — every known entry would simply be reported as `gone`, which is why
    that direction is asserted too. This pins the SHAPES, and it is deliberately
    a list of spellings rather than one idiom: the narrow version of this
    predicate reported a clean, exact population three separate times and was
    wrong each time (two sites a review lens found, then four spellings an
    independent battery walked through).
    """
    must_match = [
        ('tmp_path = index_path.with_suffix(index_path.suffix + ".tmp")', "tmp_path"),
        ('    tmp = body.with_suffix(body.suffix + ".tmp")', "tmp"),
        ('    tmp_a = path_a + ".tmp"', "tmp_a"),
        ('tmp_path = path + ".new"', "tmp_path"),
        # The shape a review lens found: the concat is not adjacent to `=`.
        ('    tmp = d / (dst.name + ".tmp")', "tmp"),
        # The four an independent battery walked through the previous version.
        ('    tmp = f"{real}.tmp"', "tmp"),
        ('    tmp = str(real) + ".tmp"', "tmp"),
        ('    tmp = "%s.tmp" % real', "tmp"),
        ('    tmp = "{}.tmp".format(real)', "tmp"),
        ('    tmp = p.with_name(p.name + ".tmp")', "tmp"),
        # Round 2 of Phase 272: spellings the docstring claimed and nothing pinned.
        ('    self.tmp = path + ".tmp"', "self.tmp"),
        ('    tmp: str = path + ".tmp"', "tmp"),
        ("    tmp = path + '.tmp'", "tmp"),
        ('    tmp = path + ".TMP"', "tmp"),
        ('    tmp = path + ".temp"', "tmp"),
        ('    tmp = path + ".swp"', "tmp"),
        ('    tmp = path + ".bak"', "tmp"),
        ('    tmp = path + "~"', "tmp"),
        ('    tmp = os.path.join(d, name + ".tmp")', "tmp"),
        # The WORD `mkstemp` on a line is not the sanctioned call (`M10`): `\\b`
        # does not separate `use_mkstemp`, so that spelling never tested it —
        # `mkstemp is None` does.
        ('    tmp = path + ".tmp" if mkstemp is None else mk()', "tmp"),
    ]
    for line, lhs in must_match:
        m = _PY_ASSIGN.match(line)
        assert m and _TEMP_LITERAL.search(m.group("rhs")), f"detector missed: {line!r}"
        assert m.group("lhs") == lhs, f"wrong lhs for {line!r}: {m.group('lhs')!r}"

    # Shell branch, including the unquoted form, `declare` with flags and
    # `export` (round 2: `M16`, `P20`).
    for line in ('  TMP="${DST}.tmp"', "  TMP=$DST.tmp", '  declare -r TMP="$DST.tmp"',
                 '    export TMP="${DST}.tmp"', '  local -r TMP="${DST}.tmp"'):
        sh = _SH_ASSIGN.match(line)
        assert sh and sh.group("lhs") == "TMP", f"detector missed the shell shape {line!r}"
    # The literal handed to a writing call with no assignment (`P28`).
    assert _scan_text('open(path + ".tmp", "w").write(data)\n', "py") == {"open(": 1}
    assert _scan_text('with open(path + ".tmp", "w", encoding="utf-8") as f:\n', "py") == {"open(": 1}
    # The line-level shapes that must NOT fire, through the real scanner:
    # a Python constant is not a shell assignment (`M09`); a wrapped kwarg with
    # its trailing comma (`M17`); the single-target sanctioned one-liner (`M26`);
    # the word `mkstemp` without a call does not exempt a line (`M10`, above).
    assert _scan_text('S=".tmp"\n', "py") == {}
    assert _scan_text('    prefix=os.path.basename(real) + ".", suffix=".tmp",\n', "py") == {}
    assert _scan_text('tmp = NamedTemporaryFile(suffix=".tmp")\n', "py") == {}
    assert _scan_text('    tmp = path + ".tmp" if mkstemp is None else mk()\n', "py") == {"tmp": 1}
    # …and a nested call inside the write call's argument does not end the search
    assert _scan_text('open(os.path.join(d, name) + ".tmp", "w").close()\n', "py") == {"open(": 1}

    must_not_match = [
        # A keyword argument on a continuation line of the SANCTIONED call. The
        # `mkstemp` line-exclusion covers the call itself; the spaces-around-`=`
        # requirement covers its wrapped arguments.
        '        dir=os.path.dirname(real), prefix=os.path.basename(real) + ".", suffix=".tmp"',
        # `.tmpl` is a template: the closing quote must follow the extension.
        'label = name + ".tmpl"',
        # No string literal with a temp extension at all.
        'out = path + ".yml"',
    ]
    for line in must_not_match:
        # `_PY_ASSIGN_SPACED` is the form used for markdown and shell, where a
        # wrapped keyword argument of the sanctioned `mkstemp` call is the shape
        # that must not fire. In real `.py` files the same line is excluded by the
        # paren-depth check in `_scan_fixed_name_temps`, which this unit test
        # cannot see — so it exercises the predicate that stands alone.
        m = _PY_ASSIGN_SPACED.match(line)
        assert not (m and _TEMP_LITERAL.search(m.group("rhs"))), (
            f"detector false-positives on {line!r}"
        )
    # And the paren-depth exclusion is asserted where it actually lives — on
    # the real scanner, not a replica of it: a wrapped kwarg inside a call must
    # not be reported as a writer, and (Phase 272's round, `D16`) a temp literal
    # on a CONTINUATION line of an assignment must be.
    assert _scan_text(
        "import os, tempfile\n"
        "def w(real):\n"
        "    fd, tmp = tempfile.mkstemp(\n"
        "        dir=os.path.dirname(real),\n"
        '        prefix=os.path.basename(real) + ".", suffix=".tmp"\n'
        "    )\n"
        "    return tmp\n", "py") == {}, "a wrapped mkstemp kwarg was reported as a writer"
    assert _scan_text('tmp = (str(real)\n    + ".tmp")\n', "py") == {"tmp": 1}, (
        "a temp literal on a continuation line was not seen")
    # Markdown heredocs get the no-space rule too (`D10`).
    assert _scan_text('tmp=str(p)+".tmp"\n', "md") == {"tmp": 1}
    # A `.partial` joins the family; `.tmpl` still does not.
    assert _scan_text('out = path + ".partial"\n', "py") == {"out": 1}
    assert _scan_text('label = name + ".tmpl"\n', "py") == {}
    # Extensionless Python scripts are population, not just shell ones (`D09`).
    assert _SHEBANG.match(b"#!/usr/bin/env python3\n") and _PY_SHEBANG.match(b"#!/usr/bin/env python3\n")
    assert _SHEBANG.match(b"#!/usr/bin/env bash\n") and not _PY_SHEBANG.match(b"#!/usr/bin/env bash\n")

    # And the population it reports must be non-empty.
    assert _scan_fixed_name_temps(), "detector scanned the tree and matched nothing"


def _legal_positions(text: str, kind: str):
    """(line index, indent) pairs where a statement may legally be inserted."""
    lines = text.splitlines()
    if kind == "py":
        import ast
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        seen = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.stmt):
                ln = node.lineno - 1
                seen.add((ln, len(lines[ln]) - len(lines[ln].lstrip())))
        return sorted(seen)
    out = []
    for i, ln in enumerate(lines):
        if ln.rstrip().endswith("\\"):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        out.append((i + 1, len(nxt) - len(nxt.lstrip()) if nxt.strip() else 0))
    return out


def test_the_detector_reaches_every_position_it_is_given():
    """The detector sees a writer wherever one can legally be written, by execution.

    Round 1 of Phase 272 measured the first version blind to 4,881 of 51,110
    scanned lines — every line after a stray `(` — and the guard written for
    it probed the TAIL of each file only. Round 2 then measured the rewrite
    blind at 650 of 20,199 sampled INTERIOR positions, where the tail probe
    could not look. So this probes both: the tail, and a deterministic sample
    of legal interior positions per file (statement starts for Python, line
    boundaries for shell and markdown), each with the canonical writer
    indented like its neighbour. The probe NAME is random per run (`M28`: a
    scanner that returns the probe's fixed name for every input satisfied the
    first guard). Windowed scans first, a full-file scan to confirm any miss,
    so a fold state at the window's edge cannot fake one.
    """
    import random
    import secrets
    import string
    rnd = random.Random(272)
    # No fixed prefix: a scanner that recognised `zz_probe_…` satisfied the
    # first draft (`M28`). Reach is what this guard measures; TRUTH is the
    # exact-population guard's job, which a scanner faking a hit cannot pass.
    name = "".join(secrets.choice(string.ascii_lowercase) for _ in range(10))
    probe = {"py": f'{name} = path + ".tmp"', "md": f'{name} = path + ".tmp"',
             "sh": f'{name.upper()}="${{DST}}.tmp"'}
    lhs_of = {"py": name, "md": name, "sh": name.upper()}
    blind, scanned, probed = [], 0, 0
    for p, kind in _scanned_files():
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        lines = text.splitlines()
        positions = _legal_positions(text, kind)
        if len(positions) > 12:
            positions = rnd.sample(positions, 12)
        positions.append((len(lines), 0))  # the tail, always
        for ln, indent in positions:
            prev = lines[ln - 1] if 0 < ln <= len(lines) else ""
            if _MINTING_CALL.search(prev):
                continue  # inside the sanctioned call's own arguments is not a legal position
            new = lines[:ln] + [" " * indent + probe[kind]] + lines[ln:]
            probed += 1
            lo, hi = max(0, ln - 120), min(len(new), ln + 120)
            if _scan_text("\n".join(new[lo:hi]) + "\n", kind).get(lhs_of[kind], 0) == 1:
                continue
            if _scan_text("\n".join(new) + "\n", kind).get(lhs_of[kind], 0) != 1:
                blind.append(f"{p.relative_to(REPO_ROOT)}:{ln + 1}")
    assert scanned > 120, f"the scanned population collapsed to {scanned} files"
    assert probed > 1500, f"only {probed} positions probed"
    assert not blind, (
        "the detector cannot see a writer at these positions:\n  " + "\n  ".join(blind[:40]))


def test_the_scanned_population_holds_what_the_rounds_planted_in():
    """Population, asserted as membership rather than as a count that could be
    widened or narrowed unseen: the four shipped hook examples (`M22` dropped
    `.example` and the reach guard could not tell), an extensionless Python
    script is read as Python (`M06`), and the shell-bearing YAML fragments are
    read at all (`P34`)."""
    files = {str(p.relative_to(REPO_ROOT)): kind for p, kind in _scanned_files()}
    examples = [f for f in files if f.startswith("core/companion/git-hooks/examples/")]
    assert len(examples) >= 4, examples
    assert all(files[f] == "sh" for f in examples)
    assert files["core/companion/git-hooks/pre-commit"] == "sh"
    assert files["install.sh"] == "sh"
    fragments = [f for f in files if f.endswith("checks.yml.fragment")]
    assert len(fragments) >= 4, fragments
    import tempfile as _tf
    with _tf.TemporaryDirectory() as d:
        py = Path(d) / "tool"
        py.write_bytes(b"#!/usr/bin/env python3\nimport os\n")
        assert _kind_for(py) == "py"
        sh = Path(d) / "hook"
        sh.write_bytes(b"#!/usr/bin/env bash\nset -e\n")
        assert _kind_for(sh) == "sh"
        none = Path(d) / "data"
        none.write_bytes(b"plain\n")
        assert _kind_for(none) == ""


def test_the_fold_is_bounded_and_cannot_hide_a_line():
    """The mechanisms round 2 found unpinned, pinned on synthetic input.

    The 40-line cap and the unindented reset bound a fold (`M02`/`M31`); a
    closer at column 0 does NOT reset (`M32`); parens are counted AFTER the
    comment is stripped (`M03`); a stray `(` in a docstring, a markdown anchor
    `(#x)`, a regex `r"(#…"` and a shell `'(…\\('` do not fold the writer
    after them out of sight; and a kwarg-shaped line right after a minting call
    is the call's argument while a spaced writer there is still a writer.
    """
    # cap: 45 INDENTED lines inside an unclosed paren still flush (the unindented
    # reset cannot be what flushes them), and the writer after is seen
    body = "    x = (\n" + "".join("        1,\n" for _ in range(45)) + '    tmp = p + ".tmp"\n'
    assert len(list(_logical_lines(body))) >= 2, "the 40-line cap did not flush"
    assert _scan_text(body, "py") == {"tmp": 1}
    # a column-0 closer does not reset
    assert len(list(_logical_lines("x = (\n    1\n)\n"))) == 1
    # comment stripped BEFORE the paren count — an indented pair, so the
    # unindented reset cannot be what separates them
    assert len(list(_logical_lines('    x = 1  # (\n    tmp = p + ".tmp"\n'))) == 2
    # the four stray-opener shapes, each followed by an indented writer
    for opener in ['    """A docstring (with a stray opener\n',
                   'See the [phases](#2-lifecycle-phases) section.\n',
                   '    pat = re.compile(r"(#\\d+")\n',
                   "    grep -qE '(foo\\()' file\n",
                   '    print("(")\n']:
        text = opener + "    y = 1\n" + '    tmp = p + ".tmp"\n'
        assert _scan_text(text, "sh" if "grep" in opener else "py").get("tmp") == 1, opener
    # kwarg after a minting call: argument; spaced writer after it: writer
    text = ('fd, t = tempfile.mkstemp(\n    dir=d,\n    suffix=".tmp"\n)\n'
            'tmp = p + ".tmp"\n')
    assert _scan_text(text, "py") == {"tmp": 1}
    # a no-space writer after a COMPLETE minting call is still a writer — the
    # lookback runs inside one fold, so only a kwarg-shaped line folded together
    # with an UNCLOSED minting call reads as its argument (the stated cost)
    assert _scan_text('fd, t = tempfile.mkstemp(dir=d)\ntmp=p+".tmp"\n', "py") == {"tmp": 1}
    assert _scan_text('fd, t = tempfile.mkstemp(\n    dir=d,\n    tmp=p+".tmp"\n)\n', "py") == {}


def test_the_two_population_lists_are_disjoint_and_both_used():
    """Neither list may quietly absorb the other's entries.

    `ASSESSED_NOT_THE_CLASS` is a judgement ("PID-qualified, so not a collision
    hazard"); `KNOWN_FIXED_NAME_TEMPS` is debt. Letting a real writer drift into
    the assessed list is how an exact assertion becomes an ignore list, so the
    two are checked disjoint and the assessed list is checked non-empty. The
    debt list is ALLOWED to be empty — it has been since Phase 272 converted the
    last nine — because its exactness is carried by the `new` direction of
    `test_no_new_fixed_name_temp_writers` (a visible writer in neither list
    reds) and the predicate's own vacuity is asserted separately.
    """
    overlap = set(KNOWN_FIXED_NAME_TEMPS) & set(ASSESSED_NOT_THE_CLASS)
    assert not overlap, f"a site is in both population lists: {overlap}"
    assert ASSESSED_NOT_THE_CLASS, "the assessed list is empty; the carve-out is unused"
    # And the lists mean what they say in BOTH directions: an assessed site
    # must carry a PID (checked in `test_no_new_fixed_name_temp_writers`), and
    # a DEBT site must not — round 2 moved `install_hooks.sh` into the debt
    # list with its `$$` intact and nothing objected (`M30`).
    pidded_debt = []
    for (rel, lhs) in KNOWN_FIXED_NAME_TEMPS:
        body = (REPO_ROOT / rel).read_text(encoding="utf-8")
        for ln, _ in _logical_lines(body):
            if _match_writer(ln, _kind_for(REPO_ROOT / rel)) == lhs and any(t in ln for t in _PID_TOKENS):
                pidded_debt.append(f"{rel}: {ln.strip()[:80]}")
    assert not pidded_debt, (
        "a KNOWN_FIXED_NAME_TEMPS entry carries a PID in its temp name — that is the "
        "assessed shape, not debt; move it to ASSESSED_NOT_THE_CLASS:\n  " + "\n  ".join(pidded_debt))
