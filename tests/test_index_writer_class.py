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
}

# `safe_dump` sites in the shipped tree that do NOT write the task index.
NON_INDEX_DUMP_SITES = {"install.sh"}

SHIPPED_ROOTS = ("core", "packs")

AUTHORING_SKILLS = {
    "core/skills/add-task/SKILL.md",
    "core/skills/intake/SKILL.md",
    "core/skills/onboard/SKILL.md",
}

TASKS_README = "core/companion/tasks/README.md"


def _flat(text: str) -> str:
    """Whitespace-normalised, so a reflow never reds a pin but a reword does."""
    return " ".join(text.split())


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
        "**Copy the fields, not the comments.**",
    ),
}

# `RULE_STATED` holds the same requirement at the level of meaning, so the rule
# cannot simply be deleted while the reason clause survives. Loose on wording.
RULE_STATED: dict[str, re.Pattern[str]] = {
    "core/skills/add-task/SKILL.md": re.compile(r"quote (every|the|each)[^.]{0,20}`title:`", re.I),
    "core/skills/intake/SKILL.md": re.compile(r"quote (every|the|each)[^.]{0,20}`title:`", re.I),
    "core/skills/onboard/SKILL.md": re.compile(r"quote (every|the|each)[^.]{0,20}`title:`", re.I),
    TASKS_README: re.compile(r"quote the title", re.I),
}


@pytest.mark.parametrize("path", sorted(PINS))
def test_the_negation_sensitive_clauses_are_present_verbatim(path: str):
    """A token check for "comment" and "read" passes on a sentence asserting the
    opposite — the round inverted the rule in all three skills and in the README
    and every one stayed green. These clauses are what catch negation."""
    flat = _flat((REPO_ROOT / path).read_text(encoding="utf-8"))
    missing = [clause for clause in PINS[path] if _flat(clause) not in flat]
    assert missing == [], (
        f"{path} no longer carries a clause whose negation is the defect. If you "
        "reworded it deliberately, update PINS in this file — that is the point "
        f"of the pin, not an obstacle to it.\n  missing: {missing}"
    )


@pytest.mark.parametrize("path", sorted(RULE_STATED))
def test_the_quoting_rule_is_stated(path: str):
    flat = _flat((REPO_ROOT / path).read_text(encoding="utf-8"))
    assert RULE_STATED[path].search(flat), f"{path} no longer states the quoting rule"


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
    for fragment in (
        "`/claim-task` Step 4a",
        "`/auto-build` Step 5.1",
        "`claim_task.sh --release`",
        "`/review-close` Step 4c",
        "`backfill_completed_dates.py`",
    ):
        assert _flat(fragment) in section, (
            f"the round-trip warning section omits {fragment}"
        )
    assert "Five code paths rewrite it whole" in section


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
    """
    files = [REPO_ROOT / "install.sh"]
    for root in SHIPPED_ROOTS:
        for ext in ("*.md", "*.sh", "*.yml", "*.yaml"):
            files.extend(sorted((REPO_ROOT / root).rglob(ext)))
    return files


_TITLE_LINE = re.compile(r"^[\s>#-]*title:\s*(?P<value>.*?)\s*$")


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
