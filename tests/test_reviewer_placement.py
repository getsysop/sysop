"""Phase 290 (`Q-490`) — the reviewer-placement rule reaches the skills that spawn reviewers.

Phase 288 wrote the rule into `_shared/adversarial-review.md` and wired its only invoker
into `CLAUDE.md`, which `tools/make_public_mirror.sh` strips. So for a consumer the rule
shipped to nobody: `/review-close` Step 2b spawned convention reviewers with a bare
`isolation: "worktree"`, which forks from the **default branch**, and under `pr` policy the
target is always a branch that has not merged. Every lens read the pre-merge tree, found
nothing, and returned `APPROVED` — this repo's *a dead review looks like a clean one* class,
in shipped code, on the close path.

**These guards test whether the requirement BINDS, not whether particular words are present.**
Every predicate below is paired with negative controls that carry the specific softening a
future edit would plausibly make — the shape `test_adversarial_review_gate.py` established
after its own round retired the gate with every test green. A guard that green-lights a
document stating the opposite of the rule is worse than no guard.

Scoping is load-bearing. `review-close/SKILL.md` is ~3,700 lines and says "worktree" more
than a hundred times, so a whole-file substring check is satisfied by prose about
`/claim-task`'s worktrees, about the harness's `.claude/worktrees/` leak sweep, or about
Step 3b's merge preparation. Each predicate is scoped to the step it governs.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from skill_runner_text import text_of

REPO = Path(__file__).resolve().parent.parent
RC = REPO / "core/skills/review-close/SKILL.md"
PARTIAL = REPO / "core/skills/_shared/adversarial-review.md"
CODEBASE_REVIEW = REPO / "core/skills/codebase-review/SKILL.md"
SECURITY_AUDIT = REPO / "core/skills/security-audit/SKILL.md"

# The four skills that spawn into a worktree an earlier step created. The rule must keep
# carving these out, or its widened scope contradicts four shipped instructions.
PRE_EXISTING_WORKTREE_SKILLS = ("claim-task", "auto-build", "auto-fix", "auto-judge")


def _rc() -> str:
    return text_of(RC)


def _slice(text: str, start_pat: str, end_pat: str, what: str) -> str:
    """The span between two anchors, so a rule elsewhere cannot satisfy a scoped check.

    **FAILS CLOSED on a missing end anchor.** It used to `return rest` — the whole file
    from the start anchor to EOF — which is the worst possible behaviour for a scoping
    helper: the independent guard lens reworded one end anchor by four words and the
    twin's span became **83% of the file**, at which point every scoped check was
    satisfied by unrelated prose and a real deletion passed. A scope that silently
    widens to everything is not a scope. Both anchors must hold or the guard says so.
    """
    m = re.search(start_pat, text, re.M)
    if m is None:
        raise AssertionError(f"could not locate the start of {what}")
    rest = text[m.start():]
    e = re.search(end_pat, rest[1:], re.M)
    if e is None:
        raise AssertionError(
            f"could not locate the END of {what} — refusing to fall back to "
            "end-of-file, which would silently widen this scope to the whole document "
            "and satisfy every check from unrelated prose"
        )
    return rest[: e.start() + 1]


def _shell(span: str) -> str:
    """Fold backslash line-continuations so a wrapped command reads as one line.

    A guard keyed to a physical line is walked by a continuation, and going red on one
    is the over-strictness that gets a guard deleted rather than fixed. Both directions
    were demonstrated by the round.
    """
    return re.sub(r"\\\n\s*", " ", span)


def _step_2b_spawn(text: str) -> str:
    """Step 2b's convention fleet: the placement step through the end of its prompt."""
    return _slice(
        text,
        r"^\s*\d+\.\s+\*\*Create each reviewer's checkout",
        r"^### 2c\.",
        "Step 2b's spawn step",
    )


def _placement_block(text: str) -> str:
    """Item 3's placement half ONLY — the header through the spawn it precedes.

    Scoped this tightly because a whole-Step-2b span is NOT a valid scope for these
    predicates, and the negative control proved it: the leak assertion further down the
    step says "They live outside the repository by design", which satisfied a prose check
    about the placement bullet from 40 lines away. A guard a sibling paragraph can satisfy
    is not measuring the paragraph it names.
    """
    return _slice(
        text,
        r"^\s*\d+\.\s+\*\*Create each reviewer's checkout",
        r"^\s*Then spawn an Agent with:",
        "the placement block",
    )


def _echo_block(text: str) -> str:
    """The prompt's `## Where you are` section ONLY.

    The author-side battery ran `echo_problems` over the whole of Step 2b and three
    mutations walked through it: the stop arm was satisfied by the CONVENTIONS
    fail-closed sentence ("STOP and report exactly that") 40 lines away, and the pin
    resolution by the echo's own `rev-parse`. Every predicate here is scoped to the
    block that carries the rule.
    """
    return _slice(
        text,
        r"^\s*## Where you are",
        r"^\s*## Target",
        "the prompt's Where-you-are block",
    )


def _twin_spawn_sentence(text: str) -> str:
    """The security twin's spawn SENTENCE, not its explanatory blockquote.

    Same lesson: a check for the word "placement" over the twin's whole paragraph is
    satisfied by the blockquote that explains why placement matters, so deleting the
    clause that actually instructs it left the guard green.
    """
    return _slice(
        text,
        r"Spawn one Agent per surviving target",
        r"The prompt is step 3's",
        "the twin's spawn sentence",
    )


# --------------------------------------------------------------------------------------
# Predicates. Each returns a list of problems; the real file must yield none.
# --------------------------------------------------------------------------------------

PINS_SCRIPT = REPO / "core/companion/scripts/review_pins.py"


def _pins_src() -> str:
    return PINS_SCRIPT.read_text(encoding="utf-8")


def _cmd_add(src: str) -> str:
    return src[src.index("def cmd_add("):src.index("def cmd_clean(")]


def placement_problems(span: str, src: str | None = None) -> list[str]:
    """Does this span actually place its reviewers at the commit under review?

    Since Phase 421 (`Q-665`) the placement is `review_pins.py add "<revision>"`: under
    `dontAsk` the step's `PIN=$(…)`, `mktemp -d`, `case` and `git -C` lines bound no rule. So
    the rule is read in two halves, the call the step prescribes and the code that call runs,
    and both are DATA FLOW, not spellings. The feature-branch arm must resolve `<target
    branch>` -- never `HEAD`, which under `pr` is the default branch this step stands on, so a
    pin taken from it recreates `Q-490` leg (a) silently: the checkout is made there, the echo
    matches, the receipt passes, and every lens reviews the tree the work is not in. The code
    must resolve the revision it was handed to a commit and make a DETACHED checkout of THAT
    commit, at a path git ignores.
    """
    problems: list[str] = []
    sh = _shell(span)
    src = _pins_src() if src is None else src
    # One revision token: a quoted string, or a bare word that may hold a `<placeholder>` with a
    # space in it.
    calls = re.findall(r"^\s*python3\s+sysop/scripts/review_pins\.py\s+add\s+"
                       r"((?:\"[^\"\n]*\")|(?:'[^'\n]*')|(?:[^\s<]*<[^>\n]*>\S*)|\S+)([^\n]*)$", sh, re.M)
    feature = [c for c in calls if re.fullmatch(r"([\"']?)refs/heads/<target branch>\1", c[0])]
    if not feature:
        problems.append(
            "no feature-branch arm places at `refs/heads/<target branch>` -- the pin resolves "
            f"only {[c[0] for c in calls]!r}. Under `pr` policy this step stands on the default "
            "branch, so a pin taken from `HEAD` recreates `Q-490` leg (a) SILENTLY")
    for rev, rest in calls:
        if rev in ("HEAD", '"HEAD"', "'HEAD'") and "unpushed-main" not in rest:
            problems.append("a `HEAD` placement is not confined to the unpushed-main group")
    if re.search(r"mktemp|\$\{?TMPDIR|/tmp/", sh):
        problems.append(
            "the placement makes a checkout in the system temp directory again -- outside the "
            "project, which a reviewer cannot read under `dontAsk`, and which the step's own "
            "removal and leak check (both `review_pins.py`) never see")
    if re.search(r"^\s*git worktree add", sh, re.M):
        problems.append("the step creates a checkout itself instead of through `review_pins.py add`")
    add = _cmd_add(src)
    if "if not ignored(p):" not in add:
        problems.append(
            "`add` no longer refuses a path git does not ignore -- a pin there is an untracked "
            "directory in the very tree the step's baseline delta compares, where it reads as a "
            "phantom mutation and git collapses it to one `??` line, hiding any real agent write")
    if "rev + '^{commit}'" not in add:
        problems.append("`add` no longer resolves the revision it was handed to a commit")
    if "git('worktree', 'add', '-q', '--detach', str(pin), sha)" not in add:
        problems.append(
            "`add` no longer makes a DETACHED checkout at the resolved commit -- a branch "
            "checkout moves under the reviewer, and a checkout at anything else is leg (a)")
    if not re.search(r"^\s*[-*+]\s+\*\*Under the ignored `sysop/runtime/`", span, re.M):
        problems.append(
            "the bullet stating why the checkout lives under the ignored `sysop/runtime/` is "
            "gone, so `add`'s refusal reads as ceremony to the next editor")
    return problems


# Reversals, not additions — so neither the verbatim pin (which sees deletion) nor the
# licence canary (which sees addition) covers them. Each is a sentence whose OPPOSITE is
# a coherent instruction an editor could write in good faith, and each opposite
# reintroduces a defect this project has already paid for.
_REVERSALS = (
    (r"[Oo]ne per agent(?!\w)",
     r"[Oo]ne shared read-only checkout for the whole fleet|"
     r"[Ss]hare (?:one|a single) (?:pinned )?checkout (?:across|for)",
     "a shared pin is the Phase 153 incident verbatim — one lens moves it and its "
     "siblings silently describe the wrong revision, which the echo cannot catch "
     "because every echo runs before any sibling has had time to mutate"),
    (r"Do not modify the pinned checkout",
     r"may (?:reorganise|reorganize|modify|rearrange) the pinned checkout",
     "a reviewer permitted to mutate the pinned tree corrupts its siblings' reads"),
    (r"It must equal <PIN>\.",
     r"must equal <PIN> or",
     "an echo that may equal something other than the pin is not a receipt"),
)


def reversal_problems(text: str) -> list[str]:
    """Scoped to the two blocks that carry these rules, never the whole file.

    The first cut ran over all of `review-close/SKILL.md` and one inverted pattern
    (`share one checkout`) matched an unrelated pre-existing sentence 2,000 lines away —
    the same incidental-substring defect this module keeps finding, committed by the
    guard written to detect it.
    """
    text = _placement_block(text) + "\n" + _echo_block(text)
    problems: list[str] = []
    for required, inverted, why in _REVERSALS:
        if re.search(inverted, text):
            problems.append(f"a rule was REVERSED, not deleted: {inverted!r} — {why}")
        elif not re.search(required, text):
            problems.append(f"the rule {required!r} is gone — {why}")
    return problems


# Bounded canary, not a filter. The same shape (and the same stated limit) as the shared
# rule's retraction blacklist: a regex screen over prose is a reversion detector, and each
# round that extends its vocabulary loses to the next author's synonyms. These are the
# licences the author-side battery actually wrote; the pin cannot see an ADDITION, and this
# can see the additions demonstrated. It does not claim to see the next one.
_PLACEMENT_LICENCES = (
    r"may be skipped",
    r"placement (?:is|may be) (?:optional|advisory|a nicety|skipped)",
    r"for a (?:small|short) (?:close|audit)",
    r"skip the (?:placement|echo|pinned checkout)",
    r"need not be placed",
    # The NEGATION arm. The round rewrote the outside-the-repo bullet to "Inside the
    # repository is fine if you clean up. Nothing about being outside the repository is
    # essential" -- which satisfied a substring check for "outside the repositor" with a
    # sentence asserting its opposite, and carried no licence vocabulary at all.
    r"inside the repositor\w* is (?:fine|ok|acceptable)",
    r"nothing about being outside",
    r"outside the repositor\w*[^.]{0,30}(?:is not|isn't) (?:essential|required|necessary)",
)


def licence_problems(span: str) -> list[str]:
    """A licence added BESIDE an intact rule — which no verbatim pin can see."""
    return [f"a licence was added beside the placement rule: {pat!r}"
            for pat in _PLACEMENT_LICENCES
            if re.search(pat, span, re.I)]


def echo_problems(span: str) -> list[str]:
    """Is the reviewer required to PROVE where it landed, with `-C`, before reviewing?"""
    problems: list[str] = []

    echo = re.search(r'python3 sysop/scripts/git_ro\.py\s+"<[^>]*pinned[^>]*>"\s+rev-parse HEAD', span)
    if echo is None:
        problems.append(
            "no `git_ro.py \"<pinned>\" rev-parse HEAD` echo — a bare rev-parse reports the "
            "reviewer's own CWD and can echo a plausible SHA while reading the wrong tree "
            "(and under `dontAsk` its `git -C` is denied)"
        )
    if not re.search(r"before (?:your|any|its) first finding|BEFORE your first finding",
                     span, re.I):
        problems.append("the echo is not required BEFORE the first finding")
    if not re.search(r"It must equal", span):
        problems.append(
            "the echo is not compared to anything — an echo nobody checks against the "
            "pin is a formality, not a receipt"
        )
    if not re.search(r"STOP and say so", span):
        problems.append(
            "a mismatched echo has no stop arm — a reviewer that silently re-points "
            "itself produces findings about an unknown tree"
        )
    if re.search(r"note it and continue|carry on", span, re.I):
        problems.append("the stop arm was replaced by a continue arm")
    return problems


def retrieval_basis_problems(text: str) -> list[str]:
    """Leg (c): the retrieval command HANDED TO THE AGENT must not resolve `HEAD`.

    In a worktree forked from the default branch, `git diff origin/<default>...HEAD` is
    EMPTY — the agent reviews nothing and reports a clean gate. Two forms sat on one line
    and only one was safe, so which the agent copied decided whether the gate ran.
    """
    problems: list[str] = []
    span = _slice(
        text,
        r"\*\*Above 1,000 lines:\*\*",
        r"^\s*> \*\*Why a threshold",
        "the above-threshold retrieval bullet",
    )
    if "EXPLICIT refs" not in span:
        problems.append("the retrieval bullet does not require explicit refs on both sides")
    # The agent-facing command must be rooted at the pinned checkout (through `git_ro.py`
    # since Phase 421: `git -C` is denied under `dontAsk`).
    if not re.search(r'git_ro\.py\s+"<[^>]*pinned[^>]*>"\s+diff', span):
        problems.append(
            "the agent's retrieval command is not rooted at the pinned checkout, "
            "so it resolves against whatever tree the agent happens to stand in"
        )
    # And it must say, in terms, that `HEAD` is not to be used on either end.
    if not re.search(r"never with `HEAD`", span):
        problems.append("nothing forbids `HEAD` in the agent-facing retrieval command")
    # THE BINDING CHECK, scoped to the PRESCRIPTION clause. The bullet legitimately
    # contains `...HEAD` twice — the orchestrator's own `--stat` forms, which run in the
    # primary worktree where `HEAD` means what they assume, and the broken form quoted as
    # the counterexample. A whole-bullet ban on `...HEAD` reddens the correct text, which
    # is how a guard gets deleted. So the shipped note now ends with a single marked
    # prescription clause, and THAT is what must be clean: every command in it `-C`-rooted
    # and `HEAD`-free, with no second form beside it. Reading only the first `Emit` clause
    # lost three mutations to the round (a fallback paragraph, a form offered before the
    # word `Emit`, and a variable command word).
    marker = "**Emit exactly one of these to the agent, and no other diff command:**"
    if marker not in span:
        problems.append(
            "the bullet no longer carries a single marked prescription clause — without "
            "one, a second diff command can be offered beside the correct one and which "
            "of the two an agent copies decides whether the gate runs at all"
        )
    else:
        prescription = _shell(span[span.index(marker) + len(marker):])
        cmds = [c for c in re.findall(r"`([^`\n]*)`", prescription) if "diff" in c]
        if not cmds:
            problems.append("the prescription clause emits no retrieval command at all")
        for cmd in cmds:
            if not re.match(r'python3 sysop/scripts/git_ro\.py\s+"<', cmd):
                problems.append(
                    f"the prescribed command `{cmd}` is not rooted at the pinned checkout, so "
                    "it resolves against whatever tree the agent happens to stand in"
                )
            if re.search(r"\.\.\.?HEAD\b", cmd):
                problems.append(
                    f"the prescribed command `{cmd}` resolves `HEAD` in the reviewer's "
                    "tree — in a default-branch-forked worktree that diff is EMPTY, so "
                    "the agent reviews nothing and reports a clean convention gate"
                )
    return problems


def scope_problems(partial: str) -> list[str]:
    """Does the shared rule reach skill-driven fleets, and keep the narrow carve-out?"""
    problems: list[str] = []
    # Structural end anchor, not a blank line: splitting one paragraph into two is a
    # legal edit that truncated this span and made the check pass on a reversion.
    span = _slice(partial, r"\*\*Scope", r"^\s*[-*+]\s+\*\*Place it\.\*\*",
                  "the scope sentence")

    # The LEAD, read on its own. A reversion reworded rather than reverted verbatim
    # ("**Scope: ad-hoc review rounds only.**") left the body's list of bound skills
    # untouched, so every other check here passed while the operative sentence said the
    # opposite of the body -- the Phase-210 shape, inside the fix for a pointer defect.
    lead_text = span[:span.find("**", span.find("**Scope") + 2) + 2]
    if re.search(r"(?<!not )(?:only|solely|just) (?:the )?ad[- ]hoc|"
                 r"ad[- ]hoc [a-z ]{0,20}(?:only|alone)\b", lead_text, re.I):
        problems.append(
            "the scope lead is back to ad-hoc-only, which excludes `/review-close` "
            "Step 2b by its own terms — the reason the pointer there bound nothing"
        )
    if re.search(r"\*\*Scope:\*\*\s*this is the ad-hoc round", span):
        problems.append("the scope sentence was reverted verbatim")
    # The BINDING sentence, sliced out and read on its own. A bare `"review-close" in
    # span` check cannot see this deletion: the span's earlier sentence explains that
    # Step 2b *pointed at* this section, so the name survives removal of the clause that
    # actually binds it. The round deleted the binding clause and the predicate stayed
    # green for exactly that reason.
    binds = re.search(r"The rule binds wherever[^.]*\.", span)
    if binds is None:
        problems.append(
            "the scope no longer states WHERE the rule binds — an explanation of the "
            "old defect is not a statement of the new scope"
        )
    else:
        for surface in ("/review-close", "/codebase-review", "/security-audit"):
            if surface not in binds.group(0):
                problems.append(
                    f"the binding sentence no longer names `{surface}`, so the rule "
                    "excludes it by its own terms — which is the exact mechanism that "
                    "made Step 2b's pointer resolve to nothing"
                )
    for skill in PRE_EXISTING_WORKTREE_SKILLS:
        if skill not in span:
            problems.append(f"the carve-out no longer names `/{skill}`")
    return problems


def venv_remedy_problems(partial: str) -> list[str]:
    """`Q-493`: the clone caveat must not offer the absolute-interpreter alternative.

    The failing checks shell out to `tools/scan_public_history.sh`, which resolves its own
    interpreter from the tree it stands in, so an absolute path reaches nothing.
    """
    problems: list[str] = []
    span = _slice(partial, r"Two clone caveats", r"\n(?=\s*[-*+]\s|\n)", "the clone caveat bullet")

    if re.search(r"absolute path to the primary checkout's `\.venv`,\s*or\s*symlink", span):
        problems.append(
            "the false `or` is back — an absolute interpreter does not reach a script "
            "that resolves its own"
        )
    if "symlink" not in span:
        problems.append("the symlink remedy is gone")
    # Keyed to the MECHANISM, not to a script path. The path was named here until the
    # mirror-leak gate caught it: this file ships, and pointing a public reader at a
    # maintainer-side script is the leak that gate exists to stop. The mechanism is what
    # makes the absolute-interpreter alternative false, and it is what a future edit
    # would have to delete to make the alternative look reasonable again.
    if not re.search(r"resolves its own interpreter|resolves its own\b", span):
        problems.append(
            "the reason the absolute path fails (the check re-resolves its own "
            "interpreter from the tree it stands in) is no longer stated, so the "
            "alternative reads as an arbitrary preference rather than a falsehood"
        )
    # `Q-563` (Phase 342): the reds are a clone's. The script resolves the primary checkout's
    # `.venv` through the git common directory, so a linked worktree reads green, and the old
    # universal told every worktree lens to expect ~25 reds it would never see.
    if re.search(r"(?<!not )\b(?:every|all|each)\b[^.]{0,40}\b(?:lens|lenses|reviewers?)\b"
                 r"[^.]{0,20}?\bmeets?\b", span, re.I):
        problems.append("the universal is back -- a linked worktree does not meet the reds")
    if not re.search(r"linked worktree does not meet", span):
        problems.append("the bullet no longer says a linked worktree reads green, so the "
                        "numbers read as true for every placement")
    return problems


def containment_sentence_problems(span: str) -> list[str]:
    """Phase 296: the containment rule and its fallback must stay two sentences.

    Phase 290 dropped the period between them in `codebase-review` and
    `security-audit` identically, in the same commit, leaving
    *"that is what contained both Where it does not, snapshot ..."*. It was one
    character and it survived that phase's own round, because a round reads for
    what a rule MEANS and this changes only where one sentence ends. It was
    caught pre-publication at the Phase 296 cut, so it never reached the mirror.

    Keyed to the JOIN rather than to either sentence: both clauses were present
    and correct the whole time, which is why every existing predicate in this
    module stayed green over it. What a re-fusing edit destroys is the boundary,
    so the boundary is what this reads.
    """
    problems: list[str] = []
    # ONE BOUNDED-GAP read, not two existence checks, and the round is why.
    #
    # The first form was a strict adjacency check. It caught the join but false-reddened
    # on a clarifying sentence inserted between the rule and its fallback, so the author
    # split it into two independent existence reads. That was WORSE THAN THE BUG: read 2
    # (`Where it does not, snapshot`) still matches the BROKEN text, because dropping the
    # period leaves the fallback's own words intact -- so only read 1 could detect the
    # defect, and read 1 was an existence check over a 1,670-char span. Any ordinary
    # sentence ending "contained both. " anywhere in that span satisfied it. Measured: the
    # real Phase 290 defect plus one such decoy returned NO problems, while the adjacency
    # form it replaced caught the same mutation.
    #
    # The gap is bounded to a single sentence (`[^.]` cannot cross a period), which keeps
    # the intervening-sentence case green without letting an unrelated occurrence 1,600
    # characters away stand in for the join.
    if not re.search(r"Where it does not,\s+snapshot", span):
        problems.append(
            "the no-harness fallback is gone — a reader without `isolation` is left "
            "with no instruction at all, which is the case the rule exists for"
        )
    elif not re.search(
        r"contained both\.(?:\s+[^.]{0,300}?\.)?\s+Where it does not,\s+snapshot", span
    ):
        problems.append(
            "the containment rule has run into its own fallback — the sentence no longer "
            "ends, so an agent reads `both Where` as a clause and the fallback loses its "
            "subject. (An unrelated `contained both.` elsewhere in the span does not "
            "satisfy this; the two must be one sentence apart at most.)"
        )
    return problems


# --------------------------------------------------------------------------------------
# The real files must be clean.
# --------------------------------------------------------------------------------------

def test_step_2b_places_its_convention_reviewers() -> None:
    assert placement_problems(_placement_block(_rc())) == []


def test_step_2b_requires_the_echo_through_the_wrapper() -> None:
    assert echo_problems(_echo_block(_rc())) == []


@pytest.mark.parametrize(
    "span_fn",
    [
        pytest.param(lambda: _placement_block(_rc()), id="review-close"),
        pytest.param(lambda: _standing_containment(CODEBASE_REVIEW), id="codebase-review"),
        pytest.param(lambda: _standing_containment(SECURITY_AUDIT), id="security-audit"),
    ],
)
def test_no_licence_sits_beside_the_placement_rule(span_fn) -> None:
    """All THREE skills, not just the one the canary started on.

    The round added "use it (placement may be skipped for a short audit);" beside a fully
    intact rule in each standing review skill and both survived, because the canary ran
    only over `review-close`'s placement block — the two files this phase widened scope to
    reach had no canary at all. A pin cannot see an addition; only this can.
    """
    assert licence_problems(span_fn()) == []


def test_a_licence_added_beside_an_intact_rule_is_caught() -> None:
    """The pin-shaped guards above all pass on this mutation: every required phrase is
    still there. Only a canary can see an ADDITION."""
    licensed = _placement_block(_rc()).replace(
        "**One checkout per agent",
        "**For a small close this may be skipped.** **One checkout per agent", 1)
    assert placement_problems(licensed) == [], (
        "precondition: the licence leaves every required phrase intact"
    )
    assert licence_problems(licensed), "a licence beside the intact rule went unseen"


def test_the_security_twin_places_its_reviewers_too() -> None:
    """Scoped to the spawn SENTENCE. Over the twin's whole paragraph, a check for
    "placement" is satisfied by the blockquote explaining why placement matters, so
    deleting the clause that instructs it left the guard green (author-side battery,
    mutations E1 and E2)."""
    span = _twin_spawn_sentence(_rc())
    assert re.search(r"pinned checkout", span), (
        "the security twin's spawn sentence no longer gives each agent a pinned "
        "checkout — it would review a tree with none of the target's new endpoints, "
        "handlers or dependencies in it, raise no violation, and be carried into step 4 "
        "as a clean security gate"
    )
    assert re.search(r"\becho\b", span), (
        "the twin's spawn sentence does not carry the echo requirement, so a "
        "misplacement there is undetectable from outside the run"
    )


def test_the_agent_facing_retrieval_command_cannot_resolve_HEAD() -> None:
    assert retrieval_basis_problems(_rc()) == []


def test_the_leak_assertion_can_see_a_pinned_checkout() -> None:
    """The pinned checkouts are ignored by git, so only `git worktree list` finds them."""
    span = _slice(_rc(), r"Remove step 3's pinned checkouts FIRST", r"^### 2c\.",
                  "the pinned-checkout removal and leak assertion")
    removal = span.find("python3 sysop/scripts/review_pins.py clean")
    assert removal >= 0, (
        "the removal is gone — the assertion then lists the orchestrator's own pinned "
        "checkouts on every close that spawned and reads as a leak")
    assert removal < span.index("assert all five are clean") < span.index(
        "python3 sysop/scripts/review_pins.py check"), (
        "the assertion runs before anything removes the pinned checkouts, so it lists them "
        "on every close that spawned and reads as a leak — the false-FAIL the same blockquote "
        "names as how a gate gets disabled by its first operator")
    src = _pins_src()
    check = src[src.index("def cmd_check("):src.index("def hooks_path(")]
    assert "pins = [p for p in paths if under(p, PINS)]" in check, (
        "the check no longer enumerates the pinned checkouts; git ignores them, so they never "
        "reach the `.claude/worktrees/` read nor the tree delta")
    assert re.search(r"DIRTY:[^.]*FINDING|FINDING, not an obstacle", span), (
        "a removal that refuses on a dirty pinned checkout means a lens mutated the revision "
        "its siblings were reading — that is a verdict about the round, not a cleanup nuisance "
        "to `--force` past")
    clean = src[src.index("def cmd_clean("):src.index("def cmd_check(")]
    assert "'--force'" not in clean, "`clean` must never force-remove: it deletes the evidence"


def test_the_placement_and_the_leak_check_read_one_location() -> None:
    """The two halves were coupled by a bare temp-dir prefix (Phase 290's battery, D4: rename
    it in the placement alone and the assertion matched nothing and certified clean). Since
    Phase 421 both are one constant in `review_pins.py`, read by `add`, `clean` and `check`."""
    src = _pins_src()
    assert "PINS = RUNTIME / 'pins'" in src
    assert "pin, scratch = PINS / pid, SCRATCH / pid" in _cmd_add(src)
    assert src[src.index("def cmd_clean("):src.index("def cmd_check(")].count("under(path, PINS)") == 1
    assert "under(p, PINS)" in src[src.index("def cmd_check("):src.index("def hooks_path(")]


def test_the_shared_rule_reaches_skill_driven_fleets() -> None:
    assert scope_problems(PARTIAL.read_text(encoding="utf-8")) == []


def test_the_venv_remedy_is_the_symlink_alone() -> None:
    assert venv_remedy_problems(PARTIAL.read_text(encoding="utf-8")) == []


def _standing_containment(skill: Path, text: str | None = None) -> str:
    """The containment paragraph of a standing review skill — ONE paragraph, or a refusal.

    Phase 327 (`Q-592` line 20). The end anchor `^\\*\\*` is "the next line that opens in bold",
    and nothing checked where that landed: widening it to `^#` grew the slice 1,670 → 5,586
    characters (3.3×) with the module green, while the sibling span has
    `test_the_slicer_fails_CLOSED_when_an_end_anchor_moves`. Width was the enabling condition
    for the bypass Phase 296's round found. So the span must be the paragraph it is named for:
    a blank line inside it means the end anchor overshot into the next one.
    """
    if text is None:
        text = skill.read_text(encoding="utf-8")
    span = _slice(text, r"This rule has been measured failing", r"^\*\*", "the containment rule")
    # A line holding only spaces or tabs is a blank line too (CommonMark), so it ends a
    # paragraph; Phase 327's round widened the span through one with the plain `\n\n` test green.
    assert not re.search(r"\n[ \t]*\n", span.rstrip(" \t\n")), (
        f"{skill.name}: the containment span runs past its own paragraph "
        f"({len(span):,} chars) — its end anchor no longer lands on the next paragraph's bold "
        "lead, so every scoped check below is reading neighbouring prose"
    )
    return span


@pytest.mark.parametrize("skill", [CODEBASE_REVIEW, SECURITY_AUDIT],
                         ids=["codebase-review", "security-audit"])
def test_the_standing_review_skills_state_the_placement_requirement(skill: Path) -> None:
    span = _standing_containment(skill)
    # Three separate clauses, because the battery walked a single "default branch"
    # substring check twice: deleting the instruction left the EXPLANATION's copy of the
    # phrase behind, and deleting the explanation left the instruction's copy behind.
    # `each|every`: the round reddened this on a one-word synonym swap.
    assert re.search(r"place (?:each|every) agent", span), (
        "the skill grants `isolation` without instructing placement — run from any "
        "non-default branch, every agent audits the default branch and reports over "
        "files that do not contain the work"
    )
    assert re.search(r"forks from the repository's \*\*default branch\*\*", span), (
        "the reason placement is needed is gone, so the instruction reads as ceremony "
        "and the next editor drops it"
    )
    # Order-agnostic. `review-close` itself ships `git worktree add --detach <dir> <sha>`
    # and these two skills ship `git worktree add <dir> --detach <sha>`; both are valid
    # git, and a guard demanding one spelling goes red on a writer using the other -- the
    # round demonstrated exactly that, using this repo's own house spelling.
    # `\s+` between every word, not a literal space: a re-wrap may break the line inside the
    # code span (`git worktree` / `add <dir>`), and CommonMark renders that as one space
    # (Phase 333's round, LOW-10 -- the literal form false-killed it).
    assert re.search(r"git\s+worktree\s+add\s+(?:--detach\s+<[^>]+>|<[^>]+>\s+--detach)", span), (
        "no mechanics — an instruction to 'place each agent' with no command behind it "
        "is the pointer-not-an-invoker shape this whole phase is about"
    )
    assert re.search(r"git\s+-C\s+<[^>]*>\s+rev-parse\s+HEAD", span), (
        "no echo requirement, so a misplacement is undetectable from outside the run"
    )


@pytest.mark.parametrize("skill", [CODEBASE_REVIEW, SECURITY_AUDIT],
                         ids=["codebase-review", "security-audit"])
def test_the_containment_span_refuses_to_run_into_the_next_paragraph(skill: Path) -> None:
    """The end-anchor control `_standing_containment` lacked. Un-bolding the next paragraph's
    lead moves the `^\\*\\*` end past it; the slicer must refuse rather than widen."""
    text = skill.read_text(encoding="utf-8")
    span = _standing_containment(skill, text)
    after = text[text.index(span) + len(span):]
    assert after.startswith("**"), "precondition: the span ends on the next paragraph's bold lead"
    unbolded = text.replace(span + "**", span + "Lead: ", 1)
    with pytest.raises(AssertionError, match="runs past its own paragraph"):
        _standing_containment(skill, unbolded)
    # The round's shape: a new paragraph joined by a whitespace-only line, not an empty one.
    for blank in (" ", "\t", "   ", " \t "):
        spaced = text.replace(span, span.rstrip("\n") + f"\n{blank}\nA reviewer may echo it.\n\n", 1)
        with pytest.raises(AssertionError, match="runs past its own paragraph"):
            _standing_containment(skill, spaced)


@pytest.mark.parametrize("skill", [CODEBASE_REVIEW, SECURITY_AUDIT],
                         ids=["codebase-review", "security-audit"])
def test_the_containment_rule_does_not_run_into_its_fallback(skill: Path) -> None:
    assert containment_sentence_problems(_standing_containment(skill)) == []


def _mutate(skill: Path, old: str, new: str) -> str:
    """Mutate the span and REFUSE to return a no-op.

    Every control below is a `str.replace` against the live file. When the real file
    already carries the defect, the anchor string is absent, `replace` silently does
    nothing, and the control then asserts the predicate against the UNMUTATED broken
    span — which it satisfies, for the wrong reason. The controls certify green over
    their own subject's failure. The round found exactly that; this refusal is what
    makes a control's subject a precondition rather than an assumption.
    """
    span = _standing_containment(skill)
    out = span.replace(old, new)
    assert out != span, (
        f"mutation did not apply to {skill.name} — the anchor {old!r} is absent, so this "
        "control was about to assert nothing. Check whether the real file already carries "
        "the defect."
    )
    return out


_JOIN = "contained both. Where it does not"


@pytest.mark.parametrize("skill", [CODEBASE_REVIEW, SECURITY_AUDIT],
                         ids=["codebase-review", "security-audit"])
@pytest.mark.parametrize(
    "replacement, why",
    [
        ("contained both Where it does not", "the exact Phase 290 edit"),
        ("contained both, Where it does not", "a comma in place of the period"),
        ("contained both.", "the fallback clause deleted outright"),
        ("contained both. Otherwise, snapshot", "the fallback reworded away"),
        ("contained both. One. Two. Where it does not", "a gap wider than one sentence"),
    ],
)
def test_a_refused_containment_sentence_boundary_is_caught(
    skill: Path, replacement: str, why: str
) -> None:
    assert containment_sentence_problems(_mutate(skill, _JOIN, replacement)), (
        f"{why} went through the predicate unnoticed in {skill.name}"
    )


@pytest.mark.parametrize("skill", [CODEBASE_REVIEW, SECURITY_AUDIT],
                         ids=["codebase-review", "security-audit"])
def test_an_unrelated_occurrence_cannot_stand_in_for_the_join(skill: Path) -> None:
    """The bypass that disqualified this guard's second form, kept as a control.

    Two independent existence reads let any ordinary sentence ending `contained both. `
    elsewhere in the span satisfy the join check, because the fallback's own words
    survive the period being dropped. Measured green over the real defect before the
    bounded-gap form replaced it.
    """
    broken = _mutate(skill, _JOIN, "contained both Where it does not")
    decoy = broken.replace("which is the dominant breach shape.",
                           "which is the dominant breach shape. Isolation is what contained both. ")
    assert decoy != broken, "the decoy did not apply; this control needs re-pointing"
    assert containment_sentence_problems(decoy), (
        "an unrelated `contained both.` satisfied the join check — the two-existence-read "
        "form is back, and it is green over the defect this guard exists to catch"
    )


@pytest.mark.parametrize("skill", [CODEBASE_REVIEW, SECURITY_AUDIT],
                         ids=["codebase-review", "security-audit"])
@pytest.mark.parametrize(
    "replacement, why",
    [
        ("contained both. Note the shape. Where it does not", "one intervening sentence"),
        ("contained both.\nWhere it does not", "a newline between the two sentences"),
        ("contained both.  Where it does not", "two spaces after the period"),
    ],
)
def test_a_legal_edit_does_NOT_redden(skill: Path, replacement: str, why: str) -> None:
    """The over-strictness direction. A strict adjacency check false-reddens all three."""
    assert containment_sentence_problems(_mutate(skill, _JOIN, replacement)) == [], (
        f"{why} reddened the guard in {skill.name} — an adjacency check is back"
    )


def test_the_two_standing_skills_carry_the_containment_rule_identically() -> None:
    """Phase 290 broke both copies in one commit; nothing asserted they agree.

    The divergence is what let a defect in one file hide behind a control that only
    ever mutated the other.
    """
    # Trailing whitespace is dropped before comparing: the slice runs to the next paragraph's
    # bold lead, so it carries the blank line(s) between, and a whitespace-only line there is
    # still a blank line to CommonMark (Phase 333's round, P10C -- it false-killed this).
    a = _standing_containment(CODEBASE_REVIEW).rstrip()
    b = _standing_containment(SECURITY_AUDIT).rstrip()
    assert a == b, (
        "the containment paragraph has diverged between codebase-review and "
        "security-audit — a fix applied to one and not the other now reads as covered"
    )


def test_the_rollback_header_comment_does_not_prescribe_a_move() -> None:
    """`Q-492`: the stale clause an editor meets FIRST pointed at the destination
    `Q-482`'s round killed — `git worktree remove` deletes gitignored content at exit 0."""
    # The header comment is the rollback's, in `pending_doc_collect.py` since Phase 386:
    # an absence read against the skill alone would pass on the stale clause.
    text = _rc() + (Path(__file__).resolve().parents[1]
                    / "core/companion/scripts/pending_doc_collect.py").read_text(encoding="utf-8")
    assert "otherwise MOVE main's copy back to the worktree" not in text, (
        "the section's own header comment prescribes a move the code does not do, and "
        "acting on it rebuilds a silent data-loss route"
    )
    assert "LEAVE main's copy exactly where it is" in text


# --------------------------------------------------------------------------------------
# Negative controls — the softenings a future edit would plausibly make.
# Each must be CAUGHT. A predicate that passes these is not a guard.
# --------------------------------------------------------------------------------------

_FEATURE_ARM = 'python3 sysop/scripts/review_pins.py add "refs/heads/<target branch>"'


@pytest.mark.parametrize(
    "mutate, expect",
    [
        pytest.param(lambda s: s.replace(_FEATURE_ARM, 'python3 sysop/scripts/review_pins.py add HEAD'),
                     "the feature-branch arm", id="feature-arm-collapsed-onto-HEAD"),
        pytest.param(lambda s: re.sub(r"[^\n]*" + re.escape(_FEATURE_ARM) + r"[^\n]*\n", "", s),
                     "the feature-branch arm", id="feature-arm-deleted"),
        pytest.param(lambda s: s.replace(_FEATURE_ARM, 'PINNED=$(mktemp -d "${TMPDIR:-/tmp}/sysop-2b-XXXXXX")\n   ' + _FEATURE_ARM),
                     "the temp-directory ban", id="checkout-back-in-the-temp-dir"),
        pytest.param(lambda s: s.replace(_FEATURE_ARM, 'git worktree add --detach sysop/runtime/p "refs/heads/<target branch>"'),
                     "the script placement", id="checkout-made-by-hand"),
        pytest.param(lambda s: re.sub(r"\*\*Under the ignored `sysop/runtime/`[^*]*\*\*", "**Wherever is convenient.**", s),
                     "the reason bullet", id="reason-bullet-dropped"),
    ],
)
def test_a_weakened_placement_is_caught(mutate, expect: str) -> None:
    span = mutate(_placement_block(_rc()))
    assert span != _placement_block(_rc()), "the control mutated nothing"
    problems = placement_problems(span)
    assert problems, f"a mutation removing {expect!r} passed the placement predicate"


@pytest.mark.parametrize(
    "old, new, expect",
    [
        ("        if not ignored(p):\n", "        if False:\n", "the ignored-path refusal"),
        ("git('worktree', 'add', '-q', '--detach', str(pin), sha)", "git('worktree', 'add', '-q', str(pin), sha)", "--detach"),
        ("git('worktree', 'add', '-q', '--detach', str(pin), sha)", "git('worktree', 'add', '-q', '--detach', str(pin), 'HEAD')", "the resolved commit"),
        ("r = git('rev-parse', '--verify', '-q', rev + '^{commit}', check=False)", "r = git('rev-parse', '--verify', '-q', 'HEAD', check=False)", "the revision handed to it"),
    ],
    ids=["add-skips-the-ignore-check", "add-loses-detach", "add-pins-HEAD", "add-ignores-its-revision"],
)
def test_a_weakened_add_is_caught(old: str, new: str, expect: str) -> None:
    src = _pins_src()
    assert src.count(old) == 1, f"stale control anchor: {old!r}"
    assert placement_problems(_placement_block(_rc()), src.replace(old, new)), (
        f"`review_pins.py add` lost {expect} and the placement predicate passed")


@pytest.mark.parametrize(
    "mutate, why",
    [
        pytest.param(
            lambda s: s.replace('python3 sysop/scripts/git_ro.py "<absolute path to the pinned checkout>" rev-parse HEAD',
                                "git rev-parse HEAD"),
            "a bare rev-parse reports the agent's own CWD",
            id="echo-loses-the-wrapper",
        ),
        pytest.param(
            lambda s: s.replace("Report that output verbatim as your first line.", "")
                       .replace("echo this BEFORE your first finding", "echo this")
                       .replace("before any finding", "at some point"),
            "an echo after the findings cannot gate them",
            id="echo-stops-being-first",
        ),
        pytest.param(
            lambda s: s.replace("If it does not, STOP and say so", "If it does not, carry on")
                       .replace("STOP", "note it").replace("stop", "note it"),
            "a mismatch with no stop arm is a silent wrong-tree review",
            id="echo-mismatch-has-no-stop-arm",
        ),
    ],
)
def test_a_weakened_echo_is_caught(mutate, why: str) -> None:
    span = mutate(_echo_block(_rc()))
    assert echo_problems(span), f"mutation passed the echo predicate — {why}"


@pytest.mark.parametrize(
    "mutate, why",
    [
        pytest.param(
            lambda s: s.replace("**Scope: every spawn that CREATES a checkout, not only the "
                                "ad-hoc round.**", "**Scope:** this is the ad-hoc round."),
            "ad-hoc-only scope excludes Step 2b by its own terms",
            id="scope-reverts-to-ad-hoc-only",
        ),
        pytest.param(
            lambda s: s.replace("`/auto-judge`", "the autonomous skills"),
            "an unnamed carve-out contradicts a shipped instruction",
            id="carve-out-loses-a-skill",
        ),
    ],
)
def test_a_narrowed_scope_is_caught(mutate, why: str) -> None:
    assert scope_problems(mutate(PARTIAL.read_text(encoding="utf-8"))), (
        f"mutation passed the scope predicate — {why}"
    )


def test_the_false_venv_alternative_coming_back_is_caught() -> None:
    text = PARTIAL.read_text(encoding="utf-8")
    anchor = ("**Wherever a check's resolution does not reach the primary checkout — a clone always, "
              "and a linked worktree for a check that reads only its own tree — symlink the "
              "primary checkout's `.venv` into the reviewer's checkout.**")
    assert anchor in text, "control anchor is stale -- this control would prove nothing"
    restored = text.replace(
        anchor,
        "Tell the reviewer the interpreter to use (an absolute path to the primary "
        "checkout's `.venv`, or symlink it in).",
    )
    assert venv_remedy_problems(restored), (
        "the `or` came back and the predicate did not notice — an absolute interpreter "
        "does not reach `scan_public_history.sh`, which resolves its own"
    )


def test_the_venv_numbers_going_universal_again_is_caught() -> None:
    """`Q-563`: the reds are a clone's, and a linked worktree reads green."""
    text = PARTIAL.read_text(encoding="utf-8")
    scope = "**A linked worktree does not meet them:**"
    assert scope in text, "control anchor is stale -- this control would prove nothing"
    assert venv_remedy_problems(text.replace(scope, "**Every placement meets them:**"))
    universal = "Tell the lens which placement it has"
    assert universal in text, "control anchor is stale -- this control would prove nothing"
    assert venv_remedy_problems(text.replace(
        universal, "From Phase 288 onward every correctly-placed lens meets those reds. " + universal))


def test_a_HEAD_based_retrieval_command_is_caught() -> None:
    prescribed = ('`python3 sysop/scripts/git_ro.py "<absolute path to the pinned checkout>" diff '
                  '<default branch>...refs/heads/<branch>`')
    assert prescribed in _rc(), "control anchor is stale -- this control would prove nothing"
    mutated = _rc().replace(prescribed, "`git diff origin/<default branch>...HEAD`").replace(
        "**Write the retrieval command with EXPLICIT refs on both sides, run through "
        "`git_ro.py` at the pinned checkout, and never with `HEAD` on either end.**",
        "Write the retrieval command.")
    assert retrieval_basis_problems(mutated), (
        "the empty-diff form came back and the predicate did not notice — that is the "
        "defect verbatim: the agent reviews nothing and reports a clean gate"
    )


# --------------------------------------------------------------------------------------
# Controls for the round's own findings — each of these MUST hold, and each is here
# because the independent guard lens walked the first version of the predicate above.
# --------------------------------------------------------------------------------------

def test_a_placement_that_ignores_its_own_pin_is_caught() -> None:
    """The round's sharpest finding: `Q-490` leg (a) restored verbatim, guards green. A checkout
    made at something other than the commit the revision resolves to -- now inside `add`."""
    src = _pins_src()
    for operand, why in (("'HEAD'", "the literal default-branch HEAD"), ("rev", "the unresolved name")):
        mutated = src.replace("str(pin), sha)", f"str(pin), {operand})")
        assert mutated != src
        assert placement_problems(_placement_block(_rc()), mutated), (
            f"the add forked at {why} and the predicate passed — that is Q-490 leg (a) "
            "restored verbatim with every test green")


@pytest.mark.parametrize("quoted", ["'refs/heads/<target branch>'", "refs/heads/<target branch>"])
def test_a_requoted_revision_does_NOT_redden(quoted: str) -> None:
    """Over-strictness is the direction that hides (Phase 168: 19 of 30 innocent edits)."""
    requoted = _placement_block(_rc()).replace('"refs/heads/<target branch>"', quoted, 1)
    assert placement_problems(requoted) == []


def test_a_backslash_continuation_does_NOT_redden() -> None:
    wrapped = _placement_block(_rc()).replace(
        _FEATURE_ARM, 'python3 sysop/scripts/review_pins.py \\\n       add "refs/heads/<target branch>"')
    assert placement_problems(wrapped) == [], (
        "a line continuation is how people write; going red on one is over-strictness"
    )


def test_the_slicer_fails_CLOSED_when_an_end_anchor_moves() -> None:
    """It used to return everything to EOF. The round reworded one end anchor by four
    words and a scoped span became 83% of the file, at which point every check was
    satisfied by unrelated prose and a real deletion passed."""
    moved = _rc().replace("The prompt is step 3's", "The prompt is the one from step 3")
    with pytest.raises(AssertionError, match="could not locate the END"):
        _twin_spawn_sentence(moved)


def test_a_second_retrieval_form_offered_beside_the_correct_one_is_caught() -> None:
    """Three of the round's mutations walked the first predicate this way: a fallback
    paragraph, a form named before the word `Emit`, and a variable command word."""
    span = _slice(_rc(), r"\*\*Above 1,000 lines:\*\*", r"^\s*> \*\*Why a threshold",
                  "the above-threshold retrieval bullet")
    marker = "**Emit exactly one of these to the agent, and no other diff command:**"
    for extra, why in (
        ("`git diff origin/<default branch>...HEAD`", "a HEAD-resolving fallback"),
        ("`$GIT_PINNED diff <default branch>...<branch>`", "a variable command word"),
    ):
        mutated = _rc().replace(
            marker, marker + f" Where the pinned checkout is unavailable, emit {extra} instead.")
        assert retrieval_basis_problems(mutated), (
            f"{why} was offered beside the correct form and went unseen"
        )


def test_no_rule_in_the_placement_block_has_been_reversed() -> None:
    assert reversal_problems(_rc()) == []


@pytest.mark.parametrize(
    "required, inverted",
    [(r, i) for r, i, _ in _REVERSALS],
    ids=["shared-checkout", "may-mutate-the-pin", "echo-may-differ"],
)
def test_each_reversal_is_caught(required: str, inverted: str) -> None:
    """Reversals are invisible to both other mechanisms: a verbatim pin sees a deletion
    and a licence canary sees an addition, and a reversal is neither. All three of these
    survived the independent execution lens's battery."""
    sample = {
        "[Oo]ne per agent(?!w)":
            "One shared read-only checkout for the whole fleet",
        "Do not modify the pinned checkout":
            "You may reorganise the pinned checkout as needed",
        "It must equal <PIN>.":
            "It must equal <PIN> or your own HEAD.",
    }[required.replace("\\", "")]
    mutated = re.sub(required, sample, _rc(), count=1)
    assert reversal_problems(mutated), f"reversing {required!r} went unseen"


def test_a_pin_collapsed_onto_HEAD_is_caught() -> None:
    """The execution lens's sharpest finding, and the one that fails SILENTLY: the checkout is
    created at whatever the revision names, so the echo matches and the receipt passes while
    every lens reviews the default branch."""
    block = _placement_block(_rc())
    collapsed = re.sub(r"[^\n]*" + re.escape(_FEATURE_ARM) + r"[^\n]*\n", "", block)
    assert collapsed != block, "the feature-branch arm's spelling moved; re-anchor this mutation"
    assert placement_problems(collapsed), (
        "the feature-branch arm was dropped and only the `HEAD` arm remained — that is "
        "Q-490 leg (a) restored, silently, with every guard green"
    )


# === Q-549 half 2: the temp root worktree isolation does not reach ===========

def test_concurrent_reviewers_are_told_to_take_a_private_tmpdir() -> None:
    """Parallel lenses share one pytest temp root, and its cleanup is count-keyed.

    Established from pytest's own source rather than from a flaky race: the
    factory builds `<tmp>/pytest-of-<user>` and calls
    `make_numbered_dir_with_cleanup(root=..., keep=<retention>)` — one root for
    every concurrent run, pruned by COUNT, with no notion of which run owns a
    directory. Phase 312 ran three lenses at once and its claims lens reported
    failures it could reproduce only under that contention.

    THIS IS A PROSE GUARD AND ITS LIMITS ARE THE USUAL ONES. It asserts the
    instruction is present and keyed on the mechanism, not that any spawner
    obeys it — this repo has measured prose screens at 70-90% bypassable. It is
    here so the rule cannot be deleted silently, not because it enforces.
    """
    body = PARTIAL.read_text(encoding="utf-8")
    # ANCHORED ON THE RULE, NOT THE WORD. The first draft asserted `"TMPDIR" in
    # body`, which was ALREADY TRUE before this phase — the token appears
    # elsewhere in the file — so that line scored nothing. The round caught it.
    # PIN THE IMPERATIVE, NOT THE NOUN PHRASE. The author's own second battery
    # rewrote the bullet as "Consider whether a reviewer might want its own
    # `TMPDIR`" — mandate to suggestion — and the previous assertion passed,
    # because "own `TMPDIR`" survives the softening intact. Phase 179 measured a
    # prose blocklist catching 0 of 21 reversals it had not been taught; this is
    # that class, found here by mutating rather than by reading.
    # A REAL LIST ITEM, IN THE RIGHT SECTION, STATED AS AN ORDER. The round got
    # four rewordings past the earlier anchors: an INVERSION keeping every
    # keyword ("Do NOT bother giving each reviewer its own `TMPDIR`"), a
    # softened close ("You may export one if you like"), the bullet MOVED out of
    # § Running more than one reviewer to the end of the file, and the bullet
    # deleted with its keywords parked in an HTML comment. Substring presence
    # cannot see any of those, so the three checks below are position, form and
    # the closing order — not vocabulary.
    bullet_lines = [
        ln for ln in body.splitlines()
        if ln.startswith("- **Give each concurrent reviewer its own `TMPDIR`.**")
    ]
    assert len(bullet_lines) == 1, (
        "the TMPDIR rule is not a single real list item stating an order — it "
        "has been deleted, duplicated, softened, inverted, or parked somewhere "
        "that is not a bullet (an HTML comment satisfies a substring check)"
    )
    assert "Export a private `TMPDIR` per reviewer when you spawn more than one." in bullet_lines[0], (
        "the bullet no longer CLOSES with the instruction; a rule whose last "
        "clause is 'you may if you like' binds nobody"
    )
    section = body.split("### Before you spawn anyone", 1)[0]
    assert bullet_lines[0] in section, (
        "the TMPDIR bullet has been moved out of the multi-reviewer section — "
        "it is only reachable where a spawner is deciding how many to spawn"
    )
    assert "**Give each concurrent reviewer its own `TMPDIR`.**" in body, (
        "the TMPDIR rule is no longer stated as an imperative — a reworded "
        "'consider whether you might want one' satisfies every looser anchor "
        "while binding nobody"
    )
    assert "own `TMPDIR`" in body, (
        "the round procedure no longer tells a spawner to give each reviewer its "
        "own temp root; concurrent lenses will corrupt each other's fixtures and "
        "report it as findings"
    )
    assert "pytest-of-" in body, (
        "the TMPDIR rule no longer names the shared root that makes it "
        "necessary, so an editor cannot tell it from a style preference"
    )
    assert "by count, not by owner" in body, (
        "the reason the shared root is unsafe — cleanup keyed on count rather "
        "than ownership — is gone, which is the half that makes the rule "
        "checkable rather than arbitrary"
    )
