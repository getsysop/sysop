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
]

NOT_A_BATCH_HEADER_AT_ALL = [
    "### A01: Broken Access Control",
    "### Some other section",
    "#### Batch 1 — Title `Pending`",         # h4, not h3
    "## Batch 1 — Title `Pending`",           # h2, not h3
    "  ### Batch 1 - indented example `Pending`",   # WORKFLOW.md's blessed form
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
    for fragment in ("GREP FALLBACK", "review_index.py ran", "canonical shape",
                     "fence-blind", "WILL still be closed", "--check-headers"):
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
