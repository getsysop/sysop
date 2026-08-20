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

import re
import subprocess
import sys
from pathlib import Path

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


def _run(script: Path, main: Path, wt: Path, branch: str = "feat/x") -> subprocess.CompletedProcess:
    """The branch being processed is an INPUT, not something inferred from the docs.

    Round 3 found that asking "do these two docs agree with each other" instead of "does
    this doc belong to the branch I am processing" let a worktree carrying a foreign-branch
    doc overwrite and then delete another branch's only surviving record, reporting
    `COLLISIONS: 0` and exit 0 throughout.
    """
    return subprocess.run(
        [sys.executable, str(script), str(wt), branch],
        cwd=main, capture_output=True, text=True,
    )


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


def test_an_uncopyable_doc_halts_rather_than_half_collecting(scripts, tmp_path):
    """Round 2, MEDIUM. `branch_of` caught OSError but `shutil.copy2` did not, so a
    broken symlink or a directory named `*.md` left a partial collect with no undo and a
    traceback. Step 3b must not remove a worktree whose docs are not all on main."""
    collect, _ = scripts
    main, wt = tmp_path / "main", tmp_path / "wt"
    live = _live(main)
    live.mkdir(parents=True)
    pd = wt / "sysop/runtime/pending-docs"
    _doc(pd / "aaa.md", "feat/x", "FINE")
    # Both docs clear stage 1; the WRITE is what fails, which is the only way to reach
    # stage 2's failure arm — an unreadable source is refused earlier, at stage 1.
    live.chmod(0o500)
    try:
        r = _run(collect, main, wt)
    finally:
        live.chmod(0o700)

    assert r.returncode == 5, f"expected the copy failure to halt: {r.returncode} {r.stdout}"
    assert "COLLECT FAILED" in r.stdout


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
    m = _re.search(r"\npython3 - \"\$SMOKE_WORKTREE_DIRS\" <<'EOF'\n(.*?)\nEOF\n",
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

        r = _sp.run([sys.executable, str(d / "script.py"), ""],
                    cwd=d, capture_output=True, text=True)

    assert r.returncode == 0, (
        "Step 3c died on a malformed pending-doc — it runs before Step 4c, so arm 3 "
        f"never gets the chance to quarantine it:\n{r.stdout}\n{r.stderr}"
    )
