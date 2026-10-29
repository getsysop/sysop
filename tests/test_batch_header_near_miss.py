"""The canonical batch header and the near-miss surfaces (Phase 220).

`Q-017` + `Q-037` + `Q-242` + `Q-274` were four reports of one fact: a
`### Batch <N>` line that misses the canonical shape — em-dash (U+2014) plus a
backticked status as the last token — is not a batch to any strict reader, and
nothing said so. Every reader disagreed about which lines were affected, so the
same tracker produced different answers depending on which tool ran.

**The ratified canon (2026-08-21) is STRICT-with-detection, not tolerance.**
Widening the strict readers to accept an ASCII hyphen was considered and
rejected: it would make every currently-invisible header appear at once across
six surfaces, on consumer trackers nobody can migrate (no shipped tool migrates
header spellings; the three that rewrite `review_tasks.md` only flip a status
token or relocate a round). Making work appear silently is the same defect
as making it disappear silently.

So the strict patterns are unchanged, the permissive twins are unchanged — the
twins MUST stay maximally permissive, which is Phase 191's § High and what
`tools/phase191_mutations.py` exists to prove — and a new predicate sits between
them and reports.

**What these tests must not become.** Every assertion here drives a real parser
or a real script over a real tracker. A test that asserts the presence of a
sentence in a comment would pass against a mechanism that had been deleted and
described, which is the failure mode this suite keeps rediscovering.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
CLOSE_BATCH = SCRIPTS / "close_batch.sh"

sys.path.insert(0, str(SCRIPTS))
import archive_review_tasks as art  # noqa: E402
import review_index as ri  # noqa: E402


ARCHIVE_SEED = (
    "# Review Tasks Archive\n"
    "\n"
    "## Grand Total (Archived)\n"
    "\n"
    "| Round | Total | Done | Deferred | Status |\n"
    "|-------|-------|------|----------|--------|\n"
    "| **Archive Total** | **0** | **0** | **0** | |\n"
)


def _tracker(*headers_and_tasks, round_header=True):
    out = ["# Review Tasks", ""]
    if round_header:
        out += ["## Round 1: Verification (2026-08-21)", ""]
    for header, tasks in headers_and_tasks:
        out += [header, "", "> **Branch:** `review/x`", ""]
        out += tasks
        out += [""]
    out += ["## Statistics", "", "Trailing section.", ""]
    return "\n".join(out)


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root: Path, tasks: str, *, archive: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "review_tasks.md").write_text(tasks)
    (root / "README.md").write_text("# seed\n")
    if archive:
        (root / "review_tasks_archive.md").write_text(ARCHIVE_SEED)
    sd = root / "sysop" / "scripts"
    sd.mkdir(parents=True, exist_ok=True)
    for n in ("review_index.py", "_log.py", "archive_review_tasks.py"):
        s = SCRIPTS / n
        if s.exists():
            shutil.copy(s, sd / n)
    (root / ".gitignore").write_text(".claude/review_index.json\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _index(cwd: Path, *args):
    return subprocess.run(
        [sys.executable, str(cwd / "sysop/scripts/review_index.py"), *args],
        cwd=str(cwd), capture_output=True, text=True)


def _archiver(cwd: Path, *args, answer="y\n"):
    return subprocess.run(
        [sys.executable, str(cwd / "sysop/scripts/archive_review_tasks.py"), *args],
        cwd=str(cwd), capture_output=True, text=True, input=answer)


def _close(cwd: Path, *args):
    return subprocess.run(["bash", str(CLOSE_BATCH), *args],
                          cwd=str(cwd), capture_output=True, text=True)


# ── The predicate itself ───────────────────────────────────────────────
#
# Shapes drawn from the corpus the four entries were measured on, plus the two
# example forms WORKFLOW.md blesses (fenced, two-space-indented), which MUST NOT
# fire — a near-miss reporter that flags documentation is the Phase 208
# false-fire trap re-minted.

CANONICAL = [
    "### Batch 1 — Title `Pending`",
    "### Batch 1 — Title `In Progress`",
    "### Batch 1 — Title `Merged`",
    "### Batch 1 — Title `Complete`",
    "### Batch 1 — Title `Review Ready`",
    "### Batch 1 — Title `Ready for Review`",
    "### Batch 1 — Title with `backticks` inside `Pending`",
    # The three forms the SHIPPED writers actually emit, copied from their
    # templates rather than from a model of them (the author-side pass's
    # "build the fixture's inputs from the source of truth" rule). The third is
    # the Step 3c ingest batch and carries TWO em-dashes — a pattern anchored on
    # a single separator would score the real writer's own output a near miss.
    "### Batch 1 — <Batch Name> `Pending`",                    # codebase-review
    "### Batch 1 — <Threat Category Name> `Pending`",          # security-audit
    "### Batch 1 — Ingested — claude-security `Pending`",      # security-audit 3c
]

NEAR_MISSES = [
    "### Batch 1 - Title `Pending`",          # ASCII hyphen
    "### Batch 1 – Title `Pending`",          # en-dash
    "### Batch 1: Title `Pending`",           # colon, no dash
    "### Batch 1 — Title",                    # no status
    "### Batch 1 — Title `Pending` (draft)",  # status not at EOL
    "###\tBatch 1 — Title `Pending`",         # tab after ###
    "###  Batch 1 — Title `Pending`",         # two spaces after ###
    "### Batch  1 — Title `Pending`",         # two spaces before number
    # `Q-375`: four shapes written AT column 0 that no reader saw and nothing
    # warned about. Each is an author meaning a batch header and losing one —
    # the batch's tasks silently join its predecessor, which is the state
    # `Q-371` was filed about and the state its warning did not reach.
    "#### Batch 1 — Title `Pending`",         # h4, not h3
    "## Batch 1 — Title `Pending`",           # h2, not h3
    "###Batch 1 — Title `Pending`",           # no space: not a heading at all
    "### BATCH 1 — Title `Pending`",          # wrong case
]

NOT_A_BATCH_HEADER_AT_ALL = [
    "### A01: Broken Access Control",
    "### Some other section",
    # **The indent is the contract, not an oversight, and this line is the one
    # thing in this module that must not move.** `WORKFLOW.md` § 4 (line 624)
    # ships it as a rule: "Indent the example by two spaces. `### Batch` is
    # matched at column 0 only, so a two-space-indented example is invisible to
    # every reader" — and it names all six. It is the sanctioned way to write a
    # batch header in a tracker without creating a batch, preferred over a fence
    # because Phase 208 measured fence-based separation false-firing on 98.2% of
    # opener positions.
    #
    # `Q-375` proposed the opposite — it called this "the sharpest of the five"
    # and argued from `_FENCE_OPEN_RE`'s `^ {0,3}` that the parsers should
    # tolerate the indent. Phase 256 built that, then found this rule and
    # reverted it: reporting an indented example is over-reporting, and BOUNDING
    # on one would turn every correctly-written example on every consumer tracker
    # into a live batch. The filing was wrong about its own sharpest case.
    "  ### Batch 1 - indented example `Pending`",   # WORKFLOW.md § 4:624
]


@pytest.mark.parametrize("line", CANONICAL)
def test_canonical_headers_are_never_near_misses(line):
    """Including every declared status. A `Pending` batch is not a near miss —
    it is canonical and simply not archivable yet."""
    text = _tracker((line, ["- [ ] **TASK-1**: a"]))
    assert ri.near_miss_batch_headers(text.splitlines()) == []
    assert art.near_miss_batch_headers(text.splitlines()) == []


@pytest.mark.parametrize("line", NEAR_MISSES)
def test_near_miss_headers_are_reported(line):
    text = _tracker((line, ["- [ ] **TASK-1**: a"]))
    hits = ri.near_miss_batch_headers(text.splitlines())
    assert len(hits) == 1, f"{line!r} should be reported exactly once"
    assert hits[0][2] == line
    assert [h[0] for h in art.near_miss_batch_headers(text.splitlines())] == \
        [hits[0][0]], "the two twins must agree on WHICH line"


@pytest.mark.parametrize("line", NOT_A_BATCH_HEADER_AT_ALL)
def test_non_batch_headings_are_not_reported(line):
    """Over-reporting is how a maintainer learns to ignore the report."""
    text = _tracker(("### Batch 1 — Real `Pending`", ["- [ ] **TASK-1**: a"]))
    text = text.replace("## Statistics", f"{line}\n\n## Statistics")
    assert ri.near_miss_batch_headers(text.splitlines()) == []
    assert art.near_miss_batch_headers(text.splitlines()) == []


def test_a_fenced_near_miss_is_not_reported():
    """The fence mask is the parser's own, so a documentation example is
    excluded by exactly the rule that excludes it from being parsed."""
    text = _tracker(("### Batch 1 — Real `Pending`", ["- [ ] **TASK-1**: a"]))
    text = text.replace(
        "## Statistics",
        "```\n### Batch 9 - fenced example `Pending`\n```\n\n## Statistics")
    assert ri.near_miss_batch_headers(text.splitlines()) == []
    assert art.near_miss_batch_headers(text.splitlines()) == []


def test_the_canonical_pattern_is_identical_in_both_modules():
    """`archive_review_tasks.CANONICAL_BATCH_RE` is duplicated from
    `review_index._BATCH_HEADER_RE` rather than imported — the archiver's only
    use of that module is a lazy import inside a try/except, because the two
    resolve their repo root differently and an import can raise. A gate may not
    rest on an import that is allowed to fail. Pinned here instead.

    Compares BEHAVIOUR over the whole corpus, not the pattern text. The two
    spell the em-dash differently on purpose — `review_index` writes the
    `\\u2014` escape, the archiver writes the character — so a string comparison
    fails while the matchers are identical. Behaviour is also the stronger pin:
    it catches a semantic divergence that a reformat-tolerant text compare
    would, and ignores a respelling that changes nothing."""
    corpus = CANONICAL + NEAR_MISSES + NOT_A_BATCH_HEADER_AT_ALL
    assert corpus, "empty corpus would make this assertion vacuous"
    disagreements = [
        line for line in corpus
        if bool(art.CANONICAL_BATCH_RE.match(line))
        != bool(ri._BATCH_HEADER_RE.match(line))
    ]
    assert not disagreements, (
        "the archiver's canonical pattern has drifted from review_index's:\n"
        + "\n".join(f"  {ln!r}" for ln in disagreements)
    )
    # Non-vacuity: the corpus must actually exercise both verdicts.
    assert any(ri._BATCH_HEADER_RE.match(ln) for ln in corpus)
    assert any(not ri._BATCH_HEADER_RE.match(ln) for ln in corpus)


def test_the_twin_is_strictly_more_permissive_than_the_canonical_pattern():
    """The invariant Phase 191 exists to protect, restated for the new
    predicate: every line the canonical pattern accepts must also match the
    permissive twin. If that ever inverts, `near_miss_batch_headers` starts
    reporting real batches."""
    for line in CANONICAL:
        assert ri._BATCH_HEADER_RE.match(line)
        assert ri._BATCH_HEADER_ANY_RE.match(line), (
            f"{line!r} matches the strict pattern but not the twin — the twin "
            f"is no longer a superset and the near-miss predicate is unsound"
        )


# ── --check-headers ────────────────────────────────────────────────────

def test_check_headers_exits_6_and_names_the_line(tmp_path):
    r = _repo(tmp_path / "r", _tracker(
        ("### Batch 1 — Fine `Pending`", ["- [ ] **TASK-1**: a"]),
        ("### Batch 2 - Hyphen `Pending`", ["- [ ] **TASK-2**: b"])))
    out = _index(r, "--check-headers")
    assert out.returncode == 6
    assert "Batch 2 - Hyphen" in out.stderr
    assert "Batch 1 — Fine" not in out.stderr


def test_check_headers_exits_0_on_a_clean_tracker(tmp_path):
    r = _repo(tmp_path / "r", _tracker(
        ("### Batch 1 — Fine `Pending`", ["- [ ] **TASK-1**: a"])))
    out = _index(r, "--check-headers")
    assert out.returncode == 0
    assert "no near-miss batch headers" in out.stdout


def test_check_headers_uses_an_exit_code_no_other_arm_claims(tmp_path):
    """1 error, 2 argparse, 3 structural fence, 4 duplicate, 5 open fence.
    A collision would make a caller's branch ambiguous."""
    src = (SCRIPTS / "review_index.py").read_text()
    # The near-miss arm is the only `sys.exit(6)` in the module.
    assert src.count("sys.exit(6)") == 1


# ── Q-242: --check-duplicates stops answering "unambiguous" ────────────

def test_check_duplicates_reports_a_near_miss_for_that_number(tmp_path):
    """The defect: `next_task.py`'s duplicate warning names this check as *the
    authority*, and it answered `batch 5 unambiguous` over a line no reader
    parses."""
    r = _repo(tmp_path / "r", _tracker(
        ("### Batch 5 — Em dash `Pending`", ["- [ ] **TASK-1**: a"]),
        ("### Batch 5 - ASCII hyphen `Pending`", ["- [ ] **TASK-2**: b"])))
    out = _index(r, "--check-duplicates", "5")
    assert "unambiguous" not in out.stdout, (
        "answering `unambiguous` here is the whole of Q-242"
    )
    # **STDERR, and the stream is the finding.** The first cut printed the
    # report to stdout — and BOTH automated callers capture stderr while
    # discarding stdout (`2>&1 >/dev/null`), so the fix was visible only on a
    # hand-run: the same "addressed to an empty room" defect this phase fixes in
    # close_batch.sh's other half. Found by the round.
    assert "Batch 5 - ASCII hyphen" in out.stderr
    assert "Batch 5 - ASCII hyphen" not in out.stdout
    # stdout still carries a one-line answer, because require_index_parser's
    # probe fails an EMPTY stdout.
    assert out.stdout.strip()


def test_check_duplicates_keeps_its_exit_contract_over_a_near_miss(tmp_path):
    """**Exit code 0, deliberately, and this is the load-bearing half.**

    `batch_work.sh`'s `require_index_parser` probes this command with
    `--check-duplicates 0` and clears the result on ANY non-zero (`|| probe=""`),
    then refuses to run at all. A new refusal code here would make a near-miss
    header numbered 0 disable every `batch_work.sh` invocation in the repo.
    Refusal belongs to `--check-headers`, which nothing probes.

    Asserts the ARITHMETIC of the contract — rc, and that stdout is non-empty so
    the probe's own positive self-test still passes — not the presence of a
    comment saying so."""
    r = _repo(tmp_path / "r", _tracker(
        ("### Batch 0 - Hyphen numbered zero `Pending`", ["- [ ] **TASK-1**: a"])))
    out = _index(r, "--check-duplicates", "0")
    assert out.returncode == 0, "the probe clears its result on any non-zero"
    assert out.stdout.strip(), "the probe fails an empty answer"


def test_check_duplicates_still_exits_4_on_a_real_duplicate(tmp_path):
    """The near-miss arm must not shadow the duplicate arm."""
    r = _repo(tmp_path / "r", _tracker(
        ("### Batch 7 — First `Merged`", ["- [ ] **TASK-1**: a"]),
        ("### Batch 7 — Second `Pending`", ["- [ ] **TASK-2**: b"])))
    out = _index(r, "--check-duplicates", "7")
    assert out.returncode == 4


def test_a_near_miss_is_not_reported_as_a_duplicate(tmp_path):
    """`duplicate_batch_numbers` must keep using the STRICT pattern. Counting
    near misses as declarations produced a false "would silently pick one and
    discard the other" plus a remedy ("renumber one of them") that did not
    apply — the regression Phase 209's round caught."""
    r = _repo(tmp_path / "r", _tracker(
        ("### Batch 5 — Real `Pending`", ["- [ ] **TASK-1**: a"]),
        ("### Batch 5 - Near miss `Pending`", ["- [ ] **TASK-2**: b"])))
    out = _index(r, "--check-duplicates", "5")
    assert out.returncode == 0
    assert "renumber" not in (out.stdout + out.stderr).lower()


# ── Q-274: the archiver refuses ────────────────────────────────────────

def test_archiver_refuses_and_writes_nothing(tmp_path):
    """The filed entry said `all_merged` goes False and therefore "the round is
    never archived ... nothing is lost". Only the first half reproduced.
    Measured before this fix, on the entry's own stated fixture: the run
    completed, the readable batch relocated into the archive, the Grand Total
    stamped `Round 1 (Batches 1-1) ... Complete`, and the near-miss batch stayed
    live under a second `## Round 1` header.

    So this asserts the WRITES did not happen, not merely that a message was
    printed."""
    r = _repo(tmp_path / "r", _tracker(
        ("### Batch 1 — Em dash `Merged`", ["- [x] **TASK-1**: a"]),
        ("### Batch 2 - ASCII hyphen `Merged`", ["- [x] **TASK-2**: b"])),
        archive=True)
    before_live = (r / "review_tasks.md").read_text()
    before_arch = (r / "review_tasks_archive.md").read_text()

    out = _archiver(r)

    assert out.returncode == 1
    assert "refusing to archive" in out.stderr
    assert "Batch 2 - ASCII hyphen" in out.stderr
    assert (r / "review_tasks.md").read_text() == before_live
    assert (r / "review_tasks_archive.md").read_text() == before_arch


def test_archiver_refuses_before_dry_run_too(tmp_path):
    """Same placement rule as the fence refusal: a preview whose totals silently
    omit a merged batch is exactly the report an operator would act on."""
    r = _repo(tmp_path / "r", _tracker(
        ("### Batch 1 — Em dash `Merged`", ["- [x] **TASK-1**: a"]),
        ("### Batch 2 - ASCII hyphen `Merged`", ["- [x] **TASK-2**: b"])),
        archive=True)
    out = _archiver(r, "--dry-run")
    assert out.returncode == 1
    assert "refusing to archive" in out.stderr
    assert "Total:" not in out.stdout, (
        "a count was printed before the refusal — the Q-240 placement rule"
    )


def test_archiver_still_archives_a_canonical_round(tmp_path):
    """The control. An over-strict gate is how a maintainer learns to bypass
    one, so the clean path must stay clean."""
    r = _repo(tmp_path / "r", _tracker(
        ("### Batch 1 — Em dash `Merged`", ["- [x] **TASK-1**: a"]),
        ("### Batch 2 — Also em dash `Merged`", ["- [x] **TASK-2**: b"])),
        archive=True)
    out = _archiver(r)
    assert out.returncode == 0, (out.stdout + out.stderr)
    arch = (r / "review_tasks_archive.md").read_text()
    assert "TASK-1" in arch and "TASK-2" in arch


def test_archiver_does_not_refuse_over_a_pending_batch(tmp_path):
    """A `Pending` batch matches the canonical pattern and is simply not
    archivable. Refusing over one would block every ordinary tracker."""
    r = _repo(tmp_path / "r", _tracker(
        ("### Batch 1 — Done `Merged`", ["- [x] **TASK-1**: a"]),
        ("### Batch 2 — Waiting `Pending`", ["- [ ] **TASK-2**: b"])),
        archive=True)
    out = _archiver(r)
    assert "refusing to archive" not in out.stderr


# ── Q-017: close_batch.sh says which resolver answered ─────────────────

def _near_miss_tracker(status="Pending"):
    return (
        "# Review Tasks\n"
        "\n"
        f"### Batch 1 - Hyphen not em-dash `{status}`\n"
        "\n"
        "> **Branch:** `feat/one`\n"
        "\n"
        "- [ ] **TASK-1**: first\n"
        "- [ ] **TASK-2**: the batch's last line\n"
        "## Statistics\n"
        "\n"
        "Trailing section.\n"
    )


def test_close_warns_when_the_range_came_from_the_fallback(tmp_path):
    """`Q-017`'s ratified disposition (2026-08-21): keep closing, stop being
    silent. Retiring the fallback is a caller-contract change the entry has
    declined three times — a refusal at that call site is overwritten by a FALSE
    "Not found in review_tasks.md" message.

    Asserts on STDOUT specifically. `close_batch.sh`'s own rule: NEARMISS and
    ORPHAN warnings used to go to stderr while `/review-close` Step 4b tells the
    operator to read stdout, so the loudness was "addressed to an empty room"."""
    r = _repo(tmp_path / "r", _near_miss_tracker())
    out = _close(r, "1")
    assert out.returncode == 0
    assert "GREP FALLBACK" in out.stdout
    assert "--check-headers" in out.stdout
    # **Every line of the warning, not just one.** A per-line assertion is
    # satisfied while a neighbouring line has been redirected to stderr — which
    # is how a single-line `>&2` walked this guard in the phase's own battery.
    # The whole block belongs on stdout: /review-close Step 4b reads stdout, and
    # a warning split across two streams is half-addressed to the empty room.
    # Fragments span the block top-to-bottom so a mid-block `>&2` is caught.
    # `fence-blind` was one of these until Phase 233 made THIS arm fence-aware
    # (Q-017). The claim moved to the no-index arm, where it is still true, and
    # `test_the_fence_blind_claim_is_made_only_on_the_arm_where_it_is_true`
    # asserts it there -- and asserts its ABSENCE here.
    # Every fragment must be UNIQUE to this block. Round finding (MEDIUM, guards
    # lens): `readers disagree` also appears in `review_index.py:812`'s near-miss
    # advisory, which prints on the same run -- so the mid-block fragment resolved
    # OUTSIDE the block, and deleting close_batch.sh's own line left this green.
    # A fragment with two referents cannot span anything. Replaced with
    # `refuses to claim it`, which the sweep below asserts is unique.
    for fragment in ("GREP FALLBACK", "review_index.py ran",
                     "could not match this batch", "boundary search skips fenced",
                     "refuses to claim it", "WILL still be closed", "--check-headers"):
        assert fragment in out.stdout, f"{fragment!r} is not on stdout"
        assert fragment not in out.stderr, f"{fragment!r} leaked to stderr"
    # and it still closed, which is the pinned half
    after = (r / "review_tasks.md").read_text()
    assert "`Merged`" in after
    assert after.count("- [x]") == 2


def test_close_counts_fallback_batches_in_its_summary(tmp_path):
    """Per-batch warnings scroll; a summary count does not. Same argument the
    two counters beside it already make."""
    r = _repo(tmp_path / "r", _near_miss_tracker())
    out = _close(r, "1")
    m = re.search(r"Batches closed via the grep fallback: (\d+)", out.stdout)
    assert m, "no summary line"
    assert m.group(1) == "1"


def test_close_is_silent_on_the_index_path(tmp_path):
    """The false-positive control. A warning that fires on the ordinary path is
    noise, and noise is how the real one gets ignored."""
    r = _repo(tmp_path / "r", _near_miss_tracker().replace(
        "### Batch 1 - Hyphen not em-dash", "### Batch 1 — Canonical"))
    out = _close(r, "1")
    assert out.returncode == 0
    assert "GREP FALLBACK" not in out.stdout
    assert "grep fallback" not in out.stdout
    after = (r / "review_tasks.md").read_text()
    assert "`Merged`" in after


def test_close_does_not_change_its_exit_code_for_a_fallback_range(tmp_path):
    """`close_batch.sh`'s stated contract: annotation warnings are "deliberately
    NOT an exit-code change" because `/review-close` Step 4b diagnoses by commit
    presence. A new non-zero here would abort a multi-batch close."""
    r = _repo(tmp_path / "r", _near_miss_tracker())
    out = _close(r, "1")
    assert out.returncode == 0


def test_check_duplicates_only_reports_near_misses_for_ITS_number(tmp_path):
    """The scoping. `--check-duplicates <N>` answers about N; reporting every
    near miss in the file would make the answer to "is batch 5 ambiguous?"
    depend on an unrelated typo under batch 9.

    Guard gap found by this phase's own battery (D12): dropping the `nm[1] == n`
    filter left every assertion above green, because they all happened to ask
    about the number that WAS near-missed."""
    r = _repo(tmp_path / "r", _tracker(
        ("### Batch 5 — Fine `Pending`", ["- [ ] **TASK-1**: a"]),
        ("### Batch 9 - Hyphen elsewhere `Pending`", ["- [ ] **TASK-2**: b"])))
    out = _index(r, "--check-duplicates", "5")
    assert out.returncode == 0
    both5 = out.stdout + out.stderr
    assert "Batch 9 - Hyphen elsewhere" not in both5, (
        "batch 5's answer named batch 9's near miss"
    )
    assert "unambiguous" in out.stdout
    # ...and the same command asked about 9 DOES report it (non-vacuity).
    out9 = _index(r, "--check-duplicates", "9")
    assert "Batch 9 - Hyphen elsewhere" in out9.stderr


# ── Findings from this phase's own review round ────────────────────────

TRAILING_WHITESPACE_SHAPES = [
    "### Batch 1 — Alpha `Merged` ",      # one trailing space
    "### Batch 1 — Alpha `Merged`  ",     # markdown hard-break idiom
    "### Batch 1 — Alpha `Merged`\t",     # trailing tab
]


@pytest.mark.parametrize("line", TRAILING_WHITESPACE_SHAPES)
def test_trailing_whitespace_is_not_a_near_miss(line):
    """**Round finding (HIGH): this was a false fire AND a regression.**

    The strict pattern is `$`-anchored so these fail it — but the archiver's own
    `BATCH_HEADER_RE` is NOT end-anchored and has always archived them. The first
    cut therefore refused whole-run on a tracker that archived cleanly before
    this phase, and showed the operator an `rstrip`ped line that looked perfectly
    canonical beside a diagnosis about a missing em-dash they were staring at.
    Trailing whitespace is invisible in rendered markdown and is not what the
    canon is about."""
    text = _tracker((line, ["- [x] **TASK-1**: a"]))
    assert ri.near_miss_batch_headers(text.splitlines()) == []
    assert art.near_miss_batch_headers(text.splitlines()) == []


@pytest.mark.parametrize("idx,line", list(enumerate(TRAILING_WHITESPACE_SHAPES)))
def test_the_archiver_still_archives_a_trailing_whitespace_header(tmp_path, idx, line):
    """The regression half, asserted end to end rather than at the predicate.

    Before the round's fix this exited 1 with "refusing to archive" on a tracker
    that archives cleanly at `f61498f`."""
    r = _repo(tmp_path / f"r{idx}", _tracker(
        (line, ["- [x] **TASK-1**: a"])), archive=True)
    out = _archiver(r)
    assert out.returncode == 0, (out.stdout + out.stderr)
    assert "TASK-1" in (r / "review_tasks_archive.md").read_text()


def test_check_duplicates_keeps_stdout_nonempty_for_the_probe(tmp_path):
    """`require_index_parser` fails an EMPTY stdout, so moving the near-miss
    report to stderr must not empty the stdout answer."""
    r = _repo(tmp_path / "r", _tracker(
        ("### Batch 0 - Hyphen numbered zero `Pending`", ["- [ ] **TASK-1**: a"])))
    out = _index(r, "--check-duplicates", "0")
    assert out.returncode == 0
    assert out.stdout.strip()


def test_close_does_not_blame_the_header_when_the_index_never_ran(tmp_path):
    """**Round finding (HIGH): the warning asserted a cause it had not checked.**

    `find_batch_range` took the fallback for four different reasons — a
    non-canonical header, an absent `python3`, an absent or partial
    `$INDEX_SCRIPT`, a parser crash — and the first cut asserted the first cause
    unconditionally. Reproduced on a byte-perfect CANONICAL tracker with the
    index script removed: the operator was told their header was malformed and
    pointed at a `python3` remedy that could not run.

    Drives the real script with `review_index.py` deleted, which is a partial or
    stale install — not a hypothetical."""
    r = _repo(tmp_path / "r", _near_miss_tracker().replace(
        "### Batch 1 - Hyphen not em-dash", "### Batch 1 — Canonical"))
    (r / "sysop/scripts/review_index.py").unlink()

    out = _close(r, "1")
    assert out.returncode == 0
    assert "did NOT run" in out.stdout, (
        "the warning did not distinguish 'index absent' from 'header bad'"
    )
    assert "self_check.sh" in out.stdout, "no actionable remedy for a broken install"
    assert "canonical shape" not in out.stdout, (
        "blamed the header on a run where the index was never consulted"
    )
    assert "`Merged`" in (r / "review_tasks.md").read_text()


def test_close_does_blame_the_header_when_the_index_ran_and_missed(tmp_path):
    """The non-vacuity twin: with the index present, the header IS the cause and
    the warning must still say so. Without this, the test above would pass
    against a script that never blames a header at all."""
    r = _repo(tmp_path / "r", _near_miss_tracker())
    out = _close(r, "1")
    assert out.returncode == 0
    # Assert WHICH ARM fired, by the content only that arm carries — not by a
    # sentence. Pinning the prose made a legal reword ("could not match" → "did
    # not match") a false alarm in this phase's own battery, and an over-strict
    # guard is how a maintainer learns to weaken one.
    assert "canonical shape" in out.stdout, "the header-blame arm did not fire"
    assert "did NOT run" not in out.stdout
    assert "self_check.sh" not in out.stdout


def test_close_batch_surfaces_the_near_miss_advisory(tmp_path):
    """**The half of `Q-242`'s fix that reached nobody until the round.**

    `--check-duplicates` was printing its near-miss report to stdout while both
    automated callers capture stderr and DISCARD stdout (`2>&1 >/dev/null`), so
    the fix for "the check lies about its own subject" was visible only on a
    hand-run — the same "addressed to an empty room" defect this phase fixes in
    `close_batch.sh`'s other half, in the same commit.

    Drives the real script, and asserts the operator SEES it. A near-miss header
    for a number that also has a real batch is the shape that reaches this
    branch: the real batch is what `close_batch.sh` acts on, so it does not
    refuse, and the advisory is the only signal that anything is wrong."""
    tracker = _tracker(
        ("### Batch 1 — Real `Pending`", ["- [ ] **TASK-1**: a"]),
        ("### Batch 1 - Near miss same number `Pending`", ["- [ ] **TASK-2**: b"]),
    )
    r = _repo(tmp_path / "r", tracker)
    out = _close(r, "1")
    assert "Batch 1 - Near miss same number" in out.stdout, (
        "the near-miss advisory was swallowed by the caller's stdout discard"
    )


def test_batch_work_surfaces_the_near_miss_advisory(tmp_path):
    """The other caller. `refuse_on_duplicate_number` captures stderr and
    branches on rc 4 alone; on rc 0 it discarded whatever it had captured."""
    tracker = _tracker(
        ("### Batch 1 — Real `Pending`", ["- [ ] **TASK-1**: a"]),
        ("### Batch 1 - Near miss same number `Pending`", ["- [ ] **TASK-2**: b"]),
    )
    r = _repo(tmp_path / "r", tracker)
    subprocess.run(["git", "init", "--bare", "-q", str(tmp_path / "origin.git")],
                   check=True, capture_output=True)
    _git(r, "remote", "add", "origin", str(tmp_path / "origin.git"))
    _git(r, "push", "-q", "origin", "main")

    out = subprocess.run(["bash", str(SCRIPTS / "batch_work.sh"), "1"],
                         cwd=str(r), capture_output=True, text=True)
    both = out.stdout + out.stderr
    assert "Batch 1 - Near miss same number" in both, (
        "the near-miss advisory was swallowed on the claim path"
    )


def test_the_advisory_is_silent_on_a_clean_tracker(tmp_path):
    """False-positive control for both tests above."""
    r = _repo(tmp_path / "r", _tracker(
        ("### Batch 1 — Real `Pending`", ["- [ ] **TASK-1**: a"])))
    out = _close(r, "1")
    assert "no reader can act on" not in out.stdout


def test_the_fallback_counter_is_per_batch_on_a_multi_batch_close(tmp_path):
    """**Round finding (HIGH): every fixture closed exactly ONE batch**, so both
    the per-batch warning and the summary counter were satisfied by a constant.

    Reproduced by the round: deleting `RANGE_SOURCE="index"` from the top of
    `find_batch_range` makes the variable STICK across loop iterations, so batch
    2 inherits batch 1's verdict — a false `GREP FALLBACK` warning for a
    perfectly canonical header, and `Batches closed via the grep fallback: 2`.
    Setting the counter to a literal `1` is invisible for the same reason.

    Two batches, one near-miss and one canonical, is the smallest fixture that
    can tell those apart."""
    tracker = _tracker(
        ("### Batch 1 - Hyphen `Pending`", ["- [ ] **TASK-1**: a"]),
        ("### Batch 2 — Canonical `Pending`", ["- [ ] **TASK-2**: b"]),
        ("### Batch 3 - Hyphen too `Pending`", ["- [ ] **TASK-3**: c"]),
    )
    r = _repo(tmp_path / "r", tracker)
    out = _close(r, "1", "2", "3")

    assert out.returncode == 0, (out.stdout + out.stderr)
    m = re.search(r"Batches closed via the grep fallback: (\d+)", out.stdout)
    assert m, f"no summary line:\n{out.stdout}"
    # **TWO near-misses, deliberately.** With one, a hard-coded `1` is
    # indistinguishable from a working increment — which is how a literal
    # survived this phase's battery.
    assert m.group(1) == "2", (
        f"counted {m.group(1)} fallback batches; batches 1 and 3 are near misses"
    )
    # ...and the canonical batch must not carry the warning. Scope to batch 2's
    # OWN block — slicing to end-of-output would catch batch 3's warning and
    # this assertion would fail for the wrong reason.
    b2 = out.stdout.split("── Batch 2 ──", 1)[-1].split("── Batch 3 ──", 1)[0]
    assert "GREP FALLBACK" not in b2, (
        "batch 2 inherited batch 1's verdict — RANGE_SOURCE is not reset per batch"
    )
    # Non-vacuity: the slice must actually contain batch 2's output.
    assert "Marked as Merged" in b2 or "already deleted" in b2, b2


WHITESPACE_NEAR_MISSES = [
    ("###\tBatch 7 — Tabbed `Pending`", "7"),
    ("###  Batch 7 — Two spaces after hashes `Pending`", "7"),
    ("### Batch  7 — Two spaces before number `Pending`", "7"),
    ("### Batch 07 - Zero padded `Pending`", "7"),
]


@pytest.mark.parametrize("line,number", WHITESPACE_NEAR_MISSES)
def test_the_near_miss_number_survives_odd_whitespace_and_padding(line, number):
    """**Round finding: `_NEAR_MISS_NUMBER_RE` was untested for the shapes the
    predicate itself documents.** Tightening it to literal single spaces let
    three of the eight declared near-miss shapes lose their number — which sends
    them to `nm[1] is None`, so `--check-duplicates` answers `unambiguous` over
    them again and `Q-242` partially re-opens. Every fixture used single spaces.

    The zero-padded case is the same class one layer down: dropping the
    `str(int(...))` normalisation makes `### Batch 07` invisible to
    `--check-duplicates 7`, which is how `duplicate_batch_numbers` keys."""
    hits = ri.near_miss_batch_headers([line])
    assert len(hits) == 1, f"{line!r} is not reported as a near miss at all"
    assert hits[0][1] == number, (
        f"{line!r} reported number {hits[0][1]!r}, expected {number!r} — "
        f"--check-duplicates {number} will not see it"
    )


def test_near_miss_line_numbers_are_one_based(tmp_path):
    """**Round finding: a consistent off-by-one was invisible** because the only
    cross-check compared the two twins to each other, never to an absolute line.
    An operator following `:N` needs N to be the line their editor shows."""
    text = _tracker(("### Batch 1 - Hyphen `Pending`", ["- [ ] **TASK-1**: a"]))
    lines = text.splitlines()
    hits = ri.near_miss_batch_headers(lines)
    assert len(hits) == 1
    lineno = hits[0][0]
    assert lines[lineno - 1] == "### Batch 1 - Hyphen `Pending`", (
        f"reported :{lineno}, but that 1-based line is {lines[lineno - 1]!r}"
    )
    assert [h[0] for h in art.near_miss_batch_headers(lines)] == [lineno]


def test_the_archiver_refusal_runs_before_the_no_rounds_early_exit(tmp_path):
    """**Round finding (MED): the refusal's position was pinned only relative to
    `--dry-run`.** Moved below `parse_archivable_batches`, a tracker whose ONLY
    `Merged` batch is a near miss hits the `if not rounds: sys.exit(0)` early
    exit first and the archiver prints "No merged/complete batches to archive."
    — a clean all-clear over the exact condition the refusal exists for."""
    r = _repo(tmp_path / "r", _tracker(
        ("### Batch 1 - Hyphen `Merged`", ["- [x] **TASK-1**: a"])), archive=True)
    out = _archiver(r)
    assert out.returncode == 1, (out.stdout + out.stderr)
    assert "refusing to archive" in out.stderr
    assert "No merged/complete batches" not in out.stdout, (
        "the early exit answered before the refusal could"
    )


def test_the_report_does_not_claim_a_reader_is_blind_that_demonstrably_is_not():
    """**The one guard that could have caught the falsehood this phase shipped.**

    The round's sharpest structural point: the message text is entirely unpinned
    — its own twelve legal-edit controls stayed green precisely because a legal
    reword and a defective one are indistinguishable to the suite. That is the
    correct trade for prose, and it is why the shipped claim that near-miss
    headers are *"invisible to /sitrep, /next-task, /roadmap and the archiver"*
    could never have been caught: `/next-task` deliberately keeps an ASCII-hyphen
    tolerance (Wade's call), so it parses one into a full batch and offers it as
    claimable, which `batch_work.sh` then refuses.

    A presence-assert on wording would be over-strict and would rot. This asserts
    the CONTRADICTION instead: for each reader the message names as blind, drive
    that reader over a near-miss tracker and require it to actually be blind.
    Rewording is free; claiming a blindness that does not hold is not.

    The blocklist cannot be exhaustive — it covers the readers a message is
    likely to name, and says so."""
    text = "\n".join(ri.describe_near_misses(
        [(5, "2", "### Batch 2 - ASCII hyphen `Pending`")], "review_tasks.md"))

    tracker = _tracker(("### Batch 2 - ASCII hyphen `Pending`",
                        ["- [ ] **TASK-1**: a"]))
    lines = tracker.splitlines()

    sys.path.insert(0, str(SCRIPTS))
    import next_task

    # (reader name as it may appear in the message, does it actually parse one?)
    sighted = {
        "/next-task": bool(next_task.parse_review_batches(tracker)),
    }
    for name, actually_sees in sighted.items():
        if not actually_sees:
            continue
        claim = f"invisible to" in text and name in text
        assert not claim, (
            f"the report calls {name} blind to near-miss headers, but it parses "
            f"one into a full batch. This phase deliberately KEPT that tolerance; "
            f"the message must not contradict the decision it ships with."
        )

    # Non-vacuity: the reader this guards is genuinely sighted, or the loop above
    # never runs and the test proves nothing.
    assert sighted["/next-task"], (
        "next_task.py no longer parses a hyphen header — if that tolerance was "
        "removed on purpose, this guard and the message both need revisiting"
    )
    # ...and the archiver genuinely is blind, which the message may say.
    assert not art.BATCH_HEADER_RE.match(lines[4] if len(lines) > 4 else "")


# === Q-017: the fallback range stops being fence-blind (Phase 233) ==========
#
# The headline defect, filed 2026-08-03 and refused three times. All three
# refusals aimed at the same thing: whether a non-canonical header should be
# CLOSED or REFUSED, which cannot be changed at `if ! find_batch_range` because
# a refusal there is overwritten by a FALSE "Not found in review_tasks.md".
#
# That verdict is untouched here, and stays as ratified (keep closing, stop
# being silent). What is fixed is the RANGE: the boundary search now skips
# fenced `## ` lines, using the same `$FENCED_LINES` mask `CLOSE_AWK` already
# rewrites around. The mask is populated under `python3 && -f $INDEX_SCRIPT`,
# which is exactly the `fallback` arm's own precondition -- so the arm where the
# defect was measured always has it, and no caller contract changes.


def _fenced_near_miss_tracker(status="Pending"):
    """A near-miss header whose batch body QUOTES a `## ` heading.

    Both halves are load-bearing: the ASCII hyphen sends the range to the grep
    fallback (the index cannot match the header), and the fenced `## Deferred`
    is what that fallback used to bound on.
    """
    return (
        "# Review Tasks\n"
        "\n"
        f"### Batch 1 - Hyphen not em-dash `{status}`\n"
        "\n"
        "> **Branch:** `feat/one`\n"
        "\n"
        "- [ ] **TASK-1**: first, above the fence\n"
        "\n"
        "```markdown\n"
        "## Deferred\n"
        "an example heading quoted inside the batch body\n"
        "```\n"
        "\n"
        "- [ ] **TASK-2**: below the fence\n"
        "- [ ] **TASK-3**: also below the fence\n"
        "\n"
        "## Statistics\n"
        "\n"
        "Trailing section.\n"
    )


def _assert_the_fixture_can_see_the_defect(tracker: str):
    """The precondition, asserted rather than assumed. Phase 232 wrote three
    fixtures that could not reach the defect they were written for; one of them
    would have passed against the unfixed script and measured nothing.

    Recomputes the OLD fence-blind range with the same shell the script used to
    run, and requires it to under-reach -- i.e. to stop at the fenced `##` and
    leave real tasks outside the batch.
    """
    lines = tracker.splitlines()
    start = next(i for i, l in enumerate(lines, 1) if l.startswith("### Batch 1 "))
    blind_off = next(i for i, l in enumerate(lines[start:], 1) if l.startswith("##"))
    blind_end = start + blind_off - 1
    assert lines[blind_end - 1 + 1].strip() == "## Deferred" or \
        lines[blind_end].strip() == "## Deferred", \
        "the fence-blind boundary is not the fenced heading -- fixture is wrong"
    t2 = next(i for i, l in enumerate(lines, 1) if "**TASK-2**" in l)
    t3 = next(i for i, l in enumerate(lines, 1) if "**TASK-3**" in l)
    assert t2 > blind_end and t3 > blind_end, (
        "TASK-2/TASK-3 are inside the fence-blind range, so this fixture cannot "
        "distinguish a fixed script from a broken one"
    )


def test_the_fallback_range_skips_a_fenced_boundary(tmp_path):
    """**The headline defect, and it must close every real task.**

    Reproduced at Phase 233's open on the unfixed script: 1 of 3 closed, header
    flipped to `Merged`, TASK-2 and TASK-3 left `[ ]` underneath it, exit 0, run
    committed. That is the state `Q-017` was filed for on 2026-08-03.
    """
    tracker = _fenced_near_miss_tracker()
    _assert_the_fixture_can_see_the_defect(tracker)
    r = _repo(tmp_path / "r", tracker)

    out = _close(r, "1")
    assert out.returncode == 0, out.stderr
    after = (r / "review_tasks.md").read_text()

    assert "- [x] **TASK-1**" in after, after
    assert "- [x] **TASK-2**" in after, (
        "TASK-2 is still open under a closed header -- the fenced `## Deferred` "
        f"is still bounding the batch early.\n{after}"
    )
    assert "- [x] **TASK-3**" in after, after
    assert "`Merged`" in after
    assert "3 tasks closed" in out.stdout, out.stdout
    # The fenced example is content and must never be rewritten.
    assert "## Deferred\nan example heading quoted inside the batch body" in after


def test_a_real_unfenced_boundary_still_bounds_the_batch(tmp_path):
    """**The over-strictness control -- the narrow end of the predicate.**

    A filter that skipped `##` lines too eagerly would run batch 1's range on
    into batch 2 and close its tasks. Phase 232's lesson: the self-serving
    widening protects the target and breaks the neighbour, so the narrow end is
    a first-class test, not a footnote.
    """
    tracker = (
        "# Review Tasks\n"
        "\n"
        "### Batch 1 - Hyphen not em-dash `Pending`\n"
        "\n"
        "> **Branch:** `feat/one`\n"
        "\n"
        "- [ ] **TASK-1**: batch one\n"
        "\n"
        "```markdown\n"
        "## Deferred\n"
        "```\n"
        "\n"
        "- [ ] **TASK-2**: still batch one\n"
        "\n"
        "### Batch 2 - Also hyphenated `Pending`\n"
        "\n"
        "> **Branch:** `feat/two`\n"
        "\n"
        "- [ ] **TASK-9**: belongs to batch TWO and must not close\n"
        "\n"
        "## Statistics\n"
    )
    r = _repo(tmp_path / "r", tracker)

    out = _close(r, "1")
    assert out.returncode == 0, out.stderr
    after = (r / "review_tasks.md").read_text()

    assert "- [x] **TASK-1**" in after and "- [x] **TASK-2**" in after, after
    assert "- [ ] **TASK-9**" in after, (
        "closing batch 1 closed a task in batch 2 -- the fenced-line filter "
        f"skipped a REAL `### Batch 2` boundary.\n{after}"
    )
    assert "### Batch 2 - Also hyphenated `Pending`" in after, (
        "batch 2's header was rewritten by batch 1's close"
    )
    assert "2 tasks closed" in out.stdout, out.stdout


def test_the_fence_blind_claim_is_made_only_on_the_arm_where_it_is_true(tmp_path):
    """**The direction guard.** Phase 220's round caught this warning asserting
    the wrong DIRECTION (it said the range could over-reach; the mechanism can
    only bound EARLY). The claim is now arm-specific and can go stale the same
    way: `fallback` has the mask and is fence-aware, `fallback-no-index` has no
    python3 to build one and is still blind. A message that states the wrong
    arm's behaviour is the same defect wearing the other hat.
    """
    # Arm 1: index present, header non-canonical -> fence-AWARE.
    r1 = _repo(tmp_path / "aware", _fenced_near_miss_tracker())
    o1 = _close(r1, "1")
    assert "canonical shape" in o1.stdout, "wrong arm fired"
    assert "fence-blind" not in o1.stdout, (
        "this arm consults $FENCED_LINES and is NOT fence-blind; the warning "
        f"claims otherwise.\n{o1.stdout}"
    )

    # Arm 2: index absent -> no mask, genuinely still blind, and it must say so.
    r2 = _repo(tmp_path / "blind", _fenced_near_miss_tracker())
    (r2 / "sysop/scripts/review_index.py").unlink()
    o2 = _close(r2, "1")
    assert "did NOT run" in o2.stdout, "wrong arm fired"
    assert "fence-blind" in o2.stdout, (
        "the no-index arm IS still fence-blind and stopped saying so -- an "
        f"operator on a python3-less host is now told nothing.\n{o2.stdout}"
    )
    # ...and the behaviour that claim describes is real, not just described.
    after2 = (r2 / "review_tasks.md").read_text()
    assert "- [ ] **TASK-2**" in after2 and "- [ ] **TASK-3**" in after2, (
        "the no-index arm closed the whole batch, so its fence-blind warning is "
        f"now the false one.\n{after2}"
    )


def test_the_fallback_summary_does_not_assert_a_cause_it_did_not_check(tmp_path):
    """One counter, two causes. `TOTAL_FALLBACK_RANGES` is incremented by BOTH
    arms, and the summary line asserted "their headers are not canonical" for
    all of them -- telling an operator with a byte-perfect tracker and no
    python3 that their header was malformed.

    This is the same wrong-cause conflation Phase 220's round fixed in the
    per-batch message and left standing in the summary 400 lines below: the
    class recurs at call-site granularity, not file granularity.
    """
    r = _repo(tmp_path / "r", _near_miss_tracker().replace(
        "### Batch 1 - Hyphen not em-dash", "### Batch 1 — Canonical"))
    (r / "sysop/scripts/review_index.py").unlink()

    out = _close(r, "1")
    assert out.returncode == 0
    m = re.search(r"Batches closed via the grep fallback: (\d+)", out.stdout)
    assert m and m.group(1) == "1", out.stdout
    assert "headers are not canonical" not in out.stdout, (
        "the summary blamed the header on a run where the index never ran.\n"
        f"{out.stdout}"
    )


def test_a_real_boundary_immediately_after_a_fence_close_is_not_skipped(tmp_path):
    """**Battery survivor `A3-offset-frame-shifted`, closed.**

    The filter converts a grep hit's stream offset to an absolute line as
    `start + $1`. Shifting that to `start + $1 - 1` changed real behaviour and
    every guard stayed green -- because `_fenced_mask` masks the fence
    DELIMITERS as well as their content, so in the ordinary fixture the fenced
    `## Deferred` (line N) and the ```` ``` ```` opener above it (N-1) are both
    masked. Consulting the wrong one of two masked lines is invisible.

    This fixture makes the two answers differ: a REAL `### Batch 2` boundary sits
    immediately after a fence CLOSE. The correct frame asks about the boundary
    itself (unmasked, so it bounds); the shifted frame asks about the ```` ``` ````
    above it (masked, so it is skipped) and batch 1's range runs on into batch 2.
    """
    tracker = (
        "# Review Tasks\n"
        "\n"
        "### Batch 1 - Hyphen not em-dash `Pending`\n"
        "\n"
        "> **Branch:** `feat/one`\n"
        "\n"
        "- [ ] **TASK-1**: batch one\n"
        "\n"
        "```markdown\n"
        "## Deferred\n"
        "```\n"
        "### Batch 2 - Also hyphenated `Pending`\n"
        "\n"
        "> **Branch:** `feat/two`\n"
        "\n"
        "- [ ] **TASK-9**: belongs to batch TWO and must not close\n"
        "\n"
        "## Statistics\n"
    )
    # The precondition that makes this fixture able to see the defect: the real
    # boundary's PREDECESSOR must be masked, or the two frames agree.
    import sys as _sys
    _sys.path.insert(0, str(SCRIPTS))
    import review_index as _ri
    lines = tracker.splitlines()
    mask = _ri._fenced_mask(lines)
    b2 = next(i for i, l in enumerate(lines, 1) if l.startswith("### Batch 2"))
    assert not mask[b2 - 1], "the real boundary is itself masked — fixture is wrong"
    assert mask[b2 - 2], (
        "the line above the real boundary is NOT masked, so a one-off frame would "
        "give the same answer and this fixture measures nothing"
    )

    r = _repo(tmp_path / "r", tracker)
    out = _close(r, "1")

    assert out.returncode == 0, out.stderr
    after = (r / "review_tasks.md").read_text()
    assert "- [x] **TASK-1**" in after, after
    assert "- [ ] **TASK-9**" in after, (
        "batch 1's close reached into batch 2 — the fenced-line frame is off by "
        f"one, so a real boundary read as fenced.\n{after}"
    )
    assert "### Batch 2 - Also hyphenated `Pending`" in after, after
    assert "1 tasks closed" in out.stdout, out.stdout


def test_the_fence_aware_claim_is_not_made_when_the_probe_failed(tmp_path):
    """**Round finding (HIGH, claims lens): a conditional stated as unconditional.**

    The `fallback` arm's warning said *"The range itself is sound: this arm has
    review_index.py"* -- but `FENCED_LINES` is `$(... --fenced-lines 2>/dev/null)
    || FENCED_LINES=""`, so a parser crash, a damaged tracker, or an older
    installed `review_index.py` yields an EMPTY mask while `RANGE_SOURCE` is still
    `fallback`. The range is then fence-blind and the operator was told it was
    sound.

    That is the same wrong-cause conflation this phase indicts in the summary
    line -- reintroduced by the fix for it. `FENCED_OK` now separates "no fences
    in this tracker" from "the probe failed", and this asserts the warning tracks
    it in both directions.
    """
    tracker = _fenced_near_miss_tracker()

    # Arm A: the probe WORKS -> the fence-aware claim is made, and is true.
    ok = _repo(tmp_path / "ok", tracker)
    out_ok = _close(ok, "1")
    assert "--fenced-lines answered" in out_ok.stdout, out_ok.stdout
    assert "probe FAILED" not in out_ok.stdout, out_ok.stdout
    assert "- [x] **TASK-3**" in (ok / "review_tasks.md").read_text()

    # Arm B: the index script is PRESENT but its --fenced-lines exits non-zero.
    # A stub, because the real failure modes (parser crash, older script without
    # the flag) are exactly this from the shell's point of view.
    bad = _repo(tmp_path / "bad", tracker)
    idx = bad / "sysop" / "scripts" / "review_index.py"
    idx.write_text(
        "import sys\n"
        "if '--fenced-lines' in sys.argv:\n"
        "    sys.stderr.write('boom\\n'); sys.exit(1)\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    out_bad = _close(bad, "1")

    assert out_bad.returncode == 0, out_bad.stderr
    assert "probe FAILED" in out_bad.stdout, (
        "the fenced-line probe failed and the warning did not say so.\n"
        f"{out_bad.stdout}"
    )
    assert "--fenced-lines answered" not in out_bad.stdout, (
        "the range was claimed fence-aware on a run that built no mask.\n"
        f"{out_bad.stdout}"
    )
    # ...and the claim it now makes is the true one: without a mask it IS blind.
    after_bad = (bad / "review_tasks.md").read_text()
    assert "- [ ] **TASK-2**" in after_bad and "- [ ] **TASK-3**" in after_bad, (
        "no mask was built yet the range was fence-aware — then the warning "
        f"above is the false one.\n{after_bad}"
    )


def test_the_stdout_fragments_are_unique_to_close_batchs_own_message(tmp_path):
    """**Round finding (MEDIUM, guards lens), generalized.**

    `test_close_warns_when_the_range_came_from_the_fallback` asserts a list of
    fragments "spanning the block top-to-bottom so a mid-block `>&2` is caught".
    That only works if each fragment has ONE referent. `readers disagree` had two
    -- `review_index.py:812`'s near-miss advisory prints it on the same run -- so
    deleting `close_batch.sh`'s own line left the guard green.

    This asserts the property directly against the shipped scripts, so the next
    fragment borrowed from a sibling reader is caught when it is added, not when
    something silently stops being tested.
    """
    others = [SCRIPTS / n for n in ("review_index.py", "next_task.py", "sitrep_survey.py",
                                    "archive_review_tasks.py", "batch_work.sh")]
    corpus = "\n".join(p.read_text(encoding="utf-8") for p in others if p.is_file())

    # `--check-headers` is exempt and the exemption is the interesting part: it is a
    # FLAG NAME, so it necessarily appears in the module that defines it. A whole-file
    # corpus check cannot tell a flag definition from printed output, and excluding the
    # fragment would lose the one that pins the block's last line. It stays in the list
    # above; what it cannot do alone is prove close_batch printed it, which is why the
    # six fragments around it must each have exactly one referent.
    EXEMPT = {"--check-headers"}
    for fragment in ("GREP FALLBACK", "review_index.py ran",
                     "could not match this batch", "boundary search skips fenced",
                     "refuses to claim it", "WILL still be closed", "--check-headers"):
        if fragment in EXEMPT:
            continue
        assert fragment not in corpus, (
            f"{fragment!r} is emitted by a sibling reader too, so asserting it "
            "does not establish that close_batch.sh printed its own line"
        )

    # ...and the direct property, which needs no uniqueness at all: deleting
    # close_batch.sh's own block must take these fragments off stdout. Run against a
    # COPY, never the shipped script.
    import shutil, subprocess as sp
    src = (SCRIPTS / "close_batch.sh").read_text(encoding="utf-8")
    start = src.index('      echo "   ⚠️  Batch ${BATCH_NUM}\'s range came from the GREP FALLBACK')
    end = src.index('      ;;\n    fallback-no-index)', start)
    stripped = src[:start] + '      :\n' + src[end:]
    assert stripped != src, "the block anchor moved; re-point, do not weaken"
    copy = tmp_path / "close_batch_stripped.sh"
    copy.write_text(stripped, encoding="utf-8")

    r = _repo(tmp_path / "r", _near_miss_tracker())
    out = sp.run(["bash", str(copy), "1"], cwd=str(r), capture_output=True, text=True)
    assert "refuses to claim it" not in out.stdout, (
        "the fragment survived deleting the block that emits it — it has another "
        f"referent and the span assertion is measuring that one.\n{out.stdout}"
    )


def test_the_fenced_line_frame_is_exact_in_both_directions(tmp_path):
    """**Round finding (guards lens, survivor A04): the `+1` twin of `A3`.**

    The phase closed the `start + $1 - 1` shift and left `start + $1 + 1`
    unguarded. This fixture kills both: a real `### Batch 2` boundary whose
    PREDECESSOR is a fence close and whose SUCCESSOR is a fence opener. Both
    neighbours are masked, so any off-by-one in either direction reads the real
    boundary as fenced, skips it, and lets batch 1 run on into batch 2.
    """
    tracker = (
        "# Review Tasks\n"
        "\n"
        "### Batch 1 - Hyphen not em-dash `Pending`\n"
        "\n"
        "> **Branch:** `feat/one`\n"
        "\n"
        "- [ ] **TASK-1**: batch one\n"
        "\n"
        "```markdown\n"
        "## Deferred\n"
        "```\n"
        "### Batch 2 - Also hyphenated `Pending`\n"
        "```markdown\n"
        "## Another quoted heading\n"
        "```\n"
        "\n"
        "> **Branch:** `feat/two`\n"
        "\n"
        "- [ ] **TASK-9**: belongs to batch TWO and must not close\n"
        "\n"
        "## Statistics\n"
    )
    import sys as _sys
    _sys.path.insert(0, str(SCRIPTS))
    import review_index as _ri
    lines = tracker.splitlines()
    mask = _ri._fenced_mask(lines)
    b2 = next(i for i, l in enumerate(lines, 1) if l.startswith("### Batch 2"))
    assert not mask[b2 - 1], "the real boundary is masked — fixture is wrong"
    assert mask[b2 - 2], "predecessor not masked — the -1 shift would agree"
    assert mask[b2], "successor not masked — the +1 shift would agree"

    r = _repo(tmp_path / "r", tracker)
    out = _close(r, "1")

    assert out.returncode == 0, out.stderr
    after = (r / "review_tasks.md").read_text()
    assert "- [x] **TASK-1**" in after, after
    assert "- [ ] **TASK-9**" in after, (
        "batch 1's close reached into batch 2 — the fenced-line frame is off by "
        f"one in some direction.\n{after}"
    )
    assert "1 tasks closed" in out.stdout, out.stdout


def test_the_fence_blind_recompute_actually_recomputes(tmp_path):
    """**Round findings (guards lens, survivors B06/B07/B08): the degradation
    floor was asserted, never exercised.**

    When the awk filter cannot run, the guard falls back to the pre-existing
    `grep -n '^##' | head -1 | cut -d: -f1`. Nothing drove that path with a
    tracker whose answer differs from "no boundary", so its `cut -f1`, its
    `grep '^##'` and its inner numeric re-validation could each be broken and
    the suite stayed green.

    This shims `awk` to fail, then asserts the fallback produced the OLD answer
    rather than either a crash or a run-to-EOF: the batch must bound at the real
    `## Statistics` and leave the next section alone.
    """
    tracker = (
        "# Review Tasks\n"
        "\n"
        "### Batch 1 - Hyphen not em-dash `Pending`\n"
        "\n"
        "> **Branch:** `feat/one`\n"
        "\n"
        "- [ ] **TASK-1**: inside batch one\n"
        "\n"
        "## Statistics\n"
        "\n"
        "- [ ] **TASK-9**: OUTSIDE the batch and must not close\n"
    )
    repo = _repo(tmp_path / "r", tracker)
    binder = tmp_path / "bin"
    binder.mkdir()
    # Fails ONLY the filter's invocation shape, keyed on `-F:` which is unique to
    # it. The first draft keyed on `-v` and that was too broad: `CLOSE_AWK` -- the
    # rewriter -- also takes `-v fenced=`, so the shim killed the rewrite path and
    # the test measured the short-write guard instead of the degradation floor.
    # `awk 'END { print NR }'` (no flags) must also keep working, or `total_lines`
    # breaks and the test measures that.
    shim = binder / "awk"
    shim.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do case "$a" in -F:) exit 3 ;; esac; done\n'
        'exec /usr/bin/awk "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    import os
    env = dict(os.environ, PATH=f"{binder}:{os.environ['PATH']}")
    r = subprocess.run(["bash", str(CLOSE_BATCH), "1"], cwd=str(repo),
                       capture_output=True, text=True, env=env)

    assert r.returncode == 0, f"the fallback crashed instead of degrading\n{r.stderr}"
    after = (repo / "review_tasks.md").read_text()
    assert "- [x] **TASK-1**" in after, (
        f"the fence-blind recompute produced no usable range.\n{after}\n{r.stderr}"
    )
    assert "- [ ] **TASK-9**" in after, (
        "the fallback ran past the real `## Statistics` boundary — the recompute "
        f"is not bounding at all.\n{after}"
    )
    assert "1 tasks closed" in r.stdout, r.stdout
