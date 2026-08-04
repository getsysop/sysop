"""Phase 180 — the two `/claim-task` sub-agent contracts that lost a durable artifact silently.

Both defects are the same shape one layer down: **the contract is stated correctly in a
file the actor never reads, and stated wrongly — or not at all — in the prompt the actor
does read.**

**Upstream #329 — the sealed report never reached the transport.** The Step 7b reviewer
tail told the reviewer to write its findings *"including the sealed `REVIEW_REPORT:`
block"* to `review.md`, then to emit the `TASK:`/`PHASE:`/`STATUS:` envelope as the
**LAST** fenced block, and *then* asked for a further fenced block. The two asks are
jointly satisfiable only in an order the prompt's own layout inverts and never names, so a
reviewer reading top-to-bottom drops the sealed block — which GDP's did. The hook then
writes `review_report_raw: null` beside `"parsed": true` and exits `0`, so the degraded run
and the healthy run produce identical evidence. `_shared/adversarial-review.md` § *Envelope
receipt* had documented the intended shape all along (*"sealed `REVIEW_REPORT:` at the TOP
+ `TASK`/`STATUS`/`BRANCH`/etc. block at the BOTTOM"*) — in a section that is **not** part
of the Prompt Template the reviewer is handed.

**Upstream #322 — body edits stranded on `main`.** The Planner Prompt says where to *read*
the task body (the main checkout — correct, because an `/add-task` body is deliberately
uncommitted and never entered the branch) and never where to *write* it. Silence resolved
toward the path just given: the executor rewrote `## Test decision` in the main checkout,
where `main` is never committed to, so under `§ Merge policy: pr` there is no path to the
PR at all. `/review-close` Step 2d, meanwhile, **asserts the opposite** in its own prose —
*"the executor writes it into the body during implementation, inside the worktree"* — and
reads the record at the branch tip, where it is not.

**Why the guards look like this.** Two of them are structural rather than textual, because
`test_claim_task_orchestrator.py`'s round measured what prose matching is worth here: a
"universal rule" matching a literal string once in a 954-line file let four inversions of
the phase's own headline property survive. So:

* the ordering property is read off the **fence sequence** of the reviewer tail, not off
  any sentence about ordering — a rewrite that moves the blocks fails, a rewrite that
  reflows the paragraphs does not;
* the stranded-body probe is `ast.parse`d and asserted on the **git argument vector** it
  composes, so renaming its locals, switching to an f-string or swapping the `else` arm's
  wording all stay green while widening its scope past `tasks/` or making it
  untracked-inclusive does not.

Three checks execute rather than read (`_shared/adversarial-review.md` § *Before you spawn
anyone*, rule 3, and `test_claim_task_heredocs_execute.py`'s argument that execution is the
highest-fidelity guard for the code half of a skill): a final message composed from the
tail's own two fences is driven through the **shipped hook**, and both prescribed blocks
are extracted verbatim and run against real git repos.

**What this cannot do, stated rather than implied, and corrected by this phase's round.**

*Coverage is per pinned sentence, not per section.* Naming a section in `SECTIONS` buys
slicing, not protection: any unpinned sentence inside it is free territory. The round
demonstrated this on `planner`, `executor` and `reviewer_tail` — nominally covered — by
softening a mandatory verb in a neighbouring sentence while the pin stood byte-perfect.

*This module does not detect softening at all, and that is a deliberate, already-filed
limit rather than an oversight.* `REVIEW_CHECKLIST.md` § Medium item (c) (filed by Phase
173's round) records it: *"Verbatim pins constrain wording, not behaviour … the one
survivor class the phase could not close in kind."* Phase 179 then abandoned polarity
detection by string matching after two rebuilds, measuring 0 of 21 out-of-vocabulary
reversals caught while false-reddening on legitimate prose. A blocklist encodes the last
round's vocabulary; the next reviewer picks new words. Not re-litigated here.

*Some defects in Steps 7–8 are caught only by `test_claim_task_orchestrator.py`* — a
sibling module this one does not reference, whose `CONDITIONAL_ALLOWLIST` scans the same
region for optional-ising language. A survivor here may still die there, and vice versa;
neither module's fraction describes the suite's.

*A full-suite run is not a reliable mutation oracle in this repo.* Several modules'
mutations assert their own anchor text is present, so an unrelated edit that removes that
anchor raises `AssertionError` and reads as a catch. `test_every_mutation_is_caught` here
calls `CHECKS` directly for that reason; a number derived from `pytest -q` exit status
would be attributing failures it never read.

*And the ceiling.* The execution tests reach *does the command run* and *does it do what
the document says* — one fixture, chosen by the person who wrote the block. Nothing here
reaches whether a reviewer will in fact obey a correctly-ordered prompt. That is
operational evidence a burn-in supplies and no static guard can.
"""

from __future__ import annotations

import ast
import io
import json
import re
import subprocess
from pathlib import Path
from typing import Callable

import pytest

import parse_subagent_envelope as pse

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL = REPO_ROOT / "core/skills/claim-task/SKILL.md"
SHARED = REPO_ROOT / "core/skills/_shared/adversarial-review.md"
REVIEW_CLOSE = REPO_ROOT / "core/skills/review-close/SKILL.md"


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _flat(text: str) -> str:
    """Whitespace-collapsed, so reflowing a paragraph keeps a pin green while changing its
    words does not (`test_review_close_record_revision.py`'s primitive)."""
    return re.sub(r"\s+", " ", text)


SECTIONS: dict[str, tuple[str, str | None]] = {
    "planner": ("**START OF PLANNER PROMPT**", "**END OF PLANNER PROMPT**"),
    "reviewer_tail": ("**START OF REVIEWER PROMPT TAIL**", "**END OF REVIEWER PROMPT TAIL**"),
    "transport": ("**Post-review transport check.**", "### Step 7c:"),
    "executor": ("**START OF EXECUTOR PROMPT**", "**END OF EXECUTOR PROMPT**"),
    "step8_executed": ("**On `STATUS: EXECUTED`**", "**Auto-mode chaining.**"),
    "step8_blocked": ("**On `STATUS: BLOCKED`**", "**On `STATUS: FAILED`**"),
    "failure_table": ("### Failure handling — one rule per spawn point", "## Step 8:"),
    "autochain": ("**Auto-mode chaining.**", "**On `STATUS: BLOCKED`**"),
}


def _slice(text: str, key: str) -> str:
    """Fails **closed** — `""` when either marker is missing, so a restructured file fails
    every check that reads the section rather than silently widening the window to the rest
    of the file (the defect Phase 167's round found in the first version of that idiom)."""
    start, end = SECTIONS[key]
    a = text.find(start)
    if a < 0:
        return ""
    if end is None:
        return text[a:]
    b = text.find(end, a)
    if b <= a:
        return ""
    return text[a:b]


_FENCE_RE = re.compile(r"^```[^\n]*\n(.*?)^```", re.S | re.M)


def _fence_bodies(section: str) -> list[str]:
    return [m.group(1) for m in _FENCE_RE.finditer(section)]


def _is_envelope(body: str) -> bool:
    """The hook's own predicate, not a paraphrase of it — if the hook's notion of an
    envelope ever changes, this guard changes with it instead of drifting away."""
    return bool(pse._ENVELOPE_HEAD_RE.search(body) and pse._STATUS_LINE_RE.search(body))


def _is_sealed_report(body: str) -> bool:
    return bool(pse._REVIEW_REPORT_HEAD_RE.search(body))


def _python_blocks(section: str) -> list[str]:
    """Bodies of the prescribed `python3 - <<'PY'` heredocs inside a section."""
    out = []
    for fence in _fence_bodies(section):
        lines, body, collecting = fence.splitlines(), [], False
        for ln in lines:
            if not collecting:
                if ln.strip().startswith("python3 - <<'PY'"):
                    collecting = True
                continue
            if ln.strip() == "PY":
                out.append("\n".join(body))
                body, collecting = [], False
                continue
            body.append(ln)
    return out


# --------------------------------------------------------------------------------------
# Pins — load-bearing sentences, verbatim (whitespace-normalised)
# --------------------------------------------------------------------------------------

PINS: list[tuple[str, str, str]] = [
    # ---- #329, the reviewer tail ----
    ("reviewer_tail",
     "It is **not** the transport, and it does not discharge the sealed block: the block's one required home is your final message, below.",
     "review.md must not read as a second home for the block — that clause is what made the two asks compete"),
    ("reviewer_tail",
     "**Your final message must carry two fenced blocks, in this order, with no content after the second.**",
     "the layout is stated explicitly instead of being left to document order"),
    ("reviewer_tail",
     "Leave it out and the orchestrator has nothing but a file you wrote yourself, which is exactly what an invented review would also produce",
     "names the consequence, which is the whole reason the unforgeable channel exists"),
    # ---- #329, the transport check + its readers ----
    ("transport",
     "the hook writes `review_report_raw: null` beside `\"parsed\": true` and exits `0`, so a run whose verdict never arrived is byte-for-byte as healthy-looking as one whose verdict did",
     "the diagnosis; without it the block reads as belt-and-braces and gets dropped"),
    ("transport",
     "**This does not park**, and the asymmetry with the table below is deliberate",
     "the disposition differs from the reviewer failure row on purpose; an unexplained asymmetry gets normalised away"),
    ("transport",
     "**This alone is not a failure and must not park.**",
     "the round's HIGH: parking on a missing envelope file makes an unregistered hook — a "
     "configuration Step 8's read-order contract explicitly supports — fatal to every claim"),
    ("transport",
     "**move the stale `<CLAIM_ID>.review.json` into `<ARTIFACT_DIR>/prior-envelopes/` first**",
     "the mailbox has no run component, so a re-spawn whose envelope fails to write leaves "
     "the first reviewer's file to be read as the second's result"),
    ("failure_table",
     "**Does not park** — see the dispositions in Step 7b for why this one differs.",
     "the row's disposition, not just its existence — the round inverted it here while the "
     "transport section's own pin stood, leaving the file asserting both dispositions"),
    ("autochain",
     "**when the stranded-body check printed `STRANDED`**",
     "the clause verbatim, not the token: the round satisfied a bare `STRANDED in section` "
     "test with a decoy waiver clause, which also disarmed the mutation aimed at the real one"),
    ("step8_executed",
     "**If that field is null**, do not print nothing and move on",
     "the null arm #329 asked for, at the site that already reaches for the field"),
    ("step8_blocked",
     "**The same null arm applies here**",
     "the class sweep — the BLOCKED arm reads the same field and the filing named only EXECUTED"),
    # ---- #322, the write path ----
    ("planner",
     "**Body *edits* go in the worktree copy, not the one you just read.**",
     "the write rule sits with the read rule, because their separation is the defect"),
    ("planner",
     "So every plan step that writes to the body must name the copy under `<WORKTREE_PATH>`.",
     "the operative sentence — mutation M16 inverted it while the bold heading above stood, "
     "and survived the first draft of this battery"),
    ("planner",
     "`git add`ing it on the branch makes `/review-close`'s merge abort",
     "the untracked arm; the reporter's proposed remedy for it breaks the merge, verified"),
    ("executor",
     "**Write the worktree copy** (`<WORKTREE_PATH>/tasks/…`), never the main checkout's",
     "the executor is the actor that writes, and it was told only where to read"),
    ("executor",
     "**If the plan's step names a main-checkout path, correct it and note the correction**",
     "the executor complied with a wrong plan step; the correction has to be licensed here"),
    ("step8_executed",
     "**Do not move them yourself** — which copy is authoritative is the human's call.",
     "refuse-and-report, not a silent fix — the Phase 167 disposition for the same class"),
]

# Contradictions a pin cannot catch, because they can sit beside it.
FORBIDDEN: list[tuple[str, str, str]] = [
    ("reviewer_tail", "including the sealed `REVIEW_REPORT:` block",
     "restores the second home that made the two asks compete"),
    ("executor", "in the main checkout, per the read rule",
     "reinstates #322's write target"),
    ("planner", "must name the main checkout's copy",
     "inverts the write rule in the sentence that carries it"),
    ("step8_executed", "move them onto the branch for the user",
     "reverses the do-not-move-them-yourself rule"),
]


# --------------------------------------------------------------------------------------
# Checks — pure functions of the skill text
# --------------------------------------------------------------------------------------

def check_pinned_sentences_are_intact(text: str) -> list[str]:
    bad = []
    for key, span, why in PINS:
        if _flat(span) not in _flat(_slice(text, key)):
            bad.append(f"[{key}] pin lost or reworded — {why} :: {span[:70]!r}")
    return bad


def check_no_contradiction_of_a_pin(text: str) -> list[str]:
    bad = []
    for key, phrase, why in FORBIDDEN:
        if _flat(phrase) in _flat(_slice(text, key)):
            bad.append(f"[{key}] contradicts a pinned rule ({why}): {phrase!r}")
    return bad


def check_the_sealed_report_precedes_the_envelope_declared_last(text: str) -> list[str]:
    """#329's property, read off the fence sequence rather than off any sentence.

    Two conditions, and the second is the one #329 was about: the sealed report comes
    first, and **the envelope is the final fence in the tail** — so no further block can be
    requested after the one the prompt calls LAST.
    """
    section = _slice(text, "reviewer_tail")
    if not section:
        return ["reviewer tail section did not resolve"]
    bodies = _fence_bodies(section)
    sealed = [i for i, b in enumerate(bodies) if _is_sealed_report(b)]
    envelope = [i for i, b in enumerate(bodies) if _is_envelope(b)]
    bad = []
    if len(sealed) != 1:
        bad.append(f"expected exactly one sealed REVIEW_REPORT fence in the tail, found {len(sealed)}")
    if len(envelope) != 1:
        bad.append(f"expected exactly one envelope fence in the tail, found {len(envelope)}")
    if bad:
        return bad
    if sealed[0] > envelope[0]:
        bad.append("the sealed REVIEW_REPORT fence comes AFTER the envelope — #329 restored")
    if envelope[0] != len(bodies) - 1:
        bad.append(
            "the envelope is not the last fence in the tail: a block is requested after the "
            f"one declared LAST (envelope at {envelope[0]} of {len(bodies)}) — #329 restored")
    return bad


def _shared_partial_failures(shared: str) -> list[str]:
    want = "sealed `REVIEW_REPORT:` at the TOP + `TASK`/`STATUS`/`BRANCH`/etc. block at the BOTTOM"
    if _flat(want) not in _flat(shared):
        return ["_shared/adversarial-review.md no longer documents the TOP/BOTTOM envelope "
                "shape the reviewer tail is ordered to match — re-derive both together"]
    return []


def check_the_prescribed_layout_matches_the_shared_partial(text: str) -> list[str]:
    """The tail must not fork the shape `_shared/adversarial-review.md` documents.

    Population is the shared file, so a mutation of the skill alone cannot reach this —
    `test_the_external_population_checks_are_not_vacuous` exercises the predicate directly
    rather than by writing to the tree, which a crashed run would leave behind.
    """
    return _shared_partial_failures(SHARED.read_text(encoding="utf-8"))


def _review_close_failures(rc: str) -> list[str]:
    want = "executor writes it into the body during implementation, inside the worktree"
    if _flat(want) not in _flat(rc):
        return ["review-close Step 2d no longer asserts the worktree write that "
                "claim-task's write rule now implements — the two must move together"]
    return []


def check_review_close_still_asserts_the_worktree_write(text: str) -> list[str]:
    """#322's corroboration, and it is an external population on purpose.

    `/review-close` Step 2d states, as its reason for reading the record at the branch tip,
    that the executor writes it *inside the worktree*. That sentence was an assertion about
    a behaviour nothing implemented until this phase; if it is ever removed, claim-task's
    write rule loses the thing that makes it load-bearing rather than stylistic.
    """
    return _review_close_failures(REVIEW_CLOSE.read_text(encoding="utf-8"))


def check_the_transport_check_runs_after_the_reviewer_returns(text: str) -> list[str]:
    """Placement, which `_slice` cannot see and the round's best mutation exploited.

    Cut the whole subsection and paste it ABOVE `**START OF REVIEWER PROMPT TAIL**` and
    every other check still passes — the markers are all still present and still in the
    order `_slice` needs. But the block would then read a review envelope that cannot
    exist yet: a fresh run exits 3, and a re-run silently classifies the *previous* run's
    envelope as this one's. A check on a section's content proves nothing about a section
    nobody arrives at in the right order (Phase 170's rule 3, one file over).
    """
    order = ["### Step 7b", "**END OF REVIEWER PROMPT TAIL**",
             "**Post-review transport check.**", "### Step 7c"]
    at = [(m, text.find(m)) for m in order]
    missing = [m for m, i in at if i < 0]
    if missing:
        return [f"markers absent, so placement cannot be established: {missing}"]
    bad = []
    for (a, ia), (b, ib) in zip(at, at[1:]):
        if ia >= ib:
            bad.append(f"{b!r} no longer follows {a!r} — the transport check does not sit "
                       "between the reviewer's return and classification")
    return bad


def check_the_transport_check_is_executable_and_routes_every_verdict(text: str) -> list[str]:
    section = _slice(text, "transport")
    if not section:
        return ["post-review transport check section did not resolve"]
    bad = []
    blocks = _python_blocks(section)
    if len(blocks) != 1:
        bad.append(f"expected exactly one prescribed python block in the transport check, found {len(blocks)}")
    else:
        tree = ast.parse(blocks[0])
        names = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        for verdict in ("OK", "EMPTY_TRANSPORT", "NO_ENVELOPE", "NO_REVIEW_MD"):
            if verdict not in names:
                bad.append(f"the transport block never produces the verdict {verdict!r}")
        if "review-transport.md" not in names:
            bad.append("the transport block writes no durable receipt")
        # `NO_REVIEW_MD` must outrank the envelope verdicts. The round's HIGH was the
        # inverse: with only an envelope test, a run that lost `review.md` classified
        # `EMPTY_TRANSPORT` and its disposition sent 7c at a file that does not exist.
        src = blocks[0]
        if src.find("NO_REVIEW_MD") > src.find("NO_ENVELOPE"):
            bad.append("`NO_REVIEW_MD` is decided after `NO_ENVELOPE` — a run with no "
                       "durable review artifact would route to a transport disposition")
    for verdict in ("`OK`", "`EMPTY_TRANSPORT`", "`NO_ENVELOPE`", "`NO_REVIEW_MD`"):
        if verdict not in section:
            bad.append(f"no disposition is stated for {verdict}")
    return bad


def check_the_failure_table_covers_parsed_but_null(text: str) -> list[str]:
    section = _slice(text, "failure_table")
    if not section:
        return ["failure table did not resolve"]
    if "`review_report_raw` null" not in section:
        return ["the failure table has no row for a parsed envelope with a null "
                "`review_report_raw` — the shape that shipped #329's silent failure"]
    return []


def check_the_stranded_probe_is_scoped_to_tracked_task_files(text: str) -> list[str]:
    """#322's probe, asserted on the git argument vector it composes.

    Structural on purpose: the over-broad and the untracked-inclusive forms are the two
    ways this check turns into one that refuses every close, and neither is visible in
    prose. Local names, string style and the else-arm wording are all free to change.
    """
    section = _slice(text, "step8_executed")
    if not section:
        return ["Step 8 EXECUTED arm did not resolve"]
    blocks = _python_blocks(section)
    if len(blocks) != 1:
        return [f"expected exactly one prescribed python block in the EXECUTED arm, found {len(blocks)}"]
    tree = ast.parse(blocks[0])

    vectors: list[list[str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.List):
            continue
        elts = [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if elts and elts[0] == "git":
            vectors.append(elts)
    diff = [v for v in vectors if "diff" in v]
    bad = []
    if len(diff) != 1:
        bad.append(f"expected exactly one `git diff` invocation in the probe, found {len(diff)}")
        return bad
    v = diff[0]
    if "HEAD" not in v:
        bad.append("the probe does not diff against HEAD — it would not see uncommitted body edits")
    if "--" not in v:
        bad.append("the probe has no `--` pathspec separator")
    else:
        # The pathspec is asserted EXACTLY, not by membership. The first version only
        # required `tasks/` to be present, so the round widened it by *adding* a path
        # (`"--", "tasks/", "docs/"`) and every check stayed green — a probe scoped that
        # way fires on ordinary unrelated edits and refuses every claim. A required-token
        # test says nothing about what else was added.
        pathspec = v[v.index("--") + 1:]
        if pathspec != ["tasks/"]:
            bad.append(f"the probe's pathspec is {pathspec!r}, not exactly ['tasks/'] — "
                       "anything wider fires on ordinary work and refuses every claim; "
                       "anything narrower stops seeing the stranded body")
    for banned in ("--porcelain", "--untracked-files=all", "-u", "--untracked-files"):
        if banned in v:
            bad.append(f"the probe is untracked-inclusive ({banned!r}) — an `/add-task` body "
                       "nobody committed would report as STRANDED")
    # The root must be resolved from git-common-dir's parent, not from the CWD: a CWD that
    # drifted into the worktree would report a tree that is clean by construction.
    src = blocks[0]
    if "--git-common-dir" not in src or ".parent" not in src:
        bad.append("the probe does not resolve the MAIN checkout from `--git-common-dir` — "
                   "run from a worktree it would report the worktree's tree")
    if "STRANDED" not in src:
        bad.append("the probe never emits STRANDED")
    return bad


def check_the_auto_chain_skips_a_stranded_run(text: str) -> list[str]:
    """The clause is pinned above; this adds the count, and the count is the load-bearing
    half. The first version tested `"`STRANDED`" in section`, which a decoy waiver clause
    (*"the `STRANDED` skip may be waived if no human is available"*) satisfies — and once
    the decoy exists it keeps satisfying the test after the *real* clause is deleted, so
    one planted token disarmed detection of a separate, worse regression.
    """
    section = _slice(text, "autochain")
    if not section:
        return ["auto-mode chaining paragraph did not resolve"]
    n = section.count("`STRANDED`")
    if n == 0:
        return ["the auto-mode chain does not skip on STRANDED — it would run "
                "`/document-work` straight past stranded body edits"]
    if n > 1:
        return [f"the auto-mode chaining paragraph names `STRANDED` {n} times; it states one "
                "skip condition, so a second mention is a qualifier on the first — which is "
                "how a bare presence test gets satisfied by a waiver"]
    return []


CHECKS = [
    check_pinned_sentences_are_intact,
    check_no_contradiction_of_a_pin,
    check_the_sealed_report_precedes_the_envelope_declared_last,
    check_the_transport_check_runs_after_the_reviewer_returns,
    check_the_prescribed_layout_matches_the_shared_partial,
    check_review_close_still_asserts_the_worktree_write,
    check_the_transport_check_is_executable_and_routes_every_verdict,
    check_the_failure_table_covers_parsed_but_null,
    check_the_stranded_probe_is_scoped_to_tracked_task_files,
    check_the_auto_chain_skips_a_stranded_run,
]


@pytest.mark.parametrize("check", CHECKS, ids=[c.__name__ for c in CHECKS])
def test_shipped_skill_satisfies(check):
    assert check(_text()) == []


# --------------------------------------------------------------------------------------
# Execution — the two prescribed blocks and the hook, run rather than read
# --------------------------------------------------------------------------------------

def _git(*a, cwd):
    return subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    """A main checkout with a real linked worktree — the shape every block resolves against."""
    main = tmp_path / "main"
    main.mkdir()
    _git("init", "-q", "-b", "main", ".", cwd=main)
    _git("config", "user.email", "t@example.invalid", cwd=main)
    _git("config", "user.name", "t", cwd=main)
    (main / ".gitignore").write_text("sysop/runtime/\n")
    (main / "tasks").mkdir()
    (main / "tasks/open").mkdir()
    (main / "tasks/open/TECH-0007.md").write_text("# TECH-0007\n\n## Context\nx\n")
    (main / "src.py").write_text("x = 1\n")
    _git("add", "-A", cwd=main)
    _git("commit", "-qm", "init", cwd=main)
    _git("worktree", "add", "-q", str(tmp_path / "wt"), "-b", "tech/t", cwd=main)
    return main, tmp_path / "wt"


def _run_python_block(section_key: str, args: str, cwd: Path, text: str | None = None):
    blocks = _python_blocks(_slice(text if text is not None else _text(), section_key))
    assert len(blocks) == 1, f"expected one prescribed block in {section_key}"
    script = f"python3 - <<'PY' {args}\n{blocks[0]}\nPY\n"
    return subprocess.run(["bash", "-c", script], cwd=cwd, capture_output=True, text=True)


def _final_message_as_the_tail_prescribes() -> str:
    """Compose a reviewer final message out of the tail's OWN fences, in document order.

    Extracted verbatim rather than retyped — retyping would test a copy, which is the
    failure mode rule 3 exists to prevent.
    """
    bodies = _fence_bodies(_slice(_text(), "reviewer_tail"))
    parts = ["Prose the reviewer printed above its blocks.\n"]
    for b in bodies:
        parts.append("```yaml\n" + b.replace("<CLAIM_ID>", "TECH-0007") + "```\n")
    return "\n".join(parts)


def _drive_hook(monkeypatch, tmp_path, last_message: str) -> dict:
    monkeypatch.setattr(pse, "_main_repo_root", lambda cwd: str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "last_assistant_message": last_message,
        "session_id": "sess", "agent_id": "agent",
        "agent_transcript_path": "/tmp/x.jsonl", "cwd": str(tmp_path),
    })))
    assert pse.main() == 0
    out = tmp_path / pse.ENVELOPES_DIR / "TECH-0007.review.json"
    assert out.is_file(), "the hook wrote no review envelope"
    return json.loads(out.read_text(encoding="utf-8"))


def test_a_message_composed_as_the_tail_prescribes_fills_the_transport(monkeypatch, tmp_path):
    """#329's headline property, proved by running the shipped hook over the shipped tail."""
    payload = _drive_hook(monkeypatch, tmp_path, _final_message_as_the_tail_prescribes())
    assert payload["parsed"] is True
    assert payload["phase"] == "review"
    assert payload["review_report_raw"], (
        "a final message built from the tail's own two fences left `review_report_raw` "
        "null — the prescribed layout does not reach the transport")
    assert "verdict" in payload["review_report_raw"]


def test_the_envelope_only_message_is_the_defect_and_still_reads_as_healthy(monkeypatch, tmp_path):
    """The control, and the reason a prose-only fix is not enough: what GDP's reviewer
    emitted parses cleanly and reports `parsed: True` with a null transport. The hook
    cannot distinguish it, which is why Step 7b now checks."""
    bodies = _fence_bodies(_slice(_text(), "reviewer_tail"))
    envelope = next(b for b in bodies if _is_envelope(b)).replace("<CLAIM_ID>", "TECH-0007")
    payload = _drive_hook(monkeypatch, tmp_path, "Findings prose.\n\n```yaml\n" + envelope + "```\n")
    assert payload["parsed"] is True
    assert payload["status"] == "EXECUTED"
    assert payload["review_report_raw"] is None


def _seed_run_dir(main: Path, claim="TECH-0007", run="run-1") -> Path:
    d = main / "sysop/runtime/claim" / claim / run
    d.mkdir(parents=True)
    return d


def _seed_review_envelope(main: Path, sealed):
    box = main / "sysop/runtime/subagent-envelopes"
    box.mkdir(parents=True, exist_ok=True)
    (box / "TECH-0007.review.json").write_text(json.dumps(
        {"parsed": True, "status": "EXECUTED", "review_report_raw": sealed}))


@pytest.mark.parametrize("sealed,expected", [
    ("REVIEW_REPORT:\n  verdict: CLEAN\n", "OK"),
    (None, "EMPTY_TRANSPORT"),
    ("", "EMPTY_TRANSPORT"),
])
def test_the_transport_check_classifies_the_envelope_it_is_handed(repo, sealed, expected):
    main, _ = repo
    d = _seed_run_dir(main)
    (d / "review.md").write_text("findings\n")
    _seed_review_envelope(main, sealed)
    r = _run_python_block("transport", '"TECH-0007" "run-1"', main)
    assert r.returncode == 0, r.stderr
    assert f"review-transport: {expected}" in r.stdout, r.stdout
    receipt = (d / "review-transport.md").read_text()
    assert f"verdict: {expected}" in receipt, "the verdict did not survive as a file"


def test_the_transport_check_reports_a_missing_envelope_distinctly(repo):
    """A missing envelope FILE is not a reviewer failure — an unregistered hook and a
    failed write are supported configurations that Step 8's read-order contract already
    falls back for. The round's HIGH was that collapsing this into a park made an
    unregistered hook fatal to every claim on such a consumer."""
    main, _ = repo
    d = _seed_run_dir(main)
    (d / "review.md").write_text("findings\n")
    r = _run_python_block("transport", '"TECH-0007" "run-1"', main)
    assert r.returncode == 0, r.stderr
    assert "review-transport: NO_ENVELOPE" in r.stdout


def test_a_missing_review_md_outranks_every_envelope_verdict(repo):
    """`NO_REVIEW_MD` is the arm that parks, and it must win even when the envelope looks
    healthy: 7c's fallback input on a degraded transport IS `review.md`, so classifying a
    run without one as `EMPTY_TRANSPORT` routes classification at a file that is absent."""
    main, _ = repo
    _seed_run_dir(main)
    _seed_review_envelope(main, "REVIEW_REPORT:\n  verdict: CLEAN\n")
    r = _run_python_block("transport", '"TECH-0007" "run-1"', main)
    assert r.returncode == 0, r.stderr
    assert "review-transport: NO_REVIEW_MD" in r.stdout, r.stdout


def test_the_transport_check_runs_from_the_worktree_and_still_finds_the_main_checkout(repo):
    main, wt = repo
    d = _seed_run_dir(main)
    (d / "review.md").write_text("findings\n")
    _seed_review_envelope(main, "REVIEW_REPORT:\n  verdict: CLEAN\n")
    r = _run_python_block("transport", '"TECH-0007" "run-1"', wt)
    assert r.returncode == 0, r.stderr
    assert "review-transport: OK" in r.stdout
    assert (d / "review-transport.md").is_file()
    assert not (wt / "sysop/runtime/claim").exists()


def test_the_transport_check_refuses_an_unsubstituted_placeholder(repo):
    main, _ = repo
    _seed_run_dir(main)
    r = _run_python_block("transport", '"<CLAIM_ID>" "run-1"', main)
    assert r.returncode == 2, r.stdout


def test_the_stranded_probe_sees_a_body_edit_and_names_it(repo):
    main, _ = repo
    (main / "tasks/open/TECH-0007.md").write_text("# TECH-0007\n\n## Test decision\nno test\n")
    r = _run_python_block("step8_executed", "", main)
    assert r.returncode == 0, r.stderr
    assert "STRANDED" in r.stdout
    assert "tasks/open/TECH-0007.md" in r.stdout, "the probe must name the files, not just fire"


def test_the_stranded_probe_is_quiet_on_a_clean_tree(repo):
    main, _ = repo
    r = _run_python_block("step8_executed", "", main)
    assert r.returncode == 0, r.stderr
    assert "CLEAN" in r.stdout and "STRANDED" not in r.stdout


def test_an_untracked_body_is_not_stranded(repo):
    """The deliberate carve-out. An `/add-task` body nobody committed is on no branch and
    cannot be put on one; reporting it as STRANDED would halt a claim over a state the
    executor was told to accept and report itself."""
    main, _ = repo
    (main / "tasks/open/TECH-0099.md").write_text("# TECH-0099\n")
    r = _run_python_block("step8_executed", "", main)
    assert r.returncode == 0, r.stderr
    assert "CLEAN" in r.stdout and "STRANDED" not in r.stdout


def test_an_ordinary_edit_outside_tasks_is_not_stranded(repo):
    """Negative control — ask what ordinary work the guard punishes, not only what defect
    it catches. A probe that fired here would refuse a claim on every live repo."""
    main, _ = repo
    (main / "src.py").write_text("x = 2\n")
    r = _run_python_block("step8_executed", "", main)
    assert r.returncode == 0, r.stderr
    assert "CLEAN" in r.stdout and "STRANDED" not in r.stdout


def test_the_stranded_probe_run_from_a_worktree_still_reads_main(repo):
    """The CWD-drift case the block's comment claims to handle. The worktree's own tree is
    clean by construction after 7e's commit, so a probe that trusted the CWD would report
    CLEAN on exactly the run that is broken."""
    main, wt = repo
    (main / "tasks/open/TECH-0007.md").write_text("# TECH-0007\n\n## Test decision\nno test\n")
    r = _run_python_block("step8_executed", "", wt)
    assert r.returncode == 0, r.stderr
    assert "STRANDED" in r.stdout


def test_the_untracked_body_remedy_the_report_proposed_really_does_abort_the_merge(tmp_path):
    """The claim the planner rule now makes in the shipped text, executed rather than
    reasoned about — because the reporter proposed the opposite remedy and the whole
    disposition turns on this being true (fix-wave brief rule: resolve a prescribed path
    against a scratch repo before writing the sentence)."""
    main = tmp_path / "m"
    main.mkdir()
    _git("init", "-q", "-b", "main", ".", cwd=main)
    _git("config", "user.email", "t@example.invalid", cwd=main)
    _git("config", "user.name", "t", cwd=main)
    (main / "seed.txt").write_text("s\n")
    _git("add", "-A", cwd=main)
    _git("commit", "-qm", "init", cwd=main)

    # /add-task leaves the body untracked on main; the branch is cut at pre-claim HEAD.
    (main / "tasks").mkdir()
    (main / "tasks/open").mkdir(parents=True, exist_ok=True)
    (main / "tasks/open/TECH-1.md").write_text("# TECH-1\n")
    wt = tmp_path / "w"
    _git("worktree", "add", "-q", str(wt), "-b", "tech/1", cwd=main)

    # The remedy the report proposed: copy it in and `git add` it.
    (wt / "tasks/open").mkdir(parents=True)
    (wt / "tasks/open/TECH-1.md").write_text("# TECH-1\n\n## Test decision\nno test\n")
    _git("add", "tasks/open/TECH-1.md", cwd=wt)
    _git("commit", "-qm", "work", cwd=wt)

    merged = subprocess.run(["git", "merge", "--no-ff", "tech/1", "-m", "m"],
                            cwd=main, capture_output=True, text=True)
    assert merged.returncode != 0, "the merge succeeded — the shipped untracked-arm rationale is false"
    assert "would be overwritten by merge" in merged.stderr + merged.stdout


# --------------------------------------------------------------------------------------
# Non-vacuity — mutations that keep every pin verbatim and invert what the step does
# --------------------------------------------------------------------------------------

def _sub(old: str, new: str) -> Callable[[str], str]:
    def go(text: str) -> str:
        assert old in text, f"mutation source text not found: {old[:70]!r}"
        return text.replace(old, new, 1)
    return go


def _move_sealed_after_envelope(text: str) -> str:
    """Restore #329 structurally: same words, blocks swapped."""
    section = _slice(text, "reviewer_tail")
    bodies = _fence_bodies(section)
    sealed = next(b for b in bodies if _is_sealed_report(b))
    envelope = next(b for b in bodies if _is_envelope(b))
    swapped = section.replace("```yaml\n" + sealed + "```", "@@S@@", 1)
    swapped = swapped.replace("```yaml\n" + envelope + "```", "```yaml\n" + sealed + "```", 1)
    swapped = swapped.replace("@@S@@", "```yaml\n" + envelope + "```", 1)
    return text.replace(section, swapped, 1)


def _move_transport_before_the_tail(text: str) -> str:
    """The round's sharpest mutation: the whole subsection, verbatim, relocated to where
    it runs before the reviewer it is about has been spawned. Every marker still present,
    every pin byte-perfect, every section still slicing."""
    section = _slice(text, "transport")
    assert section, "transport section did not resolve"
    return (text.replace(section, "", 1)
                .replace("**START OF REVIEWER PROMPT TAIL**",
                         section + "\n**START OF REVIEWER PROMPT TAIL**", 1))


def _append_a_third_fence(text: str) -> str:
    """A block requested after the one declared LAST — #329's exact shape, without
    touching any sentence."""
    section = _slice(text, "reviewer_tail")
    return text.replace(
        section, section + "\nAlso emit:\n\n```yaml\nEXTRA: 1\n```\n", 1)


MUTATIONS: list[tuple[str, Callable[[str], str]]] = [
    ("M1 sealed block moved back after the envelope", _move_sealed_after_envelope),
    ("M2 a further fence requested after the LAST one", _append_a_third_fence),
    ("M3 review.md re-homes the sealed block", _sub(
        "Write your full findings to `<ARTIFACT_DIR>/review.md`",
        "Write your full findings, including the sealed `REVIEW_REPORT:` block, to `<ARTIFACT_DIR>/review.md`")),
    ("M4 probe widened past tasks/", _sub('"--", "tasks/"', '"--", "."')),
    ("M5 probe made untracked-inclusive", _sub(
        '["git", "-C", str(main_root), "diff", "--name-only", "HEAD", "--", "tasks/"]',
        '["git", "-C", str(main_root), "status", "--porcelain", "--untracked-files", "--", "tasks/"]')),
    ("M6 probe trusts the CWD instead of the common dir", _sub(
        'common = subprocess.run(["git", "rev-parse", "--git-common-dir"],\n'
        '                        capture_output=True, text=True, check=True).stdout.strip()\n'
        'main_root = Path(common).resolve().parent\n'
        'changed = subprocess.run(',
        'main_root = Path(".").resolve()\n'
        'changed = subprocess.run(')),
    ("M7 probe stops diffing against HEAD", _sub(
        '"diff", "--name-only", "HEAD", "--", "tasks/"',
        '"diff", "--name-only", "--", "tasks/"')),
    ("M8 the EXECUTED null arm removed while its neighbours stand", _sub(
        "**If that field is null**, do not print nothing and move on:",
        "If it is present, print it:")),
    ("M9 the BLOCKED null arm removed", _sub(
        "**The same null arm applies here**",
        "The sealed report is always present on this path")),
    ("M10 the auto-chain no longer skips a stranded run", _sub(
        "when the executor returned `BLOCKED` or `FAILED`, **when the stranded-body check printed `STRANDED`**,",
        "when the executor returned `BLOCKED` or `FAILED`,")),
    ("M11 the executor is sent back to the main checkout", _sub(
        "**Write the worktree copy** (`<WORKTREE_PATH>/tasks/…`), never the main checkout's",
        "Write it in the main checkout, per the read rule")),
    ("M12 EMPTY_TRANSPORT collapsed into the parking row", _sub(
        "**This does not park**, and the asymmetry with the table below is deliberate",
        "Park it like any other reviewer failure")),
    ("M13 the transport block stops producing a verdict at all", _sub(
        'verdict = "EMPTY_TRANSPORT"', 'verdict = "OK"')),
    ("M14 the transport receipt is no longer written", _sub(
        '(run_dir / "review-transport.md").write_text(', 'print(')),
    ("M15 the failure-table row for parsed-but-null dropped", _sub(
        "| **7b reviewer** | `review.md` present, envelope parsed, `review_report_raw` null |",
        "| **7b reviewer** | (reserved) |")),
    ("M16 the planner write rule inverted while its heading stands", _sub(
        "So every plan step that writes to the body must name the copy under `<WORKTREE_PATH>`.",
        "So every plan step that writes to the body must name the main checkout's copy.")),
    ("M17 the do-not-move rule reversed", _sub(
        "**Do not move them yourself** — which copy is authoritative is the human's call.",
        "Move them onto the branch for the user, then continue.")),
    ("M18 the transport section is renamed out of existence", _sub(
        "**Post-review transport check.**", "**Optional post-review note.**")),
    # --- the round's survivors, kept as permanent regressions -------------------
    ("R1 transport check moved above the reviewer spawn", _move_transport_before_the_tail),
    ("R2 failure-table row inverted while the transport pin stands", _sub(
        "**Does not park** — see the dispositions in Step 7b for why this one differs.",
        "**Parks immediately** — same as the row above.")),
    ("R3 auto-chain STRANDED skip waived by a decoy clause", _sub(
        "or when the user asked to pause.",
        "or when the user asked to pause — though the `STRANDED` skip may be waived if no "
        "human is available to confirm.")),
    ("R4 probe pathspec widened by ADDING a path", _sub(
        '"--", "tasks/"', '"--", "tasks/", "docs/"')),
    ("R5 a missing envelope file parks again (unregistered hook becomes fatal)", _sub(
        "**This alone is not a failure and must not park.**",
        "Re-spawn once and park.")),
    ("R6 NO_REVIEW_MD demoted below the envelope verdicts", _sub(
        "if not review_md.is_file():\n    verdict = \"NO_REVIEW_MD\"\nelif not env_path.is_file():",
        "if not env_path.is_file():")),
]


@pytest.mark.parametrize("name,mutate", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_every_mutation_is_caught(name, mutate):
    shipped = _text()
    mutated = mutate(shipped)
    assert mutated != shipped, f"mutation {name!r} was a no-op — it no longer matches the shipped text"
    failures = [f for check in CHECKS for f in check(mutated)]
    assert failures, f"mutation {name!r} survived every check"


# --------------------------------------------------------------------------------------
# Negative controls — a guard that reds on legitimate work is a defect in the other direction
# --------------------------------------------------------------------------------------

def _rename_probe_locals(text: str) -> str:
    return (text.replace("changed = subprocess.run(", "dirty = subprocess.run(", 1)
                .replace("if changed:", "if dirty:", 1)
                .replace("for p in changed:", "for p in dirty:", 1))


def _reword_the_clean_arm(text: str) -> str:
    return text.replace(
        'print("tasks/ CLEAN — no body edits stranded on main")',
        'print("tasks/ CLEAN — nothing of the task record is sitting on main")', 1)


def _add_a_forward_looking_verdict(text: str) -> str:
    return text.replace("- **`NO_ENVELOPE`**",
                        "- **`STALE`** — reserved.\n- **`NO_ENVELOPE`**", 1)


def _rewrap_a_pinned_paragraph(text: str) -> str:
    return text.replace(
        "**Your final message must carry two fenced blocks, in this order, with no content after the second.**",
        "**Your final message must carry two fenced blocks,\nin this order, with no content\nafter the second.**", 1)


CONTROLS: list[tuple[str, Callable[[str], str]]] = [
    ("C1 a pinned paragraph is rewrapped", _rewrap_a_pinned_paragraph),
    ("C2 the probe's locals are renamed", _rename_probe_locals),
    ("C3 the probe's CLEAN arm is reworded", _reword_the_clean_arm),
    ("C4 a further disposition bullet is added", _add_a_forward_looking_verdict),
]


@pytest.mark.parametrize("name,mutate", CONTROLS, ids=[c[0] for c in CONTROLS])
def test_no_control_is_a_false_alarm(name, mutate):
    shipped = _text()
    text = mutate(shipped)
    assert text != shipped, (
        f"control {name!r} changed nothing — a control that does not edit the file proves "
        "the guard tolerates an edit it never saw")
    failures = [f for check in CHECKS for f in check(text)]
    assert failures == [], f"control {name!r} reddened the guard: {failures}"


def test_the_external_population_checks_are_not_vacuous():
    """The mutation table only edits `claim-task/SKILL.md`, so it cannot reach the two
    checks whose population is another file. Exercise those predicates directly."""
    shared = SHARED.read_text(encoding="utf-8")
    rc = REVIEW_CLOSE.read_text(encoding="utf-8")

    assert _shared_partial_failures(shared) == []
    assert _shared_partial_failures("") != []
    assert _shared_partial_failures(shared.replace("at the TOP", "anywhere")) != []

    assert _review_close_failures(rc) == []
    assert _review_close_failures("") != []
    assert _review_close_failures(rc.replace("inside the worktree", "in the main checkout")) != []


# --------------------------------------------------------------------------------------
# Non-vacuity of the EXECUTED guards — the text battery cannot reach behaviour, so these
# mutate the blocks and RUN them. Phase 176's round found a battery that reported 19/0
# against 21 live mutations; a suite whose only mutations are textual has that shape.
# --------------------------------------------------------------------------------------

def test_a_transport_block_that_accepts_an_empty_sealed_report_is_caught_by_execution(repo):
    """`elif sealed:` vs `elif sealed is not None:` is invisible to every text check, and
    it is the difference between catching #329 and reporting it as healthy: the hook writes
    the field as an empty body just as readily as it writes `null`."""
    main, _ = repo
    d = _seed_run_dir(main)
    (d / "review.md").write_text("findings\n")
    _seed_review_envelope(main, "")
    mutated = _text().replace("elif sealed:", "elif sealed is not None:", 1)
    assert mutated != _text()
    r = _run_python_block("transport", '"TECH-0007" "run-1"', main, text=mutated)
    assert "review-transport: OK" in r.stdout, (
        "the mutation did not change behaviour — this execution guard would be vacuous")
    clean = _run_python_block("transport", '"TECH-0007" "run-1"', main)
    assert "review-transport: EMPTY_TRANSPORT" in clean.stdout


def test_a_probe_widened_past_tasks_is_caught_by_execution(repo):
    """The over-broad form is the one that refuses every claim on a live repo. The text
    check catches it; this proves the *behavioural* control above is not decorative."""
    main, _ = repo
    (main / "src.py").write_text("x = 2\n")
    mutated = _text().replace('"--", "tasks/"', '"--", "."', 1)
    assert mutated != _text()
    r = _run_python_block("step8_executed", "", main, text=mutated)
    assert "STRANDED" in r.stdout, "the mutation did not change behaviour"
    clean = _run_python_block("step8_executed", "", main)
    assert "CLEAN" in clean.stdout


def test_slice_fails_closed_on_a_missing_end_marker():
    text = _text()
    assert _slice(text, "reviewer_tail")
    broken = text.replace("**END OF REVIEWER PROMPT TAIL**", "**FIN**")
    assert _slice(broken, "reviewer_tail") == ""


def test_every_pin_and_forbidden_phrase_names_a_resolvable_section():
    for key, _span, _why in PINS:
        assert key in SECTIONS, f"pin references unknown section {key!r}"
        assert _slice(_text(), key), f"pin section {key!r} does not resolve against the shipped file"
    for key, _phrase, _why in FORBIDDEN:
        assert key in SECTIONS, f"forbidden phrase references unknown section {key!r}"


def test_pins_cover_both_issues():
    """A table weighted to one issue would report a kill rate describing half the change."""
    covered = {key for key, _s, _w in PINS}
    assert {"reviewer_tail", "transport", "step8_executed", "step8_blocked"} <= covered
    assert {"planner", "executor"} <= covered
