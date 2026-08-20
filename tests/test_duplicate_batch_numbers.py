"""Duplicate batch numbers: refuse on mutate, warn on read (Phase 209, Q-037/Q-227).

`review_index.py` keys batches by number in a dict, so a second `### Batch <N>`
header silently OVERWRITES the first.

Measured 2026-08-16 on a sibling multi-round tracker on this machine
(de-identified per the leg-5 naming rule): **11** batch headers in the file,
**6** reported by `--list`, and `--range 1` returning line 194 — Round 2's
section — while Round 1's Batch 1 sits at line 18, 176 lines earlier. No fence
was involved, so Phase 208's `--check-fences` reported the file clean.

**Provenance, because this is the evidence a ratified decision rests on:** that
tracker was produced by a model from the shipped template during a discontinued
lab comparison. It is not a live consumer queue, and the phase's first record of
it said "a real tracker", which overstates. What it demonstrates is that the
shape is *reachable from the shipped template*, which is what the scoping
argument needs — not that a consumer has hit it.

**The scoping is the design, and these tests exist mostly to hold it.** The
refusal is keyed to THE NUMBER BEING ACTED ON, not to the file, because
per-round renumbering is legal: `WORKFLOW.md`'s template nests `### Batch <N>`
under `## Round N` and states no numbering scope. A whole-file refusal would
reject a tracker generated from the shipped template — the defect Phase 208 shipped and
had to reshape mid-round. (Phase 211 struck a third clause here — *"and no
shipped skill derives the next number from existing headers"* — which is false:
`codebase-review/SKILL.md:164` and `security-audit/SKILL.md:179` both do,
file-globally. The scoping argument rests on the template's silence and on
nothing ENFORCING the writers' rule, which is narrower than the struck
clause claimed.) So the control below
(`test_an_unambiguous_batch_on_a_renumbered_file_still_claims`) is load-bearing:
it fails if anyone widens the refusal to the file.
"""
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
BATCH_WORK = SCRIPTS / "batch_work.sh"
INDEX = SCRIPTS / "review_index.py"

sys.path.insert(0, str(SCRIPTS))


def _git(cwd, *args, check=True):
    return subprocess.run(["git", *args], cwd=str(cwd), check=check,
                          capture_output=True, text=True)


def _batch(n, title, status, branch):
    return (
        f"### Batch {n} — {title} `{status}`\n"
        f"> **Branch:** `{branch}`\n"
        f"> **Scope:** src/x.py\n"
        f"> **Verify:** pytest -q\n"
        f"\n"
        f"- [ ] **TASK-{n}01** work\n"
        f"\n"
    )


# Two rounds, numbering restarted. This is the shape measured in the wild.
RENUMBERED = (
    "# Review Tasks\n\n"
    "## Round 1 — 2026-08-16\n\n"
    + _batch(1, "Auth", "Pending", "review/r1-b1")
    + _batch(2, "API", "Pending", "review/r1-b2")
    + "## Round 2 — 2026-08-16\n\n"
    + _batch(1, "Test quality", "Pending", "review/r2-b1")
    + "## Statistics\n"
)

# Same file, but every number is unique.
UNIQUE = (
    "# Review Tasks\n\n"
    "## Round 1 — 2026-08-16\n\n"
    + _batch(1, "Auth", "Pending", "review/r1-b1")
    + _batch(2, "API", "Pending", "review/r1-b2")
    + "## Statistics\n"
)


def _repo(root, tasks):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "review_tasks.md").write_text(tasks)
    (root / ".gitignore").write_text(".claude/review_index.json\n")
    sd = root / "sysop" / "scripts"
    sd.mkdir(parents=True, exist_ok=True)
    for name in ("review_index.py", "_log.py", "batch_work.sh"):
        src = SCRIPTS / name
        if src.exists():
            shutil.copy(src, sd / name)
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(cwd, *args):
    return subprocess.run(["bash", str(BATCH_WORK), *args], cwd=str(cwd),
                          capture_output=True, text=True)


def _index(cwd, *args):
    return subprocess.run([sys.executable, str(cwd / "sysop/scripts/review_index.py"), *args],
                          cwd=str(cwd), capture_output=True, text=True)


# ── The detector itself ───────────────────────────────────────

def test_detector_reports_every_repeated_number_with_its_lines():
    import review_index as ri
    lines = RENUMBERED.split("\n")
    dupes = ri.duplicate_batch_numbers(lines)
    assert set(dupes) == {"1"}, f"expected only Batch 1 doubled, got {dupes}"
    assert len(dupes["1"]) == 2
    # The line numbers must actually point at the headers, or the diagnostic
    # sends the operator to the wrong place.
    for ln in dupes["1"]:
        assert lines[ln - 1].startswith("### Batch 1 "), \
            f"line {ln} is {lines[ln - 1]!r}, not a Batch 1 header"


def test_the_parser_overwrites_with_the_LAST_same_numbered_batch():
    """Battery row B01 — nothing pinned the direction of the overwrite.

    `Q-037`'s entire filing rests on it: *"`--list` reports the LAST one …
    because batches are keyed by number in a dict and the later entry
    overwrites the earlier"*. Flipping the write to `setdefault` (first-wins)
    left every test in this repo green, which means the sentence the filing and
    both diagnostics are written from was enforced by nothing.

    Pinned as documentation of current behaviour, NOT as an endorsement: either
    winner is a guess about intent, which is why the refusal exists. If a later
    phase makes the parser reject duplicates outright, this test should be
    rewritten to that contract rather than deleted.
    """
    import review_index as ri
    text = (
        "# Review Tasks\n\n"
        + _batch(1, "First", "Merged", "review/FIRST")
        + _batch(1, "Second", "Pending", "review/SECOND")
        + "## Statistics\n"
    )
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as fh:
        fh.write(text)
        path = fh.name
    batches = ri.parse_review_tasks(path)["batches"]
    assert list(batches) == ["1"], "two headers must collapse to one dict entry"
    assert batches["1"]["branch"] == "review/SECOND", (
        "the LAST same-numbered batch must win — if this flipped, every "
        "diagnostic that says 'only the last is reported' is now false"
    )
    assert batches["1"]["status"] == "Pending"


def test_detector_is_empty_on_a_unique_file():
    import review_index as ri
    assert ri.duplicate_batch_numbers(UNIQUE.split("\n")) == {}


def test_a_fenced_duplicate_is_not_a_duplicate():
    """The mask is applied, so a documentation example does not trip the check.

    Without this the detector would fire on every tracker that quotes a batch
    header in a fenced block — which is most of them, and is exactly the
    false-fire class Phase 208 had to reshape around.
    """
    import review_index as ri
    text = (
        "# Review Tasks\n\n"
        + _batch(1, "Real", "Pending", "review/real")
        + "An example:\n\n```markdown\n"
        + "### Batch 1 — EXAMPLE `Pending`\n"
        + "```\n\n## Statistics\n"
    )
    assert ri.duplicate_batch_numbers(text.split("\n")) == {}


def test_a_near_miss_header_is_not_a_duplicate():
    """A REGRESSION GUARD, and the first version of this test asserted the bug.

    The detector must count only headers `parse_review_tasks` actually turns
    into batches — the STRICT pattern. The first cut used the permissive twin
    `_BATCH_HEADER_ANY_RE`, which is a superset that exists solely to notice a
    header the strict pattern rejected so the open batch can be closed. That
    made every malformed `### Batch <N>` line count as a declaration.

    Consequence, measured before the fix: a tracker carrying one real Batch 1
    and one near-miss produced exactly ONE batch from the parser and was still
    refused at the claim path, with a false diagnostic ("would silently pick one
    and discard the other" — nothing was discarded) and an inapplicable remedy
    ("renumber one of them" — it is not a batch to renumber). The same file
    claimed cleanly before this phase, so the refusal was a regression.

    This test previously asserted the OPPOSITE — that a tab-separated near-miss
    *was* detected — and so pinned the defect in place. Kept as a cautionary
    note rather than silently rewritten: a guard can hold the wrong contract
    just as firmly as the right one.
    """
    import review_index as ri
    for near_miss in (
        "###\tBatch 1 — Tabbed `Pending`",        # tab, not a space
        "### Batch 1 - ASCII hyphen `Pending`",   # hyphen, not an em-dash
        "### Batch 1 draft (superseded)",         # no status token at all
    ):
        text = ("# Review Tasks\n\n"
                + _batch(1, "One", "Pending", "review/a")
                + near_miss + "\n\n## Statistics\n")
        lines = text.split("\n")
        # Precondition: the permissive twin DOES match it, so this test is
        # meaningfully distinguishing the two patterns rather than passing
        # because nothing matched at all.
        assert ri._BATCH_HEADER_ANY_RE.match(near_miss), \
            f"precondition failed: ANY should match {near_miss!r}"
        assert ri.duplicate_batch_numbers(lines) == {}, (
            f"{near_miss!r} is not a batch the parser creates, so it must not "
            "make Batch 1 ambiguous and block a legal claim"
        )


def test_the_detector_and_the_parser_agree_on_what_a_batch_is():
    """Identity, not sampling: the detector's notion of a declaration must be
    exactly the parser's. Derived from the shipped patterns rather than a list
    of spellings, so a change to either side is caught rather than guessed at.
    """
    import review_index as ri
    text = ("# Review Tasks\n\n"
            + _batch(1, "One", "Pending", "review/a")
            + _batch(1, "Two", "Pending", "review/b")
            + "## Statistics\n")
    lines = text.split("\n")
    strict_hits = [i + 1 for i, ln in enumerate(lines)
                   if ri._BATCH_HEADER_RE.match(ln)]
    assert ri.duplicate_batch_numbers(lines) == {"1": strict_hits}, \
        "the detector must report exactly the lines the strict parser accepts"


# ── The mutating half: refuse, scoped to the number ───────────

def test_claiming_an_ambiguous_number_refuses_without_mutating(tmp_path):
    repo = _repo(tmp_path / "dup", RENUMBERED)
    r = _run(repo, "1")
    assert r.returncode != 0, f"claimed an ambiguous batch: {r.stdout}"
    assert "declares Batch 1" in r.stderr, r.stderr
    # The line numbers belong in the diagnostic — "it is ambiguous" without
    # saying where is not actionable. Assert the ACTUAL line numbers, derived
    # from the fixture: the first version asserted `":" in r.stderr`, which the
    # leading "ERROR:" satisfies, so deleting the locations entirely left this
    # green. Found by the review round.
    import review_index as _ri
    expected = _ri.duplicate_batch_numbers(RENUMBERED.split("\n"))["1"]
    for ln in expected:
        assert f":{ln}" in r.stderr, (
            f"the refusal must name line {ln}; stderr was {r.stderr!r}"
        )
    assert _git(repo, "branch", "--format=%(refname:short)").stdout.split() == ["main"]
    assert not (repo / "sysop/runtime/locks").exists(), "a refused claim wrote a lock"
    assert _git(repo, "status", "--porcelain").stdout.strip() == "", \
        "a refused claim dirtied the tree"


def test_an_unambiguous_batch_on_a_renumbered_file_still_claims(tmp_path):
    """THE CONTROL. Reds if the refusal is ever widened from the number to the
    file. A tracker that restarts numbering per round is legal, and Batch 2 on
    it is unambiguous, so it must remain claimable."""
    repo = _repo(tmp_path / "ok", RENUMBERED)
    r = _run(repo, "2")
    assert r.returncode == 0, f"refused a legal, unambiguous batch: {r.stderr}"
    assert "review/r1-b2" in _git(repo, "branch", "--format=%(refname:short)").stdout


def test_releasing_an_ambiguous_number_refuses(tmp_path):
    repo = _repo(tmp_path / "rel", RENUMBERED)
    r = _run(repo, "--release", "1")
    assert r.returncode != 0, f"released an ambiguous batch: {r.stdout}"
    assert "declares Batch 1" in r.stderr


def test_force_does_not_bypass_the_refusal(tmp_path):
    """`--force` already admits `Complete|Merged|Ready for Review`. If the
    refusal sat after flag parsing, an existing flag would reopen the hole —
    the trap Phase 208 documented for the fence refusal."""
    repo = _repo(tmp_path / "forced", RENUMBERED)
    r = _run(repo, "--force", "1")
    assert r.returncode != 0, f"--force bypassed the duplicate refusal: {r.stdout}"
    assert _git(repo, "branch", "--format=%(refname:short)").stdout.split() == ["main"]


def test_check_duplicates_exit_code_is_distinct(tmp_path):
    """Exit 4, not 1: the shell arm keys on it, and 1 is every other error."""
    repo = _repo(tmp_path / "rc", RENUMBERED)
    assert _index(repo, "--check-duplicates", "1").returncode == 4
    assert _index(repo, "--check-duplicates", "2").returncode == 0


# ── The reading half: warn, never refuse ──────────────────────

def test_list_warns_but_still_exits_zero(tmp_path):
    """A reader that refused would take `/sitrep`, `/next-task`, `/triage`,
    `/auto-fix`, `/auto-judge` and `/roadmap` offline over a heading."""
    repo = _repo(tmp_path / "warn", RENUMBERED)
    r = _index(repo, "--list")
    assert r.returncode == 0, "a reading surface must not refuse"
    assert "WARNING" in r.stderr and "Batch 1" in r.stderr
    assert "invisible" in r.stderr, \
        "the warning must say a batch is missing, not merely that a number repeats"


def test_the_warning_does_not_pollute_stdout(tmp_path):
    """`batch_work.sh` parses this stream. A warning on stdout would be read as
    a batch row."""
    repo = _repo(tmp_path / "clean", RENUMBERED)
    out = _index(repo, "--list").stdout
    assert "WARNING" not in out
    for line in out.splitlines():
        assert line.split("\t")[0].isdigit(), f"non-row on stdout: {line!r}"


def test_list_all_surfaces_the_warning_through_the_shell(tmp_path):
    """The whole point of Q-227: the operator is told to run `--list-all`, so
    the collision has to be visible THERE, not only from Python."""
    repo = _repo(tmp_path / "shell", RENUMBERED)
    r = _run(repo, "--list-all")
    assert r.returncode == 0
    assert "WARNING" in r.stderr, \
        "batch_work.sh swallowed the warning — check stderr is not redirected"


# ── close_batch.sh is the OTHER mutator (round finding, HIGH) ──

def test_close_batch_refuses_an_ambiguous_number_without_rewriting(tmp_path):
    """Found by this phase's own review round, and it was a real gap.

    `batch_work.sh` refused an ambiguous number while `close_batch.sh` — which
    rewrites `review_tasks.md` AND commits — did not. It resolved the number
    through `--range`, which keys by number and returns the LAST header, so on a
    tracker with Batch 1 in two rounds it closed Round 2 and committed, leaving
    Round 1 open under an unchanged header. An operator who had merged Round 1
    would have marked the wrong work done, with no warning on any stream
    (this path calls `--range`, never `--list`, so the reader warning never
    fired).

    The phase's original scoping reasoned that `close_batch.sh` cannot refuse.
    That is true of `find_batch_range`'s internal refusal, whose sole caller
    overwrites it with a false "Not found" message — it is NOT true of an
    explicit check in the batch loop, which owns its own verdict and skips using
    the script's existing idiom.
    """
    import shutil as _sh
    repo = tmp_path / "cb"
    repo.mkdir(parents=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(repo)],
                   check=True, capture_output=True)
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "review_tasks.md").write_text(
        "# Review tasks\n\n## Round 1 — 2026-08-16\n\n"
        + _batch(1, "Round one", "In Progress", "review/r1")
        + "## Round 2 — 2026-08-16\n\n"
        + _batch(1, "Round two", "In Progress", "review/r2")
        + "## Statistics\n"
    )
    (repo / ".gitignore").write_text(".claude/review_index.json\n")
    sd = repo / "sysop" / "scripts"
    sd.mkdir(parents=True)
    for n in ("review_index.py", "_log.py", "close_batch.sh"):
        if (SCRIPTS / n).exists():
            _sh.copy(SCRIPTS / n, sd / n)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "seed")
    before = (repo / "review_tasks.md").read_text()
    commits_before = _git(repo, "rev-list", "--count", "HEAD").stdout.strip()

    r = subprocess.run(["bash", str(SCRIPTS / "close_batch.sh"), "--force", "1"],
                       cwd=str(repo), capture_output=True, text=True)
    assert "ambiguous" in (r.stdout + r.stderr).lower(), (r.stdout, r.stderr)
    assert "1:ambiguous" in r.stdout, "the skip verdict must record WHY it skipped"
    assert (repo / "review_tasks.md").read_text() == before, \
        "an ambiguous close rewrote the tracker"
    assert _git(repo, "rev-list", "--count", "HEAD").stdout.strip() == commits_before, \
        "an ambiguous close committed"


def test_a_present_but_unusable_parser_fails_loudly(tmp_path):
    """Presence is not usability — the round's HIGH 2.

    A truncated `review_index.py` defines nothing, runs nothing and exits 0 with
    empty output, so `--list` printed an empty table, said "No batches found" on
    a tracker full of them, and exited 0 with no diagnostic. The retirement's
    whole justification is that the failure becomes loud instead of silent, and
    the phase's record asserted that before it was true.
    """
    repo = _repo(tmp_path / "corrupt", RENUMBERED)
    idx = repo / "sysop/scripts/review_index.py"
    idx.write_text("\n".join(idx.read_text().splitlines()[:400]) + "\n")
    r = _run(repo, "--list")
    assert r.returncode != 0, \
        f"a corrupt parser exited {r.returncode} — silent degradation is the defect"
    assert "not usable" in r.stderr, r.stderr
    assert "No batches found" not in r.stdout, \
        "the script reported a clean empty tracker over a parser that never ran"


def test_a_leading_zero_does_not_defeat_the_detector():
    """One padded header defeated BOTH gates. Found by the review round.

    `parse_review_tasks` keys batches on `str(int(...))`, so `### Batch 07` and
    `### Batch 7` collapse into ONE entry — the later silently discarding the
    earlier, which is precisely the `Q-037` harm. The detector keyed on the raw
    digit run, saw `"07"` and `"7"` as distinct, reported no duplicate, and the
    claim proceeded and created a branch.

    The same normalization gap defeated Phase 208's `unterminated_structural_span`,
    whose `outside` set was also raw-keyed, so a fenced `### Batch 07` colliding
    with a real `### Batch 7` reported `fences ok`.

    Both are asserted here because they are one defect with two sites, and
    fixing either alone leaves a claimable phantom.
    """
    import review_index as ri
    tmpl = ("# R\n\n"
            "### Batch {a} — First `Merged`\n> **Branch:** `review/A`\n\n"
            "### Batch {b} — Second `Pending`\n> **Branch:** `review/B`\n\n"
            "## Statistics\n")
    for a, b in (("07", "7"), ("7", "07"), ("007", "007"), ("0007", "7")):
        dupes = ri.duplicate_batch_numbers(tmpl.format(a=a, b=b).split("\n"))
        assert dupes == {"7": [3, 6]}, (
            f"Batch {a} and Batch {b} are the same batch to the parser, so they "
            f"must be one duplicated number — got {dupes}"
        )

    # Phase 208's fence gate, same normalization — BOTH directions.
    #
    # Both are needed and the first version of this test had only one. That
    # function normalizes at two places: building the `outside` set from the
    # lines above the fence, and testing each line below it. A fixture that
    # pads only the FENCED header exercises the second site alone, so reverting
    # the first left the suite green. The padding can be on either side.
    for real, fenced in (("7", "07"), ("07", "7"), ("007", "7")):
        hit = ri.unterminated_structural_span([
            f"### Batch {real} — Real `Merged`",
            "```markdown",
            f"### Batch {fenced} — EXAMPLE `Pending`",
        ])
        assert hit is not None, (
            f"a fenced `Batch {fenced}` colliding with a real `Batch {real}` "
            "must still refuse — they are the same batch to the parser"
        )
    # CONTROL: genuinely different numbers must not trip the fence gate.
    assert ri.unterminated_structural_span([
        "### Batch 7 — Real `Merged`",
        "```markdown",
        "### Batch 8 — A different EXAMPLE `Pending`",
    ]) is None, "the fence gate fired on two different batch numbers"

    # CONTROLS — normalization must not invent collisions.
    assert ri.duplicate_batch_numbers(tmpl.format(a="1", b="2").split("\n")) == {}, \
        "two genuinely different numbers must not collide"
    assert ri.duplicate_batch_numbers(tmpl.format(a="10", b="1").split("\n")) == {}, \
        "10 and 1 are different batches; stripping digits rather than parsing " \
        "the integer would merge them"


# ── The two readers that never consult the index (Q-227, Phase 211) ─────
#
# Phase 209 shipped the WARNING half on `review_index.py --list`, and its own
# round then found the entry's premise false: `next_task.py` and
# `sitrep_survey.py` do not read the index at all, so that warning could never
# reach them. They carry list-shaped parsers of their own and keep BOTH
# same-numbered batches where the index collapses to one.
#
# Keeping both is better for display and is deliberately unchanged. It became a
# ROUTING defect only once Phase 209 taught the mutators to refuse an ambiguous
# number with exit 4: after that, `/sitrep` could recommend a batch that
# `batch_work.sh` and `close_batch.sh` both refuse, with nothing on any stream
# saying why.

_DUP_TRACKER = (
    "# Review Tasks\n\n"
    "## Round 1 — 2026-08-01\n\n"
    "### Batch 3 — First `Merged`\n\n"
    "> **Branch:** `review/a`\n\n"
    "- [x] **TASK-1**: done\n\n"
    "## Round 2 — 2026-08-16\n\n"
    "### Batch 3 — Second `Pending`\n\n"
    "> **Branch:** `review/b`\n\n"
    "- [ ] **TASK-2**: open\n\n"
    "## Statistics\n"
)
_UNIQ_TRACKER = _DUP_TRACKER.replace("### Batch 3 — Second", "### Batch 4 — Second")


def _parse_with_stderr(module_name: str, func_name: str, doc: str):
    """Import the reader standalone and capture what it says on stderr."""
    import contextlib
    import importlib
    import io

    sys.path.insert(0, str(SCRIPTS))
    try:
        mod = importlib.import_module(module_name)
        fn = getattr(mod, func_name)
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            out = fn(doc)
        return out, err.getvalue()
    finally:
        sys.path.remove(str(SCRIPTS))


def test_next_task_warns_on_a_duplicate_batch_number():
    out, err = _parse_with_stderr("next_task", "parse_review_batches", _DUP_TRACKER)
    assert "declares Batch 3 2 times" in err, err
    assert "--check-duplicates 3" in err, (
        "the warning does not name the authoritative check, which is the only "
        f"claim about the mutators that is true on every tracker shape\n{err}"
    )
    # The first cut asserted an outcome instead, and it was false twice over:
    # batch_work.sh exits 1, close_batch.sh exits 0, and 4 is only the internal
    # helper's code. Pinned so that wording cannot come back.
    assert "exit 4" not in err, (
        f"the warning is asserting an exit code again; no shell returns 4\n{err}"
    )
    assert [b.get("number") for b in out] == [3, 3], (
        "the parse changed — this reader is supposed to keep BOTH batches; only "
        f"the warning was added\n{out}"
    )


def test_next_task_is_silent_when_numbers_are_unique():
    """Non-vacuity control. A warning that always fires is not a detector."""
    out, err = _parse_with_stderr("next_task", "parse_review_batches", _UNIQ_TRACKER)
    assert err.strip() == "", f"warned on a tracker with no duplicates:\n{err}"
    assert [b.get("number") for b in out] == [3, 4], out


def test_sitrep_survey_warns_on_a_duplicate_batch_number(tmp_path):
    """`sitrep_survey`'s reader takes a path, so this one goes through a file."""
    import contextlib
    import importlib
    import io

    (tmp_path / "review_tasks.md").write_text(_DUP_TRACKER)
    sys.path.insert(0, str(SCRIPTS))
    try:
        mod = importlib.import_module("sitrep_survey")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            out = mod._read_review_batches(tmp_path)
    finally:
        sys.path.remove(str(SCRIPTS))

    assert "declares Batch 3 2 times" in err.getvalue(), err.getvalue()
    assert [b.get("number") for b in out] == [3, 3], (
        f"the parse changed; only the warning was meant to\n{out}"
    )


def test_sitrep_survey_is_silent_when_numbers_are_unique(tmp_path):
    """Non-vacuity control for the file-path reader."""
    import contextlib
    import importlib
    import io

    (tmp_path / "review_tasks.md").write_text(_UNIQ_TRACKER)
    sys.path.insert(0, str(SCRIPTS))
    try:
        mod = importlib.import_module("sitrep_survey")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            mod._read_review_batches(tmp_path)
    finally:
        sys.path.remove(str(SCRIPTS))
    assert err.getvalue().strip() == "", err.getvalue()


def test_both_readers_carry_the_warning_and_call_it():
    """A helper nothing calls is the inert-guard shape this repo keeps paying for.

    Asserted structurally as well as behaviourally: the behavioural tests above
    would still pass if one reader's call were deleted and the other's kept,
    because they are separate cases — this one fails if EITHER loses its call.
    """
    for name in ("next_task.py", "sitrep_survey.py"):
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        assert "def _warn_on_duplicate_batch_numbers" in text, f"{name} lost the helper"
        calls = text.count("_warn_on_duplicate_batch_numbers(")
        assert calls >= 2, (
            f"{name} defines the duplicate warning but never calls it "
            f"(found {calls} occurrence(s), need the def plus at least one call)"
        )
