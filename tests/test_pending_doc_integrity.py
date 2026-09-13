"""Phase 210 — the pending-doc pipeline's integrity contract, at all three ends.

The pipeline had no integrity check anywhere: the writer emitted YAML that does not
parse, the collect overwrote main's copy by basename, and the consumer had no arm for a
doc it could not read. Before this phase there was ZERO test coverage for any of it —
`git grep pending.doc -- tests/` matched nothing about collision, overwrite or clobber.

The collect/rollback tests EXECUTE the heredocs extracted verbatim from the shipped skill
rather than re-typing them, so a change to the skill body that breaks the mechanism fails
here. That is the point: the previous drift guard asserted a bash *string*, which is why
it could pin a command nobody had run.
"""

from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

from _prose_guard_helpers import states

import pytest

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "core" / "skills" / "review-close" / "SKILL.md"
DOCWORK = REPO / "core" / "skills" / "document-work" / "SKILL.md"

HEREDOC_RE = re.compile(
    r"python3 - \"<worktree-path>\" \"<branch name>\" <<'PY'\n(.*?)\n      PY\n", re.DOTALL
)


def _heredocs() -> list[str]:
    """The Step 3b collect and rollback bodies, dedented out of the shipped skill."""
    bodies = HEREDOC_RE.findall(SKILL.read_text(encoding="utf-8"))
    return [
        "\n".join(ln[6:] if ln.startswith("      ") else ln for ln in b.split("\n"))
        for b in bodies
    ]


@pytest.fixture(scope="module")
def scripts(tmp_path_factory) -> tuple[Path, Path]:
    d = tmp_path_factory.mktemp("p210_scripts")
    bodies = _heredocs()
    assert len(bodies) == 2, (
        f"expected exactly 2 worktree-path heredocs in Step 3b (collect + rollback), "
        f"found {len(bodies)}"
    )
    collect, rollback = d / "collect.py", d / "rollback.py"
    collect.write_text(bodies[0], encoding="utf-8")
    rollback.write_text(bodies[1], encoding="utf-8")
    return collect, rollback


def _doc(path: Path, branch: str | None, summary: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = "---\n"
    if branch is not None:
        fm += f"branch: {branch}\n"
    fm += f'type: feature\nsummary: "{summary}"\n---\n'
    path.write_text(fm, encoding="utf-8")


def _run(
    script: Path,
    main: Path,
    wt: Path,
    branch: str = "feat/x",
    tmpdir: Path | None = None,
) -> subprocess.CompletedProcess:
    """The branch being processed is an INPUT, not something inferred from the docs.

    Round 3 found that asking "do these two docs agree with each other" instead of "does
    this doc belong to the branch I am processing" let a worktree carrying a foreign-branch
    doc overwrite and then delete another branch's only surviving record, reporting
    `COLLISIONS: 0` and exit 0 throughout.
    """
    env = None
    if tmpdir is not None:
        # The undo's `tempfile.mkdtemp` otherwise lands in the machine-wide temp, where a
        # "no backup directory was left behind" assertion reads other tests' leftovers and
        # races them under xdist. Scoping TMPDIR makes that assertion exact.
        tmpdir.mkdir(parents=True, exist_ok=True)
        env = {**os.environ, "TMPDIR": str(tmpdir)}
    return subprocess.run(
        [sys.executable, str(script), str(wt), branch],
        cwd=main, capture_output=True, text=True, env=env,
    )


def _exit_codes(body: str) -> set[int]:
    """Every non-zero exit a heredoc can take, however it is spelled.

    The round's guard lens walked both table guards by adding a reachable
    `raise SystemExit(9)`: they derived from `sys\\.exit\\((\\d+)\\)` alone, so an
    undocumented halt shipped green. `sys.exit`, `raise SystemExit` and the builtin `exit`
    all end the process, and an operator reading a code off their shell cannot tell which
    one produced it — so the table owes a row to all three.
    """
    pat = r"(?:sys\.exit|raise\s+SystemExit|SystemExit|(?<![.\w])exit)\s*\(\s*(\d+)\s*\)"
    return {int(n) for n in re.findall(pat, body)} - {0}


def _live(main: Path) -> Path:
    return main / "sysop" / "runtime" / "pending-docs"


# ---------------------------------------------------------------- the collect


def test_same_branch_collision_lets_the_worktree_win(scripts, tmp_path):
    """The dominant real collision: the same branch collected twice.

    Main's copy is stale by construction, and Step 3c's dedup already states the worktree
    is the authoring source of truth. Overwriting here is CORRECT — a fix that preserved
    main's copy would quarantine a file the neighbouring step calls stale.
    """
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _doc(_live(main) / "feat-x.md", "feat/x", "STALE-MAIN")
    _doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "FRESH-WORKTREE")

    r = _run(collect, main, wt)

    assert r.returncode == 0, r.stderr
    assert 'summary: "FRESH-WORKTREE"' in (_live(main) / "feat-x.md").read_text()
    assert "PENDING-DOC COLLISIONS: 0" in r.stdout


def test_different_branch_collision_refuses_and_touches_nothing(scripts, tmp_path):
    """The defect. Two branches, one basename (`feat/foo-bar` and `feat/foo/bar` both
    sanitize to `feat-foo-bar.md`).

    The FIRST version of this fix parked main's copy under `pending-docs/superseded/`.
    Its own review round disqualified that: nothing in the shipped tree reads that
    directory, `ls pending-docs/*.md` is non-recursive, so the parked branch's task
    never closed and its record was orphaned permanently. Refusing is what preserves
    both records somewhere a reader still looks.
    """
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _doc(_live(main) / "feat-foo-bar.md", "feat/foo-bar", "BRANCH-A-WORK")
    _doc(wt / "sysop/runtime/pending-docs/feat-foo-bar.md", "feat/foo/bar", "BRANCH-B-WORK")

    r = _run(collect, main, wt, branch="feat/foo/bar")

    assert r.returncode == 3, f"a collision must refuse: {r.stdout}{r.stderr}"
    # Identity, not membership: main still holds A, byte for byte.
    assert 'summary: "BRANCH-A-WORK"' in (_live(main) / "feat-foo-bar.md").read_text()
    assert 'summary: "BRANCH-B-WORK"' in (
        wt / "sysop/runtime/pending-docs/feat-foo-bar.md"
    ).read_text(), "the worktree copy must be left where its author put it"
    assert not (_live(main) / "superseded").exists(), (
        "the withdrawn parking mechanism must not come back — it orphans the record"
    )
    assert "feat/foo-bar" in r.stdout and "feat/foo/bar" in r.stdout, (
        "the report must name the branch that owns main's copy AND the one being "
        "processed — an operator cannot act on 'a collision'"
    )


def test_a_refusal_writes_nothing_at_all(scripts, tmp_path):
    """All-or-nothing. A worktree holding a clean doc AND a colliding one must not leave
    the clean one on main: the branch is about to be SKIP'd, so a stray doc from an
    unmerged branch is exactly what Step 4c's 1b filter exists to catch later. An earlier
    draft `continue`d past the collision and kept collecting, while the prose claimed
    "nothing was collected" — a reviewer measured both halves.
    """
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _doc(_live(main) / "zz-collide.md", "feat/other", "MAIN-OTHER")
    _doc(wt / "sysop/runtime/pending-docs/aa-clean.md", "feat/b", "CLEAN")
    _doc(wt / "sysop/runtime/pending-docs/zz-collide.md", "feat/b", "COLLIDES")

    r = _run(collect, main, wt)

    assert r.returncode == 3
    assert not (_live(main) / "aa-clean.md").exists(), (
        "the clean doc collected before the collision was not undone"
    )
    assert 'summary: "MAIN-OTHER"' in (_live(main) / "zz-collide.md").read_text()


def test_an_unreadable_doc_is_never_treated_as_the_same_branch(scripts, tmp_path):
    """`branch_of()` returns None on unparseable frontmatter, and None must never compare
    equal to anything — otherwise a corrupt doc silently licenses the overwrite."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    (_live(main)).mkdir(parents=True)
    (_live(main) / "feat-x.md").write_text("no frontmatter at all\n", encoding="utf-8")
    _doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "WORKTREE")

    r = _run(collect, main, wt)

    assert r.returncode == 3, "unknown provenance must refuse, not overwrite"
    assert "no frontmatter at all" in (_live(main) / "feat-x.md").read_text()


def test_both_docs_unreadable_still_refuses(scripts, tmp_path):
    """Two None provenances must not compare equal to each other either."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    (_live(main)).mkdir(parents=True)
    (_live(main) / "feat-x.md").write_text("MAIN garbage\n", encoding="utf-8")
    (wt / "sysop/runtime/pending-docs").mkdir(parents=True)
    (wt / "sysop/runtime/pending-docs/feat-x.md").write_text("WT garbage\n", encoding="utf-8")

    r = _run(collect, main, wt)

    assert r.returncode == 3
    assert "MAIN garbage" in (_live(main) / "feat-x.md").read_text()


def test_an_unusable_worktree_path_aborts_loudly(scripts, tmp_path):
    """The regression an earlier draft of this phase INTRODUCED. The retired `cp` form
    exited 1 on a bad path; a bare glob over a missing directory yields nothing and would
    exit 0 with a success-shaped report — after which Step 3b removes the worktree and the
    untracked docs are gone. Step 3b's ONLY stated stop condition is a non-zero exit.
    """
    collect, _ = scripts
    main = tmp_path / "main"
    main.mkdir()

    unsubstituted = _run(collect, main, Path("<worktree-path>"))
    assert unsubstituted.returncode != 0, "an unsubstituted placeholder must not exit 0"

    missing = _run(collect, main, tmp_path / "no-such-worktree")
    assert missing.returncode != 0, "a nonexistent worktree path must not exit 0"


def test_convention_candidates_is_never_collected(scripts, tmp_path):
    """It is a fixed-name file the review skills own, append to, and delete themselves.
    Collecting it moves an OPEN review round's candidates onto main, where Step 4c
    consolidates (routing nothing — it has no type) and then deletes them."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    (_live(main)).mkdir(parents=True)
    cc = wt / "sysop/runtime/pending-docs/convention-candidates.md"
    cc.parent.mkdir(parents=True)
    cc.write_text("# Convention Candidates — Round 12 (2026-08-17)\n", encoding="utf-8")

    r = _run(collect, main, wt)

    assert not (_live(main) / "convention-candidates.md").exists()
    assert "SKIPPED (not a branch doc)" in r.stdout
    assert cc.exists(), "the worktree's own copy must be left alone, not moved"


# --------------------------------------------------------------- the rollback


def test_rollback_removes_only_this_branchs_own_doc(scripts, tmp_path):
    """Provenance, not basename. The retired `rm -f $(basename …)` deleted main's copy by
    name with no check that this branch ever wrote it."""
    collect, rollback = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _doc(_live(main) / "feat-x.md", "feat/x", "MAINS-OWN")
    _doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "WORKTREE")

    _run(collect, main, wt)
    assert 'summary: "WORKTREE"' in (_live(main) / "feat-x.md").read_text()
    r = _run(rollback, main, wt)

    assert r.returncode == 0, r.stderr
    assert not (_live(main) / "feat-x.md").exists(), (
        "this branch's own collected doc should be removed for re-collection later"
    )
    assert "ROLLED BACK: feat-x.md" in r.stdout


def test_rollback_leaves_a_foreign_doc_alone(scripts, tmp_path):
    """THE defect the retired form had, asserted directly: a same-named doc from another
    branch must survive a rollback that never collected it."""
    _, rollback = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _doc(_live(main) / "feat-x.md", "feat/somebody-else", "FOREIGN")
    _doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "OURS")

    r = _run(rollback, main, wt)

    assert 'summary: "FOREIGN"' in (_live(main) / "feat-x.md").read_text(), (
        "the rollback deleted another branch's record"
    )
    assert "LEFT ALONE" in r.stdout and "feat/somebody-else" in r.stdout


def test_rollback_never_touches_convention_candidates(scripts, tmp_path):
    """It was never collected, so rolling it back would delete a file this step did not
    write — the precise bug the retired blind `rm -f` had."""
    _, rollback = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    (_live(main)).mkdir(parents=True)
    (_live(main) / "convention-candidates.md").write_text("# Candidates\n", encoding="utf-8")
    cc = wt / "sysop/runtime/pending-docs/convention-candidates.md"
    cc.parent.mkdir(parents=True)
    cc.write_text("# Candidates\n", encoding="utf-8")

    _run(rollback, main, wt)

    assert (_live(main) / "convention-candidates.md").exists(), (
        "the rollback deleted a review round's candidate file it never collected"
    )


# ------------------------------------------------------------------ the writer


def test_the_summary_template_is_quoted():
    """The producer half. Unquoted, every shape this workflow's own conventions invite raises or mis-parses —
    and the silent one (`#` opening a YAML comment) truncates the summary that lands in
    PROJECT_STATUS.md. /auto-fix and /auto-judge already quote theirs.
    """
    text = DOCWORK.read_text(encoding="utf-8")
    # Either quoting style. The skill's own guidance says "escape it (\") or switch the
    # value to single quotes", and a reviewer showed that following that advice reddened
    # this test — a guard punishing the remedy its own prose prescribes.
    assert (
        'summary: "<one-sentence description' in text
        or "summary: '<one-sentence description" in text
    ), "document-work's summary: template lost its quotes"


def _pending_doc_template_files() -> list[Path]:
    """Every shipped file that can carry a pending-doc frontmatter template.

    NOT just `core/skills/**/SKILL.md`. A reviewer found three unquoted templates the
    skill-only sweep structurally could not reach — including `WORKFLOW.md` § 6.6, which
    is the CANONICAL SCHEMA, and a `cat > … << 'EOF'` block in `WORKFLOW_GUIDE.md` that a
    human is told to run and whose output raises `ScannerError`. Both install to consumers.
    The sibling guard `test_no_shipped_file_claims_step4c_deletes_by_glob` already reads
    all three populations; this one was narrower than its neighbour for no reason.
    """
    return sorted((REPO / "core" / "skills").rglob("SKILL.md")) + [
        REPO / "core" / "companion" / "docs" / "WORKFLOW.md",
        REPO / "core" / "companion" / "docs" / "WORKFLOW_GUIDE.md",
    ]


def test_no_shipped_file_emits_an_unquoted_summary():
    """DERIVED population, not a hardcoded roster, and whitespace-tolerant.

    The first version named three files and matched `ln.startswith("summary:")`. A
    reviewer walked it twice: a FOURTH writer (a new skill growing a frontmatter
    template) was unpoliced, and an EXISTING writer defeated it with one leading space,
    because an indented `  summary: Batch <N> complete: <Title>` is invisible to a
    prefix test — and that value carries the `": "` this phase measured as raising.
    So: sweep every skill, and strip before matching.
    """
    offenders = []
    for skill in _pending_doc_template_files():
        for n, ln in enumerate(skill.read_text(encoding="utf-8").splitlines(), 1):
            s = ln.strip()
            if not s.startswith("summary:"):
                continue
            value = s[len("summary:"):].strip()
            if not value:
                continue          # block scalar (`summary: |`) — safe, see below
            if value[0] not in "\"'":
                offenders.append(f"{skill.relative_to(REPO)}:{n}: {s[:70]}")
    assert not offenders, "unquoted summary: value(s) in a pending-doc template:\n" + "\n".join(offenders)


def test_the_roster_sweep_is_not_vacuous():
    """The sweep above passes trivially if it finds no `summary:` lines at all."""
    found = [
        f.relative_to(REPO)
        for f in _pending_doc_template_files()
        if any(ln.strip().startswith("summary:") for ln in f.read_text(encoding="utf-8").splitlines())
    ]
    # Name them. A bare count passed while /document-work's template was absent, because
    # an unrelated `summary:` field in /claim-task's review-report schema made up the number.
    names = {str(f) for f in found}
    for required in (
        "core/skills/document-work/SKILL.md",
        "core/companion/docs/WORKFLOW.md",
        "core/companion/docs/WORKFLOW_GUIDE.md",
    ):
        assert required in names, f"{required} no longer carries a summary: template — sweep is blind"


def test_the_silent_truncation_case_the_phase_calls_its_worst():
    """The `#` case has no exception to catch, so the parametrized guard below —
    structured as `pytest.raises` — structurally CANNOT express it. A reviewer pointed
    out that the failure mode this phase singles out as the most dangerous was therefore
    the one shape it did not test. It is quiet: no error, just a truncated summary
    landing in PROJECT_STATUS.md.
    """
    yaml = pytest.importorskip("yaml")
    summary = "resolves issue #428 by quarantining the doc"

    bare = yaml.safe_load(f"---\nbranch: feat/x\nsummary: {summary}\n---\n".split("---", 2)[1])
    assert bare["summary"] == "resolves issue", (
        "the `#`-comment truncation no longer reproduces — if PyYAML changed, re-derive "
        "the claim in /document-work's blockquote rather than deleting this test"
    )

    quoted = yaml.safe_load(f'---\nbranch: feat/x\nsummary: "{summary}"\n---\n'.split("---", 2)[1])
    assert quoted["summary"] == summary


@pytest.mark.parametrize(
    "summary",
    [
        "fix: handle the rollback case",
        "[FEAT-0001] add the collision guard",
        "adds a third arm to Step 4c: refuse and keep",
        "*always* quote this field",
    ],
)
def test_the_quoted_template_survives_summaries_that_break_it_bare(summary):
    """Non-vacuity control WITH a paired assertion: each input must genuinely break the
    bare form, and genuinely survive the quoted one. A guard that only checked the
    quoted form would pass on inputs that were never dangerous."""
    yaml = pytest.importorskip("yaml")
    bare = f"---\nbranch: feat/x\nsummary: {summary}\n---\n"
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(bare.split("---", 2)[1])

    quoted = f'---\nbranch: feat/x\nsummary: "{summary}"\n---\n'
    assert yaml.safe_load(quoted.split("---", 2)[1])["summary"] == summary


# ----------------------------------------------------------------- the consumer


def test_step4c_has_a_third_arm_that_quarantines():
    text = SKILL.read_text(encoding="utf-8")
    assert "Format detection — three arms" in text
    assert "pending-docs/quarantine/" in text
    # The two dispositions the third arm exists to reject, named so a revert is visible.
    assert "do **not** delete it" in text
    assert "do **not** leave it in place" in text


RETIRED_DISPOSITIONS = (
    "If `branch:` is absent or the ref no longer resolves, stop and ask",
    "is the one benign shape",
)


def test_the_contradictory_no_branch_dispositions_are_gone():
    """Two independent reviewers read the pre-phase file and implemented OPPOSITE
    dispositions for the identical input — one halted the close, one consolidated the doc
    and deleted it. Neither rule may return as live guidance.

    **Count-pinned, deliberately, and NOT scoped by markdown decoration.** The first
    version of this guard allowed each retired phrase anywhere inside a `>` blockquote, on
    the premise that "a live rule in this file is body prose; the explanation is a
    blockquote". A reviewer disproved that premise — this file ships normative
    instructions inside blockquotes, and the sibling guard
    `test_all_three_convention_candidates_exclusions_are_present` pins a live rule that
    IS in one — then walked the guard by reinstating both retired rules verbatim inside
    blockquotes, with the full suite green.

    So the invariant is arithmetic instead: each retired phrase appears exactly once, in
    the paragraph that explains the withdrawal. Any reinstatement adds an occurrence and
    reds this, wherever it is placed and however it is decorated. The cost is that a
    legitimate second citation also reds it — which is the right trade for a rule whose
    ambiguity two agents already resolved in opposite directions, and the fix is to say so
    here rather than to loosen the count.
    """
    text = SKILL.read_text(encoding="utf-8")
    assert "If `branch:` is ABSENT, quarantine the doc and carry on" in text, (
        "the replacement disposition is missing"
    )
    for phrase in RETIRED_DISPOSITIONS:
        n = text.count(phrase)
        assert n == 1, (
            f"{phrase!r} occurs {n} times; exactly 1 is expected (the withdrawal "
            f"explanation). More than one means a retired disposition was reinstated "
            f"somewhere in this file — check for a blockquote-wrapped copy."
        )


def test_that_count_pin_can_actually_fail():
    """Non-vacuity: the phrases must still be PRESENT, or the count check guards nothing
    and the correction is no longer readable."""
    text = SKILL.read_text(encoding="utf-8")
    for phrase in RETIRED_DISPOSITIONS:
        assert phrase in text, (
            f"{phrase!r} vanished entirely — the correction is unreadable and "
            f"test_the_contradictory_no_branch_dispositions_are_gone now guards nothing"
        )


def test_no_shipped_file_claims_step4c_deletes_by_glob():
    """The one sentence that could license the deletion the filing alleged. It sat in the
    same file that forbids it, and in WORKFLOW.md."""
    for rel in (
        "core/skills/review-close/SKILL.md",
        "core/companion/docs/WORKFLOW.md",
        "core/companion/docs/WORKFLOW_GUIDE.md",
    ):
        p = REPO / rel
        if not p.is_file():
            continue
        assert "deletes each `sysop/runtime/pending-docs/*.md`" not in p.read_text(
            encoding="utf-8"
        ), f"{rel} still asserts a glob delete that Step 4c's cleanup step forbids"


def test_no_bash_write_loop_returned_to_step3b():
    """The retired loop was one of the skill set's two write loops; the other (Step 3b's
    symlink strip) survives and is also `rm`-bearing. A future edit that
    reintroduces one would pass the staging-discipline guard if it reused a known header,
    so assert the mechanism directly."""
    text = SKILL.read_text(encoding="utf-8")
    assert 'for f in "<worktree-path>"/sysop/runtime/pending-docs/*.md; do' not in text
    assert 'rm -f "sysop/runtime/pending-docs/$(basename "$f")"' not in text


def test_all_three_convention_candidates_exclusions_are_present():
    """The commit message claims the file is excluded at three readers. A reviewer walked
    two of them: only the collect and the rollback are executable (and covered above by
    running them); Step 4c's and Step 3c's were prose/code with no guard at all.

    Named individually — a count would pass with the same site asserted twice.
    """
    text = SKILL.read_text(encoding="utf-8")
    for label, needle in (
        ("Step 3b collect + rollback", "NOT_A_BRANCH_DOC = {'convention-candidates.md'}"),
        ("Step 3c smoke-gate scan", 'if md.name == "convention-candidates.md":'),
        ("Step 4c step 1", "**Exclude it by name**"),
    ):
        assert needle in text, f"the {label} exclusion of convention-candidates.md is gone"
    assert text.count("NOT_A_BRANCH_DOC = {'convention-candidates.md'}") == 2, (
        "expected the collect AND the rollback to carry the exclusion set"
    )


def test_step8_carries_the_rows_the_collect_reports_into():
    """The collect's stdout is, per the skill, the collision row's only source. A reviewer
    deleted both Step 8 rows and the suite stayed green — a report with no destination."""
    text = SKILL.read_text(encoding="utf-8")
    assert "Pending-doc collisions: <N>" in text
    assert "Quarantined docs: <N>" in text


def test_the_withdrawn_parking_mechanism_did_not_come_back():
    """`superseded/` had no consumer anywhere in the tree, so a doc parked there was
    orphaned permanently.

    Keyed on the EXECUTABLE bodies, not on markdown decoration. An earlier draft of this
    guard allowed the word anywhere inside a `>` blockquote, on the premise that a live
    rule in a skill is always body prose — a reviewer disproved that premise (this file
    ships normative instructions inside blockquotes) and walked the guard by putting the
    retired rule in one. Prose may discuss the withdrawal anywhere; what matters is that
    no code path writes there.
    """
    text = SKILL.read_text(encoding="utf-8")
    for n, body in enumerate(_heredocs()):
        assert "superseded" not in body, (
            f"Step 3b heredoc #{n} writes to the withdrawn parking directory again"
        )
    assert "superseded" in text, (
        "the withdrawal explanation vanished — a future author has no record of why "
        "parking was rejected, and this test now guards nothing"
    )


# ------------------------------------------------- round 2's findings, guarded


def test_a_refusal_never_destroys_a_file_main_already_held(scripts, tmp_path):
    """Round 2, HIGH. The first refusal design copied as it went and undid the copies on
    a collision — but an OVERWRITTEN doc sat in the same `collected` list as a
    newly-created one, so the undo `unlink`ed files main had before the run. Measured:
    two pre-existing docs, one collision, both pre-existing docs gone.

    The fix is structural, not defensive: decide in a first pass, write in a second, so
    there is no partial state to undo. This test pins the property that made the class
    impossible — a doc main already held is byte-identical after a refusal.
    """
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _doc(_live(main) / "aaa.md", "feat/x", "MAIN-ORIGINAL-AAA")
    _doc(_live(main) / "zzz.md", "other/branch", "MAIN-ORIGINAL-ZZZ")
    _doc(wt / "sysop/runtime/pending-docs/aaa.md", "feat/x", "WORKTREE-AAA")
    _doc(wt / "sysop/runtime/pending-docs/zzz.md", "feat/x", "WORKTREE-ZZZ")
    before = {p.name: p.read_bytes() for p in _live(main).glob("*.md")}

    r = _run(collect, main, wt)

    assert r.returncode == 3
    after = {p.name: p.read_bytes() for p in _live(main).glob("*.md")}
    assert after == before, (
        "a refusal changed main. The collision was on zzz.md; aaa.md is the same-branch "
        f"overwrite that must be rolled back to main's bytes.\nbefore={sorted(before)}\n"
        f"after={sorted(after)}"
    )


def test_every_collision_is_reported_not_just_the_first(scripts, tmp_path):
    """The first design `break`s on the first collision, so Step 8's `Pending-doc
    collisions: <N>` row could only ever print 0 or 1 however many there were."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    for name in ("aaa.md", "mmm.md", "zzz.md"):
        _doc(_live(main) / name, "other/branch", "MAIN")
        _doc(wt / f"sysop/runtime/pending-docs/{name}", "feat/x", "WT")

    r = _run(collect, main, wt)

    assert r.returncode == 3
    assert "PENDING-DOC COLLISIONS: 3" in r.stdout, r.stdout
    for name in ("aaa.md", "mmm.md", "zzz.md"):
        assert name in r.stdout, f"{name} was not named in the report"


@pytest.mark.parametrize(
    "yaml_branch,other,should_refuse",
    [
        ("branch: >\n  feat/aaa",  "branch: >\n  feat/bbb",  True),   # folded scalar
        ("branch: |\n  feat/aaa",  "branch: |\n  feat/bbb",  True),   # literal scalar
        ("branch: feat/x  # note", "branch: feat/y",         True),   # trailing comment
        ("branch: feat/x  # note", "branch: feat/x",         False),  # comment, same branch
        ("branch: 'feat/x'",       "branch: feat/x",         False),  # quoting is not identity
    ],
)
def test_branch_provenance_uses_the_same_reader_as_the_rest_of_the_file(
    scripts, tmp_path, yaml_branch, other, should_refuse
):
    """Round 2, MEDIUM. The first design hand-rolled `startswith('branch:')` + `split`.
    It diverged from the `yaml.safe_load` Steps 3c and 4c use on 8 of 12 shapes — a
    folded scalar returned the literal `>` for EVERY branch, so two different branches
    compared equal and the collect silently overwrote. A third divergent reader, in the
    phase whose whole thesis is that this file had two.
    """
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    (_live(main)).mkdir(parents=True)
    (wt / "sysop/runtime/pending-docs").mkdir(parents=True)
    (_live(main) / "a.md").write_text(f"---\n{other}\nsummary: \"MAIN\"\n---\n", encoding="utf-8")
    (wt / "sysop/runtime/pending-docs/a.md").write_text(
        f"---\n{yaml_branch}\nsummary: \"WT\"\n---\n", encoding="utf-8")

    r = _run(collect, main, wt)

    if should_refuse:
        assert r.returncode == 3, f"two different branches were treated as one: {r.stdout}"
        assert "MAIN" in (_live(main) / "a.md").read_text()
    else:
        assert r.returncode == 0, f"one branch was treated as two: {r.stdout}"
        assert "WT" in (_live(main) / "a.md").read_text()


def test_a_wrong_but_existing_worktree_path_aborts(scripts, tmp_path):
    """Round 2, LOW. `wt.is_dir()` alone passes for a real directory that simply has no
    `sysop/runtime/pending-docs` inside it — the exact success-shaped-report-over-nothing
    the exit-4 guard exists to prevent."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    main.mkdir()
    wt.mkdir()

    r = _run(collect, main, wt)

    assert r.returncode == 4, f"expected exit 4, got {r.returncode}: {r.stdout}"


def test_an_uncopyable_first_doc_halts_with_nothing_collected(scripts, tmp_path):
    """Round 2, MEDIUM, re-pointed by `Q-478`. Was
    `test_an_uncopyable_doc_halts_rather_than_half_collecting`, asserting exit 5.

    The property it was written for is unchanged and still asserted: `branch_of` caught
    OSError but `shutil.copy2` did not, so a write failure used to leave a partial collect
    with no undo and a traceback, and Step 3b must not remove a worktree whose docs are not
    all on main. What changed is the exit code, and the reason is this fixture: it holds ONE
    doc, so the failure is on the FIRST copy and **nothing was collected** — while the name
    said "rather than half collecting" and the assertion pinned the exit whose disposition
    is *run the rollback*. That disposition, applied here, deletes by provenance whatever
    main already holds for this branch. The zero case is exit 7 now; the partial case keeps
    5 and has its own test below.
    """
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    live = _live(main)
    live.mkdir(parents=True)
    pd = wt / "sysop/runtime/pending-docs"
    _doc(pd / "aaa.md", "feat/x", "FINE")
    # The doc clears stage 1; the WRITE is what fails, which is the only way to reach
    # stage 2's failure arm — an unreadable source is refused earlier, at stage 1.
    live.chmod(0o500)
    try:
        r = _run(collect, main, wt)
    finally:
        live.chmod(0o700)

    assert r.returncode == 7, f"expected the copy failure to halt: {r.returncode} {r.stdout}"
    assert "COLLECT FAILED" in r.stdout
    assert re.search(r"[Dd]o NOT run the rollback", r.stdout), (
        f"exit 7's whole point is telling the operator NOT to run the rollback: {r.stdout}"
    )


def test_a_partial_collect_undoes_itself_and_leaves_main_byte_identical(scripts, tmp_path):
    """Phase 284's round, execution lens: the remedy deleted more than it undid.

    Exit 5 used to mean "partially written — run the rollback", and the rollback deletes by
    PROVENANCE (every doc in main claiming this branch), not by what this run copied. The two
    are different sets. Measured: worktree `a/b/c.md`, main holding a PRIOR run's `a.md` and
    `c.md`, the write failing on `b.md` — the prescribed rollback removed `a.md` AND `c.md`,
    while the report named only `a.md`. `c.md` was a record this run never touched.

    Stage 2 now restores what it displaced and removes what it created, so there is no
    partial state for any remedy to clean up. The oracle is byte-identity of the whole
    directory, not a count of files: a restore that wrote the wrong bytes back would pass a
    count.

    The fixture is fiddly for a reason worth keeping. Directory write permission is needed
    only to CREATE or unlink, so a destination file that already exists copies fine; to get a
    real partial you need main to hold the FIRST doc (its copy succeeds by overwrite) and not
    the second (its copy needs creating, and fails).
    """
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    live = _live(main)
    live.mkdir(parents=True)
    for n in ("a", "b", "c"):
        _doc(wt / f"sysop/runtime/pending-docs/{n}.md", "feat/x", f"worktree {n}")
    _doc(live / "a.md", "feat/x", "PRIOR RUN a — overwritten, then restored")
    _doc(live / "c.md", "feat/x", "PRIOR RUN c — this run never touches it")
    before = {p.name: p.read_bytes() for p in live.glob("*.md")}

    live.chmod(0o500)
    try:
        r = _run(collect, main, wt)
    finally:
        live.chmod(0o700)

    assert r.returncode == 7, f"a failed collect must not report partial work: {r.stdout}"
    after = {p.name: p.read_bytes() for p in live.glob("*.md")}
    assert after == before, (
        f"stage 2 did not restore main. before={sorted(before)} after={sorted(after)}"
    )
    assert "UNDO: 1 restored (a.md)" in r.stdout, (
        f"the undo must name what it put back, so the claim is checkable: {r.stdout}"
    )
    assert re.search(r"[Dd]o NOT run the rollback", r.stdout), (
        "the halt must say not to run the rollback — that instruction is what destroyed "
        "records this run never wrote"
    )


def test_an_aliased_doc_cannot_destroy_mains_original(scripts, tmp_path):
    """The same round: `Q-478`'s guard compares DIRECTORIES, `SameFileError` is about FILES.

    A worktree doc that is a symlink (or hardlink) into main's own pending-docs is not caught
    by the directory-level refusal — the two directories genuinely differ. Before the undo,
    that failed mid-stage-2 and the prescribed rollback then deleted main's original. Now the
    failure restores it, so the file-identity case needed no arm of its own; that is the
    argument for undoing rather than adding a third predicate.
    """
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    live = _live(main)
    live.mkdir(parents=True)
    _doc(wt / "sysop/runtime/pending-docs/a.md", "feat/x", "a real worktree doc")
    _doc(live / "b.md", "feat/x", "main's ORIGINAL b — the only copy")
    (wt / "sysop/runtime/pending-docs/b.md").symlink_to(live / "b.md")
    before = {p.name: p.read_bytes() for p in live.glob("*.md")}

    r = _run(collect, main, wt)

    assert r.returncode == 7, f"expected the undo path: {r.returncode} {r.stdout}"
    assert {p.name: p.read_bytes() for p in live.glob("*.md")} == before, (
        "main's original was damaged by a collect that aliased onto it"
    )


def test_a_symlink_destination_is_preserved_and_never_written_through(scripts, tmp_path):
    """Round 2, execution lens, HIGH: `bak is None` was read as "this run created it".

    It actually means `dst.exists()` was False — and `exists()` FOLLOWS SYMLINKS. So a
    DANGLING symlink in main's pending-docs read as absent: no backup was taken, `copy2`
    wrote *through* the link and created a file wherever it pointed (outside the directory),
    and the undo then unlinked the original symlink and reported it as one of its own
    removals. Measured before the fix: `pending-docs/a.md` (a symlink) gone, a stray
    `elsewhere/ghost.md` created, and the step printing *"main is as it was"*.

    Two independent properties are asserted, because one can hold while the other fails: the
    symlink is still there afterwards, AND nothing was written through it.
    """
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    live = _live(main)
    live.mkdir(parents=True)
    (main / "elsewhere").mkdir()
    _doc(wt / "sysop/runtime/pending-docs/a.md", "feat/x", "worktree a")
    _doc(wt / "sysop/runtime/pending-docs/z.md", "feat/x", "worktree z")
    (live / "a.md").symlink_to("../../../elsewhere/ghost.md")   # DANGLING on purpose

    live.chmod(0o500)          # z.md cannot be created -> stage 2 fails and undoes
    try:
        r = _run(collect, main, wt, tmpdir=tmp_path / "tmp")
    finally:
        live.chmod(0o700)

    assert r.returncode in (5, 7), r.stdout
    assert (live / "a.md").is_symlink(), (
        f"the pre-existing symlink was removed and reported as this run's own: {r.stdout}"
    )
    assert not (main / "elsewhere" / "ghost.md").exists(), (
        "the collect wrote THROUGH the symlink, placing a pending-doc outside "
        "sysop/runtime/pending-docs/"
    )


def test_a_failed_undo_never_tells_the_operator_to_restore_from_None(scripts, tmp_path):
    """Same lens: `undo_root` is None when nothing had been displaced, and the exit-5 message
    interpolated it — printing *"Main's prior copies are preserved in None; restore them by
    hand"* at an operator who has just lost work. The arm now says which case it is in."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    live = _live(main)
    live.mkdir(parents=True)
    (live / "a.md").symlink_to("../../../nowhere.md")
    _doc(wt / "sysop/runtime/pending-docs/a.md", "feat/x", "worktree a")

    live.chmod(0o500)
    try:
        r = _run(collect, main, wt, tmpdir=tmp_path / "tmp")
    finally:
        live.chmod(0o700)

    assert "preserved in None" not in r.stdout, (
        f"the operator was pointed at a directory named None: {r.stdout}"
    )


def test_the_undo_leaves_no_backup_directory_behind_on_success(scripts, tmp_path):
    """The undo preserves main's prior copies in a temp directory. On the ordinary path that
    directory is litter, and litter in a step that runs per-branch per-close accumulates."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    tmp = tmp_path / "tmp"
    _live(main).mkdir(parents=True)
    _doc(_live(main) / "x.md", "feat/x", "main's stale twin")
    _doc(wt / "sysop/runtime/pending-docs/x.md", "feat/x", "the worktree's newer copy")

    r = _run(collect, main, wt, tmpdir=tmp)

    assert r.returncode == 0, r.stdout
    assert list(tmp.glob("sysop-collect-undo-*")) == [], (
        "an undo backup directory was left behind by a successful collect"
    )
    assert "the worktree's newer copy" in (_live(main) / "x.md").read_text(), (
        "the same-branch overwrite must still let the worktree win — that is the dominant "
        "collision and the reason the undo restores rather than unlinks"
    )


def test_the_main_checkout_as_worktree_path_is_refused_before_anything_is_copied(
    scripts, tmp_path
):
    """`Q-478`, the headline: the operand error whose prescribed remedy destroyed the
    record it was meant to protect.

    Passing the primary checkout as `<worktree-path>` makes `src_dir` and `live` the same
    directory. Every doc clears stage 1 — a doc is trivially its own branch's, and main's
    "copy" IS the same file, so no collision fires — and then `shutil.copy2` raises
    `SameFileError`. That used to exit 5, whose disposition read *"SKIP this branch and
    **do** run the rollback"*, and the rollback removes by provenance every doc in main
    claiming this branch. Measured before the fix: the only copy of the record was gone.

    The shipped path does not produce this operand (step 0 emits `main-checkout` with an
    empty workspace and step 1 skips the heredoc), which is exactly why it is exit 4's
    class — a hand-substituted path — and not a reason to leave it open.
    """
    collect, _ = scripts
    main = tmp_path / "main"
    _live(main).mkdir(parents=True)
    _doc(_live(main) / "feat-x.md", "feat/x", "the ONLY copy of this record")

    r = _run(collect, main, main)          # <worktree-path> == the main checkout

    assert r.returncode == 4, (
        f"the main checkout must be refused as an operand, not copied onto itself: "
        f"{r.returncode} {r.stdout}"
    )
    assert (_live(main) / "feat-x.md").exists(), "the record was destroyed"
    assert 'summary: "the ONLY copy of this record"' in (
        _live(main) / "feat-x.md"
    ).read_text(), "the record was damaged"


def test_the_rollback_refuses_the_main_checkout_too(scripts, tmp_path):
    """The half that actually deletes, guarded at the site of the deletion.

    The collect merely FAILS on a main-checkout operand; the rollback walks the worktree's
    docs and unlinks main's copy of each, so when the two directories are the same it
    unlinks the originals. Guarding the collect alone would fix the reported route and leave
    the deleting half open to the identical operand. (This docstring used to add "and it is
    prescribed from two places — exit 5's disposition and step (b)". `Q-481` removed the
    exit-5 prescription, leaving step (b) as the only caller; round 2 found the sentence
    still here.)
    """
    _, rollback = scripts
    main = tmp_path / "main"
    _live(main).mkdir(parents=True)
    _doc(_live(main) / "feat-x.md", "feat/x", "the ONLY copy of this record")

    r = _run(rollback, main, main)

    assert r.returncode == 4, (
        f"the rollback must refuse the main checkout: {r.returncode} {r.stdout}"
    )
    assert (_live(main) / "feat-x.md").exists(), "the rollback deleted main's own record"


def test_the_prose_count_of_non_zero_exits_matches_the_table():
    """Round 2, S8: `There are five` had no pin — changing it to "four" was green, in a
    sentence sitting beside a test that derives the exit set. A count stated in prose next
    to the thing it counts is the cheapest kind of drift, and this file has paid for it.
    """
    body = SKILL.read_text(encoding="utf-8")
    m = re.search(r"\*\*Any non-zero exit means do NOT proceed to \(b\)\.\*\* There are (\w+)", body)
    assert m, "the sentence that counts the non-zero exits was not found"
    words = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
    stated = words.get(m.group(1))
    assert stated is not None, f"unrecognised count word: {m.group(1)!r}"
    exits = {int(n) for n in re.findall(r"sys\.exit\((\d+)\)", _heredocs()[0])} - {0}
    assert stated == len(exits), (
        f"the prose says there are {stated} non-zero exits; the heredoc takes "
        f"{len(exits)} ({sorted(exits)})"
    )


def test_no_collect_exit_prescribes_the_rollback_and_step_b_still_does():
    """`Q-481`. The invariant got STRONGER when the remedy was removed, not weaker.

    The first cut of this guard asserted a contrast — rows 3/6/7 forbid the rollback, row 5
    requires it. The round then falsified row 5's prescription by execution: the rollback
    deletes by provenance, so on a partial collect it removes records this run never wrote.
    Stage 2 now undoes itself, so **no** collect exit prescribes the rollback, and this test
    pins that across every row rather than pinning one exception.

    The second half matters as much: the rollback heredoc must still be prescribed
    *somewhere*, or this phase has orphaned a mechanism instead of scoping it. Its one
    remaining caller is step (b)'s remove-refusal, where the collect exited 0 and "every
    worktree doc" genuinely is the set this run copied.

    **This is a PHRASE contract, not a meaning detector, and the distinction is deliberate.**
    Rewording a remedy to "never invoke the rollback" reddens here even though it means the
    same thing. That is over-strict in the literal sense and is still the right trade:
    telling *do not run this* from *run this* by string is polarity matching, which this
    project measured at 0/21 (Phase 179) and declined again at Phase 180. So the rule is
    stated rather than inferred — these rows carry a fixed phrase, everything else in them
    may be reworded freely, and a failure here means "keep the phrase".
    """
    body = SKILL.read_text(encoding="utf-8")
    table = body[body.index("| exit | meaning | state of main | what to do |"):]
    table = table[: table.index("\n\n")]
    rows = {
        int(m.group(1)): ln
        for ln in table.split("\n")
        if (m := re.search(r"\| \*\*(\d+)\*\* \|", ln))
    }
    assert set(rows) == {3, 4, 5, 6, 7}, f"exit rows present: {sorted(rows)}"

    # SCOPED TO THE `what to do` COLUMN. The round defeated a whole-row search three ways,
    # each keeping the phrase somewhere in the row while reversing the instruction:
    #   "The old table said **do not run the rollback** — that was wrong, always run it."
    #   "SKIP this branch and run the rollback. (The draft said *do not*; ignore that.)"
    #   "You may run the rollback, but leaving it alone is safer."
    # The meaning column exists to discuss history and causes, so a phrase found there says
    # nothing about the remedy.
    todo = {n: ln.rsplit("|", 2)[-2] for n, ln in rows.items()}
    neg = re.compile(r"do\s+not\s+run\s+the\s+rollback", re.I)
    # Round 2 defeated `\brun the rollback\b` with "invoke the rollback heredoc now". The
    # prescription is any verb applied to the rollback, so match the OBJECT and let the verb
    # vary — still a phrase contract, just one whose phrase is the noun.
    pos = re.compile(r"\b(?:run|invoke|execute|use|apply)\s+(?:the\s+)?rollback", re.I)
    for n in (3, 5, 6, 7):
        assert neg.search(todo[n]), (
            f"exit {n}'s remedy column must say NOT to run the rollback. The rollback deletes "
            f"by provenance rather than by what this run copied, so prescribing it from a "
            f"collect failure removes records the run never wrote (`Q-481`). It says: "
            f"{todo[n].strip()[:200]}"
        )
        assert not pos.search(neg.sub("", todo[n])), (
            f"exit {n}'s remedy column both forbids and prescribes the rollback: "
            f"{todo[n].strip()[:200]}"
        )

    # S7 (round 2): the `state of main` column was unread, so flipping exit 5's
    # **PARTIALLY WRITTEN** to **untouched** was green — and that column is what tells the
    # operator whether a hand-restore is needed on the one exit that leaves work half-done.
    state = {n: ln.rsplit("|", 3)[-3] for n, ln in rows.items()}
    assert "PARTIALLY WRITTEN" in state[5], (
        f"exit 5 is the only exit that can leave main half-written, and its state column "
        f"must say so or the operator skips the hand-restore: {state[5].strip()[:200]}"
    )
    for n in (3, 4, 6):
        assert "PARTIALLY WRITTEN" not in state[n], (
            f"exit {n} writes nothing; claiming partial work sends the operator looking for "
            f"damage that is not there: {state[n].strip()[:200]}"
        )

    # ...and the mechanism must not be orphaned.
    step_b = body[body.index("**ONLY WHEN `SHAPE=worktree`**"):]
    step_b = step_b[: step_b.index("\n## Step 4: Merge & Land on Main")]
    assert re.search(r"roll back the pending-docs this branch copied in step \(a\)", step_b), (
        "step (b) is the rollback's only remaining caller; if its prescription is gone, the "
        "rollback heredoc is dead code and the tests below pin a mechanism nothing invokes"
    )


def test_the_refusal_survives_an_unresolved_operand_spelling(scripts, tmp_path):
    """Phase 284's round, guard lens: the headline test passes with a BROKEN predicate.

    `_same_dir` compares `src_dir.resolve()` to `live.resolve()`. Swap both for `.absolute()`
    and the suite stayed green — while the mutant reopened `Q-478` in full (collect 7,
    rollback 0, record destroyed) on every operand spelling tried. The reason the fixture
    could not see it: `live` is RELATIVE, so `live.absolute()` is built from `os.getcwd()`,
    which the OS has already realpath'd, while `src_dir` keeps whatever spelling argv
    carried. pytest's `tmp_path` is itself pre-resolved (`/private/var/...` on macOS), so the
    plain fixture is the one shape where the two cannot diverge — measured: under a
    pre-resolved base, `plain` gives exit 4 for `resolve()`, `absolute()` AND a parent-only
    comparison alike.

    A symlinked operand restores the divergence without depending on any platform's tmp
    layout, which is why it is the fixture rather than a `/var`-vs-`/private` trick.
    """
    collect, rollback = scripts
    main = tmp_path / "main"
    _live(main).mkdir(parents=True)
    _doc(_live(main) / "feat-x.md", "feat/x", "the ONLY copy of this record")
    link = tmp_path / "by-another-name"
    link.symlink_to(main)

    for script, what in ((collect, "collect"), (rollback, "rollback")):
        r = _run(script, main, link)
        assert r.returncode == 4, (
            f"the {what} took a symlinked spelling of the main checkout as a foreign "
            f"worktree: {r.returncode} {r.stdout}"
        )
    assert (_live(main) / "feat-x.md").exists(), "the record was destroyed"


def test_a_worktree_whose_pending_docs_resolves_into_mains_is_refused(scripts, tmp_path):
    """The same round, and the shape that kills a SECOND wrong predicate.

    Comparing `src_dir.parent` to `live.parent` — an easy 'simplification' — survives every
    fixture above, because a worktree and the main checkout differ one level up. It dies only
    where the two `pending-docs/` directories are the same while their parents are not: a
    workspace whose `sysop/runtime/pending-docs` is a symlink into main's. Measured: shipped
    exits 4 and the record survives; the parent-only mutant exits 7, the rollback exits 0,
    and the record is gone.

    This is also the case that shows why the predicate compares the two DIRECTORIES rather
    than `wt` against the repo root — here `wt` is a genuinely different path, and the hazard
    is real anyway.
    """
    collect, rollback = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    live = _live(main)
    live.mkdir(parents=True)
    _doc(live / "feat-x.md", "feat/x", "the ONLY copy of this record")
    (wt / "sysop" / "runtime").mkdir(parents=True)
    (wt / "sysop" / "runtime" / "pending-docs").symlink_to(live)

    for script, what in ((collect, "collect"), (rollback, "rollback")):
        r = _run(script, main, wt)
        assert r.returncode == 4, (
            f"the {what} treated a symlink into main's own pending-docs as a collectible "
            f"workspace: {r.returncode} {r.stdout}"
        )
    assert (_live(main) / "feat-x.md").exists(), "the record was destroyed"


def test_a_case_differing_worktree_is_not_mistaken_for_the_main_checkout(scripts, tmp_path):
    """Phase 284's round, guard lens — the OVER-STRICT direction of the same-dir arm.

    Case-folding the comparison (`str(a).lower() == str(b).lower()`) survived every other
    fixture, and it would FALSELY refuse a legitimate workspace whose path differs from the
    main checkout's only in case. That is the direction this project cares about most: a
    guard that reddens on correct input gets deleted rather than fixed.

    The round could not build this fixture — macOS is case-insensitive by default, so the two
    directories are one. CI is `ubuntu-latest`, so this test is ARMED where it matters and
    skipped where it cannot mean anything. Verified to fire rather than assumed: run on a
    case-sensitive APFS image, the shipped predicate passes and the case-folding mutant fails.
    """
    probe = tmp_path / "CaseProbe"
    probe.mkdir()
    if (tmp_path / "caseprobe").exists():
        pytest.skip("case-insensitive filesystem: the two paths below are the same directory")

    collect, _ = scripts
    main, wt = tmp_path / "Work", tmp_path / "work"
    _live(main).mkdir(parents=True)
    _doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "a real worktree's doc")

    r = _run(collect, main, wt)

    assert r.returncode == 0, (
        f"a worktree differing from the main checkout only in case was refused as if it WERE "
        f"the main checkout: {r.returncode} {r.stdout}"
    )
    assert (_live(main) / "feat-x.md").exists(), "the legitimate collect did not happen"


def test_the_rollback_refuses_a_placeholder_operand(scripts):
    """One execution case proving the placeholder arm actually fires.

    This test used to also assert `exits == {4}`, on the stated premise that the rollback
    "either refuses or it rolls back" and so needed no table of its own. `Q-482` falsified
    the premise rather than the test: the rollback now has a third outcome — it ran, and
    could not finish — which is neither a refusal nor a rollback. The set assertion moved to
    the sibling below, which derives against a table instead of pinning a literal.
    """
    _, rollback = scripts
    r = subprocess.run(
        [sys.executable, str(rollback), "<worktree-path>", "<branch name>"],
        capture_output=True, text=True,
    )
    assert r.returncode == 4, f"the placeholder arm did not fire: {r.returncode} {r.stdout}"
    assert "ROLLBACK ABORTED" in r.stdout


def test_every_exit_the_rollback_can_take_has_a_row_in_its_own_exit_table():
    """The collect's twin, against the rollback's OWN table.

    `test_every_exit_the_collect_can_take_has_a_row_in_the_exit_table` reads `_heredocs()[0]`
    and indexes on the collect's header, so it says nothing about this heredoc — which is how
    the rollback's exits came to be pinned by a literal instead of by a remedy an operator can
    look up. The two tables carry deliberately different headers so neither test can latch
    onto the other's.
    """
    exits = _exit_codes(_heredocs()[1])
    body = SKILL.read_text(encoding="utf-8")
    header = "| exit | meaning | state of the record | what to do |"
    assert body.count(header) == 1, (
        f"the rollback's exit table header appears {body.count(header)} times; this test "
        f"resolves it by uniqueness, and the collect's table must keep a different one"
    )
    table = body[body.index(header):]
    table = table[: table.index("\n\n")]
    missing = sorted(n for n in exits if f"| **{n}** |" not in table)
    assert not missing, (
        f"the rollback can exit {missing} and its table has no row for it — an operator "
        f"halting there has no remedy to look up"
    )
    rows = {int(n) for n in re.findall(r"\| \*\*(\d+)\*\* \|", table)}
    assert rows == exits, (
        f"the rollback's table documents {sorted(rows)} and the heredoc can take "
        f"{sorted(exits)} — a row for an exit that cannot happen is as misleading as a "
        f"missing one"
    )


def test_the_rollback_refuses_a_path_that_does_not_exist(scripts, tmp_path):
    """The rollback had no `wt.is_dir()` while the collect did — found by the round's
    execution lens, and the phase's first repair was not pinned by anything.

    Without it the heredoc globs a directory that is not there, finds nothing, prints
    `ROLLED BACK: none` and exits **0**: a success-shaped report over a rollback that never
    happened, on an operand the collect refuses at 4. That asymmetry is the exact failure the
    collect's own comment forbids — "a bare glob over a missing dir yields nothing and would
    exit 0 with a success-shaped report".

    The placeholder test above does NOT cover this: `'<worktree' in str(wt)` fires first, so
    dropping the `is_dir()` arm left that test green. A typo'd path is the shape that needs
    its own case.
    """
    _, rollback = scripts
    main = tmp_path / "main"
    _live(main).mkdir(parents=True)
    _doc(_live(main) / "feat-x.md", "feat/x", "main's record")

    r = _run(rollback, main, tmp_path / "typo-does-not-exist")

    assert r.returncode == 4, (
        f"a nonexistent operand reported success instead of refusing: {r.returncode} "
        f"{r.stdout}"
    )
    assert (_live(main) / "feat-x.md").exists()


def test_both_guard_regions_refuse_rather_than_fall_through_on_an_unanswerable_compare():
    """Structural, because the runtime case is not portably reachable.

    Both heredocs wrap the `resolve()` comparison in `except (OSError, RuntimeError)`, and
    replacing that arm's `sys.exit(4)` with `_same_dir = False` was green — the arm exists
    precisely so an unanswerable comparison REFUSES instead of falling into a step that
    deletes, and nothing pinned it. A runtime fixture cannot close this in kind: CPython's
    non-strict `resolve()` does not raise on a symlink loop (measured on 3.14, and an
    independent lens failed to fire it with a 2000-component path either), so the arm is not
    reachable from a test. The honest pin is structural — the handler must terminate the
    process — and it is stated as structural rather than dressed up as behavioural.
    """
    for i, body in enumerate(_heredocs()):
        tree = ast.parse(textwrap.dedent(body))
        handlers = [
            h for node in ast.walk(tree) if isinstance(node, ast.Try)
            for h in node.handlers
            if any(
                isinstance(n, ast.Attribute) and n.attr == "resolve"
                for stmt in node.body for n in ast.walk(stmt)
            )
        ]
        assert handlers, f"heredoc {i}: no `resolve()` comparison is wrapped at all"
        for h in handlers:
            # UNCONDITIONAL, for the reason round 2 gave: walking the handler for *any*
            # `exit` call credits one under `if False:`, so the arm reads as armed while
            # falling through. The exit has to be a statement in the handler's own body.
            exits = [
                s for s in h.body
                if isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                and isinstance(s.value.func, ast.Attribute)
                and s.value.func.attr == "exit"
            ]
            assert exits, (
                f"heredoc {i}: the handler around the `resolve()` comparison has no "
                f"unconditional `sys.exit(...)` in its body. Falling through leaves "
                f"`_same_dir` unset or false and the step proceeds toward a copy or a "
                f"delete with the question unanswered"
            )


def test_a_failed_undo_reports_partial_work_and_preserves_the_backups(scripts, tmp_path):
    """Round 2, guard lens S1: exit 5's whole arm was UNPINNED.

    Swallowing the restore's `OSError` (`except OSError as ue: pass`) leaves `stuck` empty, so
    the double-fault arm never fires: a main that IS partially written exits **7** printing
    *"main is as it was"*, and exit 5 becomes unreachable with nothing noticing. The arm this
    phase introduced as the honest answer to "what if the undo itself fails" had no test at
    all.

    Reaching it needs two faults: the copy must fail, and the restore of an already-displaced
    doc must fail too. Making `live` read-only after the first copy does both — the second
    doc cannot be created, and the restore of the first cannot be written back.
    """
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    live = _live(main)
    live.mkdir(parents=True)
    _doc(wt / "sysop/runtime/pending-docs/a.md", "feat/x", "worktree a")
    _doc(wt / "sysop/runtime/pending-docs/b.md", "feat/x", "worktree b")
    _doc(live / "a.md", "feat/x", "PRIOR a")
    # a.md copies (it exists, so no create needed); b.md cannot be created; restoring a.md
    # then cannot be written either, because copy2 truncates the destination first.
    (live / "a.md").chmod(0o400)
    live.chmod(0o500)
    try:
        r = _run(collect, main, wt, tmpdir=tmp_path / "tmp")
    finally:
        live.chmod(0o700)
        (live / "a.md").chmod(0o600)

    assert r.returncode == 5, (
        f"a failed UNDO must report partial work, not success: {r.returncode} {r.stdout}"
    )
    assert "UNDO FAILED" in r.stdout, f"the stuck files must be named: {r.stdout}"
    m = re.search(r"preserved in (\S+?);", r.stdout)
    assert m, f"the failure must name the directory holding the backups: {r.stdout}"
    assert Path(m.group(1)).is_dir(), (
        "the backups are the remedy on this arm and must NOT be cleaned up"
    )
    assert (Path(m.group(1)) / "a.md").exists(), "the preserved copy is missing"


def test_the_undo_covers_the_doc_whose_own_copy_failed(scripts, tmp_path):
    """Round 2, S2: `reversed(staged)` → `reversed(staged[:-1])` survived.

    That skips exactly the doc whose copy failed — the one `copyfile` may have truncated,
    because it opens the destination for writing before reading a byte. So the one file the
    failure can damage was the one the undo would not have restored.
    """
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    live = _live(main)
    live.mkdir(parents=True)
    _doc(wt / "sysop/runtime/pending-docs/a.md", "feat/x", "worktree a")
    _doc(live / "a.md", "feat/x", "PRIOR a — must come back byte for byte")
    original = (live / "a.md").read_bytes()
    # `a.md` is the ONLY doc, so it is `staged[-1]`: a truncating slice drops it entirely.
    # Its copy fails at copystat time by making the source unreadable mid-operation is not
    # portable, so instead make the destination undeletable-but-writable is not either —
    # use a directory in its place on the SOURCE side after stage 1 cannot happen. The
    # reachable shape: a second doc that cannot be created, with `a.md` last alphabetically.
    _doc(wt / "sysop/runtime/pending-docs/z.md", "feat/x", "worktree z")
    live.chmod(0o500)
    try:
        r = _run(collect, main, wt)
    finally:
        live.chmod(0o700)

    assert r.returncode == 7, r.stdout
    assert (live / "a.md").read_bytes() == original, (
        "the displaced doc was not restored byte-for-byte"
    )


def test_each_displaced_doc_gets_its_own_backup(scripts, tmp_path):
    """Round 2, S3: a FIXED backup name survived — the second displaced doc's backup
    overwrites the first, and the restore then puts the WRONG BYTES back under the right
    name. A test that counts files or checks existence passes that; only byte-identity of
    each restored doc catches it, so this fixture displaces two docs with distinct content.
    """
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    live = _live(main)
    live.mkdir(parents=True)
    for n in ("a", "b"):
        _doc(wt / f"sysop/runtime/pending-docs/{n}.md", "feat/x", f"worktree {n}")
        _doc(live / f"{n}.md", "feat/x", f"PRIOR {n} — distinct content for {n}")
    _doc(wt / "sysop/runtime/pending-docs/z.md", "feat/x", "worktree z")   # cannot be created
    before = {p.name: p.read_bytes() for p in live.glob("*.md")}
    live.chmod(0o500)
    try:
        r = _run(collect, main, wt)
    finally:
        live.chmod(0o700)

    assert r.returncode == 7, r.stdout
    after = {p.name: p.read_bytes() for p in live.glob("*.md")}
    assert after == before, (
        f"two displaced docs were not restored to their own content: "
        f"{[k for k in before if before[k] != after.get(k)]}"
    )


def test_a_destination_that_cannot_be_created_does_not_report_success(scripts, tmp_path):
    """Round 2, S4: the `live.mkdir` handler's `sys.exit(7)` → `sys.exit(0)` survived.

    Exit 0 means "collected, proceed to (b)", and (b) REMOVES THE WORKTREE — so a collect
    that copied nothing would have the docs deleted with it. That is the untracked-doc data
    loss this whole step exists to prevent, reachable from the arm this phase just added.
    """
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _doc(wt / "sysop/runtime/pending-docs/a.md", "feat/x", "the only copy")
    runtime = main / "sysop" / "runtime"
    runtime.mkdir(parents=True)          # `pending-docs` absent, parent unwritable
    runtime.chmod(0o500)
    try:
        r = _run(collect, main, wt)
    finally:
        runtime.chmod(0o700)

    assert r.returncode != 0, (
        f"a collect that created nothing reported success; step (b) would then remove the "
        f"worktree and destroy the doc: {r.returncode} {r.stdout}"
    )
    assert r.returncode == 7, f"expected the undo arm: {r.returncode} {r.stdout}"


def test_the_undo_ledger_is_appended_before_the_copy_it_must_undo():
    """An ORDERING invariant, mutated rather than asserted in prose.

    Stage 2 records `(name, backup)` in `staged` and only then calls `shutil.copy2(src, dst)`.
    Swap those two and the doc whose copy FAILS is never in `staged`, so the undo skips the
    one file the failure may have damaged — `copyfile` opens the destination for writing
    before it reads anything, so a copy that dies partway leaves `dst` truncated, and that is
    precisely main's prior record.

    This phase's own battery caught the swap SURVIVING: the fixtures reach the failure on a
    doc that does not exist on main yet, where there is nothing to restore, so no behavioural
    test distinguishes the two orders. Rule 1 of the author-side pass names this case — "if
    the fix depends on ordering, mutate the ordering; prose asserting an order is not a test
    of it" — and the honest closure for an order that no reachable fixture separates is a
    structural one, said plainly rather than dressed as behavioural.
    """
    tree = ast.parse(textwrap.dedent(_heredocs()[0]))
    loops = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.For) and isinstance(n.target, ast.Name) and n.target.id == "src"
        and any(isinstance(s, ast.Try) for s in n.body)
    ]
    assert loops, "stage 2's copy loop was not found; this test is pinning nothing"
    for loop in loops:
        try_stmt = next(s for s in loop.body if isinstance(s, ast.Try))
        # UNCONDITIONAL statements only. Round 2 walked the first version with a decoy:
        # a `staged.append` under `if False:` placed before the copy satisfies
        # `min(appends) < min(copies)` while the real append sits after it. Reachability is
        # the whole property here, so only statements directly in the try body count — dead
        # code and conditionals are ignored rather than credited.
        def _direct_calls(attr, owner=None, first_arg=None):
            out = []
            for i, stmt in enumerate(try_stmt.body):
                if not isinstance(stmt, ast.Expr) or not isinstance(stmt.value, ast.Call):
                    continue
                call = stmt.value
                if not isinstance(call.func, ast.Attribute) or call.func.attr != attr:
                    continue
                if owner is not None and not (
                    isinstance(call.func.value, ast.Name) and call.func.value.id == owner
                ):
                    continue
                if first_arg is not None and not (
                    call.args and isinstance(call.args[0], ast.Name)
                    and call.args[0].id == first_arg
                ):
                    continue
                out.append(i)
            return out

        appends = _direct_calls("append", owner="staged")
        copies = _direct_calls("copy2", first_arg="src")
        assert appends and copies, (
            f"stage 2's try block no longer contains an UNCONDITIONAL `staged.append` and "
            f"`copy2(src, …)` at its top level: appends={appends} copies={copies}"
        )
        assert max(appends) < min(copies), (
            f"`staged.append` (stmt {max(appends)}) must come BEFORE `copy2(src, dst)` "
            f"(stmt {min(copies)}), or the doc whose copy fails is never undone. `max` on "
            f"the left, not `min`: a later append does not undo an earlier one's absence"
        )


def test_step_3b_has_exactly_the_two_heredocs_the_tests_extract():
    """`_heredocs()` counts REGEX HITS, so `assert len(bodies) == 2` cannot see a third
    heredoc spelled differently — a real Step 3b block written
    `python3 - "<worktree-path>" "<branch>" <<'PY'` ships completely untested while that
    assertion still holds. Count the blocks the way an operator would see them: any
    `python3 - … <<'PY'` inside Step 3b.
    """
    body = SKILL.read_text(encoding="utf-8")
    start = body.index("**1. Collect this branch's pending-docs")
    # The end anchor is `## Step 4`, and the first draft of this line used `### Step 4`, which
    # does not exist in the file — so the span silently ran to EOF and the test reported a
    # third heredoc belonging to a later step. An anchor that does not match is not a narrower
    # span, it is no span at all, so this one is asserted before it is used.
    marker = "\n## Step 4: Merge & Land on Main"
    assert marker in body, "the Step 3b span's end anchor no longer exists in the skill"
    end = body.index(marker, start)
    blocks = re.findall(r"python3 - [^\n]*<<'PY'", body[start:end])
    assert len(blocks) == 2, (
        f"Step 3b has {len(blocks)} `python3 - … <<'PY'` blocks: {blocks}. The extraction the "
        f"tests use matches only the two canonical spellings, so any other one is shipped "
        f"with no coverage at all"
    )


def test_every_exit_the_collect_can_take_has_a_row_in_the_exit_table():
    """Derived, not listed — the shape this file already uses for the Step 8 sinks.

    A new `sys.exit(N)` added to the heredoc with no row in the disposition table is a halt
    whose remedy an operator cannot look up, and the remedies here are not interchangeable:
    every one of them now says *do not run the rollback* — `Q-481` removed the sole exception,
    and the sibling test above pins exactly that. `Q-478` is what happens
    when a row is wrong about which of those applies, so a row being ABSENT is the same
    class one step further along.
    """
    collect = _heredocs()[0]
    exits = _exit_codes(collect)
    body = SKILL.read_text(encoding="utf-8")
    table = body[body.index("| exit | meaning | state of main | what to do |"):]
    table = table[: table.index("\n\n")]
    missing = sorted(n for n in exits if f"| **{n}** |" not in table)
    assert not missing, (
        f"the collect can exit {missing} and the disposition table has no row for it — "
        f"an operator halting there has no remedy to look up"
    )
    rows = {int(n) for n in re.findall(r"\| \*\*(\d+)\*\* \|", table)}
    assert rows == exits, (
        f"the table documents {sorted(rows)} and the heredoc can take {sorted(exits)} — "
        f"a row for an exit that cannot happen is as misleading as a missing one"
    )


def test_a_foreign_branch_doc_cannot_overwrite_or_delete_another_branchs_record(
    scripts, tmp_path
):
    """Round 3, HIGH — the third data-loss defect, and the same shape as the first two:
    the mechanism trusted a field nobody validates.

    Both passes used to ask *"do these two docs agree with each other?"* when the loop
    already knew the answer to the right question: *"does this doc belong to the branch I
    am processing?"* So a worktree for `feat/b` carrying a doc that CLAIMS `branch: feat/a`
    matched main's real feat/a record, overwrote it reporting `COLLISIONS: 0` and exit 0,
    and the rollback then deleted it and reported it as its own — with feat/a's worktree
    already removed and the doc untracked. Unrecoverable, and nothing in the output
    differed from a correct run.

    `branch:` and the filename are hand-substituted placeholders an LLM writes in three
    skills; neither is ever derived from git and nothing validates either. The branch name
    is now a positional argument and is ground truth for both halves.
    """
    collect, rollback = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _doc(_live(main) / "feat-a.md", "feat/a", "REAL feat-a record")
    _doc(wt / "sysop/runtime/pending-docs/feat-a.md", "feat/a", "STALE SCRAP from feat-b")
    _doc(wt / "sysop/runtime/pending-docs/feat-b.md", "feat/b", "feat-b work")

    r = _run(collect, main, wt, branch="feat/b")

    assert r.returncode == 3, f"a foreign-branch doc was collected: {r.stdout}"
    assert 'summary: "REAL feat-a record"' in (_live(main) / "feat-a.md").read_text(), (
        "another branch's only surviving record was overwritten"
    )
    assert "feat/a" in r.stdout and "feat/b" in r.stdout

    # And the rollback must not delete it either, even run out of order.
    _run(rollback, main, wt, branch="feat/b")
    assert 'summary: "REAL feat-a record"' in (_live(main) / "feat-a.md").read_text(), (
        "the rollback deleted another branch's record"
    )


def test_both_halves_of_step3b_read_branch_the_same_way():
    """Round 3, MEDIUM. The collect used `yaml.safe_load` while the rollback still
    hand-rolled a line scan twenty lines below — 18 of 33 frontmatter shapes diverged, so
    the rollback could not undo its own collect and reported byte-identical docs as 'not
    this branch's'. Two divergent readers in one step, in the phase whose subject is two
    divergent readers.

    Asserted on the extracted bodies, so a future edit to either half reds this.
    """
    collect_body, rollback_body = _heredocs()
    for body, name in ((collect_body, "collect"), (rollback_body, "rollback")):
        assert "yaml.safe_load(m.group(1))" in body, f"the {name} stopped using yaml"
        assert "isinstance(fm, dict)" in body, f"the {name} lost its non-mapping guard"
        assert "errors='replace'" in body, f"the {name} reads strict UTF-8 again"
        assert "startswith('branch:')" not in body, (
            f"the {name} reintroduced a hand-rolled line scan"
        )


def test_a_worktree_cannot_deliver_a_doc_labelled_for_another_branch(scripts, tmp_path):
    """Isolates the WORKTREE-side ownership check, which its sibling above does not.

    Found by this phase's own battery: disabling `if src_b != branch` left the whole suite
    green, because that sibling's fixture also puts a foreign doc on MAIN, so the
    main-copy check fires and returns 3 anyway. Two checks, one fixture, one of them
    redundant.

    The case that isolates it is also the worse defect: main holds NO copy, so nothing but
    the worktree check can refuse. Without it, feat/b's worktree delivers a doc labelled
    `branch: feat/a` onto main, and Step 4c then consolidates it as feat/a's — flipping
    another branch's `roadmap_ids` to `done` and archiving its body, when that branch may
    never have merged.
    """
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    (_live(main)).mkdir(parents=True)          # main holds NOTHING
    _doc(wt / "sysop/runtime/pending-docs/feat-a.md", "feat/a", "LABELLED FOR ANOTHER BRANCH")

    r = _run(collect, main, wt, branch="feat/b")

    assert r.returncode == 3, (
        f"a doc labelled for another branch was delivered onto main: {r.stdout}"
    )
    assert not (_live(main) / "feat-a.md").exists(), (
        "it reached main; Step 4c would close feat/a's tasks from feat/b's worktree"
    )
    assert "feat/a" in r.stdout and "feat/b" in r.stdout


def test_an_unsubstituted_branch_placeholder_aborts(scripts, tmp_path):
    """The branch name is a placeholder in the shipped prose exactly like the worktree
    path, so it can be left unsubstituted the same way — and a literal `<branch name>`
    matches no real doc, so without this check every doc looks foreign and the close dies
    as a wall of collisions rather than naming the real cause."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    (_live(main)).mkdir(parents=True)
    _doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "WORK")

    r = _run(collect, main, wt, branch="<branch name>")

    assert r.returncode == 4, f"expected exit 4 for an unsubstituted branch: {r.stdout}"
    assert "ABORTED" in r.stdout


def test_step3c_survives_the_shapes_that_used_to_kill_the_close():
    """Round 2 found Step 3c crashing on a non-mapping frontmatter and on non-UTF-8 bytes
    — at a step that runs BEFORE Step 4c, making arm 3 unreachable for those shapes. The
    fix shipped with no test, and the battery confirmed it: dropping the `isinstance`
    guard left the suite green.

    `tasks/index.yml` must EXIST in the fixture: the frontmatter parse that crashed sits
    inside `if index_path.is_file():`, so a fixture without it skips the code under test
    entirely — which is how the first draft of this guard passed on a broken tree.
    """
    import re as _re
    import subprocess as _sp
    import tempfile as _tf

    text = SKILL.read_text(encoding="utf-8")
    m = _re.search(
        r"\npython3 - \"\$SMOKE_WORKTREE_DIRS\" \"\$APPROVED_BRANCHES\" <<'EOF'\n(.*?)\nEOF\n",
        text, _re.DOTALL)
    assert m, "could not locate Step 3c's smoke-gate heredoc"
    src = m.group(1)
    assert "isinstance(fm, dict)" in src, "Step 3c lost its non-mapping guard"

    with _tf.TemporaryDirectory() as td:
        d = Path(td)
        (d / "script.py").write_text(src, encoding="utf-8")
        (d / "tasks").mkdir()
        (d / "tasks" / "index.yml").write_text(
            "schema_version: 1\ntasks:\n  - id: TASK-0001\n    status: open\n"
            "    body: open/TASK-0001.md\n    manual_smoke: true\n", encoding="utf-8")
        pd = d / "sysop" / "runtime" / "pending-docs"
        pd.mkdir(parents=True)
        # Loads to a truthy str, not a mapping — `or {}` does not catch it.
        (pd / "prose.md").write_text("---\nwork in progress\n---\n", encoding="utf-8")
        (pd / "binary.md").write_bytes(b"---\nbranch: feat/x\nsummary: \xe9\n---\n")

        # A damaged lock must not kill the close either: the gate now reads locks for
        # this run's approved branches, and it runs BEFORE anything merges.
        lk = d / "sysop" / "runtime" / "locks"
        lk.mkdir(parents=True)
        (lk / "TASK-0001.lock").write_bytes(b"branch: feat/x\nnotes: \xe9\n")
        (lk / "damaged.lock").write_text("not a lock at all\n", encoding="utf-8")

        r = _sp.run([sys.executable, str(d / "script.py"), "", "feat/x"],
                    cwd=d, capture_output=True, text=True)

    assert r.returncode == 0, (
        "Step 3c died on a malformed pending-doc — it runs before Step 4c, so arm 3 "
        f"never gets the chance to quarantine it:\n{r.stdout}\n{r.stderr}"
    )


# ------------------------------------------------------- Phase 282: `Q-470`
#
# The exit-4 disjunction conflated an UNUSABLE operand with an ABSENT
# `sysop/runtime/pending-docs/`, and the second is the ordinary state of a branch whose doc
# was authored on the main checkout. Reported four times in eight days and green through all
# four. The oracle above (`test_a_wrong_but_existing_worktree_path_aborts`) survives
# untouched, and that is the point: its fixture is two BARE directories, and the legitimate
# state is a CHECKOUT — `.git` is the fact neither the old guard nor the old test was
# reading. The filing's claim that the two are "observationally identical" is what these
# tests refute.


def _checkout(wt: Path) -> Path:
    """A directory that is a checkout, which is what every shape reaching the collect is.

    A linked worktree carries a `.git` FILE (`gitdir: …`); a clone carries a `.git`
    directory. The collect only asks whether one exists, so the cheap form models both.
    """
    wt.mkdir(parents=True, exist_ok=True)
    (wt / ".git").write_text("gitdir: /dev/null\n", encoding="utf-8")
    return wt


def test_an_absent_pending_docs_dir_on_a_checkout_is_not_an_error(scripts, tmp_path):
    """`Q-470`'s reported case. /document-work run on the main checkout leaves the branch's
    worktree with no `pending-docs/` at all — and the doc is already on main, so the
    directory's absence PROVES there is nothing to lose. Exit 0, and (b) may proceed."""
    collect, _ = scripts
    main, wt = tmp_path / "main", _checkout(tmp_path / "wt")
    _doc(_live(main) / "feat-x.md", "feat/x", "AUTHORED ON MAIN")

    r = _run(collect, main, wt)

    assert r.returncode == 0, f"the ordinary state must not halt the close: {r.stdout}"
    assert "COLLECT SKIPPED" in r.stdout
    assert "feat-x.md" in r.stdout, "the report must name the doc it found on main"
    assert "PENDING-DOC COLLISIONS: 0" in r.stdout, "Step 8 reads this line"
    assert (_live(main) / "feat-x.md").read_text().count("AUTHORED ON MAIN") == 1


def test_an_absent_pending_docs_dir_says_so_when_main_holds_nothing(scripts, tmp_path):
    """The second legitimate reading — a hand-cut branch that never ran /document-work.
    Also exit 0, but it is NOT the same fact and the report must not collapse them: this is
    the one an operator may want to act on before the branch merges."""
    collect, _ = scripts
    main, wt = tmp_path / "main", _checkout(tmp_path / "wt")
    _live(main).mkdir(parents=True)
    _doc(_live(main) / "other.md", "feat/somebody-else", "NOT THIS BRANCH")

    r = _run(collect, main, wt)

    assert r.returncode == 0, f"a branch with no doc anywhere must not halt: {r.stdout}"
    assert "main holds no doc claiming 'feat/x'" in r.stdout
    assert "other.md" not in r.stdout, "another branch's doc is not this branch's doc"


def test_the_absent_and_the_empty_pending_docs_dir_are_dispositioned_alike(scripts, tmp_path):
    """An existing-but-EMPTY `src_dir` exited 0 before this change and still does. The two
    states carry the same proof — nothing here to lose — so a fix that split them would be
    asserting a difference that does not exist."""
    collect, _ = scripts
    empty_main, empty_wt = tmp_path / "e_main", _checkout(tmp_path / "e_wt")
    (empty_wt / "sysop/runtime/pending-docs").mkdir(parents=True)
    _live(empty_main).mkdir(parents=True)
    absent_main, absent_wt = tmp_path / "a_main", _checkout(tmp_path / "a_wt")
    _live(absent_main).mkdir(parents=True)

    empty = _run(collect, empty_main, empty_wt)
    absent = _run(collect, absent_main, absent_wt)
    assert empty.returncode == 0 and absent.returncode == 0
    # Exit codes alone are not the disposition. Routing the EMPTY directory through the
    # absent arm also exits 0 — and then prints `COLLECT SKIPPED: no <dir>` about a
    # directory that plainly exists, and newly subjects it to the `.git` gate.
    assert "COLLECT SKIPPED" not in empty.stdout, (
        "an existing-but-empty src_dir takes the ORDINARY path; reporting it as absent is "
        "a false statement about the tree"
    )
    assert "COLLECT SKIPPED" in absent.stdout
    assert "PENDING-DOC COLLISIONS: 0" in empty.stdout


def test_a_bare_directory_is_still_refused_when_it_has_no_pending_docs(scripts, tmp_path):
    """The discrimination, stated as its own claim rather than left implicit in the oracle
    above. Same inputs as `test_an_absent_pending_docs_dir_on_a_checkout_is_not_an_error`
    except for `.git` — and the dispositions differ. A fix that drops the `.git` test makes
    these two agree, which is the conflation `Q-470` was."""
    collect, _ = scripts
    main = tmp_path / "main"
    _doc(_live(main) / "feat-x.md", "feat/x", "AUTHORED ON MAIN")
    bare = tmp_path / "not-a-checkout"
    bare.mkdir()

    assert _run(collect, main, bare).returncode == 4
    assert _run(collect, main, _checkout(tmp_path / "wt")).returncode == 0


def test_a_present_pending_docs_dir_is_collected_from_a_path_without_dot_git(scripts, tmp_path):
    """The `.git` test is sited where it discriminates and NOWHERE else. Where `src_dir`
    exists the directory demonstrably holds this branch's docs and they must be collected
    whatever else is true of the path — hoisting the test into the top disjunction would
    have widened exit 4 across the whole population for no discrimination at all."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _live(main).mkdir(parents=True)
    _doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "WORKTREE")
    assert not (wt / ".git").exists()

    r = _run(collect, main, wt)

    assert r.returncode == 0, f"a doc that is there must be collected: {r.stdout}"
    assert "WORKTREE" in (_live(main) / "feat-x.md").read_text()


# ------------------------------------------------------- Phase 282: `Q-471`
#
# Step 4c routes a doc's `summary:` into `PROJECT_STATUS.md` §6 in the same commit that
# flips its task to `done`, and nothing between them asked whether the doc still described
# the branch. It is decided HERE and not there because Step 4-pre rebases/cherry-picks and
# Step 4a may squash — every one of which orphans the recorded SHA, so 4c cannot ask the
# question at all. These tests run against a REAL repository, because the measurement is
# `git rev-list` and a stubbed one would pin the stub.


def _g(root: Path, *a) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *a], cwd=root, capture_output=True, text=True, check=True)


def _repo(root: Path) -> str:
    """A primary checkout on `main` with a `feat/x` branch carrying one commit.

    Returns that branch's tip — what /document-work would stamp as `branch_tip:`.
    """
    root.mkdir(parents=True, exist_ok=True)
    _g(root, "init", "-q", "-b", "main", ".")
    _g(root, "config", "user.email", "t@example.invalid")
    _g(root, "config", "user.name", "t")
    (root / "f").write_text("a\n", encoding="utf-8")
    _g(root, "add", "f")
    _g(root, "commit", "-qm", "c1")
    _g(root, "checkout", "-q", "-b", "feat/x")
    (root / "g").write_text("b\n", encoding="utf-8")
    _g(root, "add", "g")
    _g(root, "commit", "-qm", "the work this doc describes")
    tip = _g(root, "rev-parse", "HEAD").stdout.strip()
    _g(root, "checkout", "-q", "main")
    return tip


def _worktree(main: Path, path: Path) -> Path:
    """A REAL linked worktree, not a directory with a `.git` file written into it.

    The first cut of these fixtures faked `.git`, and the staleness measurement then ran
    against the runner's CWD, so the fake passed. Running it in the workspace — which is
    what makes the `--clone` shape work at all — turns every fake into a failure, which is
    the fixtures telling the truth for the first time.
    """
    _g(main, "worktree", "add", "-q", str(path), "feat/x")
    return path


def _clone(main: Path, path: Path) -> Path:
    """The `--clone` shape: a SEPARATE repository with its own object store.

    `claim_task.sh --clone` publishes the branch and clones the remote, so the workspace's
    commits are not in the primary checkout's store at all. This is the shape the gate was
    structurally inert for when the measurement ran in the main checkout.
    """
    subprocess.run(["git", "clone", "-q", str(main), str(path)], check=True,
                   capture_output=True)
    _g(path, "config", "user.email", "t@example.invalid")
    _g(path, "config", "user.name", "t")
    _g(path, "checkout", "-q", "feat/x")
    return path


def _commit_on(root: Path, message: str) -> None:
    """A commit on `feat/x` in whichever checkout `root` names — the workspace, normally,
    because that is where work happens after `/document-work` has written its doc."""
    on_branch = _g(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() == "feat/x"
    if not on_branch:
        _g(root, "checkout", "-q", "feat/x")
    p = root / f"extra-{message.replace(' ', '-')}"
    p.write_text("x\n", encoding="utf-8")
    _g(root, "add", p.name)
    _g(root, "commit", "-qm", message)
    if not on_branch:
        _g(root, "checkout", "-q", "main")


def _tipped(path: Path, branch: str, summary: str, tip: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = f"---\nbranch: {branch}\n"
    if tip is not None:
        fm += f"branch_tip: {tip}\n"
    fm += f'type: feature\nsummary: "{summary}"\n---\n'
    path.write_text(fm, encoding="utf-8")


def test_a_doc_its_branch_has_moved_past_is_refused_and_nothing_is_collected(
    scripts, tmp_path
):
    """The § High. A prod-write task writes its doc when the code is ready and achieves its
    deliverable afterwards, on the same branch, in a later commit — so it arrives stale BY
    CONSTRUCTION. Refusing here costs nothing: main untouched, branch unmerged, worktree
    left in place, which is what makes re-running /document-work reachable at all."""
    collect, _ = scripts
    main = tmp_path / "main"
    tip = _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "NO prod write yet", tip)
    _live(main).mkdir(parents=True)
    _commit_on(wt, "the prod write, performed")

    r = _run(collect, main, wt)

    assert r.returncode == 6, f"a stale doc must not be collected: {r.stdout}"
    assert "PENDING-DOC STALE" in r.stdout
    assert "the prod write, performed" in r.stdout, (
        "the drift must name the commits, not only count them — a count alone cannot be "
        "judged in a glance and the deferral is the cost being paid"
    )
    assert not (_live(main) / "feat-x.md").exists(), "main must be untouched"
    assert (wt / "sysop/runtime/pending-docs/feat-x.md").exists(), (
        "the worktree copy is the only record; refusing must never consume it"
    )


def test_a_current_doc_collects_normally(scripts, tmp_path):
    """The control. Without it the test above is satisfied by a check that refuses
    everything, which is the failure mode this repo keeps finding in its own guards."""
    collect, _ = scripts
    main = tmp_path / "main"
    tip = _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "CURRENT", tip)
    _live(main).mkdir(parents=True)

    r = _run(collect, main, wt)

    assert r.returncode == 0, f"a current doc must collect: {r.stdout}"
    assert "PENDING-DOC STALE" not in r.stdout
    assert "CURRENT" in (_live(main) / "feat-x.md").read_text()


def test_a_doc_with_no_branch_tip_is_reported_and_collected_never_refused(scripts, tmp_path):
    """Every doc written before the key existed has none. Refusing those would halt every
    consumer's first close after an update — which is the shape `Q-470` is on this page for,
    reintroduced by its own fix. Absence of a measurement is not a measurement."""
    collect, _ = scripts
    main = tmp_path / "main"
    _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "LEGACY", None)
    _live(main).mkdir(parents=True)
    _commit_on(wt, "a commit it cannot possibly know about")

    r = _run(collect, main, wt)

    assert r.returncode == 0, f"a legacy doc must not halt the close: {r.stdout}"
    assert "STALENESS UNKNOWN" in r.stdout, "silence would read as a clean measurement"
    # The OTHER direction. Both arms print `STALENESS UNKNOWN`, so asserting only that
    # leaves a mutant where `tip_of` returns the unusable sentinel for a MISSING key —
    # telling the operator a legacy doc carries a malformed value it does not have.
    assert "no `branch_tip:`" in r.stdout, (
        "an ABSENT key must not be reported as a present-but-unusable one"
    )
    assert "is present but is not a string" not in r.stdout
    assert "LEGACY" in (_live(main) / "feat-x.md").read_text()


def test_a_branch_tip_that_does_not_resolve_is_not_evidence_either_way(scripts, tmp_path):
    """A pruned or foreign object. `git rev-list` fails, and a failed measurement must take
    the unknown arm rather than being read as drift."""
    collect, _ = scripts
    main = tmp_path / "main"
    _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "ORPHANED",
            "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    _live(main).mkdir(parents=True)

    r = _run(collect, main, wt)

    assert r.returncode == 0, f"an unresolvable tip is not staleness: {r.stdout}"
    assert "does not resolve here" in r.stdout
    assert "ORPHANED" in (_live(main) / "feat-x.md").read_text()


@pytest.mark.parametrize("hostile", ["--help", "--version", "-n1", "--output=/tmp/x"])
def test_a_branch_tip_that_is_not_an_object_name_never_reaches_git_as_an_option(
    scripts, tmp_path, hostile
):
    """`branch_tip` is free-form frontmatter. Unvalidated, a value beginning with `-`
    reaches `git rev-list` as an OPTION rather than a revision — the whole class dies on one
    `[0-9a-f]{7,64}` match, and a value that is not an object name is not a measurement."""
    collect, _ = scripts
    main = tmp_path / "main"
    _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "HOSTILE",
            f'"{hostile}"')
    _live(main).mkdir(parents=True)

    r = _run(collect, main, wt)

    assert r.returncode == 0, f"{hostile!r} must degrade to unknown: {r.stdout}"
    assert "is not an object name" in r.stdout
    assert "HOSTILE" in (_live(main) / "feat-x.md").read_text()


def test_a_collision_outranks_staleness(scripts, tmp_path):
    """Both lists populated AT ONCE, which is the only state that tests the ordering.

    The first cut of this test used a doc claiming a foreign branch — and that doc hits
    `src_b != branch` and `continue`s, so `stale` was never populated and swapping the two
    blocks verbatim left the suite green. The state where both populate is the OTHER
    collision arm: the doc legitimately claims this branch (so it is measured, and it is
    stale) while MAIN's copy of the same basename belongs to someone else."""
    collect, _ = scripts
    main = tmp_path / "main"
    tip = _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "MINE-BUT-STALE", tip)
    _live(main).mkdir(parents=True)
    _tipped(_live(main) / "feat-x.md", "feat/somebody-else", "THEIRS", tip)
    _commit_on(wt, "drift as well")

    r = _run(collect, main, wt)

    assert r.returncode == 3, f"the collision must win over the staleness: {r.stdout}"
    assert "PENDING-DOC COLLISION" in r.stdout
    assert "PENDING-DOC STALE:" not in r.stdout, (
        "a collision settles WHOSE record this is, and that must be answered before "
        "anything is said about whether a record is current"
    )
    assert "THEIRS" in (_live(main) / "feat-x.md").read_text()


def test_the_ordering_fixture_really_populates_both_lists(scripts, tmp_path):
    """The control that keeps the test above honest. Same fixture minus the foreign copy
    on main: it must exit 6, which proves the doc IS measured and IS stale, so the exit-3
    above is the ordering winning and not staleness never having been computed."""
    collect, _ = scripts
    main = tmp_path / "main"
    tip = _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "MINE-BUT-STALE", tip)
    _live(main).mkdir(parents=True)
    _commit_on(wt, "drift as well")

    assert _run(collect, main, wt).returncode == 6


def test_a_broken_git_fails_open_rather_than_refusing_the_close(scripts, tmp_path):
    """The collect runs from the main checkout; a non-repository CWD (or no git at all)
    must degrade to unknown-not-stale. A doc-integrity step that turns a missing tool into a
    refusal to close is the `Q-470` shape wearing this fix's name."""
    collect, _ = scripts
    main, wt = tmp_path / "main", _checkout(tmp_path / "wt")
    _live(main).mkdir(parents=True)
    _tipped(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "NO REPO",
            "0123456789abcdef0123456789abcdef01234567")

    r = _run(collect, main, wt)

    assert r.returncode == 0, f"no repository must not halt the close: {r.stdout}"
    assert "STALENESS UNKNOWN" in r.stdout
    assert "NO REPO" in (_live(main) / "feat-x.md").read_text()


# ------------------- Phase 282: the writer side, and the prose that binds it
#
# A gate whose producers do not emit the field it reads is a gate that prints
# `STALENESS UNKNOWN` forever while looking armed. The population is DERIVED rather than
# listed, because a listed one silently omits the next writer — which is the failure this
# repo has filed under four different names.

SKILLS_DIR = REPO / "core" / "skills"
_YAML_FENCE = re.compile(r"```ya?ml\n(.*?)```", re.DOTALL)


def _pending_doc_templates() -> list[tuple[Path, str]]:
    """Every shipped YAML fence that is a pending-doc frontmatter template.

    Identified by what makes it one — a `branch:` key and a `summary:` key in the same
    fence — not by a hand-kept list of skills."""
    found = []
    for skill in sorted(SKILLS_DIR.rglob("SKILL.md")):
        for block in _YAML_FENCE.findall(skill.read_text(encoding="utf-8")):
            if re.search(r"^branch:", block, re.M) and re.search(r"^summary:", block, re.M):
                found.append((skill, block))
    return found


def test_every_pending_doc_writer_emits_branch_tip():
    """`Q-471`. Three writers ship: /document-work (the human-driven one) and /auto-fix +
    /auto-judge (the batch ones). A writer that omits the key exempts its whole path from
    the staleness gate without anything going red."""
    templates = _pending_doc_templates()
    found = sorted({str(p.relative_to(SKILLS_DIR)) for p, _ in templates})
    assert found == [
        "auto-fix/SKILL.md",
        "auto-judge/SKILL.md",
        "document-work/SKILL.md",
    ], (
        f"the pending-doc writer set changed: {found}. A NEW writer must be given "
        f"`branch_tip:` and a stamping rule before this list is updated; a writer that "
        f"VANISHED means the discriminator in _pending_doc_templates() stopped matching, "
        f"and a sweep that finds nothing passes every other assertion in this test."
    )
    missing = [str(p.relative_to(REPO)) for p, b in templates
               if not re.search(r"^branch_tip:", b, re.M)]
    assert not missing, f"pending-doc writers with no `branch_tip:`: {missing}"


def test_every_pending_doc_writer_says_when_to_stamp_it():
    """The field is worthless stamped at the wrong moment, and each writer's LAST commit is
    at a different step. /auto-judge's shipped order wrote the doc and THEN pushed the
    `review_tasks.md` annotation, which stamps a commit the annotation moves past — exit 6
    on every all-DROP batch. The rule has to travel with the template."""
    for path, template in _pending_doc_templates():
        body = path.read_text(encoding="utf-8")
        # The rule must live OUTSIDE the template. The first cut of this guard matched the
        # template line itself (`branch_tip: <full SHA — \`git rev-parse HEAD\`, run NOW>`),
        # ~30 characters from the anchor — so deleting every stamping blockquote in all
        # three writers left it green. Strip the template, then look.
        prose = body.replace(template, "")
        assert "branch_tip" in prose, (
            f"{path.relative_to(REPO)}: `branch_tip` appears only inside the template, so "
            f"nothing says when to stamp it"
        )
        # The two obligations, each pinned on its own — a writer that carries one and not
        # the other is the /auto-judge bug this phase fixed.
        # `states()`, not a raw search: "it need not re-stamp" contains "re-stamp".
        assert any(states(prose, phr) for phr in (
            "re-stamp it", "it must re-stamp", "it must re-stamp.",
        )), f"{path.relative_to(REPO)}: no ASSERTED re-stamp obligation for a later commit"
        # And WHERE to stamp, not only that a stamp exists. Moving /document-work's stamp
        # to Step 1 — before Step 2's commit — guarantees exit 6 on every close, and the
        # value would still be "a SHA read from HEAD".
        assert states(prose, "after this branch's final commit") or states(
            prose, "Stamp it here, at Step 3, and not earlier"
        ), (f"{path.relative_to(REPO)}: the stamp POINT is unpinned — a stamp taken before "
            f"this writer's last commit is stale the moment it is written")
        assert re.search(r"rev-parse HEAD", prose), (
            f"{path.relative_to(REPO)}: the stamp is not stated as a SHA read from HEAD"
        )
        assert states(prose, "exit 6") or "exit 6" in prose, (
            f"{path.relative_to(REPO)}: the consequence of a stale stamp is not named, so "
            f"a later editor has no reason to keep the rule"
        )


def test_auto_judge_commits_the_annotation_before_it_stamps():
    """`/auto-judge`'s SHIPPED order was doc-then-push, which stamps a commit its own
    `review_tasks.md` annotation then moves past — exit 6 on every all-DROP batch. The
    phase reversed it and nothing tested the reversal, so reverting the fix was green."""
    body = (SKILLS_DIR / "auto-judge" / "SKILL.md").read_text(encoding="utf-8")
    assert states(body, "Commit and push the `review_tasks.md` annotation FIRST, then write this file"), (
        "the ordering fix is the deliverable; without it the stamp is taken at a commit "
        "the very next sentence tells the agent to supersede"
    )
    assert not re.search(r"write this file first,? then commit and push", body, re.I), (
        "the shipped-bug ordering must not be restorable while this guard stays green"
    )


def test_the_stale_exit_is_in_the_disposition_table_with_its_remedy():
    """Phase 165's lesson: an exit whose row does not state the remedy gets improvised, and
    the improvisation on this step has twice been a wholesale worktree wipe. Exit 6's whole
    safety argument is that the worktree STAYS — that is what makes the remedy reachable."""
    body = SKILL.read_text(encoding="utf-8")
    row = [ln for ln in body.split("\n") if ln.strip().startswith("| **6**")]
    assert len(row) == 1, f"expected exactly one exit-6 row, found {len(row)}"
    # The row must be INSIDE the table. A blank line terminates a Markdown table, and the
    # first cut of this row sat one blank line below row 5 — so the phase's newest and most
    # consequential row rendered as literal pipe text under no header at all.
    lines = body.split("\n")
    i = lines.index(row[0])
    assert lines[i - 1].strip().startswith("| **5**"), (
        "the exit-6 row must follow row 5 with no blank line between — a blank line ends "
        "the table and orphans it from its header"
    )
    # Columns, not the whole row: `/document-work` and `untouched` both occur in the
    # MEANING column too, so a whole-row `in` is satisfied by the half that is not the
    # remedy. Split on the pipes and assert against the column that carries each claim.
    cols = [c.strip() for c in row[0].strip().strip("|").split("|")]
    assert len(cols) == 4, f"exit-6 row has {len(cols)} columns: {cols}"
    meaning, state, todo = cols[1], cols[2], cols[3]
    assert "stale" in meaning.lower()
    # This asserted `"untouched" in state and "stage 1 writes nothing" in state` until
    # `Q-483`, and it was the GUARD'S PREMISE that changed rather than the guard. Exit 6 now
    # also fires on the `Q-470` route, where there was nothing to collect and main IS holding
    # the stale doc — so a row saying "untouched" would be false on the arm that most needs
    # the operator to look. What has to stay true is the pair: nothing was written, AND the
    # row does not let the reader conclude main is in the state they want.
    assert "nothing was WRITTEN" in state or "writes nothing" in state, (
        f"the state column must still say stage 1 wrote nothing: {state}"
    )
    assert "holding the stale doc" in state, (
        "the state column must say that on the `Q-470` route main keeps the stale doc — "
        "without it the row reads as 'main is fine', which is what sent an operator "
        "straight past it"
    )
    assert "/document-work" in todo, "the remedy must be in the WHAT-TO-DO column"
    # `Q-483`: that remedy CREATES `sysop/runtime/pending-docs/` unconditionally, which used
    # to move the close onto the arm that did not measure main — the gate turning itself off.
    # The fix is in the code (both routes measure main's surviving docs); this pins that the
    # row does not quietly go back to prescribing a remedy with no measurement behind it.
    assert "re-run the close" in todo.lower() or "re-run" in todo.lower(), todo
    assert "worktree, lock and branch intact" in todo, (
        "the branch state is the whole safety argument: the remedy needs the workspace "
        "this exit declines to remove"
    )
    assert "Do not run the rollback" in todo, (
        "exit 3 carries this and exit 6 has the same property — stage 1 writes nothing, so "
        "there is nothing to undo and a rollback would only delete main's own record"
    )


def test_the_skill_states_why_staleness_is_not_decided_at_step_4c():
    """The reason is load-bearing and not obvious, and the round corrected it twice. It is
    an ancestry test, and **Step 4a item 2's rebase** is what orphans the recorded tip — not
    a squash, which happens at Step 4d, AFTER 4c, and so cannot have orphaned anything 4c
    reads. And it is not universal: the PR-reuse shape skips 4a and a published branch is
    merged `--no-ff`, so a 4c gate would be live on the rare shapes and inert on the
    dominant one. That last clause is the actual argument for siting it at 3b, so it is the
    one pinned hardest."""
    body = SKILL.read_text(encoding="utf-8")
    # Bounded. An unbounded `body[index("PENDING-DOC STALE"):]` runs ~1,100 lines to EOF and
    # sweeps up Step 4-pre's own prose, which supplies a rebase/squash co-occurrence all by
    # itself — so deleting the mechanism from THIS paragraph left the guard green.
    start = body.index("**Why staleness is decided here and not at Step 4c")
    window = body[start:body.index("\n   b. ", start)]
    assert len(window) < 12000, f"window is {len(window)} chars — it has slipped its bound"
    assert states(window, "Step 4a item 2 rebases each approved branch")
    assert states(window, "live on the shapes that rarely fire and inert on the one that always does")
    assert "PR-reuse" in window and "--no-ff" in window, (
        "the two shapes that leave the branch intact are the argument, not a caveat"
    )
    assert not re.search(r"Step 4a may squash", window), (
        "the squash is Step 4d's and runs after 4c; naming it here was the round's finding"
    )


def test_step_1b_short_circuits_on_1c_s_hold_before_resolving_any_ref():
    """`Q-474`. 1b's stop-and-ask is a halt on a branch reference for a doc that 1c was
    never going to route — resolving it is pure downside. Both sites must say so: a rule
    stated only at the step that does not act on it is the shape Phase 180 filed."""
    body = SKILL.read_text(encoding="utf-8")
    one_b = body[body.index("1b. **Drop any pending-doc"):body.index("1c. **Hold back")]
    one_c = body[body.index("1c. **Hold back"):]
    assert states(one_b, "Before resolving anything, apply 1c's hold test")
    assert states(one_b, "Resolving the ref is then pure downside"), (
        "a raw `in` on `pure downside` passes on `is NOT pure downside` — the phrase must "
        "be asserted, not merely present"
    )
    assert "1b short-circuits its ref resolution on it" in one_c
    # The round's finding: the first cut short-circuited 1c ITSELF, so a held doc would
    # have vanished from Step 8's `Held-back docs:` row — the short-circuit silently
    # deleting the report that 1c exists to produce.
    assert states(one_b, "It short-circuits 1b's REF RESOLUTION, not 1c")
    assert states(one_c, "This pass runs over every doc regardless")
    # And it must read the ids the way 1c reads them, or it resolves a ref for exactly the
    # legacy doc 1c calls the stranding path.
    assert "`roadmap_ids`, falling back to `task_ids`" in one_b


def test_the_short_circuit_did_not_delete_1b():
    """Ordering, not deletion. 1b still runs for every doc 1c does not hold, and the three
    things it decides are unchanged — a `fix` that drops them restores the silent false
    close `Q-238` closed."""
    body = SKILL.read_text(encoding="utf-8")
    one_b = body[body.index("1b. **Drop any pending-doc"):body.index("1c. **Hold back")]
    assert 'git rev-list --count "<branch from frontmatter>" "^HEAD"' in one_b
    assert "git cherry HEAD" in one_b
    assert states(one_b, "1b still runs, unchanged, for every doc 1c does not hold")


def test_the_staleness_measurement_is_hermetic(scripts, tmp_path):
    """Phase 124's rule, and the battery's one real survivor before it was written. The
    collect runs from the main checkout while a worktree is live, and an inherited
    `GIT_DIR`/`GIT_WORK_TREE` from the caller's shell resolves a DIFFERENT repository — so
    an unstripped env would answer the staleness question about someone else's history and
    report it as this branch's. Here the hostile env names a repo where `feat/x` does not
    exist at all, which without the strip degrades a real drift to `STALENESS UNKNOWN`."""
    collect, _ = scripts
    main = tmp_path / "main"
    tip = _repo(main)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", "."], cwd=elsewhere, check=True)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "STALE", tip)
    _live(main).mkdir(parents=True)
    _commit_on(wt, "the commit the doc does not describe")

    import os
    env = dict(os.environ)
    env["GIT_DIR"] = str(elsewhere / ".git")
    env["GIT_WORK_TREE"] = str(elsewhere)
    r = subprocess.run([sys.executable, str(collect), str(wt), "feat/x"],
                       cwd=main, capture_output=True, text=True, env=env)

    assert r.returncode == 6, (
        f"the hostile GIT_DIR was honoured and the drift was lost: {r.stdout}"
    )
    assert "the commit the doc does not describe" in r.stdout


@pytest.mark.parametrize("value,expect", [
    ("1234567", "not a string"),      # a bare hex-looking value is a YAML int
    ("true", "not a string"),
    # An explicit `null` is the key PRESENT with an unusable value, not the key absent —
    # my first expectation here said otherwise and the code was right.
    ("null", "not a string"),
    ("[]", "not a string"),
])
def test_a_present_but_unusable_branch_tip_is_not_reported_as_absent(
    scripts, tmp_path, value, expect
):
    """Found by this phase's own author-side pass. All four are legal YAML that no author
    intends, and the first cut of the report called every one of them *"no `branch_tip:` —
    written before the key existed"* — a statement about the doc that is simply false, in a
    line whose whole job is to tell an operator which case they are in."""
    collect, _ = scripts
    main = tmp_path / "main"
    _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    (wt / "sysop/runtime/pending-docs").mkdir(parents=True)
    (wt / "sysop/runtime/pending-docs/feat-x.md").write_text(
        f'---\nbranch: feat/x\nbranch_tip: {value}\ntype: feature\nsummary: "V"\n---\n',
        encoding="utf-8")
    _live(main).mkdir(parents=True)

    r = _run(collect, main, wt)

    assert r.returncode == 0, f"an unusable value must not halt: {r.stdout}"
    assert expect in r.stdout, f"{value!r} misreported: {r.stdout}"
    assert "V" in (_live(main) / "feat-x.md").read_text()


def test_the_clone_shape_is_measured_not_waved_through(scripts, tmp_path):
    """The round's HIGH, and the reason `_git` takes `-C wt`.

    A `--clone` workspace is a SEPARATE repository — `claim_task.sh --clone` publishes the
    branch and clones the remote — so its commits are not in the primary checkout's object
    store. Measured from the main checkout, a genuinely stale clone-shape doc reported
    `STALENESS UNKNOWN` and collected, on every clone-shape close, forever: a gate that
    looks armed and is dead for a whole population. Run in the workspace, the objects are
    always there."""
    collect, _ = scripts
    main = tmp_path / "main"
    _repo(main)
    ws = _clone(main, tmp_path / "ws")
    tip = _g(ws, "rev-parse", "HEAD").stdout.strip()
    _tipped(ws / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "CLONE", tip)
    _live(main).mkdir(parents=True)
    _commit_on(ws, "work done inside the clone")
    # The proof that the main checkout cannot answer: it does not have the object.
    assert subprocess.run(["git", "cat-file", "-e", f"{tip}^{{commit}}"], cwd=main,
                          capture_output=True).returncode == 0
    after = _g(ws, "rev-parse", "HEAD").stdout.strip()
    assert subprocess.run(["git", "cat-file", "-e", f"{after}^{{commit}}"], cwd=main,
                          capture_output=True).returncode != 0, (
        "the clone's new commit must be absent from the primary store, or this fixture is "
        "not modelling the clone shape at all"
    )

    r = _run(collect, main, ws)

    assert r.returncode == 6, f"the clone shape must be measured, not waved through: {r.stdout}"
    assert "work done inside the clone" in r.stdout
    assert not (_live(main) / "feat-x.md").exists()


def test_the_clone_shape_control_a_current_clone_doc_collects(scripts, tmp_path):
    """The negative control for the test above — without it, a check that refuses every
    clone-shape doc would satisfy it."""
    collect, _ = scripts
    main = tmp_path / "main"
    _repo(main)
    ws = _clone(main, tmp_path / "ws")
    tip = _g(ws, "rev-parse", "HEAD").stdout.strip()
    _tipped(ws / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "CLONE-CURRENT", tip)
    _live(main).mkdir(parents=True)

    r = _run(collect, main, ws)

    assert r.returncode == 0, f"a current clone-shape doc must collect: {r.stdout}"
    assert "CLONE-CURRENT" in (_live(main) / "feat-x.md").read_text()


def test_the_measurement_runs_in_the_workspace_not_the_runners_cwd(scripts, tmp_path):
    """Stated as its own claim rather than left implicit in the clone tests. The runner's
    CWD is the primary checkout and the workspace is the operand; a measurement keyed to the
    former answers about the wrong repository whenever the two differ. Here the primary
    checkout holds a `feat/x` that is CURRENT and the workspace holds one that is not."""
    collect, _ = scripts
    main = tmp_path / "main"
    _repo(main)
    ws = _clone(main, tmp_path / "ws")
    tip = _g(ws, "rev-parse", "HEAD").stdout.strip()
    _tipped(ws / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "WS", tip)
    _live(main).mkdir(parents=True)
    _commit_on(ws, "only the workspace moved")
    assert _g(main, "rev-parse", "feat/x").stdout.strip() == tip, (
        "the primary checkout's branch must still be AT the stamped tip, so a CWD-keyed "
        "measurement would report `0` drift and collect"
    )

    r = _run(collect, main, ws)

    assert r.returncode == 6, (
        f"the primary checkout's answer (drift 0) was taken instead of the workspace's: "
        f"{r.stdout}"
    )


# ---------------------------- the round's guard-strength findings, as their own claims

def test_the_first_ever_close_works_when_main_has_no_pending_docs_dir(scripts, tmp_path):
    """`live.mkdir(parents=True, exist_ok=True)` is load-bearing and nothing tested it.

    Main's `sysop/runtime/pending-docs/` is gitignored — absent from any fresh clone,
    authored lazily by /document-work in the WORKTREE, and removed-when-empty by Step 4c's
    cleanup — so a consumer's first close arrives with no destination. Every other collect
    test pre-creates `_live(main)`, so the population never contained that run. Without the
    mkdir the copy fails and the collect exits 5, after which the prescribed rollback runs
    against docs that were never collected.
    """
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    main.mkdir()
    assert not _live(main).exists(), "this fixture's whole point is the missing destination"
    _doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "FIRST EVER")

    r = _run(collect, main, wt)

    assert r.returncode == 0, f"the first-ever close must not fail: {r.stdout}"
    assert (_live(main) / "feat-x.md").read_text().count("FIRST EVER") == 1


def test_the_absent_arm_keys_on_the_pending_docs_dir_not_on_sysop(scripts, tmp_path):
    """`_checkout()` builds a bare directory plus `.git`, and a real consumer worktree also
    carries `sysop/`. A predicate widened to `not (wt / 'sysop').is_dir()` therefore passes
    every fixture here while producing NOTHING on a real tree — the whole `Q-470` report
    silently disappearing exactly where it is needed."""
    collect, _ = scripts
    main, wt = tmp_path / "main", _checkout(tmp_path / "wt")
    (wt / "sysop" / "runtime").mkdir(parents=True)     # a real workspace has this
    (wt / "sysop" / "scripts").mkdir(parents=True)
    _doc(_live(main) / "feat-x.md", "feat/x", "ON MAIN")

    r = _run(collect, main, wt)

    assert r.returncode == 0
    assert "COLLECT SKIPPED" in r.stdout, (
        "the arm must key on the absent pending-docs directory, not on the absence of the "
        "whole `sysop/` tree — which a real workspace always has"
    )
    assert "feat-x.md" in r.stdout


def test_an_empty_branch_name_is_still_a_loud_abort(scripts, tmp_path):
    """Splitting the disjunction must not have cost the operands their own arms. An empty
    branch reaching stage 1 would classify every doc a collision (exit 3) — a quiet,
    wrong-shaped refusal in place of the loud one."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _live(main).mkdir(parents=True)
    _doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "S")

    r = subprocess.run([sys.executable, str(collect), str(wt), ""],
                       cwd=main, capture_output=True, text=True)

    assert r.returncode == 4, f"an empty branch must abort loudly: {r.returncode} {r.stdout}"
    assert "COLLECT ABORTED" in r.stdout


def test_the_doc_glob_is_not_recursive(scripts, tmp_path):
    """`quarantine/` is a SUBDIRECTORY precisely so no `*.md` reader sees it again (Step 4c
    says so in as many words). An `rglob` here would collect quarantined and nested docs and
    hand them to a step that was promised it would never see them."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    _live(main).mkdir(parents=True)
    _doc(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "TOP")
    _doc(wt / "sysop/runtime/pending-docs/quarantine/old.md", "feat/somebody-else", "NESTED")

    r = _run(collect, main, wt)

    assert r.returncode == 0, f"a nested doc must be invisible, not a collision: {r.stdout}"
    assert not (_live(main) / "old.md").exists()
    assert "NESTED" not in r.stdout


def test_a_foreign_doc_is_never_measured_for_staleness(scripts, tmp_path):
    """The collision arm `continue`s before the staleness block, and it must: reporting
    `STALENESS UNKNOWN` about a doc that does not belong to this branch states a fact about
    someone else's record in this branch's report."""
    collect, _ = scripts
    main = tmp_path / "main"
    _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/other", "FOREIGN", None)
    _live(main).mkdir(parents=True)

    r = _run(collect, main, wt)

    assert r.returncode == 3
    assert "STALENESS" not in r.stdout


@pytest.mark.parametrize("hostile", [
    "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef..HEAD --all",   # a trailing revision range
    "0123456 --not --all",
    "abcdef0\nrm -rf /",
])
def test_sha_re_is_anchored_at_both_ends(scripts, tmp_path, hostile):
    """`SHA_RE.match` without `\\Z` accepts a valid prefix and passes the whole string to
    git — so `<sha>..HEAD --all` validates and arrives as extra revisions and options."""
    collect, _ = scripts
    main = tmp_path / "main"
    _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "ANCHOR", f'"{hostile}"')
    _live(main).mkdir(parents=True)

    r = _run(collect, main, wt)

    assert r.returncode == 0, f"{hostile!r} must degrade to unknown: {r.stdout}"
    assert "is not an object name" in r.stdout


@pytest.mark.parametrize("var", ["GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"])
def test_every_git_env_var_in_the_strip_list_is_actually_stripped(scripts, tmp_path, var):
    """All four, parametrized. The first cut of the hermeticity test set only two of them,
    so dropping the other two from the strip list was a survivor — a list guarded by a
    fixture that exercises half of it is a list that can shrink."""
    collect, _ = scripts
    main = tmp_path / "main"
    tip = _repo(main)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", "."], cwd=elsewhere, check=True)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "STALE", tip)
    _live(main).mkdir(parents=True)
    _commit_on(wt, "the commit the doc does not describe")

    import os
    env = dict(os.environ)
    env[var] = str(elsewhere / ".git") if var != "GIT_WORK_TREE" else str(elsewhere)
    if var == "GIT_INDEX_FILE":
        env[var] = str(elsewhere / ".git" / "index")
    r = subprocess.run([sys.executable, str(collect), str(wt), "feat/x"],
                       cwd=main, capture_output=True, text=True, env=env)

    assert r.returncode == 6, f"{var} was honoured and the drift was lost: {r.stdout}"


def test_step_8_carries_a_row_for_every_line_the_collect_prints():
    """A gate whose SKIP has no row in the run's report is a SKIP nobody sees, and the
    first cut of this phase shipped both new stdout lines with no sink at all. Derive the
    pairing rather than listing it: every `PENDING-DOC <X>:` prefix the heredoc prints must
    have a Step 8 row, and each row must say what happened to the doc."""
    body = SKILL.read_text(encoding="utf-8")
    step8 = body[body.index("Pending-doc collisions: <N>"):]
    step8 = step8[:step8.index("\n## ")] if "\n## " in step8 else step8

    stale = [ln for ln in step8.split("\n") if ln.startswith("Stale pending-docs:")]
    unknown = [ln for ln in step8.split("\n") if ln.startswith("Staleness not measured:")]
    assert len(stale) == 1, "exit 6 has no Step 8 row"
    assert len(unknown) == 1, "`STALENESS UNKNOWN` has no Step 8 row"

    stale_block = step8[step8.index(stale[0]):step8.index(unknown[0])]
    assert "exited 6" in stale_block and "NOTHING was collected" in stale_block
    assert "/document-work" in stale_block, "the row must carry the remedy"
    unknown_block = step8[step8.index(unknown[0]):]
    unknown_block = unknown_block[:unknown_block.index("\nQuarantined docs:")]
    assert "WAS collected" in unknown_block, (
        "the two rows mean opposite things about the doc — one refused, one routed — and a "
        "row that does not say which is worse than no row"
    )


def test_the_collect_prints_no_prefix_without_a_step_8_sink():
    """The general form of the test above: the pairing is DERIVED from the heredoc's own
    `print` statements, so a future line added with no row reddens here rather than being
    noticed when an operator misses a SKIP."""
    body = SKILL.read_text(encoding="utf-8")
    collect = _heredocs()[0]
    prefixes = set(re.findall(r"'PENDING-DOC ([A-Z][A-Z ]+):", collect))
    prefixes |= set(re.findall(r'"PENDING-DOC ([A-Z][A-Z ]+):', collect))
    step8 = body[body.index("Pending-doc collisions: <N>"):]
    # The Step 8 template's row names, lower-cased and de-spaced, must cover each prefix.
    covered = {
        "COLLISION": "pending-doc collisions:",
        "COLLISIONS": "pending-doc collisions:",
        "STALE": "stale pending-docs:",
        "STALENESS UNKNOWN": "staleness not measured:",
        "COLLECT ABORTED": None,      # exit 4 — the close never reaches Step 8
        # exits 5 and 7 DO reach Step 8: each SKIPs one branch and the close continues with
        # the others, exactly as 3 and 6 do. The first draft of this mapping said "likewise"
        # about exit 4 and was wrong — a SKIP with no row in the run's report is a SKIP
        # nobody sees, which is this step's own stated doctrine. Found by Phase 284's round.
        "COLLECT FAILED": "pending-doc write failures:",
        "UNDO": "pending-doc write failures:",
        "UNDO FAILED": "pending-doc write failures:",
        "COLLECT SKIPPED": None,      # exit 0, reported inline in the collect's own output
        "COLLECTED": None,
        "SKIPPED": None,
    }
    unmapped = sorted(p for p in prefixes if p not in covered)
    assert not unmapped, (
        f"the collect prints {unmapped} and this test does not know whether Step 8 has a "
        f"row for it — decide, then add the mapping"
    )
    for prefix, row in covered.items():
        if row and prefix in prefixes:
            assert row in step8.lower(), f"`PENDING-DOC {prefix}:` has no Step 8 row"


@pytest.mark.parametrize("short", ["a", "abc", "abcdef"])
def test_a_too_short_hex_value_is_named_as_malformed_not_as_a_missing_object(
    scripts, tmp_path, short
):
    """`SHA_RE`'s lower bound of 7 is a diagnostic, and dropping it to 1 is otherwise an
    equivalent mutation — both roads end at `STALENESS UNKNOWN` and a collect. What changes
    is what the operator is told: *"is not an object name"* says fix the doc, *"does not
    resolve here"* says the object is gone from this workspace. They are different actions,
    and git's own minimum unambiguous abbreviation is what makes 7 the right cut."""
    collect, _ = scripts
    main = tmp_path / "main"
    _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(wt / "sysop/runtime/pending-docs/feat-x.md", "feat/x", "SHORT", f'"{short}"')
    _live(main).mkdir(parents=True)

    r = _run(collect, main, wt)

    assert r.returncode == 0
    assert "is not an object name" in r.stdout, (
        f"{short!r} was passed to git and reported as unresolvable, which sends the "
        f"operator looking for a missing commit instead of a malformed field: {r.stdout}"
    )


# ------------------------------------------------------------------ `Q-482`: the population
def test_the_rollback_still_unlinks_when_the_worktree_holds_its_own_copy(scripts, tmp_path):
    """The ordinary route is unchanged, and this is the test that says so.

    `Q-482`'s fix must not turn every rollback into a move: where the worktree still holds
    its own copy, main's is a copy and unlinking it is correct and cheapest. The
    discriminator is *"does another copy survive"*, nothing else.
    """
    _, rollback = scripts
    main, wt = tmp_path / "main", _checkout(tmp_path / "wt")
    _doc(_live(main) / "feat-x.md", "feat/x", "mains copy")
    src = wt / "sysop" / "runtime" / "pending-docs" / "feat-x.md"
    _doc(src, "feat/x", "the worktree original")

    r = _run(rollback, main, wt)

    assert r.returncode == 0, r.stdout
    assert "ROLLED BACK: feat-x.md" in r.stdout, r.stdout
    assert "MAIN'S ONLY COPY, LEFT IN PLACE: none" in r.stdout, (
        "a doc with a surviving worktree copy was treated as main's only one"
    )
    assert not (_live(main) / "feat-x.md").exists()
    assert "the worktree original" in src.read_text(encoding="utf-8"), (
        "the worktree's own copy was overwritten by a restore that should never have run"
    )


def test_a_dangling_symlink_in_main_is_not_read_as_absent(scripts, tmp_path):
    """`exists()` FOLLOWS SYMLINKS — Phase 284 found this exact substitution in stage 2's
    undo, and the same one was live in the half that deletes.

    A dangling symlink in main's pending-docs read as absent, so the loop skipped it and the
    step printed `ROLLED BACK: none` at exit 0 while the entry was still sitting there. It
    carries no branch claim, so this step cannot attribute it and must not remove it — but it
    must SAY it saw it, which is the whole difference from a silent skip.
    """
    _, rollback = scripts
    main, wt = tmp_path / "main", _checkout(tmp_path / "wt")
    _live(main).mkdir(parents=True)
    (_live(main) / "feat-x.md").symlink_to(_live(main) / "nowhere.md")
    _doc(wt / "sysop" / "runtime" / "pending-docs" / "feat-x.md", "feat/x", "the original")

    r = _run(rollback, main, wt)

    assert r.returncode == 0, r.stdout
    assert "feat-x.md" in r.stdout.split("LEFT ALONE")[-1], (
        f"a dangling entry was skipped silently rather than reported: {r.stdout}"
    )
    assert os.path.lexists(_live(main) / "feat-x.md"), (
        "an entry carrying no branch claim was removed anyway"
    )


def test_a_rollback_that_cannot_finish_exits_8_and_names_the_file(scripts, tmp_path):
    """Previously a raw `PermissionError` traceback at exit 1 with NOTHING on stdout — a code
    this page does not carry, on the half that deletes. Measured against a read-only
    `sysop/runtime/pending-docs/`.

    Exit 8 is a partial pass, not a refusal: whatever the other lines report did happen.
    """
    _, rollback = scripts
    main, wt = tmp_path / "main", _checkout(tmp_path / "wt")
    _doc(_live(main) / "feat-x.md", "feat/x", "unremovable")
    _doc(wt / "sysop" / "runtime" / "pending-docs" / "feat-x.md", "feat/x", "the original")
    os.chmod(_live(main), 0o500)
    try:
        r = _run(rollback, main, wt)
    finally:
        os.chmod(_live(main), 0o700)

    assert r.returncode == 8, f"expected the documented partial-pass exit: {r.returncode}"
    assert "PENDING-DOC ROLLBACK FAILED: feat-x.md" in r.stdout, r.stdout
    assert "Traceback" not in r.stderr, f"a raw traceback reached the operator: {r.stderr}"
    # `"ROLLED BACK:" in stdout` was the original assertion here and the round's guard lens
    # killed it: that substring is satisfied equally by `ROLLED BACK: none` (correct) and
    # `ROLLED BACK: feat-x.md` (the lie you get when `removed.append` is hoisted above the
    # unlink). Pinning the full line is what makes this an ordering test on the unlink arm.
    assert "ROLLED BACK: none" in r.stdout, (
        f"a doc that was never unlinked was reported as rolled back: {r.stdout}"
    )


def test_the_rollbacks_population_is_not_the_worktree_alone(scripts):
    """A declared REVERSION guard, and its limit is stated rather than left implied.

    The defect was that the loop's population came solely from the worktree, so on a route
    where the worktree has no docs it ran zero times over a main that was holding one. What
    has to stay true is that main's own directory is read as a source of names, gated on the
    branch claim — not merely as the place each name is looked up.

    **What this cannot catch:** it matches on a phrase, so a dead-branch construction keeps
    the phrase while reverting the behaviour. The battery's `M01` is that revert, and it is
    killed by the behaviour tests above, not by this one — which is where the weight actually
    sits. This guard is cheap insurance against a silent refactor, not the coverage.
    """
    rollback = _heredocs()[1]
    assert "_md_names(live)" in rollback, (
        "the rollback's population no longer reads main's own pending-docs, so the "
        "`Q-470` route reverts to iterating zero worktree docs and reporting success"
    )
    assert "branch_of(live / n) == branch" in rollback, (
        "main's docs entered the population without the branch-claim gate — that is the "
        "foreign-branch deletion Phase 210 fixed"
    )
def test_convention_candidates_is_excluded_even_when_it_claims_this_branch(scripts, tmp_path):
    """`NOT_A_BRANCH_DOC` is an exclusion from the POPULATION, and the battery found nothing
    testing it as one.

    The sibling above puts a `convention-candidates.md` in place that claims no branch, so it
    lands in `LEFT ALONE` on its branch claim alone and the exclusion never has to fire —
    deleting the filter left that test green. The file is never collected, so it can never be
    something this step rolled back, whatever its frontmatter says.
    """
    _, rollback = scripts
    main, wt = tmp_path / "main", _checkout(tmp_path / "wt")
    _doc(_live(main) / "convention-candidates.md", "feat/x", "NEVER COLLECTED")
    _doc(wt / "sysop" / "runtime" / "pending-docs" / "convention-candidates.md",
         "feat/x", "NEVER COLLECTED")

    r = _run(rollback, main, wt)

    assert r.returncode == 0, r.stdout
    assert "convention-candidates.md" not in r.stdout, (
        f"the never-collected doc entered the rollback's population: {r.stdout}"
    )
    kept = _live(main) / "convention-candidates.md"
    assert kept.is_file() and "NEVER COLLECTED" in kept.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "occupant",
    [None, "dangling-symlink", "directory"],
    ids=["no entry at all", "a dangling symlink", "a directory"],
)
def test_main_s_only_copy_is_left_in_place_and_said_out_loud(scripts, tmp_path, occupant):
    """`Q-482`, as its own round settled it — and the phase's FIRST answer was worse.

    That answer moved main's copy into the worktree. The round disqualified it by execution:
    `git worktree remove`, the command step (b) is trying to run, deletes a worktree's
    gitignored `sysop/runtime/` content SILENTLY at exit 0 (verified directly), and
    `claim_task.sh` runs it at two sites with no pending-doc awareness anywhere in the file.
    So the move relocated the only copy of a record into the one directory scheduled for
    deletion — turning a REPORTING defect into a durability one.

    What has to hold now: the doc is not removed, not moved, and not reported as a success.
    All three occupants are the same case — the worktree holds no readable copy — because the
    discriminator must not confuse "something is at that name" with "the record survives".
    """
    _, rollback = scripts
    main, wt = tmp_path / "main", _checkout(tmp_path / "wt")
    _doc(_live(main) / "feat-x.md", "feat/x", "THE ONLY RECORD")
    src = wt / "sysop" / "runtime" / "pending-docs"
    if occupant is not None:
        src.mkdir(parents=True)
        if occupant == "dangling-symlink":
            (src / "feat-x.md").symlink_to(src / "nowhere.md")
        else:
            (src / "feat-x.md").mkdir()

    r = _run(rollback, main, wt)

    assert r.returncode == 8, f"main still holds the doc; exit 0 is a false pass: {r.stdout}"
    assert "MAIN'S ONLY COPY, LEFT IN PLACE: feat-x.md" in r.stdout, r.stdout
    assert "ROLLED BACK: none" in r.stdout, "the only copy was unlinked"
    assert "Do NOT delete it by hand" in r.stdout, (
        "the operator is told main still holds it without being told not to fix it by hand"
    )
    kept = _live(main) / "feat-x.md"
    assert kept.is_file() and "THE ONLY RECORD" in kept.read_text(encoding="utf-8")
    if occupant == "directory":
        # Only meaningful for this parameter: a path *under* a dangling symlink can never
        # exist, so asserting it for the other two measures nothing. The round's guard lens
        # pointed out the original did exactly that in two runs of three.
        assert not (src / "feat-x.md" / "feat-x.md").exists(), (
            "shutil.move nested the doc inside the destination directory, out of the "
            "collect's non-recursive glob"
        )


def test_the_rollback_never_writes_into_the_worktree_at_all(scripts):
    """The structural half of the round's HIGH finding.

    A behaviour test cannot see a write arm reintroduced on a path its fixtures do not reach,
    and the reason no write belongs here is not obvious from the code: the worktree's
    `sysop/runtime/` is deleted silently by `git worktree remove`. This step reads that
    directory and never writes to it.
    """
    rollback = _heredocs()[1]
    for forbidden in ("shutil.move", "src_dir.mkdir", "shutil.copy", "os.replace"):
        assert forbidden not in rollback, (
            f"the rollback writes into the worktree via {forbidden!r} — that directory is "
            f"deleted silently by `git worktree remove`, the command step (b) is running"
        )


@pytest.mark.parametrize(
    "shape", ["yaml-recursion", "fifo"], ids=["a YAML nesting bomb", "a FIFO"]
)
def test_a_bystander_doc_cannot_crash_or_hang_the_rollback(scripts, tmp_path, shape):
    """The population `Q-482` widened is the population this covers, and the phase's own
    nine-case corpus missed it: every case there was about the TARGET doc.

    Reading main's directory for names means `branch_of` now parses docs with nothing to do
    with the branch being processed. Measured before the fix: the nesting bomb raised
    `RecursionError` straight through `except yaml.YAMLError` — exit 1, empty stdout, on the
    half that deletes — and the FIFO blocked `read_text` forever.
    """
    _, rollback = scripts
    main, wt = tmp_path / "main", _checkout(tmp_path / "wt")
    _doc(_live(main) / "feat-x.md", "feat/x", "mine")
    _doc(wt / "sysop" / "runtime" / "pending-docs" / "feat-x.md", "feat/x", "the original")
    bystander = _live(main) / "neighbour.md"
    if shape == "yaml-recursion":
        bystander.write_text("---\nbranch: " + "[" * 80000 + "\n---\n", encoding="utf-8")
    else:
        os.mkfifo(bystander)

    r = subprocess.run(
        [sys.executable, str(rollback), str(wt), "feat/x"],
        cwd=main, capture_output=True, text=True, timeout=90,
    )

    assert r.returncode == 0, f"a bystander doc changed this branch's outcome: {r.stdout}"
    assert "Traceback" not in r.stderr, f"a raw traceback reached the operator: {r.stderr}"
    assert "ROLLED BACK: feat-x.md" in r.stdout, r.stdout


def test_the_rollback_exit_8_row_names_every_line_that_can_produce_it():
    """A RECURRENCE guard, and it exists because the count form kept being wrong.

    Phase 284 shipped an exit-4 row saying "two conditional arms" when the code had three.
    Phase 285 shipped an exit-4 row naming four arms when the code had five — the same class,
    the next phase, caught by a human re-read both times. `tools/AUTHOR_DEFECT_REGISTER.md`'s
    rule is that a recurrence gets mechanized or dropped rather than written a second time.

    Counting arms is not mechanizable from prose. What IS mechanizable is the thing the count
    was standing in for: every report line that can send the operator to this exit must be
    named in its row, so looking the code up actually finds the remedy. The rows no longer
    assert a number, and this pins the naming instead.
    """
    rollback = _heredocs()[1]
    body = SKILL.read_text(encoding="utf-8")
    header = "| exit | meaning | state of the record | what to do |"
    table = body[body.index(header):]
    table = table[: table.index("\n\n")]
    rows = [ln for ln in table.split("\n") if "| **8** |" in ln]
    assert len(rows) == 1, f"expected exactly one exit-8 row, found {len(rows)}"
    row = rows[0]

    # Derive the report lines from the heredoc rather than listing them here.
    emitted = {
        lit for lit in ("MAIN'S ONLY COPY, LEFT IN PLACE:", "PENDING-DOC ROLLBACK FAILED:")
        if lit in rollback
    }
    assert emitted, "neither exit-8 report line is emitted any more; this guard lost its subject"
    missing = sorted(lit for lit in emitted if lit.strip(":") not in row)
    assert not missing, (
        f"exit 8's row does not name {missing} — an operator who saw that line has no row "
        f"telling them which of the exit's cases they are in"
    )


@pytest.mark.parametrize("alias", ["symlink", "hardlink"])
def test_an_alias_of_mains_own_copy_is_not_a_surviving_copy(scripts, tmp_path, alias):
    """The round's guard lens found this OUTSIDE its mutation frame, on the shipped heredoc.

    `is_file()` follows symlinks, so a worktree entry that is a symlink pointing AT main's own
    copy answered "a copy survives". The step then unlinked the file the link points to and
    the link dangled: `ROLLED BACK: feat-x.md`, exit 0, **zero readable copies** — the exact
    outcome this phase exists to prevent. The collect, one heredoc away, already refuses
    file-identity aliasing at exit 7 (`SameFileError`), so the half that copies guarded it and
    the half that deletes did not.

    The two alias shapes are deliberately NOT treated alike, which is why this is
    parametrized: a hardlink IS a surviving copy — unlinking one link leaves the other
    readable — so holding it too would be a false alarm on the one aliasing shape that is
    fine. Comparing resolved paths separates them; `samefile` would not.
    """
    _, rollback = scripts
    main, wt = tmp_path / "main", _checkout(tmp_path / "wt")
    _doc(_live(main) / "feat-x.md", "feat/x", "THE ONLY RECORD")
    src = wt / "sysop" / "runtime" / "pending-docs"
    src.mkdir(parents=True)
    if alias == "symlink":
        (src / "feat-x.md").symlink_to(_live(main) / "feat-x.md")
    else:
        os.link(_live(main) / "feat-x.md", src / "feat-x.md")

    r = _run(rollback, main, wt)
    readable = [q for q in (_live(main) / "feat-x.md", src / "feat-x.md") if q.is_file()]

    assert readable, "the only copy of the record was destroyed by an alias reading as a copy"
    if alias == "symlink":
        assert r.returncode == 8, f"an alias was treated as a surviving copy: {r.stdout}"
        assert "MAIN'S ONLY COPY, LEFT IN PLACE: feat-x.md" in r.stdout, r.stdout
        assert "ROLLED BACK: none" in r.stdout, r.stdout
    else:
        assert r.returncode == 0, f"a genuine hardlinked copy was held: {r.stdout}"
        assert "ROLLED BACK: feat-x.md" in r.stdout, r.stdout


def test_the_rollbacks_exit_table_lives_in_the_step_it_documents():
    """The round's guard lens moved the table ~1,900 lines away, into an unrelated step, and
    every guard stayed green: they resolve it by header uniqueness with no proximity rule.

    Deleting the table outright IS caught. Misplacing it was not — and a remedy an operator
    halting at step (b) cannot find is the same failure as a remedy that is not written.
    """
    body = SKILL.read_text(encoding="utf-8")
    header = "| exit | meaning | state of the record | what to do |"
    assert body.count(header) == 1
    table_at = body.index(header)
    # the rollback heredoc is the second `<worktree-path>` invocation in the file
    first = body.index('python3 - "<worktree-path>" "<branch name>"')
    rollback_at = body.index('python3 - "<worktree-path>" "<branch name>"', first + 1)
    step4_at = body.index("\n## Step 4:")
    assert rollback_at < table_at < step4_at, (
        "the rollback's exit table is not between its heredoc and the end of Step 3b — an "
        "operator halting at step (b) has to go looking for the remedy"
    )


def test_a_foreign_doc_with_no_worktree_twin_is_never_mentioned(scripts, tmp_path):
    """The branch-claim gate on the union's `live` half had TEXT coverage only.

    The round's guard lens showed the author's own revert of it is killed solely because that
    spelling deletes a literal string a phrase guard asserts — keep the literal alive in a
    dead lambda and the identical behaviour change is green. The dangerous direction
    (narrowing back to the worktree alone) is covered behaviourally; this covers the widening
    direction, where main's unrelated docs enter the population and surface as noise in a
    report that decides whether an operator goes looking for a problem.
    """
    _, rollback = scripts
    main, wt = tmp_path / "main", _checkout(tmp_path / "wt")
    _doc(_live(main) / "feat-x.md", "feat/x", "mine")
    _doc(_live(main) / "someone-else.md", "feat/other", "NOT THIS BRANCH")
    _doc(wt / "sysop" / "runtime" / "pending-docs" / "feat-x.md", "feat/x", "the original")

    r = _run(rollback, main, wt)

    assert r.returncode == 0, r.stdout
    assert "ROLLED BACK: feat-x.md" in r.stdout
    assert "someone-else.md" not in r.stdout, (
        f"another branch's doc entered this branch's population: {r.stdout}"
    )
    assert (_live(main) / "someone-else.md").is_file(), "another branch's record was removed"


# ------------------------------------------- the `Q-470` route walked past `Q-471` (`Q-483`)


def test_a_stale_doc_on_main_is_caught_when_the_worktree_has_none(scripts, tmp_path):
    """Phase 282 shipped `Q-470` and `Q-471` together, and the first walked past the second.

    `Q-470` made an absent worktree `pending-docs/` a legitimate exit-0 state; `Q-471` added
    the `branch_tip:` comparison. But the comparison lived inside the `src_dir`-PRESENT loop
    and the `Q-470` arm returns before it — so a doc authored into the MAIN checkout (the
    path `/document-work` explicitly supports, and the one `Q-470` exists to let through)
    was never compared against the branch tip at all.

    The harm is not a lost record, it is a false one: Step 4c routes the outdated `summary:`
    into the shared docs **in the same commit that flips the task `done`**, so two durable
    artifacts disagree and the close reports success.
    """
    collect, _ = scripts
    main = tmp_path / "main"
    tip = _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    # authored on MAIN, so the worktree has no pending-docs of its own
    _tipped(_live(main) / "feat-x.md", "feat/x", "ADDS THE PARSER", tip)
    _commit_on(wt, "rewrote the parser and removed it again")

    r = _run(collect, main, wt)

    assert r.returncode == 6, f"the stale doc on main was not caught: {r.returncode} {r.stdout}"
    assert "PENDING-DOC STALE: feat-x.md" in r.stdout, r.stdout
    # Every quantity in the report, because the round's guard lens walked all of them: the
    # per-doc line was asserted and the TALLY was not (so `len(stale_here)` could report 0
    # while refusing 1 — and SKILL.md names these lines as Step 8's only source), the drift
    # COUNT was not (so `{drift}` could be off by one), and the log line's label was not.
    assert "1 commit(s) landed" in r.stdout, f"the drift count is wrong or absent: {r.stdout}"
    assert "PENDING-DOC STALE: 1 — refusing" in r.stdout, (
        f"the tally disagrees with the refusal, or is missing: {r.stdout}"
    )
    assert "    after the doc: " in r.stdout, "the log line must carry its label"
    assert "rewrote the parser" in r.stdout, "the report must name what landed after the doc"
    # A refusal must NOT also print the collect's success marker. Step 8 reads that line.
    assert "PENDING-DOC COLLISIONS: 0" not in r.stdout, (
        f"a refusing run printed the success marker Step 8 reads: {r.stdout}"
    )
    assert (_live(main) / "feat-x.md").is_file(), (
        "refusing must not remove the only copy of the record"
    )


def test_a_CURRENT_doc_on_main_with_no_worktree_copy_still_passes(scripts, tmp_path):
    """The over-strictness direction, which is where a staleness gate does its damage.

    `Q-470`'s whole point is that this route is ORDINARY. If adding the comparison turned it
    into a refusal for every main-authored doc, the fix would be worse than the defect: every
    close of a branch whose doc was written on the main checkout would halt.
    """
    collect, _ = scripts
    main = tmp_path / "main"
    tip = _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(_live(main) / "feat-x.md", "feat/x", "ADDS THE PARSER", tip)   # no drift

    r = _run(collect, main, wt)

    assert r.returncode == 0, f"a current doc was refused: {r.returncode} {r.stdout}"
    assert "COLLECT SKIPPED" in r.stdout
    assert "PENDING-DOC STALE" not in r.stdout, r.stdout
    assert "PENDING-DOC COLLISIONS: 0" in r.stdout, "Step 8 reads this line"


def test_a_main_side_doc_with_no_branch_tip_fails_open_on_this_route_too(scripts, tmp_path):
    """The same fail-open `Q-470` is on this page for, on the arm `Q-471` now also covers.

    Every doc written before `branch_tip:` existed has none. Refusing those would halt every
    consumer's first close after an update — so absence of a measurement is reported, never
    treated as a measurement.
    """
    collect, _ = scripts
    main = tmp_path / "main"
    _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(_live(main) / "feat-x.md", "feat/x", "LEGACY DOC", None)
    _commit_on(wt, "work that landed after")

    r = _run(collect, main, wt)

    assert r.returncode == 0, f"a doc with no branch_tip was refused: {r.stdout}"
    assert "PENDING-DOC STALENESS UNKNOWN" in r.stdout, r.stdout
    assert "no `branch_tip:`" in r.stdout


def test_the_staleness_comparison_has_exactly_one_reader():
    """Single-sourced, and this is what keeps it that way.

    The defect `Q-483` fixed was one rule living at one of two sites that both needed it.
    Copying it into the second site would have fixed the symptom and recreated the class this
    step already paid for once — the rollback hand-rolled a frontmatter scan while the collect
    used yaml, and the two halves of one step disagreed on 18 of 33 shapes.

    **Derived from the AST, not from literals, and the round is why.** The first cut asserted
    `collect.count("staleness(") == 3` and `"tip_of(src)"` — which the guard lens walked in
    both directions at once: a hand-rolled second reader added *beside* the call kept both
    counts intact and passed, while two behaviour-preserving renames (the helper, and its loop
    variable) went red. It measured spelling, and it measured it in the wrong direction.
    """
    collect = _heredocs()[0]
    tree = ast.parse(collect)

    # 1. Exactly ONE function may read the frontmatter key. A constant STARTING WITH
    #    `branch_tip` is the key itself or a hand-rolled `startswith('branch_tip:')` scan;
    #    the message strings that merely mention it start with other characters.
    def reads_key(node):
        return any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                   and n.value.startswith("branch_tip") for n in ast.walk(node))

    fns = [f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)]
    readers = sorted(f.name for f in fns if reads_key(f))
    assert len(readers) == 1, (
        f"{len(readers)} functions read `branch_tip` ({readers}); there must be exactly one, "
        f"or the two will disagree about a doc the way the collect and rollback once did"
    )
    reader = readers[0]

    # 2. ...and nothing may read it OUTSIDE a function, which is where an inline scan lands.
    outside = ast.Module(body=[n for n in tree.body if not isinstance(n, ast.FunctionDef)],
                         type_ignores=[])
    assert not reads_key(outside), (
        "`branch_tip` is read at module level, outside the single reader — that is a second "
        "reader by another name"
    )

    # 3. The helper that calls the reader must be reached from BOTH routes. Names derived,
    #    so a rename of either function is not a finding.
    helpers = sorted(f.name for f in fns
                     if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                            and n.func.id == reader for n in ast.walk(f)))
    assert len(helpers) == 1, f"expected one caller of {reader!r}, found {helpers}"
    helper = helpers[0]

    lines = collect.split("\n")
    absent_at = next(i for i, l in enumerate(lines) if "if not src_dir.is_dir():" in l)
    populated_at = next(i for i, l in enumerate(lines)
                        if "docs = [p for p in sorted(src_dir.glob" in l)
    calls = [n.lineno for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == helper]
    assert any(absent_at < ln <= populated_at + 1 for ln in calls), (
        f"the `Q-470` absent-src_dir route never calls {helper!r} — that is `Q-483` in full"
    )
    assert any(ln > populated_at for ln in calls), (
        f"the src_dir-present route never calls {helper!r}"
    )

def test_a_foreign_doc_on_main_never_refuses_this_branchs_close(scripts, tmp_path):
    """The absent-`src_dir` arm's population must be main's docs claiming THIS branch.

    Widening it to every `*.md` in main's pending-docs would let another branch's stale doc
    refuse a close this branch has no part in — the mirror of the guard the populated path
    already carries, on the arm that previously had no population at all.
    """
    collect, _ = scripts
    main = tmp_path / "main"
    _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    # The first draft of this fixture stamped MY doc, then committed — which made my own
    # doc stale, so the refusal it caught was correct and the test was measuring nothing.
    # Commit first, then stamp at the resulting tip: mine current, theirs not.
    _commit_on(wt, "work on this branch")
    tip = _g(main, "rev-parse", "feat/x").stdout.strip()
    _tipped(_live(main) / "feat-x.md", "feat/x", "MINE, CURRENT", tip)
    _tipped(_live(main) / "someone-else.md", "feat/other", "NOT MINE", "0" * 40)

    r = _run(collect, main, wt)

    assert r.returncode == 0, (
        f"another branch's doc refused this branch's close: {r.returncode} {r.stdout}"
    )
    assert "someone-else.md" not in r.stdout, (
        f"another branch's doc was measured for this branch's staleness: {r.stdout}"
    )


def test_a_fifo_in_mains_pending_docs_cannot_hang_the_collect(scripts, tmp_path):
    """`glob('*.md')` matches by NAME, so a FIFO carrying that name reaches the readers —
    and `read_text` on a FIFO blocks forever, which no caller recovers from.

    This guards `branch_of`, which is the reader that actually receives a bystander. An
    earlier docstring here said `Q-483` meant such a file "now reaches two readers instead of
    none" — **both halves were false, and the round caught it**: `56cef41` already ran
    `branch_of` over every `*.md` in main's pending-docs, and after the change a bystander
    still reaches exactly that one reader, because the staleness population is pre-filtered.
    The test is a sound regression guard for `branch_of`; its rationale was not what it
    measured.
    """
    collect, _ = scripts
    main = tmp_path / "main"
    tip = _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(_live(main) / "feat-x.md", "feat/x", "MINE", tip)
    os.mkfifo(_live(main) / "neighbour.md")

    r = subprocess.run(
        [sys.executable, str(collect), str(wt), "feat/x"],
        cwd=main, capture_output=True, text=True, timeout=60,
    )

    assert r.returncode == 0, f"a bystander changed this branch's outcome: {r.stdout}"
    assert "Traceback" not in r.stderr, r.stderr
    assert "COLLECT SKIPPED" in r.stdout


def test_absent_and_empty_are_dispositioned_alike_on_a_REAL_repo_with_drift(scripts, tmp_path):
    """The invariant's sibling above runs on `_checkout()` — a FAKE `.git` file, an empty main
    and no drift — so there is no doc to measure and no repo to measure it in, and it stayed
    green while `Q-483`'s first cut split the two states wide open.

    Found by Phase 286's round. The file states the invariant two lines above the arm that
    phase rewrote: *"an existing but EMPTY `src_dir` … The two states must not be
    dispositioned differently, and that is the property to preserve if this arm is ever
    rewritten."* Measured on the round's fixtures before the fix: absent exited **6**, empty
    exited **0**, over the identical stale doc on main.

    Real repo, real worktree, real drift — so the measurement actually runs.
    """
    collect, _ = scripts
    out = {}
    for label in ("absent", "empty"):
        main = tmp_path / f"{label}_main"
        tip = _repo(main)
        wt = _worktree(main, tmp_path / f"{label}_wt")
        _tipped(_live(main) / "feat-x.md", "feat/x", "STALE", tip)
        if label == "empty":
            (wt / "sysop" / "runtime" / "pending-docs").mkdir(parents=True)
        _commit_on(wt, "landed after the doc")
        out[label] = _run(collect, main, wt)

    assert out["absent"].returncode == out["empty"].returncode, (
        f"absent exited {out['absent'].returncode} and empty exited "
        f"{out['empty'].returncode} over the identical stale doc — the two states are "
        f"dispositioned differently, which this file forbids in as many words"
    )
    for label, r in out.items():
        assert r.returncode == 6, f"{label}: stale doc on main not caught ({r.stdout})"
        assert "PENDING-DOC STALE: feat-x.md" in r.stdout, f"{label}: {r.stdout}"


def test_the_exit_6_remedy_does_not_turn_the_gate_off(scripts, tmp_path):
    """Phase 286's round, HIGH: the remedy the exit-6 row prescribes used to DISABLE the gate.

    `/document-work` runs `mkdir -p sysop/runtime/pending-docs` unconditionally and writes one
    doc named after the sanitized branch. So on the `Q-470` route, applying the documented
    remedy created the directory and moved the next close onto the arm that did not measure
    main's docs — the operator did exactly what the table said and the close then proceeded
    carrying the stale doc the gate exists to stop.

    Measured before the fix: first run exit 6 naming two stale docs; after the remedy, exit 0
    with the second one still sitting on main.
    """
    collect, _ = scripts
    main = tmp_path / "main"
    tip = _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(_live(main) / "feat-x.md", "feat/x", "STALE", tip)
    _tipped(_live(main) / "feat-x-older.md", "feat/x", "ALSO STALE", tip)
    _commit_on(wt, "landed after both docs")

    first = _run(collect, main, wt)
    assert first.returncode == 6, first.stdout
    assert "feat-x-older.md" in first.stdout

    # the remedy, exactly as /document-work performs it: mkdir -p, then one branch-named doc
    src = wt / "sysop" / "runtime" / "pending-docs"
    src.mkdir(parents=True)
    _tipped(src / "feat-x.md", "feat/x", "FRESH",
            _g(main, "rev-parse", "feat/x").stdout.strip())

    second = _run(collect, main, wt)

    assert second.returncode == 6, (
        f"the documented remedy turned the gate off: {second.returncode} {second.stdout}"
    )
    assert "PENDING-DOC STALE: feat-x-older.md" in second.stdout, (
        f"main's other stale doc survived the remedy uncaught: {second.stdout}"
    )
    assert "feat-x.md —" not in second.stdout, (
        "the re-stamped doc is about to be overwritten by the fresh copy, so its staleness "
        "is about to stop existing and must not refuse the close"
    )


def test_a_main_side_doc_is_measured_in_main_not_in_a_clone_workspace(scripts, tmp_path):
    """Phase 286's round, MEDIUM: on the `Q-470` route the measurement ran in the WORKSPACE.

    `_git` defaults to `-C wt`, and that default has a good argument behind it — a `--clone`
    workspace is a separate repository whose commits live in its own object store, so a doc
    collected FROM the workspace must be measured there. But a doc already on MAIN was
    authored on the main checkout, which is what `Q-470`'s first reading means, and asking a
    clone about it asks a repository that need not hold the commits.

    The failure mode is the bad one: `rev-list` SUCCEEDS and returns 0, so the run reports
    measured-and-clean over a record it never measured — silent, not fail-open.
    """
    collect, _ = scripts
    main = tmp_path / "main"
    tip = _repo(main)
    clone = _clone(main, tmp_path / "clone")
    # the doc lives on main, stamped at the tip as it was then
    _tipped(_live(main) / "feat-x.md", "feat/x", "STALE", tip)
    # main's branch moves on; the clone knows nothing about it
    _commit_on(main, "landed on the branch after the doc")

    assert _g(clone, "rev-list", "--count", f"{tip}..feat/x").stdout.strip() == "0", (
        "fixture is not exercising the split — the clone already sees the drift"
    )

    r = _run(collect, main, clone)

    assert r.returncode == 6, (
        f"a main-side doc's drift was measured in the clone, which cannot see it: "
        f"{r.returncode} {r.stdout}"
    )
    assert "PENDING-DOC STALE: feat-x.md" in r.stdout, r.stdout


def test_the_populated_routes_main_side_term_ignores_another_branchs_doc(scripts, tmp_path):
    """The populated route now measures main's SURVIVING docs too, and that term needs the
    same branch-claim filter the worktree term has.

    Found by this phase's own battery as a survivor: the existing foreign-doc guards cover the
    absent route (where `on_main` is filtered when it is built) and the worktree term, so
    dropping the filter from the new main-side term left the suite green.
    """
    collect, _ = scripts
    main = tmp_path / "main"
    _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _commit_on(wt, "work on this branch")
    tip = _g(main, "rev-parse", "feat/x").stdout.strip()
    # the worktree's doc is CURRENT and lands under its own name
    _tipped(wt / "sysop" / "runtime" / "pending-docs" / "feat-x.md", "feat/x", "FRESH", tip)
    # main holds another branch's doc, long stale by its own branch's standards
    _tipped(_live(main) / "someone-else.md", "feat/other", "NOT MINE", "0" * 40)

    r = _run(collect, main, wt)

    assert r.returncode == 0, (
        f"another branch's doc on main refused this branch's close: {r.returncode} {r.stdout}"
    )
    assert "someone-else.md" not in r.stdout, r.stdout
    assert "PENDING-DOC COLLECTED: feat-x.md" in r.stdout, r.stdout


def test_the_populated_routes_main_side_term_is_measured_in_main(scripts, tmp_path):
    """The other half of the same battery survivor.

    `_git` defaults to the workspace, which is right for a doc collected FROM the workspace
    and wrong for one already on main. The clone shape is where the two answers diverge: a
    `--clone` workspace is a separate repository and need not hold main's commits, and
    `rev-list` SUCCEEDS there — so the run reports measured-and-clean over a record it never
    measured. The sibling clone test covers the ABSENT route; this covers the populated one.
    """
    collect, _ = scripts
    main = tmp_path / "main"
    tip = _repo(main)
    clone = _clone(main, tmp_path / "clone")
    # a doc on main under a name the incoming copy will NOT overwrite -> it survives
    _tipped(_live(main) / "feat-x-notes.md", "feat/x", "STALE", tip)
    _commit_on(main, "landed on the branch after the notes doc")
    # the clone brings its own, current by the clone's own view
    _tipped(clone / "sysop" / "runtime" / "pending-docs" / "feat-x.md", "feat/x", "FRESH",
            _g(clone, "rev-parse", "feat/x").stdout.strip())

    assert _g(clone, "rev-list", "--count", f"{tip}..feat/x").stdout.strip() == "0", (
        "fixture is not exercising the split — the clone already sees main's drift"
    )

    r = _run(collect, main, clone)

    assert r.returncode == 6, (
        f"a surviving main-side doc was measured in the clone, which cannot see the drift: "
        f"{r.returncode} {r.stdout}"
    )
    assert "PENDING-DOC STALE: feat-x-notes.md" in r.stdout, r.stdout


@pytest.mark.parametrize(
    "tipval, why",
    [
        ("0" * 40, "a 40-zero sha, which YAML parses as the INT 0 rather than a string"),
        ("--all", "a value beginning with a dash, the option-injection shape SHA_RE exists for"),
        ("-n1", "a short option"),
        ("<branch tip>", "the writer emitted its own template verbatim"),
        ("null", "a YAML null"),
        ("not-a-sha", "a string that is not an object name"),
    ],
)
def test_a_hostile_branch_tip_on_the_main_side_route_fails_open(scripts, tmp_path, tipval, why):
    """The `Q-483` arm's hostile corpus, living in the tests rather than in a scratch script.

    Phase 286's author-side pass ran a ten-case corpus and reported it in the record — but the
    corpus itself was an unpreserved script, and the round's record lens correctly called the
    claim unverifiable, noting that two of its cases appear in no test at all. This repo's own
    rule is that the corpus lives here.

    Every one of these must reach `PENDING-DOC STALENESS UNKNOWN` and **exit 0**. Fail-open is
    the whole disposition `Q-470` is on this page for: a doc whose `branch_tip` cannot be read
    is an absent measurement, never a measurement of staleness, and refusing on one would halt
    every close carrying a legacy or machine-mangled doc.
    """
    collect, _ = scripts
    main = tmp_path / "main"
    _repo(main)
    wt = _worktree(main, tmp_path / "wt")
    _tipped(_live(main) / "feat-x.md", "feat/x", "MAIN-AUTHORED", tipval)
    _commit_on(wt, "work that landed after the doc")

    r = _run(collect, main, wt)

    assert r.returncode == 0, f"{why}: refused instead of failing open ({r.stdout})"
    assert "PENDING-DOC STALENESS UNKNOWN" in r.stdout, f"{why}: {r.stdout}"
    assert "PENDING-DOC STALE:" not in r.stdout, (
        f"{why}: an unreadable tip was reported as a measured drift"
    )
    assert "Traceback" not in r.stderr, r.stderr
