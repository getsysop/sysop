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
    assert "untouched" in state and "stage 1 writes nothing" in state
    assert "/document-work" in todo, "the remedy must be in the WHAT-TO-DO column"
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
        "COLLECT FAILED": None,       # exit 5 — likewise
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
