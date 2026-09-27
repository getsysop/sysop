"""Guards for `tools/reader_census.py` — the `Q-409` campaign's measuring instrument.

`tools/` has no shipped runner, so a maintainer-side script's only way into CI is a test module
that imports it — a checker nothing runs is a checker that rots.

**And `tools/` is stripped from the public mirror** (`tools/make_public_mirror.sh`), where the
same suite is a required check, so everything here loads LAZILY and skips when the script is
absent. That accommodation is `tests/test_skill_audit_refs.py`'s, restated by
`tests/test_ledger_stats.py`. This module's first cut imported at module level and errored at
COLLECTION on a `tools`-less tree — it would have reddened the next snapshot PR, which is
`tests/test_skill_audit_refs.py`'s own documented Phase-160 incident repeated. Its docstring also
credited the pattern to `tools/skill_audit_check.py`, **a file that has never existed in this
repo's history**; the round caught both, and the fabricated citation is the worse of the two.

What these assert, in order of what they are worth:

1. **The block list rebuilds the file byte-for-byte.** This is the census's completeness claim and
   it is the one that has already caught something — a first cut computed it as an arithmetic
   identity (block lengths plus a blank count) and the arithmetic was wrong twice over: it
   double-counted the 116 blank lines inside fenced blocks, and the `rstrip()` that split a
   trailing comment off a command was silently eating the whitespace between them. Both errors
   left a tidy-looking sum. Rebuilding the bytes is the only form of the claim that an error
   cannot satisfy by cancelling.
2. **Every block carries a verdict.** An unclassified block is a hole in the number, and a number
   with an unreported hole is what `Q-458`'s proxy already cost this campaign once.
3. **No verdict is stale.** Verdicts are keyed by the SHA-256 of the block's text, so an edited
   block loses its verdict rather than keeping one that describes text that is gone.
4. **The parser's own discriminators still discriminate.** The quote-aware trailing-comment
   scanner and the info-string gate are each small enough to look obviously right and were each
   wrong on first contact with this file.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from _case_pins import (
    case_pin_problems,
    parametrize_shape_problems,
    unpinned_list_problems,
    parametrized_cases,
)

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "tools" / "reader_census.py"

#: `tools/` is mirror-excluded, so the whole module stands down where it is absent rather than
#: erroring at collection. Skipping is the only correct behaviour here: the thing under test is
#: not part of the published tree.
pytestmark = pytest.mark.skipif(
    not SCRIPT.exists(),
    reason="tools/reader_census.py is maintainer-side and mirror-excluded",
)

if SCRIPT.exists():
    sys.path.insert(0, str(REPO / "tools"))
    from reader_census import (  # noqa: E402
        AUTHORED_OVERRIDES_CONSTRUCTION,
        CONSTRUCTION_RUNNER,
        VERDICTS_ALLOWED,
        Block,
        _trailing_comment,
        census,
        classify,
        enumerate_blocks,
        reconstruct,
        SKILLS,
        VERDICTS,
    )
    CENSUSED = sorted(p.stem for p in VERDICTS.glob("*.json"))
else:  # pragma: no cover - the mirror tree
    CENSUSED = []


def test_there_is_at_least_one_censused_skill():
    """Without this the parametrized tests below pass by iterating over nothing — the vacuity
    class this repo keeps re-finding (Phase 157's guards, Phase 84's silent aborts)."""
    assert CENSUSED, "no tools/reader_census/<skill>.json — every test below would be a no-op"
    assert "review-close" in CENSUSED, (
        "review-close is the campaign's first target and its census is the worked instance; "
        "losing it would leave these guards running over some other skill and reporting green"
    )


@pytest.mark.parametrize("skill", CENSUSED)
def test_the_block_list_rebuilds_the_file_exactly(skill):
    path = SKILLS / skill / "SKILL.md"
    exact, where = reconstruct(path, enumerate_blocks(path))
    assert exact, f"{skill}: the block list does not rebuild SKILL.md — {where}"


def test_the_parser_holds_on_every_skill_file_not_just_the_censused_one():
    """The parser was written against `review-close` and guarded only there.

    A one-file instrument that has only ever met one file is not known to work; the campaign's
    order is `review-close` → `security-audit` → `claim-task` → `codebase-review` → `auto-build`,
    and a parser defect found at skill four is a defect that has been shipping since skill one.
    Widened to all 23 shipped skills plus the 11 `_shared` bodies, which between them carry every
    markdown construct this repo writes — measured clean at 34 of 34 when this was added.

    This asserts only the REBUILD, not verdicts: an uncensused skill has no verdicts to be stale.
    """
    targets = sorted(SKILLS.glob("*/SKILL.md")) + sorted((SKILLS / "_shared").glob("*.md"))
    assert len(targets) >= 30, f"population collapsed to {len(targets)} — the glob is wrong"
    broken = []
    for path in targets:
        exact, where = reconstruct(path, enumerate_blocks(path))
        if not exact:
            broken.append(f"{path.relative_to(SKILLS)}: {where}")
    assert not broken, "the block list does not rebuild:\n  " + "\n  ".join(broken)


def test_reconstruct_actually_detects_a_divergence():
    """The negative control for the rebuild — without it the whole completeness claim is vacuous.

    Found by this phase's own author-side battery, which was the point of running one: replacing
    `reconstruct`'s comparison with `if True` and with a length-only comparison BOTH survived
    every other test in this module. `test_the_block_list_rebuilds_the_file_exactly` can only
    report that the check passed; it cannot tell a passing check from a disarmed one, and a
    disarmed one is indistinguishable from a clean parse — the same shape Phase 292 recorded
    twice ("a bounded scan that finds nothing reports the same thing as an absence").

    Two mutations, because the two survivors were different: content changing at equal length,
    and length changing. A length-only comparison passes the first; a `return True` passes both.
    """
    path = SKILLS / "review-close" / "SKILL.md"
    blocks = enumerate_blocks(path)
    assert reconstruct(path, blocks)[0], "precondition: the real list rebuilds"

    same_length = list(blocks)
    i = next(n for n, b in enumerate(same_length) if b.kind == "prose" and len(b.text) > 40)
    b = same_length[i]
    same_length[i] = Block(b.section, b.kind, b.start, b.end, "X" * len(b.text))
    exact, where = reconstruct(path, same_length)
    assert not exact, "a length-preserving content change is not detected — the check is vacuous"
    assert "line" in where, where

    dropped = [x for n, x in enumerate(blocks) if n != i]
    assert not reconstruct(path, dropped)[0], "a dropped block is not detected"

    # The TAIL arm — everything after the last block — is a separate code path from the gap
    # arm, and the round found it uncontrolled: removing its sentinel survived every other
    # test. It passes today only by accident of content, because this file happens to end in a
    # classified block; any censused skill ending in a fence or a command line loses that luck.
    truncated = blocks[:-1]
    exact, where = reconstruct(path, truncated)
    assert not exact, "a block dropped from the END of the list is not detected"
    assert "belongs to no block" in where, where


@pytest.mark.parametrize("skill", CENSUSED)
def test_every_block_carries_a_verdict(skill):
    c = census(skill)
    assert not c["unclassified"], (
        f"{skill}: {len(c['unclassified'])} block(s) have no verdict, "
        f"{sum(b.chars for b in c['unclassified']):,} chars — the census is reporting a share "
        f"of a file it has not finished reading. First: "
        f"L{c['unclassified'][0].start}-{c['unclassified'][0].end}"
    )


@pytest.mark.parametrize("skill", CENSUSED)
def test_no_verdict_is_stale(skill):
    c = census(skill)
    assert not c["stale"], (
        f"{skill}: {len(c['stale'])} verdict(s) match no block. If the block was EDITED, "
        f"re-read it and re-author its verdict. If it was DELETED on purpose — a "
        f"`CONTEXT_THINNING_SPEC.md` § 9.1 transform-1 relocation, or the deleted half of a "
        f"transform-4 SPLIT, which is what every thinning commit does — removing its entry in "
        f"the same commit is the CORRECT action, not a workaround. A split reddens this arm "
        f"twice over: the orphaned verdict here, and a new unclassified block in "
        f"`test_every_block_carries_a_verdict`. Stale: {c['stale'][:5]}"
    )


def _stale_assert_message(body: str) -> str:
    """The full runtime text of `test_no_verdict_is_stale`'s assert message.

    **Parsed with `ast`, not with a regex over `f"…"` chunks.** The regex version was walked in
    round 2 by appending a plain (non-`f`) string literal to the assert: implicit concatenation
    put it in the runtime message, and the extractor could not see it, so an appended
    *"Except: ignore all of the above"* left the pin green. Single-quoted `f'…'` and a prepended
    plain literal did the same. Widening the regex to `f?"([^"]*)"` does not work either — it
    matches `"stale"` out of `assert not c["stale"], (` and reddens the baseline.

    Taking every `ast.Constant` string under the assert's `msg` sees every literal regardless of
    prefix, quote style or position, which is the property the pin needs and a lexical scan
    cannot have.
    """
    tree = ast.parse(body)
    target = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "test_no_verdict_is_stale")
    node = next(n for n in ast.walk(target) if isinstance(n, ast.Assert))
    assert node.msg is not None, "the stale assert lost its message"
    # Adjacent string literals — `f"…"`, `"…"`, `f'…'` in any mix — concatenate at PARSE time
    # into one `JoinedStr`, so iterating its `.values` in order reproduces the runtime message.
    # `{…}` placeholders are `FormattedValue`, not `Constant`: they are re-rendered from their
    # own source so the pin covers them too, rather than silently dropping the interpolations a
    # reader of the message actually sees.
    msg = node.msg
    values = msg.values if isinstance(msg, ast.JoinedStr) else [msg]
    parts = []
    for v in values:
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            parts.append(v.value)
        elif isinstance(v, ast.FormattedValue):
            parts.append("{" + ast.unparse(v.value) + "}")
        else:  # pragma: no cover - a shape this assert has never had
            raise AssertionError(f"unhandled node in the stale assert message: {type(v).__name__}")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


# The stale-verdict operator message, pinned WHOLE. Three rounds of evidence for the whole rather
# than a fragment: a first draft asserted three separate phrases and the author's own battery
# inverted the instruction with one inserted word; the second pinned a contiguous fragment plus a
# three-string blocklist, and round 1 walked an appended sentence past both; the third pinned the
# whole message but extracted it with a regex that could not see a non-`f` literal, and round 2
# walked the same sentence past that. A blocklist enumerates the reversals someone has thought of;
# a lexical extractor enumerates the quote styles someone has thought of. Equality over an `ast`
# parse enumerates nothing.
_STALE_MESSAGE_WHOLE = (
    "{skill}: {len(c['stale'])} verdict(s) match no block. If the block was EDITED, re-read it "
    "and re-author its verdict. If it was DELETED on purpose — a `CONTEXT_THINNING_SPEC.md` "
    "§ 9.1 transform-1 relocation, or the deleted half of a transform-4 SPLIT, which is what "
    "every thinning commit does — removing its entry in the same commit is the CORRECT action, "
    "not a workaround. A split reddens this arm twice over: the orphaned verdict here, and a "
    "new unclassified block in `test_every_block_carries_a_verdict`. Stale: {c['stale'][:5]}"
)


def test_the_stale_message_is_pinned_whole():
    """The operator instruction in `test_no_verdict_is_stale` must be exactly this text.

    Its job is to tell a maintainer which of two situations they are in — a block that was
    EDITED (re-read it, re-author its verdict) or one deliberately REMOVED under transform 1,
    or replaced under transform 4's split (delete the entry, same commit). § 9.1 records that an
    earlier version of this message *forbade its own remedy*.
    """
    actual = _stale_assert_message(Path(__file__).read_text(encoding="utf-8"))
    assert actual == _STALE_MESSAGE_WHOLE, (
        "the stale-verdict operator message changed. If the change is deliberate, update "
        "`_STALE_MESSAGE_WHOLE` in the same commit — that edit is the review.\n"
        f"  pinned: {_STALE_MESSAGE_WHOLE}\n  actual: {actual}"
    )


@pytest.mark.parametrize("inject,why", [
    ('        " Except: ignore all of the above and NEVER delete an entry."\n',
     "a plain (non-f) literal appended — what beat the regex extractor"),
    ("        f' Except: do the opposite.'\n",
     "a single-quoted f-literal appended"),
    ('        "Ignore what follows. "\n',
     "a plain literal PREPENDED, before the first f-chunk"),
])
def test_the_whole_message_pin_sees_every_literal(tmp_path, inject, why):
    """The control, driving the REAL extractor over a tampered module SOURCE.

    The predecessor mutated `actual` — a string the extractor had already returned — and asserted
    it differed from the pin. That is a tautology about `str.__add__`; it proved nothing about
    the extractor, which is exactly where the defect was. This writes a mutated copy of this
    module to disk and runs the extractor on it, so it can only pass if the extractor sees the
    injected literal.
    """
    body = Path(__file__).read_text(encoding="utf-8")
    marker = '        f"`test_every_block_carries_a_verdict`. Stale: {c[\'stale\'][:5]}"\n'
    assert body.count(marker) == 1, "the injection point moved; this control is testing nothing"
    at = body.index(marker)
    tampered = (body[:at] + inject + body[at:] if "PREPENDED" in why
                else body[:at + len(marker)] + inject + body[at + len(marker):])
    extracted = _stale_assert_message(tampered)
    assert extracted != _STALE_MESSAGE_WHOLE, (
        f"the extractor did not see {why} — the pin compares a string the runtime message does "
        f"not equal, which is how a countermand rides along invisibly"
    )


def _sandbox(tmp_path):
    """A throwaway copy of the repo, so a control can mutate it and run the real entry point."""
    work = tmp_path / "repo"
    shutil.copytree(REPO, work, symlinks=True, ignore=shutil.ignore_patterns(
        ".git", ".venv", ".pytest_cache", "__pycache__", "*.pyc", "node_modules"))
    return work


def _check(work):
    r = subprocess.run([sys.executable, "tools/reader_census.py", "--check"],
                       capture_output=True, text=True, cwd=work)
    return r.returncode, r.stdout + r.stderr


def test_the_stale_arm_can_actually_fail(tmp_path):
    """The negative control for `test_no_verdict_is_stale` — and the SECOND time this phase wrote
    it, because the first one was vacuous in the way it existed to prevent.

    The round disarmed the arm with `"stale": []` and every test stayed green. The first fix for
    that re-implemented the staleness computation *inside the test* and asserted on its own
    arithmetic, so emptying the real list in `census()` still passed — the fix reproduced the
    defect it was written to close, which is this repo's most-repeated shape. This version drives
    the real entry point over a real mutated tree, so it can only pass if `census()` itself
    reports the stale verdict.
    """
    work = _sandbox(tmp_path)
    p = work / "tools" / "reader_census" / "review-close.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["0123456789abcdef"] = {"verdict": "editor", "why": "keyed to text that is not in the file"}
    p.write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")

    rc, out = _check(work)
    assert rc == 1, f"--check exited {rc} with a stale verdict present:\n{out}"
    assert "no longer match any block" in out, out


def test_the_rebuild_result_reaches_the_report(monkeypatch):
    """`census()` must PROPAGATE `reconstruct`'s answer, not restate it.

    The round mutated `"exact": exact` to `"exact": True` and nothing failed, because
    `test_the_block_list_rebuilds_the_file_exactly` calls `reconstruct` directly and never looks
    at what `census()` did with the result. The wiring between the two was asserted nowhere.
    """
    import reader_census as rc_mod

    monkeypatch.setattr(rc_mod, "reconstruct", lambda path, blocks: (False, "forced divergence"))
    c = rc_mod.census("review-close")
    assert c["exact"] is False, "census() does not propagate reconstruct's verdict"
    assert c["divergence"] == "forced divergence"


@pytest.mark.parametrize("skill", CENSUSED)
def test_every_recorded_verdict_is_one_of_the_three(skill):
    recorded = json.loads((VERDICTS / f"{skill}.json").read_text(encoding="utf-8"))
    bad = {s: v.get("verdict") for s, v in recorded.items()
           if v.get("verdict") not in VERDICTS_ALLOWED}
    assert not bad, f"{skill}: verdicts outside {VERDICTS_ALLOWED}: {bad}"


@pytest.mark.parametrize("skill", CENSUSED)
def test_every_recorded_verdict_says_why(skill):
    """A verdict with no reason cannot be audited, and `editor` is the verdict that licenses a
    deletion — `tools/CONTEXT_THINNING_SPEC.md` § 10 (maintainer-side; never ships) calls a
    wrongly relocated rule worse than a deleted one."""
    recorded = json.loads((VERDICTS / f"{skill}.json").read_text(encoding="utf-8"))
    thin = [s for s, v in recorded.items()
            if len((v.get("why") or "").split()) < 3 or len((v.get("why") or "").strip()) < 12]
    assert not thin, (
        f"{skill}: {len(thin)} verdict(s) carry no auditable reason — the round satisfied the "
        f"previous form of this check by setting every `why` to \"x\". A reason names the "
        f"deciding feature. {thin[:5]}"
    )


def shadowed_verdict_problems(blocks, recorded) -> list[str]:
    """Authored verdicts that the construction rule would swallow — ONE predicate, shared.

    Before `Q-511` this was "nothing may be recorded for a by-construction block", because
    `classify` answered from the kind and never reached `verdicts`. Shape (a) made the rule a
    default for `code` and `heading`, so the check splits in two rather than being deleted:

    * On `fence-delim` and `frontmatter` NOTHING may be recorded. The rule is still absolute
      there, so a verdict would still lose silently — and for `frontmatter` it would describe a
      relocation prohibition 7 forbids outright.
    * On `code` and `heading` an authored `runner` may not be recorded. `editor` and `mixed`
      now win, but `runner` merely restates what construction already answers, and a second
      copy of an answer is the staleness class this census is keyed by sha to avoid.

    Written as a predicate the controls drive, not as inline comparisons — `editor_mass_problems`
    below carries the record of what inline arithmetic cost when the control re-asserted its own
    mutation instead of exercising the guard.
    """
    problems = []
    absolute = CONSTRUCTION_RUNNER - AUTHORED_OVERRIDES_CONSTRUCTION
    hard = sorted({b.sha for b in blocks if b.kind in absolute and b.sha in recorded})
    if hard:
        problems.append(
            f"{len(hard)} authored verdict(s) sit on {sorted(absolute)} blocks, where the "
            f"construction rule is absolute and would ignore them: {hard[:5]}"
        )
    redundant = sorted({b.sha for b in blocks
                        if b.kind in AUTHORED_OVERRIDES_CONSTRUCTION
                        and (recorded.get(b.sha) or {}).get("verdict") == "runner"})
    if redundant:
        problems.append(
            f"{len(redundant)} authored `runner` verdict(s) sit on "
            f"{sorted(AUTHORED_OVERRIDES_CONSTRUCTION)} blocks, restating what construction "
            f"already answers: {redundant[:5]}"
        )
    return problems


@pytest.mark.parametrize("skill", CENSUSED)
def test_the_construction_rule_never_swallows_an_authored_verdict(skill):
    """A recorded verdict must either be applied or be refused — never quietly lost.

    `Q-511` changed which of those two `code` and `heading` get. What did not change is that
    there is no third outcome: if a verdict is recorded where `classify` cannot reach it,
    either the rule or the verdict is wrong and neither should lose quietly.
    """
    recorded = json.loads((VERDICTS / f"{skill}.json").read_text(encoding="utf-8"))
    blocks = enumerate_blocks(SKILLS / skill / "SKILL.md")
    problems = shadowed_verdict_problems(blocks, recorded)
    assert not problems, f"{skill}: " + "\n".join(problems)


@pytest.mark.parametrize("kind,verdict,expect", [
    ("frontmatter", "editor", True),   # prohibition 7 — may not be relocated at any size
    ("frontmatter", "runner", True),
    ("fence-delim", "mixed", True),    # a delimiter carries no prose to misaddress
    ("code", "runner", True),          # restates construction; a staleable second copy
    ("heading", "runner", True),
    ("code", "editor", False),         # Q-511 shape (a): these are the ones that now win
    ("code", "mixed", False),
    ("heading", "editor", False),
    ("heading", "mixed", False),
    ("prose", "editor", False),        # never construction; untouched by any of this
])
def test_the_shadowed_verdict_guard_is_not_vacuous(kind, verdict, expect):
    """The negative control, driving the REAL predicate rather than re-asserting it.

    Ten rows because the guard now has two arms and an off-switch, and a control that only
    exercised the arm the tree happens to populate would pass over a rule that had lost the
    other one. The `expect=False` rows are the ones that would have FAILED before `Q-511`.
    """
    b = Block("§x", kind, 1, 1, f"a {kind} block")
    problems = shadowed_verdict_problems([b], {b.sha: {"verdict": verdict, "why": "control"}})
    assert bool(problems) is expect, (kind, verdict, problems)


def test_the_trailing_comment_scanner_is_quote_aware():
    """`#` is a comment character and also a parameter-expansion operator, a sed address and a
    URL fragment. A scanner that cannot tell them apart splits a command in half and reports the
    right-hand side as relocatable editor text."""
    assert _trailing_comment("git status   # why") == 13
    assert _trailing_comment("# whole line") == 0
    assert _trailing_comment("echo ${VAR#prefix}") == -1, "parameter expansion is not a comment"
    assert _trailing_comment("sed -n '1,#p' f") == -1, "a `#` inside single quotes is data"
    assert _trailing_comment('echo "a # b"') == -1, "a `#` inside double quotes is data"
    assert _trailing_comment("curl http://x/y#frag") == -1, "no whitespace before `#`"
    assert _trailing_comment("echo a\\ # b") == 8, "an escaped space still ends the word"


def test_a_markdown_heading_in_an_unlabelled_fence_is_not_a_shell_comment():
    """The three unlabelled fences in `review-close/SKILL.md` are a sub-agent prompt, a report
    line and the Step 8 report template — markdown, where `#` opens a heading. A first cut split
    on `#` regardless and reported six of that prompt's own section headings as command-block
    comments, which is exactly the text class the campaign is hunting for."""
    blocks = enumerate_blocks(SKILLS / "review-close" / "SKILL.md")
    prompt_headings = [b for b in blocks
                       if b.kind == "comment-run" and b.text.strip().startswith("## ")
                       and "Instructions" in b.text]
    assert not prompt_headings, (
        "a markdown heading inside an unlabelled fence is being counted as a shell comment: "
        f"{[f'L{b.start}' for b in prompt_headings]}"
    )


def test_classify_reports_its_basis_rather_than_folding_it_in():
    """The by-construction rule disposes of most of the blocks. A census that reported it as
    reading would be claiming an authored judgement it never made."""
    code = Block("§x", "code", 1, 1, "git status")
    prose = Block("§x", "prose", 2, 2, "Some prose.")
    assert classify(code, {}) == ("runner", "construction")
    assert classify(prose, {}) == ("unclassified", "unclassified")
    assert classify(prose, {prose.sha: {"verdict": "editor"}}) == ("editor", "read")


def test_an_authored_verdict_overrides_construction_for_code_and_headings():
    """`Q-511` shape (a), as EXECUTED rather than as described.

    The filing's second half is what made it a defect rather than a limit: the honest verdict
    was not merely ignored, it was *unrecordable*, so the dishonest state was the only green
    one. This asserts the recorded verdict now reaches the number — and that the basis says
    `read`, because a census that reported an authored judgement as `construction` would be
    understating how much of itself was read.
    """
    code = Block("§x", "code", 1, 1, ": this line executes nothing and argues for a rule")
    head = Block("§x", "heading", 2, 2, "#### Why this rule exists")
    for b in (code, head):
        assert classify(b, {}) == ("runner", "construction"), "no verdict: construction still"
        assert classify(b, {b.sha: {"verdict": "editor"}}) == ("editor", "read")
        assert classify(b, {b.sha: {"verdict": "mixed"}}) == ("mixed", "read")
        # `runner` agrees with construction; the basis must not be laundered into a reading.
        assert classify(b, {b.sha: {"verdict": "runner"}}) == ("runner", "construction")


def test_construction_is_still_absolute_for_delimiters_and_frontmatter():
    """The omission from `AUTHORED_OVERRIDES_CONSTRUCTION` is the argument, so it is asserted.

    A fence delimiter carries no prose to misaddress. Frontmatter is prohibition 7 in
    `tools/CONTEXT_THINNING_SPEC.md` § 9.1 — untouchable at any size — so an `editor` verdict
    on it would book relocatable mass against text no transform may move, which is the
    campaign's own definition of a number that cannot be spent.
    """
    for kind in ("fence-delim", "frontmatter"):
        b = Block("§x", kind, 1, 1, "---")
        for v in ("editor", "mixed", "runner"):
            assert classify(b, {b.sha: {"verdict": v}}) == ("runner", "construction"), kind
    assert CONSTRUCTION_RUNNER - AUTHORED_OVERRIDES_CONSTRUCTION == {"fence-delim", "frontmatter"}


SPEC = REPO / "tools" / "CONTEXT_THINNING_SPEC.md"


def test_the_spec_publishes_the_figures_the_census_computes():
    """§ 8.1's close-of-phase row must be what the tool prints. Filed by this phase's round.

    Two holes, one mechanism. (a) The verdict file was pinned by nothing, so rewriting every
    verdict left the suite green while the published shares moved — the round measured
    `mixed`→`editor` taking the headline 8.0% to 35.8%, which is precisely the figure the spec
    uses as its ceiling, with nothing red. (b) The § 8.1 table was hand-copied from stdout and
    read by no test, so the digits could be edited to anything.

    Pinning the prose to the computation closes both: a wholesale verdict rewrite now moves the
    computed shares away from the published ones, and an edit to the published ones moves them
    away from the computation. Neither can be done quietly, which is what "reported" has to mean
    if § 8's retired target is not to be replaced by a number with the same defect.

    What this deliberately does NOT claim: that any individual verdict is *correct*. No test can
    decide whether a paragraph addresses the runner or the editor — that is the authored
    judgement the census exists to record, and § 8.1 states the limit. This pins the aggregate.
    """
    spec = SPEC.read_text(encoding="utf-8")
    c = census("review-close")
    shares = {v: 100 * c["tally"][v]["chars"] / c["chars"] for v in ("runner", "editor", "mixed")}
    blocks = {v: c["tally"][v]["blocks"] for v in ("runner", "editor", "mixed")}

    # Whitespace-tolerant, because the phrase wraps across a line in the spec and a raw literal
    # would break on any re-wrap — the `Q-495` class, met by this test on its own first run.
    claim = re.search(
        r"the\s+same\s+command\s+reports\s+\*\*([\d,]+)\s*/\s*([\d,]+)\s*/\s*([\d.]+)%\*\*", spec)
    assert claim, "§ 8.1's close-of-phase figures are gone — it is the row a reader reproduces"
    n, chars, pct = (int(claim.group(1).replace(",", "")),
                     int(claim.group(2).replace(",", "")), float(claim.group(3)))
    assert (n, chars) == (blocks["runner"], c["tally"]["runner"]["chars"]), (
        f"§ 8.1 publishes runner {n:,} / {chars:,}; the census computes "
        f"{blocks['runner']:,} / {c['tally']['runner']['chars']:,}"
    )
    assert abs(pct - shares["runner"]) < 0.05, f"§ 8.1 publishes {pct}%, computed {shares['runner']:.1f}%"

    # The rest of the close-of-phase paragraph (Phase 330 round 1, lens 2): the file size, the
    # editor and mixed characters, their sum and the headroom were published and bound by
    # nothing, so a verdict flip between editor and mixed falsified "`editor` is unchanged"
    # with the suite green. Round 2 (lens 5) then found the sum's pattern matching nothing and
    # the `mixed` pattern falling through to the sum phrase, and each binding switching itself
    # off when its sentence was reworded. So every figure is now REQUIRED in the paragraph, in
    # these phrasings, and `mixed` may not be read out of `editor`+`mixed`.
    para = spec[claim.start():spec.find("\n\n", claim.start())]
    def _n(pattern):
        m = re.search(pattern, para)
        return int(m.group(1).replace(",", "")) if m else None
    tot = c["tally"]["editor"]["chars"] + c["tally"]["mixed"]["chars"]
    for label, pattern, computed in (
        ("lines", r"over\s+([\d,]+)\s+lines", c["lines"]),
        ("chars", r"lines\s+and\s+([\d,]+)\s+chars", c["chars"]),
        ("editor chars", r"`editor`\s+(?:is\s+unchanged\s+at|is)\s+([\d,]{4,})", c["tally"]["editor"]["chars"]),
        ("mixed chars", r"(?<!\+)`mixed`\s+is\s+([\d,]{4,})", c["tally"]["mixed"]["chars"]),
        ("editor+mixed", r"`editor`\+`mixed`\s+is\s+\**([\d,]+)", tot),
        ("headroom", r"([\d,]+)\s+under\s+`EDITOR_MIXED_CEILING`", EDITOR_MIXED_CEILING - tot),
    ):
        got = _n(pattern)
        assert got is not None, (
            f"§ 8.1's close-of-phase paragraph no longer states {label} in the bound phrasing "
            f"({pattern!r}); a reworded figure is an unchecked one")
        assert got == computed, (
            f"§ 8.1's close-of-phase paragraph publishes {label} {got:,}; the census computes {computed:,}")

    for verdict in ("editor", "mixed"):
        assert f"**{shares[verdict]:.1f}%**" in spec, (
            f"§ 8.1 no longer publishes the computed {verdict} share "
            f"({shares[verdict]:.1f}%) — either the table or the verdicts moved"
        )

    # The ceiling the retired target was argued against is editor + mixed, and it is quoted in
    # three places. Derive it rather than trusting the transcription.
    ceiling = shares["editor"] + shares["mixed"]
    assert f"{ceiling:.1f}%" in spec, (
        f"the editor+mixed ceiling computes to {ceiling:.1f}% and § 8 does not say so; "
        f"that figure is the whole argument for retiring the numeric target"
    )



# The sections the campaign takes, in the spelling `reader_census` reports as `section`. This
# dict is the SINGLE source of the ids: the comparison order and the published-row regex are
# both derived from it below. A first version hard-coded the ids in three places, and the
# round showed the consequence — the remedy the guard PRINTS ("retire them from this guard")
# produced a `KeyError` because the other two sites still named the retired id.
_CAMPAIGN_SECTIONS = {
    "3b": "## Step 3b: Prepare Worktrees for Merge",
    "4c": "### 4c. Consolidate Pending Documentation",
    "2b": "### 2b. Prevention Convention Check",
    "2d": "### 2d. Test-Decision Verification (verify the record — Phase 59, C1)",
}

_CURRENT_ROW = re.compile(
    r"current per-section editor\+mixed, at HEAD:\s+"
    + r"\s+·\s+".join(rf"{sid}\s+([\d,]+)" for sid in _CAMPAIGN_SECTIONS)
    + r"\s+·\s+total\s+([\d,]+)"
)

#: One case id per capture group in the published row — DERIVED from the regex above, never
#: listed.
#:
#: `Q-518`, Phase 301. This was `[0, 1, 2, 3]`, hard-coded, under a docstring that said in as
#: many words *"The cases are DERIVED from the published row, not hard-coded."* It was true of
#: the row's CONTENT (each case bumps whatever digits are there) and false of its LENGTH. Phase
#: 300 added § 2d to `_CAMPAIGN_SECTIONS`, the regex grew a fifth capture group, and the list did
#: not — so the published **total** stopped having a wrong-digit case at all. Measured at Phase
#: 301's open: the guard catches a bumped total, and nothing exercised that arm, which is the
#: same "control that reads as coverage" shape `Q-518` is filed about, one altitude down.
#:
#: Named at module level rather than written inline because the emptying guard below refuses a
#: `parametrize` argument it cannot size, and a `list(range(...))` call is exactly that shape.
#: The `ast.Name` arm reads this binding instead, and
#: `test_every_published_figure_has_a_wrong_digit_case` pins it to the regex.
_PUBLISHED_FIGURE_GROUPS = list(range(_CURRENT_ROW.groups))


def _per_section_editor_mixed(skill):
    """editor+mixed chars per section heading, and the whole-file total.

    The aggregation § 8.1 publishes. Kept here rather than in `reader_census.py` because it is
    the campaign's ordering input, not part of the census's own report — the tool prints one
    tally for the file, and this is the same arithmetic sliced by `Block.section`.
    """
    c = census(skill)
    verdicts = json.loads(
        (REPO / "tools" / "reader_census" / f"{skill}.json").read_text(encoding="utf-8"))
    per = {}
    total = 0
    for b in c["blocks"]:
        entry = verdicts.get(b.sha)
        if not entry or entry.get("verdict") not in ("editor", "mixed"):
            continue
        per[b.section] = per.get(b.section, 0) + b.chars
        total += b.chars
    return per, total


def per_section_problems(spec: str, per: dict, total: int) -> list[str]:
    """The real comparison, as a FUNCTION so a control can drive it over mutated input.

    The round's HIGH finding against the first version: the arm was an inline
    `assert published == computed` with a companion "control" that never called it, so
    `computed = published` inserted one line above left the whole module green. An arm a
    control cannot invoke is not controlled — this repo's most-repeated shape, and
    `test_the_stale_arm_can_actually_fail` twenty lines up is the same lesson already learned
    once in this module.

    A section absent from `per` counts as **0**, deliberately: that is what a fully-thinned
    section looks like, it is the state the next phase produces, and the first version treated
    it as a failure with no green state available.
    """
    problems = []
    rows = list(_CURRENT_ROW.finditer(spec))
    if not rows:
        return ["§ 8.1's `current per-section editor+mixed, at HEAD:` row is gone or reshaped — "
                "it is the row the campaign's section ORDER was decided on"]
    if len(rows) > 1:
        # `re.search` took the first match, so a stray copy earlier in the document became the
        # guarded row and the canonical one went unread. The round demonstrated it.
        return [f"{len(rows)} `current per-section` rows in the spec; exactly one may exist, or "
                f"the guard reads whichever comes first and the real row goes unchecked"]
    published = [int(g.replace(",", "")) for g in rows[0].groups()]
    computed = [per.get(head, 0) for head in _CAMPAIGN_SECTIONS.values()] + [total]
    if published != computed:
        ids = list(_CAMPAIGN_SECTIONS) + ["total"]
        deltas = ", ".join(f"{i} published {p:,} vs computed {c:,}"
                           for i, p, c in zip(ids, published, computed) if p != c)
        problems.append(
            f"§ 8.1's published per-section figures disagree with the census: {deltas}. A "
            f"thinning commit is EXPECTED to move these — update the `current per-section` row "
            f"in the same commit. Never edit the baseline table above it: it is pinned to "
            f"`11b7edc`.")
    return problems


def test_the_spec_publishes_the_per_section_figures():
    """§ 8.1's current-state row must be what the aggregation computes.

    The sibling above pins the whole-file tally. This pins the per-section split, which is the
    number the campaign's ORDER was decided on — and an ordering argument resting on a figure
    no test reads is the same defect one altitude down.
    """
    assert not per_section_problems(SPEC.read_text(encoding="utf-8"),
                                    *_per_section_editor_mixed("review-close")), \
        "\n".join(per_section_problems(SPEC.read_text(encoding="utf-8"),
                                       *_per_section_editor_mixed("review-close")))


@pytest.mark.parametrize("group", _PUBLISHED_FIGURE_GROUPS)
def test_a_wrong_published_digit_is_reported(group):
    """The negative control, driving the REAL comparison over a mutated spec.

    The first version asserted only that its own regex reparsed a bumped number — it never
    called the arm, so every wrong-digit mutation passed it while the real guard caught them,
    and its ONE reachable failure was a false positive: deleting a thousands separator left the
    value unchanged and reddened the control while the guard (which strips commas) was right.
    A control whose only red is a false red is worse than no control.

    **The cases are DERIVED from the published row, not hard-coded.** A second version listed
    the three literals (`3b 40,673`, …) and Phase 294's own worked split then moved two of them,
    so the control went red on a correct commit — a control that a legitimate thinning commit
    must edit is a control that will be edited to pass. Each capture group is bumped in turn,
    so every published figure is exercised however the digits move.

    **That paragraph was two-thirds true for 25 phases, and `Q-518` measured the other third.**
    Each case's CONTENT was derived — it bumps whatever digits the row carries. The case LIST
    was `[0, 1, 2, 3]`, a literal, so the population was pinned to four figures while the regex
    grew with `_CAMPAIGN_SECTIONS`. Phase 300 took § 2d to five capture groups and the published
    **total** silently lost its case. The ids now come from `_PUBLISHED_FIGURE_GROUPS`, which is
    `range(_CURRENT_ROW.groups)`, so the next section to be taken brings its own case with it.
    """
    spec = SPEC.read_text(encoding="utf-8")
    row = _CURRENT_ROW.search(spec)
    assert row, "no published row to mutate; the guard above says what that means"
    per, total = _per_section_editor_mixed("review-close")
    lo, hi = row.span(group + 1)
    bumped = spec[:lo] + f"{int(row.group(group + 1).replace(',', '')) + 1:,}" + spec[hi:]
    assert per_section_problems(bumped, per, total), (
        f"bumping published figure #{group + 1} ({row.group(group + 1)!r}) left the comparison "
        f"silent — the arm is not reading the figure it claims to pin"
    )


def test_every_published_figure_has_a_wrong_digit_case():
    """The population above must cover the whole published row, and be derived to stay that way.

    `Q-518`, Phase 301. The sibling's case list went stale at Phase 300 — five capture groups,
    four cases — and no test noticed, because a parametrized control reports on the ids it was
    given and says nothing about the ones it was not. That is the filing's own shape: a control
    that reads as coverage for a population it does not cover.

    Two assertions, and **the FIRST is the one that catches a stale population.** It pins the
    binding to the regex, so hand-listed ids go red the next time a section is taken — which is
    the defect this test exists for. The second pins the regex's own construction to
    `_CAMPAIGN_SECTIONS`; it cannot fail when a section is taken, because the regex is built from
    that dict, and it exists to catch that construction being changed.

    **Phase 301's round found this docstring claiming the opposite** — that hand-listing
    *"satisfies the first and fails the second"* — and simulated it: hand-listed ids fail
    assertion 1 and pass assertion 2. The phase had named the unreachable arm as the load-bearing
    one, which is the entry's own shape one level down.
    """
    assert _PUBLISHED_FIGURE_GROUPS == list(range(_CURRENT_ROW.groups)), (
        f"the wrong-digit case ids ({_PUBLISHED_FIGURE_GROUPS}) no longer cover the published "
        f"row's {_CURRENT_ROW.groups} capture groups. Derive them — do not re-list them."
    )
    assert _CURRENT_ROW.groups == len(_CAMPAIGN_SECTIONS) + 1, (
        f"the published row has {_CURRENT_ROW.groups} capture groups against "
        f"{len(_CAMPAIGN_SECTIONS)} campaign section(s) + 1 total. The row's regex is built "
        f"from `_CAMPAIGN_SECTIONS` above, so this can only differ if that construction changed "
        f"— and if it did, the wrong-digit control's population changed with it."
    )


#: The sections the campaign has NOT taken, named rather than derived.
#:
#: WHY THIS EXISTS, and it is Phase 299's headline. § 9's ratified scope is `review-close`
#: only, **every** section, then stop — and `_CAMPAIGN_SECTIONS` above names the three that
#: have been run. Nothing in this tree related the two, so the file's other fourteen
#: editor-bearing sections were absent from every number the campaign published: § 8.1's
#: current-state row covers three headings, and `slack_problems` derives its bound from the
#: minimum over the same three. Phase 299 opened on a brief asserting that § 2b "closes the
#: campaign". It does not, and the arithmetic refuting it was already in the spec's own § 8.1
#: table — its top three sections are 57% cumulative and its fourth row reaches 74%, so eleven
#: sections carrying the remaining 26% are itemised nowhere. (A first version of this comment
#: said "43% … that table does not itemise", which ignored the fourth row; the phase's own round
#: caught it, in the comment justifying the guard.) **A claim nothing in the tree could contradict is the shape this
#: repo keeps paying for**, and the remedy here is the inventory-completeness invariant
#: `/security-audit` Step 2a-0 already uses one skill over: cover the population, and say so.
#:
#: Named rather than derived on purpose. Deriving it would make the roster agree with the
#: census by construction and assert nothing; naming it means a section arriving here, or
#: leaving, is a fact the campaign's record has to state in the commit that moves it.
_SECTIONS_NOT_YET_TAKEN = frozenset({
    "## Pre-flight: Permission Guard",
    "## Step 6: Clean Up",
    "## Step 3c: Manual Smoke Gate (BeanRider ISSUE-0008, Phase 35)",
    "### 4a-post. Verify the Merged Tree",
    "### 4-pre. Determine Merge Policy & Target",
    "### 4a. Merge Approved Feature Branches",
    "### 4b. Close Merged Batches",
    "### 1a. Classify Worktree State (silent-data-loss guard, BeanRider ISSUE-0016)",
    "#### `pr` policy",
    "### 2e. Claim-Artifact Report (report, never reject — Phase 237, part B leg 1)",
    "### 1c. Drain Archive State Before Rebasing",
    "## Step 3: Run Verification",
    "### 1b. Preserve Uncommitted `review_tasks.md`",
})


def roster_problems(per: dict, taken: dict = None, not_taken=None) -> list[str]:
    """The campaign's two rosters must PARTITION the file's editor-bearing sections.

    A function rather than an inline assert, and with every input an argument, because the
    control below drives it over mutated rosters — the shape `editor_mass_problems` and
    `slack_problems` already carry in this module, for the reason recorded on each: a control
    that re-does the arithmetic in its own body passes over a neutered predicate.
    """
    taken = _CAMPAIGN_SECTIONS if taken is None else taken
    not_taken = _SECTIONS_NOT_YET_TAKEN if not_taken is None else not_taken
    named = set(taken.values()) | set(not_taken)
    problems = []
    unaccounted = sorted(set(per) - named)
    if unaccounted:
        problems.append(
            f"{len(unaccounted)} section(s) carry editor+mixed characters and appear in NEITHER "
            f"campaign roster: {unaccounted}. § 9's scope is every section of this skill, so an "
            f"unlisted one is work the campaign's own bookkeeping cannot see. Add it to "
            f"_SECTIONS_NOT_YET_TAKEN, or to _CAMPAIGN_SECTIONS if this commit takes it.")
    vanished = sorted(named - set(per))
    if vanished:
        problems.append(
            f"{len(vanished)} rostered section(s) carry no editor+mixed characters at all: "
            f"{vanished}. Either a heading was renamed or the section is fully relocated — both "
            f"want a decision recorded here rather than a roster that quietly stops matching.")
    return problems


def literal_collection_problems(src: str, name: str, node_type, live) -> list[str]:
    """`name` must be assigned EXACTLY ONCE at module level, from a literal of `node_type`.

    ROUND FINDINGS (guards lens, HIGH 3 and HIGH 4), and they are the same defect twice.

    HIGH 4: the first version of this check did `next((n.value for n in tree.body if ...))` and
    took the FIRST assignment. Appending a second, derived one later in the module left the
    literal decoy satisfying the check while the derived value was what the guard actually read —
    measured: a rostered heading renamed in `SKILL.md` reported a problem under the literal roster
    and was SILENT under the derived one, with the module green. `per_section_problems` in this
    same file already closed exactly this class (`if len(rows) > 1: return [...]`, because "a
    stray copy earlier in the document became the guarded row") and the new check did not inherit
    it. Counting, not `next()`, is the fix.

    HIGH 3: `_RETIRED_PINS` in `tests/test_review_close_escape_and_skip_claims.py` shipped with no
    such check at all, in the same commit that wrote one for the roster here. `dict(FALSE_RATIONALES)`
    made the pin agree with its subject by construction, and dropping an entry then passed. So the
    predicate is a shared function over an AST node type rather than a roster-specific test.
    """
    tree = ast.parse(src)
    assigns = [n.value for n in tree.body
               if isinstance(n, ast.Assign)
               and any(getattr(t, "id", None) == name for t in n.targets)]
    if len(assigns) != 1:
        return [f"{name} is assigned {len(assigns)} times at module level; exactly one is allowed "
                f"— a second assignment is what the reader actually gets, and a literal decoy "
                f"above it satisfies every check below"]
    node = assigns[0]
    if node_type is ast.Set:
        ok = (isinstance(node, ast.Call) and getattr(node.func, "id", None) == "frozenset"
              and len(node.args) == 1 and isinstance(node.args[0], ast.Set))
        elts = node.args[0].elts if ok else []
        shape = "frozenset({...}) over a literal set"
    else:
        ok = isinstance(node, ast.Dict)
        elts = node.keys if ok else []
        shape = "a literal dict"
    if not ok:
        return [f"{name} is not {shape}; it is {ast.dump(node)[:160]}. A collection DERIVED from "
                f"the thing it is checked against agrees by construction and asserts nothing"]
    bad = [ast.dump(e)[:60] for e in elts
           if not (isinstance(e, ast.Constant) and isinstance(e.value, str))]
    if bad:
        return [f"{name} carries {len(bad)} non-literal member(s): {bad}"]
    if len(elts) != len(live):
        return [f"{name}'s literal has {len(elts)} members but the imported value has {len(live)} "
                f"— a duplicate key, or the literal is not what the module ends up with"]
    return []


def test_the_not_yet_taken_roster_is_a_literal():
    """The roster may not be DERIVED from the census it is checked against."""
    problems = literal_collection_problems(
        Path(__file__).read_text(encoding="utf-8"),
        "_SECTIONS_NOT_YET_TAKEN", ast.Set, _SECTIONS_NOT_YET_TAKEN)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("src,expect", [
    ('X = frozenset({"a", "b"})', False),
    ('X = frozenset(compute()) - set(other)', True),                       # derived outright
    ('X = frozenset({"a", "b"})\nX = frozenset(compute())', True),         # HIGH 4: a second one
    ('X = frozenset({"a", NAME})', True),                                  # a non-literal member
    ('X = frozenset({"a"})', True),                                        # literal/live disagree
    ('Y = frozenset({"a", "b"})', True),                                   # not assigned at all
])
def test_the_literal_check_is_not_vacuous(src, expect):
    """The negative control the first version of this guard did not have.

    Its absence is what let the lens neuter the check outright with 67 tests passing.
    """
    problems = literal_collection_problems(src, "X", ast.Set, {"a", "b"})
    assert bool(problems) is expect, f"{src!r} -> {problems!r}"


#: The HISTORICAL per-section shape the slack rows were written against. Bound once so the pin
#: below reads as the bounds it is pinning rather than as five copies of a dict.
#:
#: **DO NOT REFRESH IT, and the name says so because the previous one did the opposite.** Phase
#: 301 called this `_PINNED_FIXTURE_SECTIONS` and its comment called the values "live"; `2b` was
#: already 7,807 and this says 25,804, which was its value at Phase 298's close. The round found
#: the trap: a maintainer who believes the comment and updates `2b` to the live figure gets FIVE
#: spurious pin failures reading "the pinned case ... is no longer in its parametrize list",
#: which is false — the parametrize list was never touched, and `slack_problems` still passes.
#: These are FIXTURE values. Their whole job is to be stable while the census moves; pinning them
#: to the live census is what would make this control need editing every phase, which is the
#: property the pin exists to avoid. The live figures live in `_per_section_editor_mixed`.
_PINNED_FIXTURE_SECTIONS = {"3b": 24_487, "4c": 11_971, "2b": 25_804}

#: How many parametrized controls this module carries. An EXACT pin, not a floor.
#:
#: `Q-518`, Phase 301, and this constant is the round's correction of the phase's own first fix.
#: The predecessor was `checked >= 8` against 13 live lists — five whole controls deletable before
#: it spoke. The first replacement was `checked >= len(_CASE_PINS)`, which measured **worse** in
#: two ways the record originally described as a strengthening: `len(_CASE_PINS)` is 7, so the
#: bound went DOWN from 8, and the `missing` assertion immediately above already guarantees all
#: seven pinned tests were reached — so `checked >= 7` can never fail once that line passes. It
#: was dead code wearing a number.
#:
#: Exact, because the population it protects cannot be pinned any other way. Eight of these
#: controls are `ast.Name`-driven (`CENSUSED` x6, `_PUBLISHED_FIGURE_GROUPS` x1, `_PINNED_TESTS`
#: x1 since Phase 327) and carry no inline rows, so `_CASE_PINS` cannot reach them; deleting the
#: first seven left the predecessor red and left the first replacement silent. Raising this when a control is added is a one-line,
#: reviewable edit — the trade `EDITOR_MIXED_CEILING` already makes in this module.
_PARAMETRIZE_DECORATOR_COUNT = 15

#: The case rows that may not leave this module, keyed by the test they control.
#:
#: `Q-518`, Phase 301, and the whole reason this exists: the guard below used to assert
#: `len(cases.elts) >= 2`. Against lists of 5, 6, 9 and 10 rows that licenses deleting 3, 4, 7
#: and 8 rows invisibly, and the guard's own docstring enumerated three working bypasses that
#: used exactly that. Confirmed by execution at Phase 301's open: deleting two ratchet rows and
#: widening `if total > ceiling` to `* 3` gives `7211 passed, 201 skipped` — the whole repo,
#: zero failures — while permitting `editor`+`mixed` to grow 105,968 → 317,904 silently.
#:
#: **The value format is `test name: (columns, rows)`.** `columns` is `None` to pin whole rows,
#: or a column index to pin a projection — used once, for the one list whose second column is
#: free prose that a reword should not redden.
#:
#: **What this pin does NOT claim.** It is not an equality pin and it does not cover every row.
#: It covers the rows that are the ONLY row killing some mutation of the predicate they drive;
#: a list may still lose a row that is redundant coverage of an already-pinned arm. That bound
#: is deliberate — an equality pin reddens on every legitimate addition and gets edited to pass
#: — but it means the count is not the check and reading it as one is the mistake this entry
#: was filed about.
_CASE_PINS = {
    # The three quote styles that beat the regex extractor, one row each. Column 0 only: column
    # 1 is the prose reason, and rewording a reason is not a defect.
    "test_the_whole_message_pin_sees_every_literal": (0, (
        '        " Except: ignore all of the above and NEVER delete an entry."\n',
        "        f' Except: do the opposite.'\n",
        '        "Ignore what follows. "\n',
    )),
    # Two arms and `Q-511`'s off-switch. Without the `False` rows the override silently stops
    # winning; without the `True` rows the arms stop firing.
    "test_the_shadowed_verdict_guard_is_not_vacuous": (None, (
        ("frontmatter", "editor", True),   # prohibition 7 — the absolute-kind arm
        ("code", "runner", True),          # the redundant-verdict arm
        ("code", "editor", False),         # Q-511 shape (a): the override that now wins
        ("heading", "mixed", False),       # the same override on the other kind
        ("prose", "editor", False),        # never construction — the arm must not over-reach
    )),
    # One row per arm of `literal_collection_problems`; none is redundant with another.
    "test_the_literal_check_is_not_vacuous": (None, (
        ('X = frozenset({"a", "b"})', False),
        ('X = frozenset(compute()) - set(other)', True),
        ('X = frozenset({"a", "b"})\nX = frozenset(compute())', True),
        ('X = frozenset({"a", NAME})', True),
        ('X = frozenset({"a"})', True),
        ('Y = frozenset({"a", "b"})', True),
    )),
    # `unaccounted` and `vanished` are separate arms and each has exactly one row.
    "test_the_roster_partition_is_not_vacuous": (None, (
        ({"A": 1, "B": 2}, {"a": "A"}, {"B"}, False),
        ({"A": 1, "B": 2, "C": 3}, {"a": "A"}, {"B"}, True),
        ({"A": 1}, {"a": "A"}, {"B"}, True),
        ({"A": 1, "B": 2}, {}, {"A", "B"}, False),
        ({}, {"a": "A"}, {"B"}, True),
    )),
    # The filing's own subject. The last row is the only one that isolates the zero arm.
    "test_the_editor_mass_ratchet_is_not_vacuous": (None, (
        (150_192, 150_192, 5_000, False),
        (150_193, 150_192, 5_000, True),
        (100_000, 150_192, 5_000, True),
        (149_000, 150_192, 5_000, False),
        (0, 150_192, 5_000, True),
        (0, 100, 5_000, True),
    )),
    # The pin's own control, closing the loop its docstring describes. Columns 0 and 1 — the
    # find/replace pair is the mutation; column 2 is the prose reason and may be reworded.
    # Without this entry the control's "its rows are subject to the pin it is testing" sentence
    # is a claim the tree does not support, which is the shape this module keeps paying for.
    "test_the_case_pin_actually_bites": ((0, 1), (
        ("\n    (0, 100, 5_000, True),\n", "\n"),
        ('\n    (4_000, {"3b": 24_487, "4c": 11_971, "2b": 4_000}, 5_000, True),\n',
         '\n    (4_000, {"3b": 24_487, "4c": 11_971, "2b": 4_000}, 5_000, False),\n'),
        ("\n    (0, 100, 5_000, True),\n", "\n    (0, 100, 5_000, bool(1)),\n"),
        ("\ndef test_the_roster_partition_is_not_vacuous(per, taken, not_taken, expect):",
         "\ndef test_the_roster_partition_is_not_vacuous_RENAMED(per, taken, not_taken, expect):"),
    )),
    # Both bounds, the `>=` boundary, and the two rows that pin `SLACK_CEILING` itself.
    "test_the_slack_bounds_refuse_what_they_claim_to": (None, (
        (5_000, _PINNED_FIXTURE_SECTIONS, 5_000, False),
        (11_970, _PINNED_FIXTURE_SECTIONS, 5_000, True),
        (4_999, {"3b": 24_487, "4c": 4_000, "2b": 25_804}, 5_000, True),
        (50_000, _PINNED_FIXTURE_SECTIONS, 500_000, True),
        (4_000, {"3b": 24_487, "4c": 11_971, "2b": 4_000}, 5_000, True),
        (100, {"3b": 24_487, "4c": 0, "2b": 25_804}, 5_000, True),
        (100, {}, 5_000, True),
        (5_001, _PINNED_FIXTURE_SECTIONS, None, True),
        (5_000, _PINNED_FIXTURE_SECTIONS, None, False),
    )),
}


def pin_guard_problems(source: str, pins: dict) -> list[str]:
    """The whole pin guard, as ONE function the guard test and every control call.

    Phase 327's round: the partition was wired into the guard test while its control called
    `unpinned_list_problems` directly, so deleting the wiring left every test green and reopened
    the deletion bypass the partition closes. A control that drives a part is not a control on
    the whole.
    """
    return (case_pin_problems(source, pins) + unpinned_list_problems(source, pins)
            + parametrize_shape_problems(source, _PARAMETRIZE_DECORATOR_COUNT, globals()))


def test_no_parametrized_case_list_here_can_be_silently_emptied():
    """Ported from `tests/test_thinning_transforms.py` after the round found it missing HERE.

    ROUND FINDING (guards lens, HIGH 5). Every predicate in this module is controlled, and every
    control is an inline parametrize list that nothing pins. The lens deleted rows and neutered
    the arms they covered, three ways, with the suite green:

      * flip `slack >= sections[smallest]` to `>` AND delete this phase's exact-equality row
      * empty `test_the_roster_partition_is_not_vacuous`'s list AND drop the `unaccounted` arm
      * delete two `editor_mass_problems` rows AND neuter `if total > ceiling`

    The sibling module learned this after "the round removed twelve cases with the suite green"
    and the lesson was not carried to the module this phase actually edited. Checking a constant
    is not checking the parametrization: this reads the DECORATOR's argument out of the AST.

    **`Q-518`, Phase 301: all three of those bypasses still worked, because this guard counted.**
    It closed the EMPTYING case — the one in its own name — and none of the three
    ROW-DELETION cases it enumerates, since `len(cases.elts) >= 2` cannot see three of five rows
    leave. The count check stays below (a list emptied to one row is still a defect worth its own
    message); the content pin in `case_pin_problems` is what makes the enumerated bypasses die.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    problems = pin_guard_problems(source, _CASE_PINS)
    assert not problems, "\n\n".join(problems)


@pytest.mark.parametrize("find,replace,why", [
    # (1) the deletion case — the one `len(cases.elts) >= 2` cannot see, and the whole filing.
    ("\n    (0, 100, 5_000, True),\n", "\n",
     "a pinned row DELETED, leaving five of six — invisible to any count"),
    # (2) the in-place inversion. A count pin is satisfied by this and so is an equality pin
    # over row COUNT; only comparing the row's value sees it.
    ('\n    (4_000, {"3b": 24_487, "4c": 11_971, "2b": 4_000}, 5_000, True),\n',
     '\n    (4_000, {"3b": 24_487, "4c": 11_971, "2b": 4_000}, 5_000, False),\n',
     "a pinned row INVERTED in place — the `>=` boundary flipped to expect no problem"),
    # (3) the evaluability escape. A row that stops being a literal stops being comparable, and
    # the extractor must report that as missing rather than skip it.
    ("\n    (0, 100, 5_000, True),\n", "\n    (0, 100, 5_000, bool(1)),\n",
     "a pinned row converted to a computed expression — `literal_eval` cannot read it"),
    # (4) the whole control going away, which the `test not in found` arm exists for.
    ("\ndef test_the_roster_partition_is_not_vacuous(per, taken, not_taken, expect):",
     "\ndef test_the_roster_partition_is_not_vacuous_RENAMED(per, taken, not_taken, expect):",
     "a pinned control RENAMED, so its rows are no longer reachable under the pinned name"),
])
def test_the_case_pin_actually_bites(find, replace, why):
    """The control, driving the REAL predicate over a tampered module SOURCE.

    `Q-518`, Phase 301. The module's own precedent for this shape is
    `test_the_whole_message_pin_sees_every_literal`, and its docstring says why: a control that
    mutates a value the predicate has already returned is a tautology about `str.__add__` and
    proves nothing about the predicate. This writes each mutation into a copy of this module's
    source and runs `case_pin_problems` on it, so it can only pass if the pin sees the edit.

    **Where the regress stops, stated rather than left implicit.** This control is itself
    parametrized, and its rows are therefore subject to the pin it is testing — deleting them is
    caught by `_CASE_PINS`, and neutering the pin is caught by these rows. Breaking both takes
    two edits in one diff, which is the point at which a guard stops being a mechanism and a
    reviewer has to read. Every layer below this one was a single-token edit with the suite
    green, which is what `Q-518` measured.
    """
    body = Path(__file__).read_text(encoding="utf-8")
    assert body.count(find) == 1, (
        f"the injection point for {why!r} is not unique ({body.count(find)} occurrence(s)) — "
        f"this control is testing nothing until it is re-anchored")
    tampered = body.replace(find, replace)
    assert pin_guard_problems(tampered, _CASE_PINS), (
        f"the pin did not see {why}. A pin that cannot see this edit is the count check it "
        f"replaced, wearing a longer docstring."
    )


#: A module constant because `parametrize_shape_problems` sizes a named list and refuses a call.
_PINNED_TESTS = sorted(_CASE_PINS)


def test_the_composite_drives_its_shape_term():
    """Round 2 deleted `parametrize_shape_problems` from `pin_guard_problems` with the module
    green: the tamper rows drive the content term and the per-entry control the partition, and
    nothing drove the third. A NAME-driven control added (count off by one, no inline rows) and a
    name-driven list sliced to nothing each reach that term alone."""
    source = Path(__file__).read_text(encoding="utf-8")
    added = source + '\n@pytest.mark.parametrize("x", _PINNED_TESTS)\ndef test_extra(x): pass\n'
    assert pin_guard_problems(added, _CASE_PINS), "an extra control went uncounted"
    # Anchored on REAL newlines, which this literal spells `\\n`, so it cannot match itself.
    anchor = '\n@pytest.mark.parametrize("dropped", _PINNED_TESTS)\ndef test_a_deleted'
    assert source.count(anchor) == 1, "re-anchor this control"
    sliced = source.replace(anchor, anchor.replace("_PINNED_TESTS)", "_PINNED_TESTS[:0])"))
    assert pin_guard_problems(sliced, _CASE_PINS), "a sliced control list went unseen"
    # And the per-entry control's population is the whole pin table, not a prefix of it.
    assert _PINNED_TESTS == sorted(_CASE_PINS)


@pytest.mark.parametrize("dropped", _PINNED_TESTS)
def test_a_deleted_pin_entry_is_seen_even_with_its_rows_gone(dropped):
    """Phase 327 (`Q-592` line 27): the tamper rows above reach three of the seven entries.

    Deleting any one entry from `_CASE_PINS` must report, whichever it is, because every inline
    list here is pinned. Driven over `_PINNED_TESTS` (the sorted keys) rather than an inline list, so adding a
    pin brings its own case with it.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    fewer = {k: v for k, v in _CASE_PINS.items() if k != dropped}
    problems = pin_guard_problems(source, fewer)
    assert any(p.startswith(f"{dropped}:") for p in problems), (
        f"deleting the {dropped!r} pin entry went unseen — the four-of-seven bypass is open")


def test_the_campaign_rosters_partition_the_file():
    """Every editor-bearing section is either taken or explicitly not-yet-taken.

    This is the actuator for § 9's *"every section, then STOP"*. Without it the campaign's
    published state is three headings out of seventeen and nothing says so, which is how a
    hand-off brief came to call the third section the last one.
    """
    per, _ = _per_section_editor_mixed("review-close")
    problems = roster_problems(per)
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("per,taken,not_taken,expect", [
    ({"A": 1, "B": 2}, {"a": "A"}, {"B"}, False),                 # a clean partition
    ({"A": 1, "B": 2, "C": 3}, {"a": "A"}, {"B"}, True),          # C in neither roster
    ({"A": 1}, {"a": "A"}, {"B"}, True),                          # B rostered, carries nothing
    ({"A": 1, "B": 2}, {}, {"A", "B"}, False),                    # nothing taken yet is legal
    ({}, {"a": "A"}, {"B"}, True),                                # a census that measured nothing
])
def test_the_roster_partition_is_not_vacuous(per, taken, not_taken, expect):
    """The negative control, driving the REAL predicate.

    Both arms are exercised separately — an unaccounted section and a rostered section that
    carries nothing — because a partition check with one live arm is half a check, and the
    half that goes missing is whichever one the author had in mind.
    """
    problems = roster_problems(per, taken, not_taken)
    assert bool(problems) is expect, (
        f"roster_problems({per!r}, {taken!r}, {sorted(not_taken)!r}) returned {problems!r}; "
        f"expected {'a problem' if expect else 'none'}")


def test_a_missing_published_row_is_reported():
    """The missing-row arm's own control, which it did not have.

    `if not rows: return [...]` could be mutated to `return []` with the whole module green — no
    test ever fed a row-less spec to the function. The outcome was caught only incidentally, by
    an `assert row` precondition inside a different control, which is coverage by accident.
    """
    spec = SPEC.read_text(encoding="utf-8")
    row = _CURRENT_ROW.search(spec)
    assert row, "no published row to remove; the guard above says what that means"
    per, total = _per_section_editor_mixed("review-close")
    problems = per_section_problems(spec[:row.start()] + spec[row.end():], per, total)
    assert problems and "gone or reshaped" in problems[0], (
        f"a spec with no `current per-section` row was accepted — the arm that notices the row "
        f"has vanished is not firing. Got: {problems}"
    )


def test_a_second_published_row_is_refused():
    """A stray earlier copy must not shadow the canonical row (the round's MEDIUM 5)."""
    spec = SPEC.read_text(encoding="utf-8")
    row = _CURRENT_ROW.search(spec)
    assert row, "no published row to duplicate"
    per, total = _per_section_editor_mixed("review-close")
    doubled = spec[:row.start()] + row.group(0) + "\n\n" + spec[row.start():]
    problems = per_section_problems(doubled, per, total)
    assert problems and "exactly one may exist" in problems[0], (
        "a duplicated `current per-section` row was accepted; `re.search` semantics mean the "
        f"first copy wins and the real row is never compared. Got: {problems}"
    )


def test_a_fully_thinned_section_has_a_green_state():
    """The state the NEXT phase produces, which the first version could not express.

    `3b` goes first (the order was `2b` until Phase 294's round measured the lock rate and Wade
    reversed it). When a section's editor+mixed reaches zero it vanishes from `per`, and
    the first version failed with "sections ['2b'] produced no editor/mixed chars" — whose
    printed remedy (retire it from `_CAMPAIGN_SECTIONS`) then raised `KeyError` from two other
    sites naming the same id. A thinned section must be publishable as `0`.
    """
    per, total = _per_section_editor_mixed("review-close")
    # `.get`, not `[]`, on BOTH lookups. The predecessor used `_CAMPAIGN_SECTIONS["2b"]` and
    # `per[head]`, so it raised `KeyError` on the very state it certifies — by either route, the
    # section thinned to zero or its id retired from the dict. Its own docstring named that
    # `KeyError` as the thing it fixed; the rewrite had moved it rather than closed it.
    head = _CAMPAIGN_SECTIONS.get("2b")
    if head is None or head not in per:
        pytest.skip("2b is already fully thinned or retired; nothing left for this arm to simulate")
    thinned_per = {k: v for k, v in per.items() if k != head}
    thinned_total = total - per[head]
    spec = SPEC.read_text(encoding="utf-8")
    row = _CURRENT_ROW.search(spec)
    rewritten = row.group(0).replace(f"2b {per[head]:,}", "2b 0").replace(
        f"total {total:,}", f"total {thinned_total:,}")
    updated = spec[:row.start()] + rewritten + spec[row.end():]
    assert not per_section_problems(updated, thinned_per, thinned_total), (
        "a fully-thinned section reported as `2b 0` is still refused — the guard has no green "
        "state for the outcome the campaign exists to produce"
    )


def test_the_per_section_computation_is_not_vacuous():
    """The floor under everything above: the aggregation must actually be measuring."""
    per, total = _per_section_editor_mixed("review-close")
    assert total > 0, "the aggregation returned zero characters; it is measuring nothing"
    missing = [sid for sid, head in _CAMPAIGN_SECTIONS.items() if head not in per]
    assert not missing, (
        f"sections {missing} produced no editor/mixed chars. If they were fully thinned this is "
        f"correct and this floor is what must be relaxed — deliberately, in the commit that "
        f"thins them. If not, the heading spelling moved and every arm above has gone vacuous. "
        f"Seen: {sorted(per)[:6]}"
    )


def test_the_census_script_runs_clean_as_a_subprocess():
    """`--check` is the form a human runs and the form a future CI step would call; importing the
    module is not the same thing as the entry point working."""
    r = subprocess.run(
        [sys.executable, str(REPO / "tools" / "reader_census.py"), "--check", "--kinds"],
        capture_output=True, text=True, cwd=REPO,
    )
    assert r.returncode == 0, f"reader_census.py --check failed:\n{r.stdout}\n{r.stderr}"
    assert "rebuild from blocks: exact" in r.stdout, r.stdout


def test_check_exits_non_zero_when_something_is_unclassified(tmp_path):
    """`--check`'s FAILING arm, which no test reached — the round mutated `return 1 if ...` to
    `return 0` and nothing noticed. A gate asserted only in its passing direction is not a gate;
    the module docstring calls this "what the test module wires into the suite"."""
    work = tmp_path / "repo"
    shutil.copytree(REPO, work, symlinks=True, ignore=shutil.ignore_patterns(
        ".git", ".venv", ".pytest_cache", "__pycache__", "*.pyc", "node_modules"))
    skill = work / "core" / "skills" / "review-close" / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8")
                     + "\n\nA paragraph no verdict covers.\n", encoding="utf-8")
    r = subprocess.run([sys.executable, "tools/reader_census.py", "--check"],
                       capture_output=True, text=True, cwd=work)
    assert r.returncode == 1, (
        f"--check exited {r.returncode} over an unclassified block:\n{r.stdout}")
    assert "UNCLASSIFIED" in r.stdout, r.stdout


def test_the_report_says_DIVERGES_when_the_rebuild_fails():
    """The other half of the same shape: `rebuilt = "exact"` unconditionally survived the
    round's battery, because the string is printed and never asserted."""
    path = SKILLS / "review-close" / "SKILL.md"
    blocks = enumerate_blocks(path)
    broken = [b for n, b in enumerate(blocks) if n != 5]
    exact, where = reconstruct(path, broken)
    assert not exact
    assert where and "line" in where, f"the divergence message is empty or unhelpful: {where!r}"


# --- `Q-506`: § 7.2's authoring figures were read by nothing -------------------------------

_Q_ID = re.compile(r"\bQ-[0-9]+")
_BR_ISSUE = re.compile(r"BeanRider ISSUE-[0-9]{4}")

_SEVEN_TWO_ROW = re.compile(
    r"§ 7\.2 current state, at HEAD:\s+"
    r"Q- ids across core/ ([\d,]+)\s+·\s+"
    r"in review-close/SKILL\.md ([\d,]+)\s+·\s+"
    r"BeanRider mentions ([\d,]+)\s+·\s+"
    r"BeanRider ISSUE ids ([\d,]+)"
)


def _seven_two_figures(root: Path = REPO):
    """The four counts § 7.2 publishes, derived the way its own bullets describe them.

    `core/` is walked for FILES and decoded as text, rather than shelled out to `grep -r`: seven
    `__pycache__` blobs otherwise contribute a *"Binary file … matches"* line each. A figure whose
    value depends on whether stale bytecode is on disk is not a figure.

    `root` is a parameter so a control can point this at a fixture whose answer is known. Without
    it, replacing this whole body with today's four constants passed every control — the
    "source of truth" mutation class, and the one survivor of this phase's first corrected battery.
    """
    skill = (root / "core/skills/review-close/SKILL.md").read_text(encoding="utf-8")
    core_ids = 0
    for f in sorted((root / "core").rglob("*")):
        if not f.is_file() or "__pycache__" in f.parts:
            continue
        try:
            core_ids += len(_Q_ID.findall(f.read_text(encoding="utf-8")))
        except (UnicodeDecodeError, OSError):
            continue
    return (core_ids, len(_Q_ID.findall(skill)),
            skill.count("BeanRider"), len(_BR_ISSUE.findall(skill)))


def test_the_authoring_figures_are_derived_from_the_tree(tmp_path):
    """Control: the deriving arm must READ, not recite.

    Points `_seven_two_figures` at a fixture whose four answers are known by construction. A body
    replaced with the repo's current constants ignores `root` and returns the wrong tuple here,
    which is what closes the source-of-truth class. It also pins the two things the prose claims
    about the walk: `__pycache__` is skipped, and an undecodable file is passed over rather than
    crashing the count.
    """
    skill_dir = tmp_path / "core/skills/review-close"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "Q-1 and Q-22 and Q-1 again. BeanRider ISSUE-0001, BeanRider ISSUE-0002, BeanRider.",
        encoding="utf-8")
    (tmp_path / "core/other.md").write_text("Q-7 Q-8", encoding="utf-8")
    pyc = tmp_path / "core/__pycache__"
    pyc.mkdir()
    (pyc / "stale.pyc").write_text("Q-999 Q-998 Q-997", encoding="utf-8")
    (tmp_path / "core/blob.bin").write_bytes(b"\xff\xfe Q-555")
    # skill: Q-1, Q-22, Q-1 = 3 ; other.md: 2 ; pycache and undecodable excluded => core 5
    assert _seven_two_figures(root=tmp_path) == (5, 3, 3, 2)


def seven_two_problems(spec: str, computed: tuple) -> list[str]:
    """The real comparison, as a FUNCTION so a control can drive it over mutated input.

    Extracted after this phase's round found the first version's control VACUOUS: it re-ran the
    regex on its own mutation and asserted `n + 1 != n`, which is arithmetically always true, and
    never called the guard at all. Four mutations that killed the gate outright — comparing the
    computed tuple to itself, returning no problems, hard-coding the figures, neutering the
    duplicate-row arm — were caught by NONE of it.

    The sibling `per_section_problems` above already carries this exact lesson, including a
    docstring recording the identical prior failure. Inheriting that guard's shape without its
    lesson is what produced this one, twice in one phase: the duplicate-row arm was the first.
    A comparison written inline in a test body cannot be driven by a control; that is the whole
    reason this is a function.
    """
    rows = list(_SEVEN_TWO_ROW.finditer(spec))
    if not rows:
        return ["§ 7.2's `current state, at HEAD:` row is gone or reshaped — it is the only thing "
                "reading that section's four figures, and `Q-506` is about what happens without it"]
    # EXACTLY one, for the reason the per-section guard above carries: `re.search` takes the FIRST
    # match, so a second row left by a half-applied update sits there drifted and unread. This
    # phase's author-side battery demonstrated it — a drifted row appended AFTER the real one
    # passed, while the same row placed BEFORE it failed.
    if len(rows) != 1:
        return [f"{len(rows)} `§ 7.2 current state` rows in the spec; exactly one may exist, or "
                f"the guard silently reads whichever comes first"]
    published = tuple(int(g.replace(",", "")) for g in rows[0].groups())
    # Non-vacuity: published 0 against a computed 0 would agree over an empty population, which is
    # the shape `Q-506` is a symptom of rather than a cure for.
    if not all(c > 0 for c in computed):
        return [f"§ 7.2's derived population is empty somewhere: {computed} — the comparison "
                f"would pass by agreeing about nothing"]
    labels = ("Q- ids across core/", "Q- ids in review-close/SKILL.md",
              "BeanRider mentions", "BeanRider ISSUE ids")
    return [f"{lab}: published {p:,}, computed {c:,}"
            for lab, p, c in zip(labels, published, computed) if p != c]


def test_the_spec_publishes_the_authoring_figures_it_computes():
    """§ 7.2's four figures must be what the tree holds — `Q-506`.

    Filed by Phase 294's round: only two modules open this spec, and NEITHER reads § 7.2, so its
    four load-bearing counts rot exactly as the originals did. Phase 295 then moved two more with
    its own splits, which is the second demonstration in two phases.

    It does NOT claim the surrounding prose is correct — only that these four numbers describe
    this tree.
    """
    problems = seven_two_problems(SPEC.read_text(encoding="utf-8"), _seven_two_figures())
    assert not problems, (
        "§ 7.2's published authoring figures disagree with the tree:\n  "
        + "\n  ".join(problems)
        + "\n\nRe-derive with `tools/phase294_figures.py` (maintainer-side; never ships) and "
          "update the `§ 7.2 current state` row in the same commit."
    )


def test_every_tools_script_a_remedy_here_names_exists():
    """A remedy naming a file that does not exist is a remedy nobody can follow.

    `tools/phase295_figures.py` was named as the way to re-derive § 7.2's four figures and has
    **never existed in this repository's history** — those figures come from
    `tools/phase294_figures.py`, which prints all four. Same fabricated-citation class this
    module's docstring already records once, where a first cut credited the lazy-import pattern
    to `tools/skill_audit_check.py`, another file that never existed.

    **Scoped to ASSERTION MESSAGES, not to the file.** A first cut read the whole source and
    failed on its own docstring — which names both nonexistent scripts, correctly, as the
    history of this defect. A guard about dangling citations that cannot survive a record of
    the citations it fixed is the wrong guard: prose may name a file that is gone, a remedy
    may not.
    """
    tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    named: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assert) or node.msg is None:
            continue
        for sub in ast.walk(node.msg):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                named |= set(re.findall(r"tools/[A-Za-z0-9_./-]+\.(?:py|sh|md)", sub.value))
    assert named, "no tools/ path named in any assertion message — the guard finds nothing"
    missing = sorted(n for n in named if not (REPO / n).exists())
    assert not missing, (
        f"{len(missing)} tools/ path(s) named in a remedy here do not exist: {missing}. "
        f"A remedy message is only as good as the command it names."
    )


def test_a_drifted_authoring_row_is_reported():
    """Control: a row disagreeing with the tree must be REFUSED, driving the real arm."""
    spec = SPEC.read_text(encoding="utf-8")
    computed = _seven_two_figures()
    row = _SEVEN_TWO_ROW.search(spec)
    assert row, "no row to drift"
    drifted = spec.replace(row.group(0),
                           row.group(0).replace(f"BeanRider mentions {computed[2]}",
                                                f"BeanRider mentions {computed[2] + 7}"), 1)
    assert drifted != spec, "the control mutated nothing"
    assert seven_two_problems(drifted, computed), "a drifted row was accepted"


def test_a_duplicated_authoring_row_is_reported():
    """Control: a SECOND row — before or after the real one — must be refused either way.

    Both orders, because the defect this closes was order-dependent: the first version passed a
    drifted duplicate placed after the real row and failed the same one placed before it.
    """
    spec = SPEC.read_text(encoding="utf-8")
    computed = _seven_two_figures()
    row = _SEVEN_TWO_ROW.search(spec).group(0)
    bogus = ("§ 7.2 current state, at HEAD:  Q- ids across core/ 1 · in review-close/SKILL.md 1 "
             "· BeanRider mentions 1 · BeanRider ISSUE ids 1")
    for label, replacement in (("after", row + "\n" + bogus), ("before", bogus + "\n" + row)):
        assert seven_two_problems(spec.replace(row, replacement, 1), computed), (
            f"a duplicate row placed {label} the real one was accepted"
        )


def test_an_empty_authoring_population_is_reported():
    """Control: agreeing about nothing is not agreement.

    The row must be ZEROED TOO. A first version passed the live row against a zeroed population,
    where the ordinary drift comparison reports a problem anyway — so removing the non-vacuity arm
    left that control green and the mutation survived. The failure this arm exists for is a zeroed
    row agreeing with a zeroed tree, and only that input reaches it.
    """
    spec = SPEC.read_text(encoding="utf-8")
    row = _SEVEN_TWO_ROW.search(spec).group(0)
    zeroed = re.sub(r"(?<= )\d[\d,]*(?=(\s|$))", "0", row)
    assert zeroed != row, "the control zeroed nothing"
    problems = seven_two_problems(spec.replace(row, zeroed, 1), (0, 0, 0, 0))
    assert problems, "a zeroed row against an empty population was accepted"
    assert "empty" in problems[0], (
        f"refused, but not by the non-vacuity arm — message was {problems[0]!r}"
    )


def test_a_missing_authoring_row_is_reported():
    """Control: the guard must not fall silent when its own row is deleted.

    Asserts the MESSAGE, not just that something was returned. Without that, neutering the
    missing-row arm still reports a problem — the exactly-one arm catches `rows == []` as a count
    of zero — and the control cannot tell the two apart, which is how it survived its own
    mutation.
    """
    spec = SPEC.read_text(encoding="utf-8")
    row = _SEVEN_TWO_ROW.search(spec).group(0)
    problems = seven_two_problems(spec.replace(row, "(row removed)", 1), _seven_two_figures())
    assert problems, "a spec with no `§ 7.2 current state` row was accepted"
    assert "gone or reshaped" in problems[0], (
        f"refused, but not by the missing-row arm — message was {problems[0]!r}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# The editor-mass ratchet — `Q-504`, ratified 2026-09-15, built in Phase 297.
#
# The convention it enforces is written in `core/skills/review-close/REFERENCE.md`
# § *Where new rationale goes*: new rationale is authored in the reference, not the
# runner. Without a gate that is a convention honoured by memory, which is what
# Phase 154 ruled is not a mechanism.
#
# **Absolute characters, not a share.** A share ratchet (`editor+mixed` as a percentage
# of the file) is satisfied by adding runner text: write four kilobytes of new
# procedure and the same rationale mass reads as a smaller fraction. The measured
# behaviour of this file is that it grows — roughly +8 KB per touching commit across
# the eleven that ran from Phase 275 to Phase 290 — so a share denominator is the one
# quantity an author can move without deleting anything.
#
# **Not the ceiling `tools/CONTEXT_THINNING_SPEC.md` § 10 refuses.** That refusal is
# about a per-file token budget, and it stands: Phase 168 built a character ratchet on
# a whole file, measured it, and removed it when a 19-character softening fit under the
# slack with every test green. This one constrains EDITOR mass only. Instructions are
# unconstrained — a phase may add as much procedure as the work needs — so the
# shrink-and-add bypass has nothing to trade against.
#
# **What it cannot do, stated rather than implied.** The ceiling is a constant in a test
# file, so raising it is possible; what the gate buys is that raising it is a deliberate,
# visible edit in the diff rather than a side effect of writing prose. That is the half
# `CLAUDE.md`'s round dimension covers — a reviewer reads the phase's own diff for
# rationale belonging in `REFERENCE.md` — and it is why `Q-504` was ratified as BOTH
# halves. Neither alone is a mechanism: the ratchet nets out under shrink-and-add, and a
# dimension is recall that can be skipped silently.
#
# The figures are NOT repeated here. A first version of this comment read "verified at
# authoring … 37,211 `editor` + 112,981 `mixed` = 150,192", which was already wrong in all
# three numbers by the time Phase 299 edited the line below it and left the comment standing
# — the `Q-495` class, one line above the constant the campaign moves most often. The live
# values are what `test_the_ratchet_constants_describe_this_tree` compares against; a comment
# restating them is a second copy nothing checks. Round finding, guards lens.
EDITOR_MIXED_CEILING = 105_968

# How far the ceiling may sit ABOVE the measured value before the guard demands it be
# lowered. Without this the ratchet is one-directional in the wrong way: the thinning
# campaign relocates a section, the measured mass drops, the constant stays where it was,
# and the phase after that silently inherits a section's worth of headroom to re-fill.
#
# 642, not 5,000, since `Q-513` (Phase 300). The number is derived, not chosen: it is one
# below § 1b's 643, the smallest section in `campaign_population()`. The old 5,000 was sized
# against "the campaign's unit of work — the sections it relocates run 24,000–29,000
# characters", which was true of the three sections the campaign had RUN and false of the
# fourteen § 9's scope still covers; eight of those sat below 5,000 and could each have been
# relocated whole and banked.
#
# The cost is stated rather than discovered: the same comment used to promise that "an
# ordinary edit that moves a few hundred characters does not force a constant update", and
# at 642 that promise is gone. Most commits touching editor mass now carry a visible ceiling
# edit. Wade accepted that trade at Phase 300's open as the honest half of shape (a).
CEILING_FOLLOWS_WITHIN = 642


def editor_mass_problems(total: int, ceiling: int = None, slack: int = None) -> list[str]:
    """Both bounds as ONE predicate the tests and their controls share.

    The first version put the comparisons inline in each test and gave the control its own
    arithmetic — so the control re-asserted its own mutation instead of driving the guard,
    and this phase's battery walked `assert total <= EDITOR_MIXED_CEILING or True` straight
    through it (M15). That is the exact shape `test_a_wrong_published_digit_is_reported`
    above was rewritten to avoid, made again later in the same file.
    """
    ceiling = EDITOR_MIXED_CEILING if ceiling is None else ceiling
    slack = CEILING_FOLLOWS_WITHIN if slack is None else slack
    problems = []
    if total <= 0:
        return ["the census computed no editor+mixed characters — the ratchet would pass by "
                "measuring nothing, which is the shape its sibling guards exist to refuse"]
    if total > ceiling:
        problems.append(
            f"`review-close/SKILL.md` carries {total:,} characters of editor-facing text "
            f"(`editor` + `mixed`), against a ceiling of {ceiling:,} — {total - ceiling:,} "
            "over.\n\nNew rationale is authored in `core/skills/review-close/REFERENCE.md`, "
            "not in the runner (§ *Where new rationale goes*). The runner gets the "
            "instruction plus a one-line reason ONLY where the reason changes what the "
            "runner does.\n\nIf the added text really is runner material, say so by "
            "classifying its blocks `runner` in the census verdicts — that is a claim a "
            "reviewer reads, which is the point. Raising this ceiling is the last resort."
        )
    if ceiling - total > slack:
        problems.append(
            f"the ceiling sits {ceiling - total:,} characters above the measured {total:,} — "
            f"more than the {slack:,} a single edit should ever open up. Editor text has been "
            f"relocated out of the runner and the gain was not locked in: lower "
            f"EDITOR_MIXED_CEILING to {total:,} in the same commit that removed the text."
        )
    return problems


def test_review_close_editor_mass_does_not_grow():
    """The ratchet. `editor` + `mixed` absolute characters may not exceed the ceiling."""
    _, total = _per_section_editor_mixed("review-close")
    assert not editor_mass_problems(total), "\n".join(editor_mass_problems(total))


def test_the_ceiling_follows_the_campaign_down():
    """A relocated section must be locked in, not banked as headroom.

    The ratchet refuses growth. This refuses a ceiling that has drifted far above the
    measured value — which is what happens by default every time the thinning campaign lands
    a section and nobody edits the constant.
    """
    _, total = _per_section_editor_mixed("review-close")
    drift = [p for p in editor_mass_problems(total) if "above the measured" in p]
    assert not drift, "\n".join(drift)


@pytest.mark.parametrize("total,ceiling,slack,expect", [
    (150_192, 150_192, 5_000, False),          # the live shape: green
    (150_193, 150_192, 5_000, True),           # one character over the ceiling
    (100_000, 150_192, 5_000, True),           # a section relocated, ceiling not lowered
    (149_000, 150_192, 5_000, False),          # ordinary drift, inside the slack
    (0, 150_192, 5_000, True),                 # a census that measured nothing
    # THE ZERO ARM, ISOLATED — `Q-518`, Phase 301. The row above does not pin the zero arm and
    # `Q-515` cites it as though it does. Measured: with `if total <= 0:` neutered to
    # `if False:`, a ceiling of 150,192 against a measured 0 is a 150,192-character gap, so the
    # DRIFT arm answers instead and `expect=True` is satisfied either way. Here the ceiling sits
    # inside the slack (100 - 0 < 5,000) and 0 is not over it, so no other arm can fire: neuter
    # the zero arm and this row alone goes green-to-red. Keep the pair — the row above is the
    # realistic shape, this one is the discriminator.
    (0, 100, 5_000, True),
])
def test_the_editor_mass_ratchet_is_not_vacuous(total, ceiling, slack, expect):
    """The negative control, driving the REAL predicate rather than re-asserting it.

    The first version did its own arithmetic in the test body, so mutating the guard to
    `assert total <= EDITOR_MIXED_CEILING or True` left it green — the control was testing a
    copy of the rule instead of the rule. Every case here calls `editor_mass_problems`, so
    neutering either bound reddens this.
    """
    problems = editor_mass_problems(total, ceiling, slack)
    assert bool(problems) is expect, (
        f"editor_mass_problems({total:,}, ceiling={ceiling:,}, slack={slack:,}) returned "
        f"{problems!r}; expected {'a problem' if expect else 'none'}"
    )


def test_the_zero_section_arm_is_the_one_that_answers():
    """`Q-518`, Phase 301's round (MS6) — and the row that was supposed to pin this could not.

    `slack_problems` refuses a census where a section measured zero, BEFORE deriving a bound from
    what is left. Deleting `or not all(sections.values())` left the whole suite green, because the
    parametrize row commented *"a zero section is a decision, not a bound"* is answered by the
    derived bound instead: with a zero section, `slack >= 0` holds for every non-negative slack,
    so both arms return `True` and the boolean cannot discriminate.

    **A first fix added a second row with a smaller slack and it survived too** — for the same
    reason, which is that no slack makes `>= 0` false. The arm is only reachable through its
    MESSAGE, so that is what this asserts, exactly as the drift arm's control does one predicate
    over. The `len == 1` half is the second claim: the arm must RETURN, not append and continue.
    """
    problems = slack_problems(100, {"3b": 24_487, "4c": 0, "2b": 25_804}, 5_000)
    assert len(problems) == 1, (
        f"the zero-section arm must RETURN, not fall through into the derived bound — "
        f"got {len(problems)}: {problems!r}")
    assert "renamed" in problems[0] and "relocated" in problems[0], (
        f"a zero section was answered by the wrong arm — the derived bound cannot refuse a "
        f"census that measured nothing, it can only bound from what is left: {problems!r}")


def test_the_ratchet_zero_arm_returns_rather_than_falling_through():
    """`Q-518`, Phase 301's round (MS2). The sibling of the `slack_problems` fix, one predicate over.

    The phase asserted *"the missing arm must RETURN, not fall through"* for `slack_problems` and
    asserted nothing of the kind for `editor_mass_problems`' zero arm — so changing its `return`
    to an append left the suite green. A census that measured nothing is a refusal, not a finding
    to be listed alongside a drift complaint: the arm exists to say the measurement is void, and a
    void measurement has no drift to report.

    The ceiling here sits far above 0, so a fall-through would add the drift problem and give two.
    """
    problems = editor_mass_problems(0, 150_192, 5_000)
    assert len(problems) == 1, (
        f"the zero arm must RETURN, not fall through — got {len(problems)} problem(s): {problems!r}")
    assert "measuring nothing" in problems[0], problems


def test_the_follower_drift_arm_is_not_vacuous():
    """The control `test_the_ceiling_follows_the_campaign_down` shipped without.

    Phase 300's round neutered that test three ways and the suite stayed green every time:
    `drift = []`, rewording the message its string filter selects on, and deleting the inline
    backstop. A test whose only assertion is `assert not drift` where `drift` is a filtered list
    is one token from inert, and nothing was driving the filter.

    This drives `editor_mass_problems` directly for the drift arm, so neutering the arm, widening
    it, or breaking the phrase the filter selects on all redden here.
    """
    # the arm fires: ceiling far above the measured value
    problems = editor_mass_problems(100_000, 150_192, 5_000)
    drift = [p for p in problems if "above the measured" in p]
    assert drift, "the drift arm did not fire on a 50,192-character gap"
    # and it does NOT fire inside the slack
    assert not [p for p in editor_mass_problems(149_000, 150_192, 5_000)
                if "above the measured" in p], "the drift arm fired inside its own slack"
    # the boundary, which is what a 10x widening walks through
    assert [p for p in editor_mass_problems(145_191, 150_192, 5_000) if "above the measured" in p]
    assert not [p for p in editor_mass_problems(145_192, 150_192, 5_000) if "above the measured" in p]


def test_the_section_map_fork_guard_is_not_vacuous():
    """`test_every_copy_of_the_campaign_section_map_agrees` has no control of its own.

    Phase 300's round killed every mutation to the map's SUBJECT — removing `2d` from any of the
    three copies, one-character heading drift, a phantom id — and then neutered the guard itself
    two ways (`distinct = {}`, dropping a copy from `copies`) with the suite green. The guard is
    load-bearing for every phase in the ratified bundle plan and was red-on-arrival in this very
    phase, which is the strongest evidence it works and no evidence at all that it cannot be
    switched off.
    """
    import test_thinning_transforms as TT
    ref = {"3b": "a", "4c": "b"}
    assert TT.section_map_problems({"x": ref, "y": dict(ref)}, ref) == []
    assert TT.section_map_problems({"x": ref, "y": {"3b": "a"}}, ref), "a forked copy passed"
    assert TT.section_map_problems({"x": ref, "y": {}}, ref), "an empty copy passed"


def test_the_ratchet_constants_describe_this_tree():
    """The constants are wired to the live census, not to a stale copy of its numbers.

    Both bounds are constants in this file, so both can be edited. What this asserts is the
    property an edit cannot fake: the ceiling is a real measurement of THIS file, within the
    slack the follower allows. Raising the constant to buy headroom is still possible and is
    deliberately visible in the diff — that is what `CLAUDE.md`'s round dimension 10 reads,
    and why `Q-504` was ratified as both halves rather than the ratchet alone.
    """
    _, total = _per_section_editor_mixed("review-close")
    # Driving the REAL predicate, not a copy of it. ROUND FINDING (guards lens, LOW 8): this
    # body did its own arithmetic, so widening `editor_mass_problems`' follower arm to
    # `slack * 10` AND raising the ceiling to match left the whole module green — the two
    # bounds covered for each other because neither test called the other's predicate. That is
    # the shape three docstrings in this file already condemn, in the one test positioned as
    # everything else's backstop.
    assert total > 0, "the census measured nothing; every bound below is vacuous"
    assert not editor_mass_problems(total), "\n".join(editor_mass_problems(total))
    assert EDITOR_MIXED_CEILING <= total + CEILING_FOLLOWS_WITHIN, (
        f"measured {total:,}, ceiling {EDITOR_MIXED_CEILING:,}, slack "
        f"{CEILING_FOLLOWS_WITHIN:,} — the ceiling no longer describes this tree"
    )


#: A hard cap on the follower slack, on top of the derived bound below.
#:
#: WHY BOTH, and the first version of this guard had only the derived half. That half bounds the
#: slack by the SMALLEST campaign section — and after a section is thinned, the smallest section
#: IS the thinned remnant, so the bound loosens exactly when the campaign succeeds. Measured by
#: Phase 298's round at that phase's own close: § 4c had just fallen to 11,971, so the derived
#: bound alone permitted a slack of 11,970 and a ceiling 11,970 above the measured total — 2.39x
#: what the constant's own justification allows, and about the entire mass that phase had just
#: relocated. "A completed section cannot be banked" was the point, and the derived bound was
#: sized by the completed section.
#:
#: 5,000 is the campaign's unit of work as § 9.1 states it: the sections it relocates run
#: 24,000-29,000 characters, and the three relocations on record moved 1,317 / 7,256 / 8,939
#: characters off the file. A slack under 5,000 forces the ceiling down on any of the last two
#: while leaving an ordinary few-hundred-character edit alone.
SLACK_CEILING = 5_000


def _section_label(head: str) -> str:
    """A short, stable id for a heading, for the bound's own error message.

    `_CAMPAIGN_SECTIONS` carries ids; `_SECTIONS_NOT_YET_TAKEN` carries headings. Since `Q-513`
    the bound reads both, so the untaken ones need a label too — printing fourteen full headings
    in a failure message buries the one number the reader came for. Collisions are asserted
    against, not hoped for: two sections sharing a label would silently drop one from the
    population this bound is derived from, which is the defect `Q-513` itself was.
    """
    t = re.sub(r"^#+\s*", "", head).strip()
    # `Step 3b:` and `3b.` are the same section in two spellings, and `_CAMPAIGN_SECTIONS`
    # calls it `3b` in both cases. Deriving `Step 3b` here would put the two rosters in
    # different vocabularies, so a heading sitting on BOTH would land under two labels and be
    # counted twice instead of refused — found by this module's own collision control.
    m = re.match(r"^Step\s+([0-9]+[a-z]?)\s*:", t) or re.match(r"^([0-9][0-9a-z-]*)\.\s", t)
    return m.group(1) if m else t.split(":")[0].strip()


def campaign_population(taken: dict | None = None, not_taken=None) -> dict:
    """`{label: heading}` for every section § 9's ratified scope covers — taken or not.

    `Q-513`, shape (a), ratified by Wade 2026-09-16. The bound below was derived from
    `_CAMPAIGN_SECTIONS` alone — the sections the campaign had already RUN — while § 9's scope is
    *"`review-close` only, every section, then STOP"*. Measured at Phase 299's close, that made
    the guard's own stated job false: the slack was 5,000 and the smallest TAKEN section was
    § 2b's 7,807, so the bound passed, while EIGHT rostered sections sat below the slack — § 1b
    643 through § 4a 4,994. A phase taking any one of them would have relocated it whole and owed
    no ceiling edit, which is exactly the headroom this bound exists to refuse.

    Shape (b) — lowering `SLACK_CEILING` to the same number — was declined: it is the same value
    reached by a route that leaves the reasoning in a constant, so the next phase to add a section
    smaller than § 1b gets no signal. Shape (c) — bounding by the section the next phase will take
    — was declined for coupling the guard to a plan rather than to the file.

    The cost is real and was Wade's to accept: the honest population makes the slack 642, below
    the *"ordinary few-hundred-character edit"* `CEILING_FOLLOWS_WITHIN`'s own comment was sized
    to tolerate, so most commits that move editor mass now carry a visible ceiling edit.
    """
    named = dict(_CAMPAIGN_SECTIONS if taken is None else taken)
    for head in (_SECTIONS_NOT_YET_TAKEN if not_taken is None else not_taken):
        label = _section_label(head)
        if label in named:
            raise AssertionError(
                f"the label {label!r} is claimed twice: {named[label]!r} and {head!r} — either "
                f"two headings derive the same label, or one heading is on BOTH rosters. Each "
                f"silently drops a member from the population the slack bound is derived from, "
                f"which is `Q-513` arriving by another route.")
        named[label] = head
    return named


def campaign_sections(per: dict) -> tuple[dict, list[str]]:
    """`({label: chars}, [missing labels])` for every section in the campaign's scope.

    Absence is detected by MEMBERSHIP and not by a sentinel default. The first version built the
    dict with `per.get(head, 0)` and let `all(sections.values())` notice the zero — which Phase
    298's round defeated in one token by changing the default to `10**9`: the renamed heading then
    reports as the largest section in the file, the zero-detector sees nothing, and the derived
    bound is taken from a section that no longer exists. A detector whose signal is a default
    value is a detector a default value can switch off.
    """
    named = campaign_population()
    present = {sid: per[head] for sid, head in named.items() if head in per}
    missing = [sid for sid in named if sid not in present]
    return present, missing


def slack_problems(slack: int, sections: dict, cap: int = None,
                   missing: list | None = None) -> list[str]:
    """Both bounds on `CEILING_FOLLOWS_WITHIN` as ONE predicate the test and its control share.

    The shape `editor_mass_problems` above already carries, for the reason recorded there: a
    control that does its own arithmetic re-asserts its own mutation instead of driving the
    guard, and Phase 297's battery walked exactly that. Phase 298 then shipped this guard's
    predecessor with **no control at all**, and its round widened the derived bound tenfold with
    every arm green.
    """
    cap = SLACK_CEILING if cap is None else cap
    problems = []
    if missing:
        return [f"campaign section(s) {missing} carry no editor+mixed blocks at all — either a "
                f"heading was renamed or the section is fully relocated. Both want a decision "
                f"here rather than a bound derived from what is left."]
    if not sections or not all(sections.values()):
        return [f"a campaign section reports zero editor+mixed characters — {sections}. Either a "
                f"heading was renamed or the section is fully relocated; both want a decision "
                f"here rather than a bound derived from a zero."]
    smallest = min(sections, key=sections.get)
    if slack >= sections[smallest]:
        problems.append(
            f"slack {slack:,} is not smaller than § {smallest}'s {sections[smallest]:,} "
            f"editor+mixed characters — a phase could relocate that whole section and bank it "
            f"as headroom. Lower CEILING_FOLLOWS_WITHIN in the commit that relocates the text."
            f"\n  per-section: {sections}")
    if slack > cap:
        problems.append(
            f"slack {slack:,} exceeds the campaign's unit of work ({cap:,}). The derived bound "
            f"below loosens as sections are thinned — it is sized by the smallest section, which "
            f"after a relocation is the section just relocated — so this cap is what stops a "
            f"completed section being banked as headroom.")
    return problems


def test_the_follower_slack_is_smaller_than_a_section():
    """The slack's own justification, asserted rather than left in a comment.

    `CEILING_FOLLOWS_WITHIN` exists so a COMPLETED SECTION cannot be banked as headroom for the
    next phase to re-fill. That reasoning was written down and nothing held it: Phase 298's
    battery widened the constant tenfold, to 50,000, and every arm stayed green, because the
    constants arm compares a ceiling that already equals the measured total and a wider slack
    changes nothing about it.

    Two bounds, because the derived one alone points the wrong way as the campaign proceeds —
    see `SLACK_CEILING`.

    Since `Q-513` the population is every section § 9's scope names, not the three the campaign
    had run. The floor is therefore read off the CENSUS as well as off the roster: a roster that
    lost members could otherwise satisfy the bound by shrinking its own population, which is
    exactly the shape `Q-513` was.
    """
    per, _ = _per_section_editor_mixed("review-close")
    sections, missing = campaign_sections(per)
    problems = slack_problems(CEILING_FOLLOWS_WITHIN, sections, missing=missing)
    assert not problems, "\n".join(problems)

    floor = min(per.values())
    assert CEILING_FOLLOWS_WITHIN < floor and min(sections.values()) == floor, (
        f"slack {CEILING_FOLLOWS_WITHIN:,} against a file floor of {floor:,} and a bound "
        f"population whose smallest is {min(sections.values()):,} — a bound derived from a "
        f"subset of the sections in scope is `Q-513` reopened")


def test_a_label_collision_is_raised_rather_than_silently_dropping_a_section():
    """The collision arm, driven — it is unreachable on the current headings, so nothing else
    drives it, and the author battery walked `assert True or ...` straight through it.

    A collision does not fail loudly on its own: the second heading overwrites the first in a
    dict and the population quietly loses a member, which is `Q-513`'s own defect — a bound
    derived from fewer sections than § 9's scope names — arriving by a different route.
    """
    taken = {"3b": "## Step 3b: Prepare Worktrees for Merge"}
    # two DIFFERENT headings deriving one label
    with pytest.raises(AssertionError, match="claimed twice"):
        campaign_population(taken, ["### 3b. A different heading that labels the same"])
    # the SAME heading on both rosters — taken and not-taken at once. An earlier cut of this
    # arm carried `and named[label] != head`, which made exactly this case pass silently; the
    # author battery found it by removing the inequality and staying green.
    with pytest.raises(AssertionError, match="claimed twice"):
        campaign_population(taken, list(taken.values()))
    # and the non-colliding case still builds, so the arm is a discriminator not a blanket
    ok = campaign_population(taken, ["### 1b. Preserve Uncommitted `review_tasks.md`"])
    assert set(ok) == {"3b", "1b"}, ok


@pytest.mark.parametrize("slack, sections, cap, expect", [
    # (the live shape) — inside both bounds
    (5_000, {"3b": 24_487, "4c": 11_971, "2b": 25_804}, 5_000, False),
    # the derived bound alone would allow this; the cap refuses it. THE ROUND'S FINDING.
    (11_970, {"3b": 24_487, "4c": 11_971, "2b": 25_804}, 5_000, True),
    # the cap alone would allow this; the derived bound refuses it.
    (4_999, {"3b": 24_487, "4c": 4_000, "2b": 25_804}, 5_000, True),
    # a loosened cap is caught by the derived bound rather than sailing through
    (50_000, {"3b": 24_487, "4c": 11_971, "2b": 25_804}, 500_000, True),
    # EXACT EQUALITY. `>=`, not `>` — a slack equal to the smallest section still permits that
    # section to be relocated whole and banked. Phase 299's battery flipped the operator and
    # nothing reddened, because every other row here sits strictly one side or the other.
    (4_000, {"3b": 24_487, "4c": 11_971, "2b": 4_000}, 5_000, True),
    # a zero section is a decision, not a bound
    (100, {"3b": 24_487, "4c": 0, "2b": 25_804}, 5_000, True),
    # NOTE — the zero-section arm cannot be isolated by a boolean row at all, and the attempt is
    # recorded because it looks like it should work. Any zero section makes the DERIVED bound fire
    # too (`slack >= 0` for every non-negative slack), so both arms answer `True` and no `expect`
    # value can tell them apart. It is pinned by
    # `test_the_zero_section_arm_is_the_one_that_answers` below, on the MESSAGE — the shape
    # `test_the_follower_drift_arm_is_not_vacuous` already uses for the same reason.
    (100, {}, 5_000, True),
    # THE DEFAULT CAP ITSELF. `cap=None` reads `SLACK_CEILING`, so raising that constant turns
    # this row False and reddens the control. Without a row that omits `cap`, every case passes
    # its own value and the module constant is pinned by nothing — the round widened it tenfold
    # with the whole suite green.
    (5_001, {"3b": 24_487, "4c": 11_971, "2b": 25_804}, None, True),
    (5_000, {"3b": 24_487, "4c": 11_971, "2b": 25_804}, None, False),
])

def test_the_slack_bounds_refuse_what_they_claim_to(slack, sections, cap, expect):
    """The control the first version of this guard did not have.

    Every case calls `slack_problems`, so neutering either bound — or widening the derived one,
    which the round did with a single `* 10` — reddens this.
    """
    problems = slack_problems(slack, sections, cap)
    assert bool(problems) is expect, (
        f"slack_problems({slack:,}, {sections}, cap={cap:,}) returned {problems!r}; "
        f"expected {'a problem' if expect else 'none'}")


def test_a_renamed_or_emptied_section_is_reported_rather_than_derived_around():
    """The `missing` arm, driven — it is unreachable on a clean tree, so nothing else drives it.

    Phase 298's round defeated the predecessor's zero-detector by changing a `.get` default; the
    replacement detects absence by membership, and this is what proves the replacement is not
    itself decorative. Both halves are exercised: `campaign_sections` must NOTICE the absence, and
    `slack_problems` must REFUSE on it rather than bounding from what is left.
    """
    population = campaign_population()
    per = {head: 20_000 for head in population.values()}
    sections, missing = campaign_sections(per)
    assert missing == [] and len(sections) == len(population), (sections, missing)

    # Since `Q-513` the population is BOTH rosters, so the absence has to be exercised on an
    # untaken section too — a fixture built from `_CAMPAIGN_SECTIONS` alone would have kept
    # passing while the sections the widening added went unchecked.
    #
    # EVERY member, sorted — not `next(iter(frozenset))`. The first cut used exactly that, and
    # Phase 300's round measured it exercising ONE of thirteen untaken sections, chosen by
    # CPython's per-process `str` hash salt: three distinct headings across five bare runs, and
    # a mutation that dropped § 1b passed under `PYTHONHASHSEED=1` and failed under `0`.
    # `tests/conftest.py` states the rule this broke — *"a salted key is not a flaky run, it is
    # ids that quietly go unrun"* — in this same suite.
    for gone in [_CAMPAIGN_SECTIONS["3b"], *sorted(_SECTIONS_NOT_YET_TAKEN)]:
        sections, missing = campaign_sections({h: v for h, v in per.items() if h != gone})
        assert missing, f"a section absent from the census was not noticed: {gone!r}"
        assert len(sections) == len(population) - 1, sections

    # The slack here is 20,000 and not 100, and the value is the whole assertion below.
    #
    # `Q-518`, Phase 301. With a slack of 100 against sections of 20,000, NEITHER later arm can
    # fire — the derived bound wants `100 >= 20,000` and the cap wants `100 > 5,000`. So
    # `return` and `append`-then-continue produce the same single problem and the
    # `len(problems) == 1` assertion below, whose entire subject is that difference, passed
    # under both. At 20,000 the derived bound fires (`20,000 >= 20,000`, the `>=` this module
    # already pins elsewhere) and so does the cap, so a fall-through yields three problems and
    # the assertion is finally load-bearing. **The precise threshold is the CAP, not this value:**
    # the round measured a fall-through surviving at 100 and at 5,000 and dying from 5,001 up, so
    # anything above the cap restores the test. 20,000 is chosen to trip both later arms rather
    # than one; a first version of this comment claimed the arm dies if the number is lowered at
    # all, which overstates a fixture's precision and is the kind of claim a maintainer trusts.
    problems = slack_problems(20_000, sections, cap=5_000, missing=missing)
    assert problems and "renamed" in problems[0], problems
    assert len(problems) == 1, (
        "the missing arm must RETURN, not fall through — a bound derived from the sections that "
        "remain is exactly what it exists to refuse")


# ─────────────────────────────────────────────────────────────────────────────
# The convention's other two surfaces — `Q-504`'s dimension half.
#
# The ratchet above is mechanical and self-evidently wired. These are the two places
# the convention is WRITTEN, and prose is what goes stale: a destination that stops
# existing, or a round dimension deleted in a tidying pass, both leave the ratchet
# guarding one skill while the rule it enforces has quietly stopped being stated.
RATIONALE_REFERENCE_SKILLS = ("review-close", "claim-task", "security-audit", "codebase-review")
RATIONALE_SECTION = "## Where new rationale goes"

# Both constants above are the guard's subject, and the round's guards lens disarmed each with
# a one-token edit that left the module green: `RATIONALE_SECTION = "#"` (every `REFERENCE.md`
# contains a `#`) and `RATIONALE_REFERENCE_SKILLS = ("review-close",)`, which stops checking
# `Q-504`'s entire deliverable. Unlike the three declared constant-edit no-ops, those make an
# arm assert NOTHING rather than assert a looser bound, so they are pinned rather than declared.
assert RATIONALE_SECTION.startswith("## ") and len(RATIONALE_SECTION) > 12, (
    "RATIONALE_SECTION no longer names a heading; a short or prefix-weakened value is "
    "satisfied by any markdown file and the destination check stops checking"
)
assert len(RATIONALE_REFERENCE_SKILLS) >= 4, (
    "the destination check covers fewer than the four skills `CLAUDE.md` round dimension 10 "
    "names. Narrowing this set is how `Q-504`'s sibling deliverable stops being guarded — "
    "if a skill genuinely leaves the convention, remove it from CLAUDE.md in the same commit "
    "and this bound with it."
)


def test_every_named_skill_has_a_reference_destination():
    """A rule that says "author it over there" needs a *there* for each skill it binds.

    Phase 290's finding was an invoker that shipped to nobody; this is the same defect
    pointed the other way — a convention naming a destination that does not exist reads as
    binding and enforces nothing. `CLAUDE.md`'s dimension 10 names these four skills, so
    these four must each carry the section that receives the text.
    """
    missing = []
    for slug in RATIONALE_REFERENCE_SKILLS:
        ref = REPO / "core/skills" / slug / "REFERENCE.md"
        if not ref.is_file():
            missing.append(f"{slug}: no REFERENCE.md")
            continue
        if RATIONALE_SECTION not in ref.read_text(encoding="utf-8"):
            missing.append(f"{slug}: REFERENCE.md has no `{RATIONALE_SECTION}` section")
    assert not missing, (
        "`CLAUDE.md` round dimension 10 sends new rationale to a skill's `REFERENCE.md`, "
        "and for these skills there is nowhere for it to go:\n  " + "\n  ".join(missing)
    )


def test_the_round_dimension_is_stated_in_claude_md():
    """The recall half of `Q-504`, and the half that can be deleted without anything failing.

    Kept deliberately narrow: it asserts the dimension is stated and that it still names the
    skills the sibling guard checks, not the wording. A guard pinned to prose gets deleted
    when the prose is legitimately rewritten — the over-strictness direction Phase 288's
    round measured — so what is pinned here is the JOIN between the two surfaces.
    """
    claude_md = REPO / "CLAUDE.md"
    if not claude_md.is_file():
        pytest.skip("CLAUDE.md is maintainer-side and excluded from the public mirror")
    text = claude_md.read_text(encoding="utf-8")
    assert "Round dimension 10" in text, (
        "`CLAUDE.md` no longer states round dimension 10. The ratchet in this module is the "
        "mechanical half of `Q-504`; without the dimension, a phase that adds rationale to a "
        "skill with no census — three of the four — is read by nobody and caught by nothing."
    )
    dimension = text[text.index("Round dimension 10"):][:2000]
    unnamed = [s for s in RATIONALE_REFERENCE_SKILLS if f"`{s}`" not in dimension]
    assert not unnamed, (
        f"round dimension 10 no longer names {unnamed}, but "
        "`test_every_named_skill_has_a_reference_destination` still demands a destination "
        "for them — the two surfaces have drifted apart, and one of them is wrong"
    )


def test_every_reference_destination_is_reachable_from_its_runner():
    """A destination nobody is pointed at is Phase 290's defect one step further along.

    `review-close/SKILL.md` has carried an "Editing this skill rather than running it?" pointer
    since its `REFERENCE.md` was written. The three siblings Phase 297 added shipped without
    one, so an editor opening those runners got no signal the destination existed — found by
    the round's execution lens, which noted the sibling test's own docstring cites Phase 290's
    "invoker that shipped to nobody" while committing the same defect.

    The pointer must also be EARLY: a reader who has to scroll past the procedure to learn
    where rationale goes has already started writing it in the runner.
    """
    unreachable = []
    for slug in RATIONALE_REFERENCE_SKILLS:
        body = (REPO / "core/skills" / slug / "SKILL.md").read_text(encoding="utf-8")
        if "REFERENCE.md" not in body:
            unreachable.append(f"{slug}: SKILL.md never mentions REFERENCE.md")
            continue
        line = body[:body.index("REFERENCE.md")].count("\n") + 1
        if line > 40:
            unreachable.append(f"{slug}: the pointer is at line {line}, past the opening")
    assert not unreachable, (
        "skill runners that do not point at their editor reference:\n  "
        + "\n  ".join(unreachable)
    )
