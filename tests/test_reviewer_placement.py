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

REPO = Path(__file__).resolve().parent.parent
RC = REPO / "core/skills/review-close/SKILL.md"
PARTIAL = REPO / "core/skills/_shared/adversarial-review.md"
CODEBASE_REVIEW = REPO / "core/skills/codebase-review/SKILL.md"
SECURITY_AUDIT = REPO / "core/skills/security-audit/SKILL.md"

# The four skills that spawn into a worktree an earlier step created. The rule must keep
# carving these out, or its widened scope contradicts four shipped instructions.
PRE_EXISTING_WORKTREE_SKILLS = ("claim-task", "auto-build", "auto-fix", "auto-judge")


def _rc() -> str:
    return RC.read_text(encoding="utf-8")


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


def _step_3c_spawn(text: str) -> str:
    """Step 2b's security twin — the second fleet, spawned from the same step."""
    return _slice(
        text,
        r"Spawn one Agent per surviving target",
        r"^\s*4\.\s+\*\*Collect all verdicts",
        "the security twin's spawn paragraph",
    )


# --------------------------------------------------------------------------------------
# Predicates. Each returns a list of problems; the real file must yield none.
# --------------------------------------------------------------------------------------

def placement_problems(span: str) -> list[str]:
    """Does this span actually place its reviewers at the commit under review?

    Keyed to DATA FLOW, not to spellings. The round's battery walked the first cut three
    times over by satisfying each check from a different sentence: `PIN=$(git rev-parse`
    existed, `git worktree add --detach` existed, and nothing tied them together — so
    `git worktree add --detach "$PINNED" HEAD` passed, which is leg (a) restored verbatim
    with every test green. The predicate now reads the variable the pin is resolved into
    and requires the `add` to use THAT variable, which also stops it going red on a
    consistent rename (`PIN` -> `COMMIT`) — a legal edit the first cut reddened.
    """
    problems: list[str] = []
    sh = _shell(span)

    pin = re.search(r"(\w+)=\"?\$\(\s*git rev-parse\b", sh)
    if pin is None:
        problems.append(
            "the pin is not resolved to a commit — no `<VAR>=$(git rev-parse ...)`, so "
            "the placement forks at a moving ref and the echo has no fixed value to equal"
        )
    else:
        # WHAT it resolves, not just that it resolves something. The execution lens
        # walked the shape check four ways, and the silent ones all resolve a ref that
        # IS the default branch: `HEAD` (under `pr` this step stands on the default
        # branch), `origin/<default branch>`, `<default branch>`. The checkout is then
        # created at whatever PIN holds, so the agent's echo MATCHES and the receipt
        # passes while every lens reviews the pre-merge tree. `PIN=$(git rev-parse HEAD)`
        # is the likeliest of all, because the shipped block names it for the
        # unpushed-main arm and collapsing the two reads as a tidy-up.
        name = pin.group(1)
        arms = re.findall(re.escape(name) + r"=\"?\$\(\s*git rev-parse\s+([^)]*)\)", sh)
        if not any("<target branch>" in a for a in arms):
            problems.append(
                "no feature-branch arm resolves `<target branch>` — the pin resolves "
                f"only {arms!r}. Under `pr` policy this step stands on the default "
                "branch, so a pin taken from `HEAD` (or from the default branch by "
                "name) recreates `Q-490` leg (a) SILENTLY: the checkout is made at that "
                "commit, the echo matches it, the receipt passes, and every lens "
                "reviews the tree the work is not in"
            )
    dirv = re.search(r"(\w+)=\"?\$\(\s*mktemp -d\b", sh)
    if dirv is None:
        problems.append(
            "the placement command does not create a temp directory — a relative path "
            "leaves an untracked directory inside the very tree the step's own "
            "`git status --porcelain -uall` delta is about to be compared against"
        )

    add = re.search(r"git worktree add[^\n]*", sh)
    if add is None:
        problems.append(
            "no `git worktree add` — the span spawns without creating a checkout at the "
            "commit under review"
        )
    else:
        cmd = add.group(0)
        if "--detach" not in cmd:
            problems.append(
                "`git worktree add` is not `--detach` — it would create or check out a "
                "BRANCH, which moves under the reviewer and collides with any other "
                "worktree already on it"
            )
        for var, role, why in (
            (pin, "pin", "the checkout is created at something other than the resolved "
                         "commit, which is leg (a) of `Q-490` restored verbatim: every "
                         "reviewer lands on the default branch, finds nothing, and "
                         "returns APPROVED"),
            (dirv, "directory", "the checkout is not created at the temp directory the "
                                "step made, so it may land inside the repository"),
        ):
            if var is None:
                continue
            name = var.group(1)
            if not re.search(r"\$\{?" + re.escape(name) + r"\}?\b", cmd):
                problems.append(
                    f"`git worktree add` does not use the resolved {role} "
                    f"(`${name}`) — {why}"
                )

    # STRUCTURAL, not prose. The prose check was satisfied from six lines away by the
    # bullet's own lead-in, so deleting the bullet that states the reason passed. And the
    # prose was never the guarantee anyway: `mktemp` delegates "outside the repository" to
    # $TMPDIR, and a project-local `TMPDIR=$PWD/.tmp` — legal, and used by several CI
    # images and nix shells — lands the pin inside the tree.
    if not re.search(r"git rev-parse --show-toplevel", sh):
        problems.append(
            "nothing verifies the checkout is outside the repository — `mktemp` only "
            "delegates that to $TMPDIR, and a project-local $TMPDIR puts the pin inside "
            "the tree, where it reads as a phantom mutation in the step's own delta and "
            "where git collapses the whole nested worktree to one `??` line, hiding any "
            "real agent write in it"
        )
    # Keyed to the BULLET, not to the phrase anywhere in the block: the block's own
    # lead-in six lines up says "outside the repository" too, so a loose check passed
    # when the bullet stating the REASON was deleted. The structural check above is the
    # guarantee; this one keeps the reason next to it, which is what stops the next
    # editor removing the guarantee as ceremony.
    # `Q-495`: `[-*+]`, not `-`. The subject is the BULLET stating the reason; which of
    # CommonMark's interchangeable unordered markers carries it is presentational, and
    # pinning one made a uniform reformat redden four guards in this module alone.
    if not re.search(r"^\s*[-*+]\s+\*\*Outside the repository", span, re.M):
        problems.append(
            "the bullet stating why the checkout lives outside the repository is gone, "
            "so the containment check above reads as ceremony to the next editor"
        )
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

    echo = re.search(r"git -C\s+\S[^\n]*rev-parse HEAD", span)
    if echo is None:
        problems.append(
            "no `git -C <path> rev-parse HEAD` echo — without `-C` a reviewer reports "
            "its own CWD and can echo a plausible SHA while reading the wrong tree"
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
    # The agent-facing command must be `-C`-rooted at the pinned checkout.
    if not re.search(r"git -C\s+<[^>]*pinned[^>]*>\s+diff", span):
        problems.append(
            "the agent's retrieval command is not `-C`-rooted at the pinned checkout, "
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
            if not re.search(r"git -C\s", cmd):
                problems.append(
                    f"the prescribed command `{cmd}` is not `-C`-rooted, so it resolves "
                    "against whatever tree the agent happens to stand in"
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


def test_step_2b_requires_the_echo_with_dash_C() -> None:
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
    """The pinned checkouts live outside the repo, so no other command can find them."""
    # Slice from the REMOVAL block, which now precedes the assertion. The execution lens
    # found the assertion running before anything deleted the pinned checkouts, so it
    # reported a leak on every close that spawned — a false-FAIL on the dominant path.
    span = _slice(_rc(), r"Remove step 3's pinned checkouts FIRST", r"^### 2c\.",
                  "the pinned-checkout removal and leak assertion")
    # The LOOP, not the words. Keyed to `git worktree remove` alone this passed with the
    # loop deleted, because the paragraph explaining a refused removal names the command
    # too and sits before the assertion.
    loop = re.search(r"while read -r entry; do git worktree remove", span)
    assert loop, (
        "the removal loop is gone — the assertion then lists the orchestrator's own "
        "pinned checkouts on every close that spawned and reads as a leak"
    )
    assert loop.start() < span.index("assert all five are clean"), (
        "the assertion runs before anything removes the pinned checkouts, so it lists "
        "them on every close that spawned and reads as a leak — the false-FAIL the same "
        "blockquote names as how a gate gets disabled by its first operator"
    )
    assert "/sysop-2b-" in span, (
        "nothing enumerates the pinned checkouts; they are outside the repository, so "
        "they never reach the `.claude/worktrees/` grep nor the `git status` delta"
    )
    assert re.search(r"dirty[^.]*FINDING|FINDING, not an obstacle", span), (
        "a `remove` that refuses on a dirty pinned checkout means a lens mutated the "
        "revision its siblings were reading — that is a verdict about the round, not "
        "a cleanup nuisance to `--force` past"
    )


def test_the_placement_prefix_and_the_leak_grep_are_one_string() -> None:
    """The two halves are coupled by a bare string, so nothing but this notices a rename.

    The placement creates `${TMPDIR}/<prefix>XXXXXX` and the leak assertion finds it with
    `grep -F '/<prefix>'`. Rename the prefix in the placement alone and the assertion
    matches nothing, prints `no pinned checkouts`, and certifies clean over every leaked
    reviewer tree — a check reporting green because its subject moved, which is this
    phase's own defect wearing a different hat. Found by the author-side battery (D4), the
    one mutation of twenty-nine that walked through every other guard.
    """
    text = _rc()
    made = re.search(r'mktemp -d "\$\{TMPDIR:-/tmp\}/([A-Za-z0-9_-]+?)X{3,}"',
                     _placement_block(text))
    assert made, "the placement no longer creates a templated temp directory"
    prefix = made.group(1)

    assertion = _slice(text, r"assert all five are clean", r"^### 2c\.", "the leak assertion")
    found = re.search(r"git worktree list --porcelain \| grep -F '/([A-Za-z0-9_-]+?)-?'", assertion)
    assert found, "the leak assertion no longer greps for a pinned-checkout prefix"

    assert found.group(1).rstrip('-') == prefix.rstrip('-'), (
        f"the placement creates {prefix!r} but the leak assertion greps "
        f"{found.group(1)!r} — the assertion will match nothing, print "
        "'no pinned checkouts', and certify clean over every leaked reviewer tree"
    )


def test_the_shared_rule_reaches_skill_driven_fleets() -> None:
    assert scope_problems(PARTIAL.read_text(encoding="utf-8")) == []


def test_the_venv_remedy_is_the_symlink_alone() -> None:
    assert venv_remedy_problems(PARTIAL.read_text(encoding="utf-8")) == []


def _standing_containment(skill: Path) -> str:
    """The containment paragraph of a standing review skill."""
    return _slice(skill.read_text(encoding="utf-8"),
                  r"This rule has been measured failing", r"^\*\*",
                  "the containment rule")


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
    assert re.search(r"git worktree add\s+(?:--detach\s+<[^>]+>|<[^>]+>\s+--detach)", span), (
        "no mechanics — an instruction to 'place each agent' with no command behind it "
        "is the pointer-not-an-invoker shape this whole phase is about"
    )
    assert re.search(r"git -C\s+<[^>]*>\s+rev-parse HEAD", span), (
        "no echo requirement, so a misplacement is undetectable from outside the run"
    )


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
    a = _standing_containment(CODEBASE_REVIEW)
    b = _standing_containment(SECURITY_AUDIT)
    assert a == b, (
        "the containment paragraph has diverged between codebase-review and "
        "security-audit — a fix applied to one and not the other now reads as covered"
    )


def test_the_rollback_header_comment_does_not_prescribe_a_move() -> None:
    """`Q-492`: the stale clause an editor meets FIRST pointed at the destination
    `Q-482`'s round killed — `git worktree remove` deletes gitignored content at exit 0."""
    text = _rc()
    assert "otherwise MOVE main's copy back to the worktree" not in text, (
        "the section's own header comment prescribes a move the code does not do, and "
        "acting on it rebuilds a silent data-loss route"
    )
    assert "LEAVE main's copy exactly where it is" in text


# --------------------------------------------------------------------------------------
# Negative controls — the softenings a future edit would plausibly make.
# Each must be CAUGHT. A predicate that passes these is not a guard.
# --------------------------------------------------------------------------------------

@pytest.mark.parametrize(
    "mutate, expect",
    [
        pytest.param(
            lambda s: s.replace("git worktree add --detach", "git worktree add"),
            "detach", id="placement-loses-the-detach",
        ),
        pytest.param(
            lambda s: re.sub(r"git worktree add[^\n]*\n", "", s, count=1),
            "worktree add", id="placement-deleted-entirely",
        ),
        pytest.param(
            lambda s: re.sub(r'PINNED=\$\(mktemp[^\n]*\n', 'PINNED=./reviewer-$N\n', s),
            "mktemp", id="checkout-moves-inside-the-repo",
        ),
        pytest.param(
            # Both statements, not one: the block says it twice (the bullet header and
            # the bullet body), so a control that removes only one is passed by the
            # survivor and proves nothing about the predicate.
            lambda s: re.sub(r"(?i)outside the repositor\w*", "wherever is convenient", s),
            "every outside-the-repo instruction", id="outside-the-repo-prose-dropped",
        ),
    ],
)
def test_a_weakened_placement_is_caught(mutate, expect: str) -> None:
    span = mutate(_placement_block(_rc()))
    problems = placement_problems(span)
    assert problems, f"a mutation removing {expect!r} passed the placement predicate"


@pytest.mark.parametrize(
    "mutate, why",
    [
        pytest.param(
            lambda s: s.replace("git -C <absolute path to the pinned checkout> rev-parse HEAD",
                                "git rev-parse HEAD"),
            "a bare rev-parse reports the agent's own CWD",
            id="echo-loses-the-dash-C",
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
    restored = text.replace(
        "**Symlink the primary checkout's `.venv` into the reviewer's checkout.**",
        "Tell the reviewer the interpreter to use (an absolute path to the primary "
        "checkout's `.venv`, or symlink it in).",
    )
    assert venv_remedy_problems(restored), (
        "the `or` came back and the predicate did not notice — an absolute interpreter "
        "does not reach `scan_public_history.sh`, which resolves its own"
    )


def test_a_HEAD_based_retrieval_command_is_caught() -> None:
    mutated = _rc().replace(
        "Emit `git -C <absolute path to the pinned checkout> diff <default branch>...<branch>`",
        "Emit `git diff origin/<default branch>...HEAD`",
    ).replace("**Write the retrieval command with EXPLICIT refs on both sides, "
              "`-C`-rooted at the pinned checkout, and never with `HEAD` on either end.**",
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
    """The round's sharpest finding: `Q-490` leg (a) restored verbatim, guards green.

    `PIN=$(git rev-parse …)` existed and `git worktree add --detach` existed, and nothing
    tied them together — so `git worktree add --detach "$PINNED" HEAD` passed every check
    while every reviewer landed on the default branch, found nothing and returned
    APPROVED.
    """
    block = _placement_block(_rc())
    for operand, why in (
        ('HEAD', 'the literal default-branch HEAD'),
        ('"$BRANCH"', 'an unrelated variable'),
        ('"<target branch, or HEAD for the unpushed-main group>"', 'the raw placeholder'),
    ):
        mutated = block.replace('git worktree add --detach "$PINNED" "$PIN"',
                                f'git worktree add --detach "$PINNED" {operand}')
        assert placement_problems(mutated), (
            f"the add forked at {why} and the predicate passed — that is Q-490 leg (a) "
            "restored verbatim with every test green"
        )


def test_a_consistent_rename_of_the_pin_variable_does_NOT_redden() -> None:
    """Over-strictness is the direction that hides. The first predicate was keyed to the
    literal name `PIN` and went red on a legal, consistent rename."""
    renamed = (_placement_block(_rc())
               .replace('PIN=$(git rev-parse', 'COMMIT=$(git rev-parse')
               .replace('"$PINNED" "$PIN"', '"$PINNED" "$COMMIT"'))
    assert placement_problems(renamed) == [], (
        "a consistent variable rename went red — that is how a guard gets deleted "
        "rather than fixed (Phase 168: 19 of 30 innocent edits)"
    )


def test_a_backslash_continuation_does_NOT_redden() -> None:
    wrapped = _placement_block(_rc()).replace(
        'git worktree add --detach "$PINNED" "$PIN"',
        'git worktree add --detach \\\n       "$PINNED" "$PIN"')
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
    """The execution lens's sharpest finding, and the one that fails SILENTLY: the
    checkout is created at whatever `PIN` holds, so the echo matches and the receipt
    passes while every lens reviews the default branch."""
    block = _placement_block(_rc())
    collapsed = re.sub(r'PIN=\$\(git rev-parse "<target branch>"\)[^\n]*\n', "", block)
    assert placement_problems(collapsed), (
        "the feature-branch arm was dropped and only the `HEAD` arm remained — that is "
        "Q-490 leg (a) restored, silently, with every guard green"
    )
