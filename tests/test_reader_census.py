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


@pytest.mark.parametrize("skill", CENSUSED)
def test_the_construction_rule_never_overrides_an_authored_verdict(skill):
    """`classify` answers `construction` first, so an authored verdict on a `code` block would be
    silently ignored rather than applied. Nothing should be recorded for those blocks; if
    something is, either the rule or the verdict is wrong and neither should lose quietly."""
    recorded = json.loads((VERDICTS / f"{skill}.json").read_text(encoding="utf-8"))
    blocks = enumerate_blocks(SKILLS / skill / "SKILL.md")
    shadowed = sorted({b.sha for b in blocks
                       if b.kind in CONSTRUCTION_RUNNER and b.sha in recorded})
    assert not shadowed, (
        f"{skill}: {len(shadowed)} authored verdict(s) sit on by-construction blocks and are "
        f"being ignored: {shadowed[:5]}"
    )


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
}

_CURRENT_ROW = re.compile(
    r"current per-section editor\+mixed, at HEAD:\s+"
    + r"\s+·\s+".join(rf"{sid}\s+([\d,]+)" for sid in _CAMPAIGN_SECTIONS)
    + r"\s+·\s+total\s+([\d,]+)"
)


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


@pytest.mark.parametrize("group", [0, 1, 2, 3])
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
        + "\n\nRe-derive with `tools/phase295_figures.py` (maintainer-side; never ships) and "
          "update the `§ 7.2 current state` row in the same commit."
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
