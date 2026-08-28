"""The unterminated fence that lets an example impersonate a batch (Q-012, Phase 208).

`review_index.py`'s `_fenced_mask` ignores an **unterminated** fence on purpose:
honouring it would mask to EOF, run a batch's `line_end` to the end of the file
and let `close_batch.sh` flip every checkbox in that range. Phase 181 made that
call deliberately and its docstring records why.

What was never re-examined is the consequence, after Phase 191 added a status
gate that *acts* on what these readers report. Reproduced end to end before any
of this was written, on one tracker, twice:

* **index present** — `batch_work.sh 7` creates branch `review/FENCED`, a
  worktree and `BATCH-7.lock`, and prints `Status: Pending`.
* **index absent** — the grep fallback prints
  `Batch 7 is already 'Merged' — refusing to claim finished work.`

So the *preferred* path is the broken one and the *fallback* is correct. The
mechanism: `_parse_batches_fallback` emits both batch-7 rows and the consumer
takes the first (the real one), while `parse_review_tasks` keys batches by
number in a dict, so the fenced EXAMPLE overwrites the real batch. This is why
the fix is a refusal rather than "route the shells through the index", which was
the shape originally proposed and would have made the wrong answer universal.

**Why the check is not "is the fence balanced".** An imbalance is only
consequential when the unmasked span contains a line the parser acts on. A
tracker quoting `> **Flag:**` or a code sample inside an unterminated fence is
both legal and common — `review_index.py`'s own parser comment says the fence
work exists to serve exactly that shape. Refusing on imbalance alone would turn
a working claim into a hard refusal for those. Measured across ~32,000 lines of
real trackers (BeanRider, GDP, two archives, the loop-mode dogfood): **zero**
carried any imbalance, so a blanket refusal would have looked free in testing
and cost the operator on their first mid-edit run. `test_a_harmless_unterminated_fence_does_not_refuse`
is that false-positive case, and it is the reason this module exists in the shape
it does.
"""
import shutil
import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "core/companion/scripts"
BATCH_WORK = SCRIPTS / "batch_work.sh"
CLOSE_BATCH = SCRIPTS / "close_batch.sh"
REVIEW_INDEX = SCRIPTS / "review_index.py"


# ── Fixtures ───────────────────────────────────────────────────────────

_REAL = (
    "# Review Tasks\n"
    "\n"
    "### Batch 7 — The real one `Merged`\n"
    "\n"
    "> **Branch:** `review/batch-7`\n"
    "\n"
    "- [x] **TASK-1**: done\n"
    "\n"
    "## Notes\n"
    "\n"
)

# An unterminated fence whose body contains a `### Batch` header — the
# consequential shape.
#
# The header sits FOUR lines into the span, not on the line after the opener.
# With it adjacent, narrowing the scan to `range(start + 1, start + 2)` was
# invisible and the mutation walked the corpus.
STRUCTURAL = _REAL + (
    "```markdown\n"
    "Here is how a batch header is written:\n"
    "\n"
    "(the shape below is an illustration, not a real batch)\n"
    "\n"
    "### Batch 7 — EXAMPLE ONLY `Pending`\n"
    "\n"
    "> **Branch:** `review/FENCED`\n"
    "> **Verify:** `echo fenced`\n"
)

# A DIFFERENT spelling of the same collision — `~~~`, another title, another
# status. A detector narrowed to the literal its own fixture happens to use
# ("### Batch 7 — EXAMPLE ONLY") passes everything while still matching
# STRUCTURAL; one literal per route is satisfied by a pattern matching only that
# literal.
STRUCTURAL_ALT = _REAL + (
    "~~~\n"
    "### Batch 7 — quite another title `Merged`\n"
)

# A bare `## ` inside the span, no batch header anywhere. NOT refused: it
# truncates the enclosing batch, which is the conservative direction and is
# Q-017's subject. The first cut of the detector refused here.
SECTION_ONLY = _REAL + (
    "```markdown\n"
    "## Deferred\n"
    "\n"
    "an example of a section heading quoted inside a task body\n"
)

# THE FALSE POSITIVE THAT SHIPPED IN THE FIRST CUT.
#
# It was the reason the detector keyed on a COLLISION rather than on "a
# structural line follows the opener" — a rationale Phase 211 deliberately
# inverted. This fixture is now refused (exit 5) and forceable, because leaving
# it unrefused is what let Q-229 and Q-231(2) stand. The paragraph below is kept
# as written because it is still an accurate description of the COST; only its
# concluding rationale changed.
#
# An operator pastes a failing run into a Round 1 task and forgets the closing
# fence. Round 2 exists below. This file parses IDENTICALLY to its balanced
# control — same batches, same statuses, same branches, same tasks — and the
# first cut refused every claim, release and close on it, with the diagnostic
# pointing at `## Round 2`. There is no `--force`, so that was an operator dead
# end, and it landed on exactly the mid-edit operator the check exists for.
MULTI_ROUND_BENIGN = (
    "# Review Tasks\n"
    "\n"
    "## Round 1 — 2026-08-01\n"
    "\n"
    "### Batch 1 — First `Merged`\n"
    "\n"
    "> **Branch:** `review/batch-1`\n"
    "\n"
    "- [x] **TASK-1**: done, and here is the run I pasted:\n"
    "\n"
    "```text\n"
    "$ pytest\n"
    "E   AssertionError\n"
    "\n"
    "## Round 2 — 2026-08-10\n"
    "\n"
    "### Batch 2 — Second `Pending`\n"
    "\n"
    "> **Branch:** `review/batch-2`\n"
    "\n"
    "- [ ] **TASK-3**: open\n"
)

# An unterminated fence whose body contains NO structural line — legal, common,
# and must NOT refuse.
HARMLESS = _REAL + (
    "```markdown\n"
    "> **Flag:** an example of the metadata shape a task may quote\n"
    "- [ ] not a real task, just an illustration\n"
)

BALANCED = _REAL + (
    "```markdown\n"
    "### Batch 7 — EXAMPLE ONLY `Pending`\n"
    "```\n"
)


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def _repo(root: Path, tasks: str, *, with_index: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(root)],
                   check=True, capture_output=True)
    _git(root, "config", "user.email", "test@test")
    _git(root, "config", "user.name", "test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "review_tasks.md").write_text(tasks)
    (root / "README.md").write_text("# seed\n")
    if with_index:
        dst = root / "sysop" / "scripts"
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copy(REVIEW_INDEX, dst / "review_index.py")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "seed")
    return root


def _run(script: Path, cwd: Path, *args):
    return subprocess.run(["bash", str(script), *args],
                          cwd=str(cwd), capture_output=True, text=True)


# ── The detector ───────────────────────────────────────────────────────

def test_check_fences_separates_the_proven_case_from_the_ambiguous_one(tmp_path):
    """Three outcomes, and more than one spelling of each.

    * **3 — proven.** A fenced batch header collides with a real number, so the
      fenced copy demonstrably overwrites a real batch. Never forceable.
    * **5 — ambiguous.** An unterminated span contains a batch header that
      collides with nothing (Q-229 after an archive, or Q-231(2)'s unique
      number). Textually identical to a real batch below a stray fence, so it
      refuses but IS forceable.
    * **0 — nothing to say.** No unterminated span, or one containing no batch
      header at all.

    `SECTION_ONLY` staying 0 is the load-bearing negative: the blanket form that
    also refused a bare `## ` inside the span false-fired on 98.2% and 96.8% of
    opener positions on two real trackers, because every tracker ends in
    `## Statistics`. Phase 208 shipped that and reverted it; this row is what
    stops it being re-derived.
    """
    for name, doc, expected in (
        ("collision", STRUCTURAL, 3),
        ("collision-alt-spelling", STRUCTURAL_ALT, 3),
        ("section-only-no-batch-header", SECTION_ONLY, 0),
        ("multi-round-benign", MULTI_ROUND_BENIGN, 5),
        ("harmless", HARMLESS, 0),
        ("balanced", BALANCED, 0),
    ):
        repo = _repo(tmp_path / name, doc)
        r = subprocess.run(["python3", "sysop/scripts/review_index.py", "--check-fences"],
                           cwd=str(repo), capture_output=True, text=True)
        assert r.returncode == expected, f"{name}: rc={r.returncode}\n{r.stdout}\n{r.stderr}"


def test_the_reported_line_is_the_structural_one_not_the_fence(tmp_path):
    """A reach assertion, not a presence one.

    The diagnostic names the line the span swallows. A detector that stopped at
    the opener would still exit 3 and still look like it worked; this is what
    distinguishes it.
    """
    repo = _repo(tmp_path / "reach", STRUCTURAL)
    r = subprocess.run(["python3", "sysop/scripts/review_index.py", "--check-fences"],
                       cwd=str(repo), capture_output=True, text=True)
    assert r.returncode == 3, r.stderr
    assert "### Batch 7 — EXAMPLE ONLY" in r.stderr, (
        f"the diagnostic does not name the swallowed structural line\n{r.stderr}"
    )
    # …and it is four lines past the opener, so the reach is real.
    fence_line = STRUCTURAL.splitlines().index("```markdown") + 1
    struct_line = STRUCTURAL.splitlines().index("### Batch 7 — EXAMPLE ONLY `Pending`") + 1
    assert struct_line - fence_line >= 4, "fixture no longer separates the two"
    assert f":{struct_line}" in r.stderr, r.stderr


def test_exit_code_3_is_not_used_by_any_other_path(tmp_path):
    """The refusal is distinguishable only if 3 is otherwise unused.

    Derived rather than asserted from memory: argparse takes 2, every other
    error path in this script takes 1.
    """
    repo = _repo(tmp_path / "codes", BALANCED)
    for args, expected in (
        (["--range", "999"], 1),
        (["--batch", "999"], 1),
        (["--nonsense"], 2),
        (["--check-fences"], 0),
    ):
        r = subprocess.run(["python3", "sysop/scripts/review_index.py", *args],
                           cwd=str(repo), capture_output=True, text=True)
        assert r.returncode == expected, f"{args}: rc={r.returncode}\n{r.stderr}"


def test_the_plain_check_flag_still_resolves_exactly(tmp_path):
    """`--check-fences` must not shadow the pre-existing `--check`."""
    repo = _repo(tmp_path / "abbrev", BALANCED)
    r = subprocess.run(["python3", "sysop/scripts/review_index.py", "--check"],
                       cwd=str(repo), capture_output=True, text=True)
    assert r.stdout.strip() in {"stale", "fresh"}, f"{r.stdout!r} {r.stderr!r}"


# ── The gate the refusal exists to close ───────────────────────────────

def test_claim_refuses_and_writes_nothing_when_a_fence_swallows_a_batch(tmp_path):
    repo = _repo(tmp_path / "claim", STRUCTURAL)
    r = _run(BATCH_WORK, repo, "7")

    assert r.returncode != 0, f"claim succeeded\n{r.stdout}\n{r.stderr}"
    assert "unterminated fence" in r.stderr, r.stderr
    # Nothing was created — the harm this refusal exists to prevent.
    assert "Created branch" not in r.stdout, r.stdout
    assert not (repo / "sysop/runtime/locks").exists(), "a lock was written"
    branches = subprocess.run(["git", "branch", "--list"], cwd=str(repo),
                              capture_output=True, text=True).stdout
    assert "review/FENCED" not in branches, branches


def test_the_shell_surfaces_the_python_diagnostic_to_the_operator(tmp_path):
    """The shell's own `❌` line is not the diagnostic.

    `refuse_on_structural_fence` captures stderr with `2>&1 >/dev/null` and
    echoes it. Dropping that redirection to a plain `2>/dev/null` leaves `$err`
    empty — the refusal still fires, the exit code is still 1, and the operator
    loses the file:line naming entirely. Every other shell case here asserts only
    the shell's own echo, so nothing observed that. This does.
    """
    repo = _repo(tmp_path / "diag", STRUCTURAL)
    r = _run(BATCH_WORK, repo, "7")
    assert r.returncode != 0, r.stdout
    assert "review_tasks.md:" in r.stderr, (
        f"the fence's own line number never reached the operator\n{r.stderr}"
    )
    assert "### Batch 7 — EXAMPLE ONLY" in r.stderr, (
        f"the colliding header was not named\n{r.stderr}"
    )


def test_the_shell_refusal_is_not_pinned_to_one_document(tmp_path):
    """A shell-layer guard keyed on a literal from the single fixture passes
    everything. The alt spelling exercises the shell path, not just the Python."""
    repo = _repo(tmp_path / "shell-alt", STRUCTURAL_ALT)
    r = _run(BATCH_WORK, repo, "7")
    assert r.returncode != 0, f"{r.stdout}\n{r.stderr}"
    assert "quite another title" in r.stderr, r.stderr


def test_the_preflight_runs_before_flag_parsing_in_both_entry_points():
    """The placement invariant, asserted structurally.

    Both preflight calls must appear BEFORE the `while [[ "${1:-}" == --* ]]`
    loop that consumes `--force`. Moving either below it leaves every behavioural
    test green — the refusal still fires, just later and bypassably — so the
    invariant the comments argue for twice had no enforcement at all.
    """
    body = BATCH_WORK.read_text(encoding="utf-8")

    release = body.index('if [[ "${1:-}" == "--release" ]]; then')
    rel_preflight = body.index("refuse_on_structural_fence \"$_fence_force\"", release)
    rel_flags = body.index('while [[ "${1:-}" == --* ]]; do', release)
    assert rel_preflight < rel_flags, (
        "--release parses flags before the fence preflight, so --force reaches past it"
    )

    claim_flags = body.index("CLAIM_FORCE=false")
    claim_preflight = body.rindex("refuse_on_structural_fence \"$_fence_force\"", 0, claim_flags)
    assert claim_preflight < claim_flags, (
        "the claim path parses flags before the fence preflight"
    )


def test_force_cannot_bypass_the_fence_refusal(tmp_path):
    """`--force` already admits `Complete|Merged|Ready for Review` — precisely the
    statuses a doc example carries — so a refusal placed after flag parsing would
    be reachable by a flag that already ships."""
    repo = _repo(tmp_path / "force", STRUCTURAL)
    r = _run(BATCH_WORK, repo, "--force", "7")
    assert r.returncode != 0, f"--force bypassed the fence refusal\n{r.stdout}\n{r.stderr}"
    assert "unterminated fence" in r.stderr, r.stderr


def test_release_refuses_before_flag_parsing(tmp_path):
    repo = _repo(tmp_path / "release", STRUCTURAL)
    r = _run(BATCH_WORK, repo, "--release", "--force", "7")
    assert r.returncode != 0, f"{r.stdout}\n{r.stderr}"
    assert "unterminated fence" in r.stderr, r.stderr


def test_close_refuses(tmp_path):
    repo = _repo(tmp_path / "close", STRUCTURAL)
    r = _run(CLOSE_BATCH, repo, "7")
    assert r.returncode != 0, f"{r.stdout}\n{r.stderr}"
    assert "unterminated fence" in r.stderr, r.stderr


def test_close_dry_run_warns_but_does_not_refuse(tmp_path):
    """A preview writes nothing, and the operator running it is the one most
    likely to be mid-edit on the file."""
    repo = _repo(tmp_path / "dry", STRUCTURAL)
    r = _run(CLOSE_BATCH, repo, "--dry-run", "7")
    assert r.returncode == 0, f"dry-run refused\n{r.stdout}\n{r.stderr}"
    assert "--dry-run: continuing anyway" in r.stderr, r.stderr


# ── The false positive the original design would have shipped ──────────

def test_a_harmless_unterminated_fence_does_not_refuse(tmp_path):
    """The case that killed "refuse on imbalance".

    A tracker quoting the metadata shapes inside an unterminated fence is legal
    and is the very shape `review_index.py`'s parser comment says the fence work
    exists to serve. Refusing here would break a working claim.
    """
    repo = _repo(tmp_path / "harmless", HARMLESS)
    r = _run(BATCH_WORK, repo, "7")
    assert "unterminated fence" not in r.stderr, (
        "The refusal fired on a fence that swallows no structural line — this is "
        f"the false positive the detector is scoped to avoid.\n{r.stderr}"
    )


def test_the_ordinary_multi_round_tracker_refuses_but_forces_through(tmp_path):
    """The regression that shipped in the first cut of this detector — now a
    DELIBERATE refusal with an escape, which is a different trade, not a revert.

    Phase 208 reverted the first cut because this file is benign and there was
    no way past the refusal: "there is no --force, so that was an operator dead
    end". Phase 211 refuses it again, because leaving it unrefused is what let
    Q-229 and Q-231(2) stand — a phantom batch claimable with the gate green.
    The two halves asserted here are what make that trade honest:

    1. the file still parses identically to its balanced control, so the
       refusal is a false positive and this test says so rather than pretending
       the fixture stopped being benign; and
    2. `--force` gets through it, so the operator is never stuck. The proven
       case (exit 3) is still unforceable — `test_force_cannot_bypass_the_fence_refusal`
       is the twin that pins that, and the pair is the whole contract.
    """
    control = MULTI_ROUND_BENIGN.replace(
        "E   AssertionError\n\n## Round 2", "E   AssertionError\n```\n\n## Round 2"
    )
    assert control != MULTI_ROUND_BENIGN, "the control did not close the fence"

    def parsed(doc: str, name: str):
        repo = _repo(tmp_path / name, doc)
        out = subprocess.run(
            ["python3", "-c",
             "import sys; sys.path.insert(0, 'sysop/scripts');\n"
             "import review_index as r;\n"
             "d = r.parse_review_tasks('review_tasks.md');\n"
             "print(sorted((k, b['status'], b['branch']) for k, b in d['batches'].items()))"],
            cwd=str(repo), capture_output=True, text=True,
        )
        assert out.returncode == 0, out.stderr
        return out.stdout.strip()

    # (1) Still benign: refusing it is a cost we are choosing, not a defect found.
    assert parsed(MULTI_ROUND_BENIGN, "mr-open") == parsed(control, "mr-closed"), (
        "the unterminated tracker parses differently from its balanced control — "
        "if that is now true, this fixture is no longer benign and the case needs "
        "re-deriving rather than the assertion relaxing"
    )

    # (2) The escape works. Asserted on the diagnostic, not the exit code: the
    # claim continues past this point into `git pull --ff-only`, which has no
    # origin here — what is under test is whether --force gets THROUGH the
    # fence refusal, not whether the whole claim succeeds.
    repo = _repo(tmp_path / "mr-force", MULTI_ROUND_BENIGN)

    plain = _run(BATCH_WORK, repo, "2")
    assert plain.returncode != 0, f"the refusal did not fire\n{plain.stdout}{plain.stderr}"
    assert "unterminated fence is open" in plain.stderr, plain.stderr

    # The escape is its OWN flag. `--force` must NOT carry it: in close_batch.sh
    # `--force` means "skip the merge-base ancestry check" and `/review-close`
    # Step 4b mandates it for every `pr`-policy consumer, so binding the escape
    # to it disarmed this gate for exactly those consumers. The round measured a
    # `--force` close rewriting a fenced example to `Merged`.
    still_refused = _run(BATCH_WORK, repo, "--force", "2")
    assert "unterminated fence is open" in still_refused.stderr, (
        "`--force` bypassed the ambiguous-fence refusal. It must not: it is "
        f"mandated on the close path for every protected-main consumer.\n{still_refused.stderr}"
    )

    forced = _run(BATCH_WORK, repo, "--allow-open-fence", "2")
    assert "proceeding under --allow-open-fence" in forced.stderr, (
        "--allow-open-fence did not get past the ambiguous-fence refusal, so the "
        f"operator is in the dead end Phase 208 reverted this detector for.\n{forced.stderr}"
    )
    assert "unterminated fence is open" not in forced.stderr, forced.stderr

def test_the_two_shell_copies_of_the_refusal_are_identical():
    """`batch_work.sh` and `close_batch.sh` install standalone and source no
    shared library, so the helper is duplicated — the same deliberate
    duplicate-and-pin `resolve_main_root` already uses, and `_fenced_mask` uses
    across four Python modules. Pinned so the copies cannot drift.
    """
    def body(path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        start = text.index("refuse_on_structural_fence() {")
        end = text.index("\n}\n", start)
        return "\n".join(
            ln for ln in text[start:end].splitlines() if ln.strip() and not ln.strip().startswith("#")
        )

    a, b = body(BATCH_WORK), body(CLOSE_BATCH)
    assert a == b, f"the two copies have drifted\n--- batch_work\n{a}\n--- close_batch\n{b}"
    assert "check-fences" in a and len(a.splitlines()) >= 8, (
        "the pinned body no longer contains the check it exists to pin"
    )


def test_force_alone_does_not_open_the_fence_gate_on_the_close_path(tmp_path):
    """`--force` must not carry the fence escape — the close path is the proof.

    `close_batch.sh --force` means "skip the merge-base ancestry check". Step 4b
    used to mandate it in bold for **every** `pr`-policy consumer ("Under `pr`
    policy, always pass `--force`"), and Phase 211's first cut bound the exit-5
    escape to that flag — disarming this gate on the close path for precisely
    the consumers it exists to protect, not by operator choice, because the
    skill left none.

    **The mandate is retired (Phase 233, `Q-020`):** the ancestry gate now
    targets `HEAD` rather than the literal `main`, so a `pr`-policy merge passes
    it and `--force` is back to meaning only what it says. This test is
    unaffected either way — the point is that `--force` must never carry the
    fence escape, whoever passes it and for whatever reason.

    Measured by the round before the fix: the close rewrote a fenced example's
    header to `Merged`, flipped its illustration task to `[x]` INSIDE the fence,
    and corrupted the Grand Total — a phantom counted as done while a real open
    task went under-reported. Exit 0, committed.
    """
    tracker = (
        "# Review Tasks\n\n"
        "### Batch 8 — Real `Pending`\n\n"
        "> **Branch:** `review/real`\n\n"
        "- [ ] **TASK-1**: real work\n\n"
        "```markdown\n"
        "### Batch 9 — EXAMPLE ONLY `Pending`\n\n"
        "- [ ] **TASK-X**: illustration\n"
    )
    repo = _repo(tmp_path / "pr-close", tracker)

    r = _run(CLOSE_BATCH, repo, "--force", "9")
    text = (repo / "review_tasks.md").read_text()

    assert "unterminated fence is open" in r.stderr, (
        f"`--force` bypassed the fence gate on the close path.\n{r.stderr}"
    )
    assert "### Batch 9 — EXAMPLE ONLY `Pending`" in text, (
        "the fenced documentation example was rewritten by a --force close — "
        f"this is the exact harm the round measured.\n{text}"
    )
    assert "- [ ] **TASK-X**: illustration" in text, text

    # …and the dedicated flag still gets through, so nobody is stuck.
    forced = _run(CLOSE_BATCH, repo, "--allow-open-fence", "--force", "9")
    assert "proceeding under --allow-open-fence" in forced.stderr, forced.stderr
