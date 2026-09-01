"""Leg C of Phase 184 — a `file:NN` citation must still point at what it claims.

THE DEFECT, and why it is the hard half of this phase. `claim_task.sh:86` cited
`self_check.sh:61-66` for the interpreter-shadowing hazard. That range was
correct at `adbf0cf~1`; the *same commit* that wrote the citation hoisted
`MAIN_ROOT` above probe 3 and moved the hazard text to `:75-83`. A citation
invalidated by its own commit, in a file that installs into consumer repos, and
nothing could see it:

It happened AGAIN in Phase 224, which is the argument for this registry pinning the
literal range rather than only an anchor-in-range: that phase added two comment lines
to `self_check.sh`'s header, shifting the hazard block to `:77-85`, and the citation
at `claim_task.sh:86` went stale in the same commit for the second time in two phases.
The anchor check alone would NOT have caught it — the anchor string stays inside a
range shifted by less than the block length — but the registered range string no longer
matched the tree, and that is what reddened. Keep both halves.

Original note: the mirror gate asks whether the tree contains a blocked
string, never whether a pointer still lands.

LEG C WAS ALLOWED TO CONCLUDE "NOT GUARDABLE". It measured instead, and the
measurement split the class in two rather than settling it either way:

* **The acting surface** — `core/skills/**`, `core/companion/**`, `install.sh`,
  `packs/**`, `docs/**` — carries **9** mechanically-findable intra-repo line
  citations, of which **2 were stale** (`claim_task.sh:86` and
  `docs/one-rule.md:117`, whose `grep.py:190` had drifted 41 lines to `:231`).
  Nine is small enough to pin exactly. That is this module.
* **`PHASE_LOG.md`** is not scanned here, and the reason is a measurement
  rather than a silence. A phase entry's job is to cite the line it changed, so
  the line stops holding that content by design; an anchor guard there is
  high-false-positive by construction.

  **RE-DERIVED BY PHASE 245** — the figure that stood here was **220 at a
  sampled 50% stale**, and `Q-322`'s remedy was being reasoned about from it.
  Against the tree: **405 unique citations — 386 unambiguous, 15 ambiguous,
  4 dangling.**

  The 15 are a HARD blocker on ever un-excluding this file, not merely a cost.
  They name a bare basename resolving to many files (`SKILL.md` matches 23,
  `README.md` matches 4), and `test_no_registered_citation_is_ambiguous` below
  refuses to register an ambiguous citation on purpose (round finding M6). No
  legal registry entry exists for them, so un-excluding would require editing
  fifteen historical entries or weakening that refusal.

  The checkable sub-property — **does the cited file still exist** — is guarded
  instead, in `tests/test_phase_log_citation_targets.py`. Line drift stays
  unguarded, deliberately and for the reason above.

WHY A REGISTRY, AND WHY IT IS NOT A HAND-LIST. A table of citations someone must
remember to extend is the "derive the population from an index, not the source
of truth" failure this repo has paid for repeatedly. So the population is swept
from the tree and the registry is checked *against the sweep*: a new citation
that nobody registers fails `test_every_discovered_citation_is_registered`, and
a registered one that no longer exists fails as stale registry. The table only
supplies the ANCHOR — the string the cited range must still contain — which is
the one thing a sweep cannot infer.

WHAT THIS CANNOT DO.

* **Prose citation forms are invisible.** `document-work/SKILL.md:311` cites
  "`tasks/schema.md` line 60" in words; the sweep's regex wants `file:NN`. The
  registry cannot pin what the sweep cannot find, and widening the regex to
  natural language is the judgement this module declines to make.
* **Extensionless forms** (`review-close:387`, `/auto-build:671`) are out of
  scope here. ~314 exist tree-wide against a skill/script-stem vocabulary; none
  is in the acting surface today, which is the load-bearing half.
* **Unresolved targets are baselined, not checked.** A citation naming a file
  this repo does not contain cannot have an anchor pinned, so the nine in the
  acting surface — teaching placeholders and external-repo provenance — sit in
  `UNRESOLVED_ALLOWED` with a reason each. That is what stops a pointer to a
  *deleted* file from reading like a placeholder, but it is a baseline: it
  forces a classification, it does not make one.
* **It pins the pointer, not the paraphrase.** The anchor proves the cited range
  still contains the named thing. Whether the citing sentence *characterises* it
  correctly is exactly the class Phase 183 filed as having no mechanical
  enforcement, and this module does not close it: `claim_task.sh:86` also said
  the hazard was documented "in the other direction", which Phase 182's own
  round refuted in prose that never reached the comment. The line number is now
  guarded; the adjective is not.
"""
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The surface a consumer acts on. `PHASE_LOG.md` is deliberately absent — see
# the docstring's measurement, not an oversight.
# Round finding M7: the declared surface used to be wider than the code. `docs/`
# was named while `SCANNED_SUFFIXES` dropped `docs/workflow.html` and
# `docs/index.html` — the published monograph and landing page — and the
# root-level reader-facing docs were not in SCOPE_ROOTS at all. Both closed
# rather than the claim narrowed, since those are exactly the pages a public
# reader lands on.
SCOPE_ROOTS = (
    "core/skills", "core/companion", "packs", "docs", "install.sh",
    "README.md", "CONTRIBUTING.md", "SECURITY.md",
)
SCANNED_SUFFIXES = {
    ".md", ".py", ".sh", ".example", ".fragment", ".yml", ".yaml", ".html",
}

CITATION = re.compile(
    r"([A-Za-z0-9_./-]+\.(?:md|py|sh|json|ya?ml|example|fragment)):(\d+)(?:-(\d+))?"
)

# Citations into OTHER repositories, quoted as provenance. `docs/analysis/`
# reports gdp's own files by basename, which collide with ours — the sweep
# resolved `codebase-review/SKILL.md:304` to *this* repo's skill and would have
# demanded an anchor for a line in a repo we do not ship.
#
# TOKEN-SCOPED, NOT LINE-SCOPED (round finding M4). The first version dropped
# the whole LINE, so `See `self_check.sh:12` (the gdp backport).` removed a real
# citation from the sweep entirely — never registered, never checked. That is
# the exact Pass-1a line-vs-token defect that put a blocked identifier on the
# public repo, reproduced one module away from the test written to prevent it
# (`test_the_claude_md_carveout_does_not_blind_the_scan`). The marker must now
# precede the citation, which is how provenance actually reads: "(gdp `x:12`)".
FOREIGN_CITATION_MARKERS = ("gdp ", "gdp-query", "gdp `")
FOREIGN_LOOKBEHIND = 60

# Citations whose target is not a file in this repo. All nine in the acting
# surface are deliberate — illustrative placeholders in teaching prose, and
# external-repo provenance. They are baselined rather than ignored (round
# finding M3): silently dropping every unresolved citation means a pointer to a
# DELETED or RENAMED file — the plainest dangling pointer there is — reads clean
# forever. A new entry here is either a placeholder worth declaring or a real
# dangling pointer worth fixing, and the failure message says so.
UNRESOLVED_ALLOWED = {
    "foo.py": "illustrative placeholder in adversarial-review.md's rubric",
    "src/db/writer.py": "illustrative example in contribute-convention/SKILL.md",
    "bea_client.py": "gdp-side file, cited as provenance in docs/one-rule.md",
    "bls_client.py": "gdp-side file, cited as provenance in docs/one-rule.md",
    "fred_client.py": "gdp-side file, cited as provenance in docs/one-rule.md",
    "alphavantage_client.py": "gdp-side file, cited as provenance in docs/one-rule.md",
    "isr_client.py": "invented module name inside a semgrep fixture",
    "watchdog.py": "invented module name inside a semgrep fixture",
}

# (citing file, cited "target:range") -> anchor the cited range must contain.
# The anchor is the load-bearing column: a line number alone re-breaks silently,
# which is the entire defect. Anchors are short and distinctive, never a whole
# line — a whole line makes the guard a reversion detector for reformatting.
#
# ANCHORS MUST FIT ON ONE LINE, and that is enforced below rather than trusted.
# The first anchor written here spanned a wrapped comment, so the search string
# carried a newline the file renders as "\n# " and the guard reported a stale
# citation that was perfectly correct — a false positive in the guard's own
# phase, which is how a real check gets an exemption written for it.
CITATION_ANCHORS = {
    # Phase 232: the runtime-artifact probe's comment names the installer line that
    # makes `sysop/runtime/` gitignored, because the probe's whole correctness rests
    # on that being true. The anchor is the array literal itself — if the installer
    # ever stops appending that entry, the probe is scoped to a path nothing ignores
    # and the comment becomes the false claim it replaced.
    ("core/companion/scripts/cleanup_worktrees.sh", "install.sh:3484"):
        'want=("sysop/runtime/"',
    # Phase 234: cleanup_worktrees.sh's MAIN_ROOT block cites the fail-closed
    # precedent it follows (claim_task.sh, which exits on the same class of
    # resolution failure) and the two batch_work.sh lines that put a caller inside
    # a worktree in the first place; if that prescription moves, the "this is the
    # prescribed path" claim needs re-checking rather than silently becoming false.
    # It no longer cites self_check.sh — the round replaced the copied `dirname`
    # shape outright, so that pointer went with it.
    # Phase 234: batch_work.sh's MAIN_ROOT block cites the line that makes
    # `$INDEX_SCRIPT` the READ anchor — review_index.py resolves review_tasks.md
    # from its own location, so if that ever changes, the comment's split of
    # read-side vs write-side is no longer true and the anchoring is arguing for
    # something the code does not do.
    ("core/companion/scripts/batch_work.sh", "review_index.py:47"):
        'TASKS_FILE = os.path.join(REPO_ROOT, "review_tasks.md")',
    ("core/companion/scripts/cleanup_worktrees.sh", "claim_task.sh:208-211"):
        "cannot resolve canonical",
    ("core/companion/scripts/cleanup_worktrees.sh", "batch_work.sh:1285"):
        "cd ${WORKTREE_DIR}",
    ("core/companion/scripts/cleanup_worktrees.sh", "batch_work.sh:1290"):
        "cleanup_worktrees.sh --clean",
    ("core/companion/scripts/claim_task.sh", "self_check.sh:77-85"):
        "then verify PyYAML on THAT interpreter",
    ("core/skills/auto-fix/SKILL.md", "archive_review_tasks.py:101"):
        "Merged|Complete",
    ("core/skills/auto-judge/SKILL.md", "archive_review_tasks.py:101"):
        "Merged|Complete",
    ("core/skills/triage/SKILL.md", "archive_review_tasks.py:101"):
        "Merged|Complete",
    # Phase 209 retired `_parse_batches_fallback` (62 lines), moving this anchor
    # up. The anchor string is what makes that a caught drift rather than a
    # silent one.
    ("core/skills/claim-task/SKILL.md", "batch_work.sh:375-377"):
        "left as-is",
    # Phase 211: this was written `(`:763-765`)` — a BARE self-citation, which
    # CITATION's regex cannot see because it requires a filename token before
    # the colon. It had drifted 90 lines and nothing could tell. Qualifying it
    # with its own filename is what put it under this guard; the sweep found
    # exactly one such citation in the shipped tree, and there are now none.
    # Anchored on the rule's CONSEQUENCE clause, not on "NOT an exit-code
    # change" — that phrase also appears in the sentence doing the citing, so it
    # resolved to two lines and the staleness check could not tell them apart.
    #
    # Phase 248 RETIRED the `close_batch.sh:<lines>` self-citation that sat here.
    # It drifted three times inside one phase — twice from the phase's own edits
    # and once from its round's fixes — and each repair was arithmetic on the
    # previous number, which is how it inherited an off-by-5 nobody noticed. The
    # prose now names the section ("the § Summary counters below") instead, so
    # there is no coordinate to go stale. A citation that needs re-deriving on
    # every edit to its own file is a citation that should not carry a line.
    # Phase 211: the duplicate-refusal comment used to assert that no shipped
    # skill derives the next batch number. These two are the only writers of
    # `### Batch` headers in the tree and both do, file-globally, which is why
    # the comment now cites them by line.
    ("core/companion/scripts/batch_work.sh", "codebase-review/SKILL.md:166"):
        "next_batch_number",
    ("core/companion/scripts/batch_work.sh", "security-audit/SKILL.md:183"):
        "next_batch_number",
    # Phase 211's round found the same struck premise in review_index.py's own
    # docstring — the copy where it is load-bearing, since it justifies the
    # scoping decision. The author-side sweep missed it because the sentence
    # wraps across two lines there and the grep was line-oriented.
    ("core/companion/scripts/review_index.py", "codebase-review/SKILL.md:166"):
        "next_batch_number",
    ("core/companion/scripts/review_index.py", "security-audit/SKILL.md:183"):
        "next_batch_number",
    ("core/skills/review-close/SKILL.md", "intake/SKILL.md:111"):
        "tasks/schema.md",
    ("core/skills/review-close/SKILL.md", "add-task/SKILL.md:63"):
        "open/<TASK-ID>.md",
    ("core/skills/review-close/SKILL.md", "onboard/SKILL.md:95"):
        "Test decision",
    ("docs/one-rule.md", "core/companion/scripts/run_checks/grep.py:300"):
        "nosemgrep: recompile-inside-def",
}


def _tracked():
    return [
        p
        for p in subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split("\0")
        if p
    ]


def _scanned_files():
    out = []
    for rel in _tracked():
        if not any(rel == r or rel.startswith(r + "/") for r in SCOPE_ROOTS):
            continue
        if Path(rel).suffix and Path(rel).suffix not in SCANNED_SUFFIXES:
            continue
        out.append(rel)
    return out


def _resolve(target, tracked):
    """A citation names a path or a suffix of one.

    Returns every match. Ambiguity is NOT silently resolved to the first hit —
    `test_no_registered_citation_is_ambiguous` below refuses to let an ambiguous
    citation be registered, because its anchor would then be validated against
    an arbitrary file forever. The docstring used to CLAIM ambiguity was a
    finding while the caller took `resolved[0]`; round finding M6.
    """
    return [t for t in tracked if t == target or t.endswith("/" + target)]


def _is_foreign(line, match_start):
    """True if a foreign-provenance marker precedes this citation.

    Scoped to the text before the citation, never the whole line — see the note
    on FOREIGN_CITATION_MARKERS.
    """
    before = line[max(0, match_start - FOREIGN_LOOKBEHIND):match_start].lower()
    return any(m.lower() in before for m in FOREIGN_CITATION_MARKERS)


def _discovered_citations():
    """Sweep the acting surface. (citing_rel, citing_line, cite_text, resolved)."""
    tracked = _tracked()
    found = []
    for rel in _scanned_files():
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(lines, 1):
            for m in CITATION.finditer(line):
                if _is_foreign(line, m.start()):
                    continue
                target, start, end = m.group(1), int(m.group(2)), m.group(3)
                resolved = _resolve(target, tracked)
                cite = f"{target}:{start}" + (f"-{end}" if end else "")
                found.append(
                    (rel, lineno, cite, resolved, start, int(end or start), target)
                )
    return found


def _resolved_citations():
    return [c for c in _discovered_citations() if c[3]]


def test_every_anchor_fits_on_one_line():
    """See the note on CITATION_ANCHORS — a wrapped anchor can never match."""
    multiline = [k for k, v in CITATION_ANCHORS.items() if "\n" in v]
    assert not multiline, (
        f"these anchors span a line break and so can never be found: "
        f"{multiline}. The window is joined with newlines, but a wrapped "
        "comment re-inserts its prefix, so the search string never matches. "
        "Pick a distinctive fragment from a single line."
    )


def test_the_citation_sweep_is_not_vacuous():
    """A collapsed sweep makes both checks below pass while pinning nothing."""
    found = _resolved_citations()
    assert len(found) >= 8, (
        f"only {len(found)} intra-repo citations found in the acting surface; "
        "the sweep has collapsed and this module now pins nothing"
    )
    citing = {rel for rel, *_ in found}
    assert "core/companion/scripts/claim_task.sh" in citing, (
        "claim_task.sh is the file whose citation this module exists for, and "
        "the sweep no longer sees it"
    )


def _unregistered(citations):
    """Extracted so a control can exercise the REAL predicate.

    The first draft re-implemented this filter inline inside its control, so
    disabling the real one left both green — the same decorative-control shape
    the author-side battery caught in the staleness check next door. One
    predicate, two callers.
    """
    return [
        (rel, lineno, cite)
        for rel, lineno, cite, *_ in citations
        if (rel, cite) not in CITATION_ANCHORS
    ]


def test_no_unresolved_citation_is_unaccounted_for():
    """Round finding M3 — a pointer to a deleted file must not read clean.

    Unresolved citations are dropped from the checks above by necessity (a
    placeholder like `foo.py` has no anchor to pin). Dropping them SILENTLY is
    the hole: a citation whose target was renamed or deleted looks identical to
    a teaching placeholder. Baselined, so a new one has to be classified.
    """
    unknown = _unknown_unresolved(_discovered_citations())
    assert not unknown, (
        "these citations name a file that does not exist in this repo:\n"
        + "\n".join(f"  {t}  cited at {', '.join(v)}" for t, v in sorted(unknown.items()))
        + "\n\nEither it is a dangling pointer to a renamed/deleted file — fix "
        "the citation — or it is a deliberate placeholder or external-repo "
        "reference, in which case add it to UNRESOLVED_ALLOWED with its reason."
    )


def test_the_unresolved_baseline_does_not_hide_a_real_file():
    """A baseline entry naming a real repo file would mask a live citation."""
    tracked = _tracked()
    shadowing = [
        t for t in UNRESOLVED_ALLOWED
        if any(x == t or x.endswith("/" + t) for x in tracked)
    ]
    assert not shadowing, (
        f"these UNRESOLVED_ALLOWED entries now name real files: {shadowing}. "
        "They would be swept normally anyway, but the baseline claims they "
        "cannot be — drop them from it."
    )


def test_no_registered_citation_is_ambiguous():
    """Round finding M6 — `_resolve` returns all matches; the caller takes [0].

    A citation like `SKILL.md:64` matches 23 tracked files. Registering one
    would validate its anchor against whichever sorted first, permanently and
    silently. Refuse instead.
    """
    ambiguous = _ambiguous_registered(_discovered_citations())
    assert not ambiguous, (
        "these registered citations resolve to more than one file, so their "
        "anchor is checked against an arbitrary one:\n" + "\n".join(ambiguous)
        + "\n\nCite the full repo-relative path instead of a bare basename."
    )


def test_every_discovered_citation_is_registered():
    """The population comes from the tree; the registry only supplies anchors.

    A new `file:NN` citation in the acting surface must be registered with the
    string its range has to keep containing — otherwise it is a pointer nothing
    can tell has broken, which is the defect.
    """
    unregistered = _unregistered(_resolved_citations())
    assert not unregistered, (
        "these intra-repo line citations are not registered in "
        "CITATION_ANCHORS, so nothing can tell when they go stale:\n"
        + "\n".join(f"  {r}:{n}  cites {c}" for r, n, c in unregistered)
        + "\n\nAdd each with a short distinctive string its cited range must "
        "still contain — or drop the line number and cite by name."
    )


def test_no_registered_citation_has_gone_stale():
    """The check itself: the cited range must still contain its anchor."""
    discovered = {
        (rel, cite): (matches[0], s, e)
        for rel, _, cite, matches, s, e, _t in _resolved_citations()
    }
    stale, vanished = [], []
    for (rel, cite), anchor in sorted(CITATION_ANCHORS.items()):
        if (rel, cite) not in discovered:
            vanished.append(f"  {rel} no longer cites {cite}")
            continue
        target, start, end = discovered[(rel, cite)]
        lines = (REPO_ROOT / target).read_text(encoding="utf-8").splitlines()
        if _staleness(anchor, start, end, lines):
            where = [
                i + 1 for i, l in enumerate(lines) if anchor in l
            ]
            stale.append(
                f"  {rel} cites {cite}, but {anchor!r} is not in that range"
                + (f" — it is now at line(s) {where}" if where else " (gone entirely)")
            )
    assert not stale, (
        "stale intra-repo citations — a reader following these lands on the "
        "wrong lines:\n" + "\n".join(stale)
    )
    assert not vanished, (
        "CITATION_ANCHORS registers citations the sweep no longer finds; the "
        "registry has gone stale against the tree:\n" + "\n".join(vanished)
    )


def _staleness(anchor, cited_start, cited_end, file_lines):
    """The range check, extracted so a control can exercise the REAL path.

    Kept as one function used by both the test above and the controls below.
    The first draft's control re-implemented the slice inline and therefore
    tested nothing: widening the real check to read the whole file left it
    green, which the author-side battery demonstrated.
    """
    window = "\n".join(file_lines[cited_start - 1:cited_end])
    return anchor not in window


def test_the_anchor_check_detects_a_planted_drift():
    """Positive control. `assert not stale` passes identically when broken.

    Reproduces the real defect in miniature: text is hoisted out of a cited
    range and the citation is not updated. It must ALSO stay red when the
    anchor is still elsewhere in the file — that is the whole point of a range.
    """
    before = ["a", "b", "HAZARD text here", "c"]
    assert not _staleness("HAZARD", 3, 3, before), "control setup is wrong"

    after = ["x", "y", "z", "a", "b", "HAZARD text here", "c"]
    assert _staleness("HAZARD", 3, 3, after), (
        "POSITIVE CONTROL FAILED: text was hoisted out of the cited range and "
        "the check still reported it present — most likely because the window "
        "is no longer the cited RANGE but the whole file, which makes every "
        "citation permanently fresh. Every 'no stale citations' result in this "
        "module is worthless until this passes."
    )


def test_the_registration_check_fires_on_an_unregistered_citation():
    """Positive control for the population half.

    `assert not unregistered` passes vacuously today because every citation is
    registered — so disabling the check entirely is invisible without this.
    """
    fake = [("core/skills/fake/SKILL.md", 12, "self_check.sh:1-2", "x", 1, 2)]
    assert _unregistered(fake), (
        "POSITIVE CONTROL FAILED: an unregistered citation was not reported. "
        "The registration check has been disabled, and a new `file:NN` "
        "citation can now be added with nothing able to tell when it breaks."
    )


def test_the_anchor_check_has_no_slop():
    """LOW round finding: `_staleness` with +1 line of slack survived.

    A range check that quietly reads one line either side tolerates exactly the
    drift it exists to catch, and reports nothing.
    """
    lines = ["a", "ANCHOR", "c"]
    assert not _staleness("ANCHOR", 2, 2, lines), "control setup is wrong"
    assert _staleness("ANCHOR", 1, 1, lines), (
        "the range check reads beyond the cited range; a citation one line off "
        "now passes, which is the drift this module exists to detect"
    )
    assert _staleness("ANCHOR", 3, 3, lines), (
        "the range check reads beyond the cited range in the other direction"
    )


def test_each_scope_root_contributes_files():
    """LOW round finding: dropping `packs` or `install.sh` from SCOPE_ROOTS survived."""
    files = _scanned_files()
    for needle in (
        "core/skills/review-close/SKILL.md",
        "core/companion/scripts/claim_task.sh",
        "docs/one-rule.md",
        "install.sh",
    ):
        assert needle in files, (
            f"{needle} is no longer swept for citations; a SCOPE_ROOTS entry "
            "has been dropped and the population is short without saying so"
        )
    assert any(f.startswith("packs/") for f in files), (
        "no packs/ file is swept for citations; SCOPE_ROOTS has lost `packs`"
    )
    # Round finding M7: the declared surface said docs/** while the code
    # dropped the two published HTML pages.
    assert "docs/workflow.html" in files and "docs/index.html" in files, (
        "the published monograph and landing page are no longer swept; "
        "SCANNED_SUFFIXES has lost `.html` while the docstring still claims "
        "the whole of docs/**"
    )
    assert "README.md" in files, "README.md has dropped out of SCOPE_ROOTS"


def _unknown_unresolved(citations):
    """Extracted so a control exercises the REAL predicate (round finding M3)."""
    unknown = {}
    for rel, lineno, _cite, matches, _s, _e, target in citations:
        if matches or target in UNRESOLVED_ALLOWED:
            continue
        unknown.setdefault(target, []).append(f"{rel}:{lineno}")
    return unknown


def test_the_unresolved_check_fires_on_a_planted_dangling_pointer():
    """The tree has no unknown-unresolved citation, so the check passes
    vacuously and disabling it is invisible without this."""
    planted = [("core/skills/fake/SKILL.md", 3, "gone.sh:4", [], 4, 4, "gone.sh")]
    assert _unknown_unresolved(planted), (
        "POSITIVE CONTROL FAILED: a citation to a nonexistent file was not "
        "reported. A pointer to a deleted or renamed file now reads clean."
    )
    benign = [("core/skills/fake/SKILL.md", 3, "foo.py:4", [], 4, 4, "foo.py")]
    assert not _unknown_unresolved(benign), (
        "NEGATIVE CONTROL FAILED: a baselined placeholder was reported."
    )


def _ambiguous_registered(citations):
    """Extracted so a control exercises the REAL predicate (round finding M6)."""
    return [
        f"  {rel}:{lineno} cites {cite} -> {len(matches)} files: {matches[:3]}"
        for rel, lineno, cite, matches, _s, _e, _t in citations
        if len(matches) > 1 and (rel, cite) in CITATION_ANCHORS
    ]


def test_the_ambiguity_check_fires_on_a_planted_ambiguous_citation():
    """No registered citation is ambiguous today, so this passes vacuously."""
    key = next(iter(CITATION_ANCHORS))
    rel, cite = key
    planted = [(rel, 1, cite, ["a/SKILL.md", "b/SKILL.md"], 1, 1, "SKILL.md")]
    assert _ambiguous_registered(planted), (
        "POSITIVE CONTROL FAILED: a registered citation resolving to two files "
        "was not reported. Its anchor would be validated against an arbitrary "
        "one, permanently and silently."
    )


def test_the_registry_is_not_empty():
    """Vacuity control. An emptied registry makes the staleness check silent."""
    assert len(CITATION_ANCHORS) >= 8, (
        f"CITATION_ANCHORS holds {len(CITATION_ANCHORS)} entries; the registry "
        "has been emptied and no citation in the acting surface is pinned"
    )


def test_foreign_citations_are_excluded_by_marker_not_by_luck():
    """Negative control for the gdp carve-out.

    `docs/analysis/REPORT.md` quotes gdp's own `codebase-review/SKILL.md:304`,
    whose basename collides with ours. Without the marker filter the sweep
    demands an anchor for a line in a repo this one does not ship — a guard
    crying wolf, which is how blanket exemptions get written.
    """
    line = "(gdp `codebase-review/SKILL.md:304`, `WORKFLOW.md:542`) — and nothing in it"
    for m in CITATION.finditer(line):
        assert _is_foreign(line, m.start()), (
            f"the real REPORT.md provenance line's citation {m.group(0)!r} is no "
            "longer recognised as foreign, so a gdp-side line number would be "
            "demanded of this repo"
        )

    plain = "see codebase-review/SKILL.md:304 for the dispatch rule"
    for m in CITATION.finditer(plain):
        assert not _is_foreign(plain, m.start()), (
            "an ordinary intra-repo citation is being treated as foreign, which "
            "silently drops it from the sweep"
        )

    # The line-scoped form's exact failure: marker AFTER the citation.
    trailing = "See `core/companion/scripts/self_check.sh:12` (the gdp backport)."
    for m in CITATION.finditer(trailing):
        assert not _is_foreign(trailing, m.start()), (
            "a trailing 'gdp' mention still removes the citation before it. The "
            "filter has gone LINE-scoped again — the Pass-1a defect, one module "
            "over, and it takes the citation out of the sweep entirely."
        )


# ── The shape this guard structurally could not see (Phase 211) ────────

BARE_SELF_CITATION = re.compile(r"\(`:\d+(?:-\d+)?`")


def test_no_citation_is_written_as_a_bare_line_number():
    """A `` (`:855-857`) `` self-citation is invisible to CITATION above.

    `CITATION` requires a *filename* token before the colon, so a file citing
    its own lines by number alone is swept by nothing — not registered, not
    checked for staleness, not reported as unregistered. `close_batch.sh`
    carried exactly one, pointing at `:763-765` for a rule that on the tree
    carrying the stale pointer sat at `:832-836`: a ~70-line drift, in a comment
    whose whole job was to justify a control-flow decision by quoting that rule.
    (A first draft of this docstring said 90 lines, measured against the rule's
    position AFTER this phase's own edits rather than on the tree where the
    pointer was stale. Measuring a historical drift against the present tree
    inflates it; the round caught that.)

    Derived over the shipped tree rather than assumed: the sweep found one
    instance, and this guard exists so a second cannot arrive quietly. The fix
    is always the same and always cheap — write the filename, which puts the
    citation under `CITATION_ANCHORS` and under the staleness check with it.
    """
    offenders = []
    for rel in _scanned_files():
        text = (REPO_ROOT / rel).read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if BARE_SELF_CITATION.search(line):
                offenders.append(f"  {rel}:{n}  {line.strip()[:90]}")
    assert not offenders, (
        "these cite line numbers with no filename, so nothing sweeps them for "
        "staleness:\n" + "\n".join(offenders) +
        "\n\nWrite the filename (`foo.sh:123-125`) and register an anchor."
    )


def test_the_bare_self_citation_pattern_would_catch_one():
    """Non-vacuity control: the guard above passes because the tree is clean,
    not because its pattern matches nothing.

    Without this, deleting `BARE_SELF_CITATION`'s body to `re.compile("$^")`
    leaves the suite green over a guard that can never fire.
    """
    assert BARE_SELF_CITATION.search("  # is to report and continue (`:763-765`: annotation")
    assert BARE_SELF_CITATION.search("see (`:855-857`)")
    assert not BARE_SELF_CITATION.search("see (`close_batch.sh:855-857`)")
    assert not BARE_SELF_CITATION.search("a plain :123 with no backticks")
