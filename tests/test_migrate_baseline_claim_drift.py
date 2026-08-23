"""`Q-258` — the shipped `--migrate-baseline` prose, pinned to the code.

**What went wrong.** `baseline.py` retired an all-or-nothing refusal in favour
of per-check holds. Three shipped sites went on describing the retired form —
`WORKFLOW.md`, a `baseline.py` docstring, and `cli.py`'s `--migrate-baseline`
help — and `git grep` over `tests/` found no guard referencing any of that
wording. They were corrected by hand; nothing stopped them drifting again, and
Phase 225's verification pass then found **three more** shipped sites saying the
same retired thing, one of them in a test module that ships to the public repo.

**Why it is worse than ordinary doc drift.** The sentence *inverts a safety
property*. A consumer told "the whole migration refuses" reads a non-refusing
exit-0 run as a complete migration — when in fact entries whose check did not
execute are silently **held**: still two-field, still not suppressing, and the
run exits 0 either way. The false version is the reassuring one.

**Scope, deliberately narrow.** The general form — "no shipped file claims a
condition the code does not implement" — is unbounded and undecidable. This
module takes the tractable slice the entry names: the *baseline verbs*, and one
predicate (`held == entry_checks`). It asks a yes/no question with no judgment
in it — does a shipped sentence about `--migrate-baseline` refusing also say
*when* it refuses — and it is allowed to be exactly that small.
"""
import ast
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PY = REPO_ROOT / "core/companion/scripts/run_checks/baseline.py"

# Files free to quote the retired claim, because recording that it WAS said is
# their job. Matched by name against `git ls-files` output — never opened, and
# never built into a path, so this module stays clear of the mirror-skip rule.
_RECORD_FILES = {
    "PHASE_LOG.md", "REVIEW_CHECKLIST.md", "REVIEW_ARCHIVE.md", "CLAUDE.md",
    # This module. Its own docstring quotes the claim shape it hunts for, so it
    # flags itself — and it did NOT while it was untracked, because `git
    # ls-files` cannot see an uncommitted file. That is the nastier half: the
    # guard was green for its whole authoring life and went red at the commit
    # that shipped it. Caught by running the suite inside the sterilized mirror,
    # which is the run that would otherwise have reddened the public snapshot's
    # required `pytest` check.
    "tests/test_migrate_baseline_claim_drift.py",
}

# The FLAG form only. `the migration` was tried and withdrawn: it swept in
# past-tense narration of the bug that WAS fixed ("a degraded semgrep run made
# the migration refuse outright") at two sites. That is a true sentence about
# history, and history is not a claim about shipped behaviour.
_FLAG = re.compile(r"--migrate-baseline")
# A sentence naming some OTHER `--flag` and not this one is about that command.
# Without this, `WORKFLOW.md`'s true sentence about `--update-baseline` refusing
# was reported as an unconditional claim about the migration.
_OTHER_FLAG = re.compile(r"--(?!migrate-baseline)[a-z][a-z-]+")
_REFUSAL = re.compile(r"\brefus\w*", re.I)
# Deliberately NOT a bare `every`. The first cut used one, and `WORKFLOW.md`'s
# section satisfied it on the words "preserves every comment" — a check
# satisfied by an INCIDENTAL use of its own token is worse than a gap, because
# it marks the dangerous text compliant.
# `per[- ]check` was a member until a round showed it is satisfied incidentally:
# "`--migrate-baseline` refuses the whole run as soon as one per-check skip
# appears" scored compliant. That is the identical defect as the bare `every`
# this module already has a control for — a qualifier satisfied by a phrase that
# can sit inside the FALSE claim. Every surviving member names the *population*,
# which the false claim cannot do and stay false.
_QUALIFIER = re.compile(
    r"every baselined check|all baselined checks|nothing (?:it )?could convert|"
    r"nothing to convert|nothing could be migrated",
    re.I,
)

# Sentences that mention the refusal without asserting its condition and are
# correct as written. Permitted BY THEIR TEXT, and
# test_every_permitted_sentence_is_still_in_the_tree keeps the list from
# outliving its subject — a permit that has lost its sentence is a hole.
_PERMITTED = (
    "A refusal keyed to `non_executed_ids` would refuse the baseline write on "
    "every fresh install, and would remove the documented escape from a "
    "`--migrate-baseline` refusal",
)


def _shipped_text_files():
    """The population, derived from git rather than from a list in this file."""
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=REPO_ROOT,
        capture_output=True, text=True, check=True,
    ).stdout
    keep = []
    for rel in (p for p in out.split("\0") if p):
        if rel in _RECORD_FILES or rel.startswith("tools/"):
            continue
        if rel.endswith((".md", ".py", ".sh", ".html", ".txt")):
            keep.append(rel)
    return keep


def _source_prose(text):
    """Docstrings, comments, and CLI help strings — the parts of source that
    make claims to a reader.

    Code is not a claim: the first cut swept whole files and an ordinary
    `rows, refusal = baseline.migrate_baseline(...)` fixture read as a shipped
    assertion about behaviour.

    **`help=` is here because a round found the guard blind to the site it was
    built for.** `cli.py`'s `--migrate-baseline` help text is one of the three
    that carried the retired claim — this module's own docstring says so — and
    it is a plain keyword argument, not a docstring or a comment. Planting the
    retired falsehood there left the guard green. It is also the single most
    consumer-facing sentence in the set: it is what `--help` prints.

    `ast` rather than a regex, so implicit concatenation across lines (which is
    how argparse help is usually written) is recovered whole.
    """
    parts = re.findall(r'"""(.*?)"""', text, re.S)
    parts += re.findall(r"(?m)^\s*#(.*)$", text)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return parts
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg in ("help", "description", "epilog") and isinstance(
                    kw.value, ast.Constant) and isinstance(kw.value.value, str):
                parts.append(kw.value.value)
    return parts


def _unqualified_claims(rel, text):
    """Refusal statements about this command that never say WHEN it refuses.

    **The two dialects get different scopes, and both were measured.**

    *Docs* (`.md`/`.txt`/`.html`) are read by SECTION. Paragraph scope was tried
    and a control killed it: the retired sentence can sit in a paragraph that
    never repeats the flag name — one reformat from how `WORKFLOW.md` reads
    today — and a paragraph reader called that decoy compliant.

    *Source prose* is read by SENTENCE. Section scope was tried there too and
    was far too coarse: a docstring long enough to mention the flag also
    contains `Returns (rows, refusal).`, and every such line was reported.
    Docstrings state this claim in one sentence; docs spread it over several.
    """
    out = []
    if rel.endswith((".md", ".txt", ".html")):
        body = re.sub(r"(?ms)^```.*?^```", "", text)
        units = []
        for section in re.split(r"(?m)^#{1,6} ", body):
            if _FLAG.search(section):
                units += re.split(r"(?<=[.!?])\s+", " ".join(section.split()))
    else:
        units = []
        for chunk in _source_prose(text):
            for sent in re.split(r"(?<=[.!?])\s+", " ".join(chunk.split())):
                if _FLAG.search(sent):
                    units.append(sent)
    for sent in units:
        if not _REFUSAL.search(sent):
            continue
        if _OTHER_FLAG.search(sent) and not _FLAG.search(sent):
            continue
        if _QUALIFIER.search(sent):
            continue
        # Permits match the WHOLE normalised sentence, not a substring of it. A
        # round appended a false condition to a permitted sentence and the
        # permit swallowed the whole thing — an exemption list that matches
        # substrings exempts every sentence that quotes one.
        if any(permit == sent.strip().rstrip(".") for permit in _PERMITTED):
            continue
        out.append(sent)
    return out


def test_no_shipped_file_claims_an_unconditional_migrate_baseline_refusal():
    """The sweep. Population derived from `git ls-files`, not from a list."""
    files = _shipped_text_files()
    assert len(files) > 200, (
        f"only {len(files)} shipped text files; this sweep would be reporting "
        "on almost nothing"
    )
    offenders = {}
    # Counted, not assumed. A battery replaced this loop's population with an
    # empty list and the assertion below was satisfied by construction — the
    # shape a reviewer has twice demonstrated on this repo's guards.
    scanned = 0
    for rel in files:
        try:
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        bad = _unqualified_claims(rel, text)
        if bad:
            offenders[rel] = bad
    assert scanned > 200, (
        f"only {scanned} files were actually read (of {len(files)} derived); "
        "the sweep is reporting on a filtered population"
    )
    # And the predicate must still be alive on the file that carries the claim.
    subject = REPO_ROOT / "core/companion/docs/WORKFLOW.md"
    assert _FLAG.search(subject.read_text(encoding="utf-8")), (
        "WORKFLOW.md no longer names `--migrate-baseline`; this sweep's "
        "principal subject has moved and the guard is looking at nothing"
    )
    assert not offenders, (
        "shipped file(s) describe `--migrate-baseline` refusing without saying "
        "WHEN it refuses. The shipped behaviour is per-check holds; it refuses "
        "outright only when EVERY baselined check failed to execute. An "
        "unqualified sentence inverts a safety property — a consumer reads a "
        "non-refusing exit-0 run as a complete migration.\n\n"
        + "\n\n".join(f"--- {rel} ---\n{bad[0][:400]}" for rel, bad in offenders.items())
    )


def test_the_code_still_implements_the_condition_the_prose_states():
    """The other half. A guard on prose alone drifts the moment the code moves.

    Both directions matter: prose can go stale against the code, and the code
    can be "simplified" back to the all-or-nothing form that made the upgrade
    path a dead end. This pins the predicate the prose promises.
    """
    src = BASELINE_PY.read_text(encoding="utf-8")
    # Keyed to the SHAPE, not to the local's name. A round renamed `held`
    # throughout the function — a behaviour-preserving refactor — and this
    # reddened, which is over-strictness in the direction that gets a correct
    # guard deleted. The invariant is "a set intersected with skipped_ids, and a
    # refusal conditioned on that set being the whole population".
    m = re.search(r"(\w+) = entry_checks & set\(skipped_ids\)", src)
    assert m, (
        "`migrate_baseline` no longer computes the held set per check — every "
        "shipped sentence about holding entries is now false"
    )
    held_name = m.group(1)
    assert re.search(rf"if entry_checks and {held_name} == entry_checks:", src), (
        "the refusal is no longer conditioned on `held == entry_checks`. If it "
        "now refuses on ANY skip, the upgrade path is a dead end again (that "
        "regression is why the condition exists) and every shipped 'holds, not "
        "drops' sentence is false."
    )
    assert "every baselined check did not execute" in src, (
        "the refusal message no longer names its own condition; a consumer who "
        "hits it cannot tell it apart from a per-check hold"
    )


def test_the_sweep_catches_the_sentence_it_was_written_for():
    """Positive control, using the exact retired wording from the record.

    Without this the sweep passes just as well with a broken predicate — and a
    predicate that matches nothing is the failure mode this repo keeps paying
    for.
    """
    retired = (
        "Converting an existing baseline: `--migrate-baseline`, once. It rewrites "
        "in place and preserves every comment. If a baselined check did not "
        "execute this run, the whole migration refuses and nothing is written."
    )
    # `every comment` sits in the window, so the qualifier cannot be a bare word
    # match — it has to be the retired claim's own shape that fails.
    assert _unqualified_claims("docs/x.md", retired.replace("every comment", "each comment")), (
        "the retired all-or-nothing sentence does not trip the sweep; the "
        "predicate has stopped matching and the guard is decorative"
    )


def test_naming_a_second_command_is_not_an_escape_hatch():
    """The other-flag exclusion must drop only sentences about OTHER commands.

    It exists because `WORKFLOW.md` has a true sentence about `--update-baseline`
    refusing, inside the section that names this flag. Widening it to "drop any
    sentence mentioning another flag" is a one-token edit that turns it into an
    escape hatch — and a battery made exactly that edit and survived, because no
    real sentence happens to name both.
    """
    both = (
        "`--migrate-baseline` refuses the whole run as soon as one baselined "
        "check is skipped, unlike `--update-baseline`."
    )
    assert _unqualified_claims("docs/x.md", both), (
        "a false claim about `--migrate-baseline` escaped by also naming "
        "`--update-baseline`. The exclusion is for sentences about a DIFFERENT "
        "command, not for any sentence that mentions one."
    )
    # The real shape: the flag names the SECTION, and a later sentence is about a
    # different command. The first draft of this control put both flags in one
    # sentence, which is not the case the exclusion is for — and it failed,
    # correctly. Kept as written because getting it wrong is the easy mistake.
    only_other = (
        "Converting an existing baseline uses `--migrate-baseline`, once. "
        "`--update-baseline` refuses when a blocking check failed, because a "
        "crashed tool is not a state to snapshot."
    )
    assert not _unqualified_claims("docs/x.md", only_other), (
        "a true sentence about another command is reported; the exclusion has "
        "stopped working in the direction it was written for"
    )


def test_the_sweep_accepts_the_shipped_wording():
    """Negative control. Over-strictness is the direction that gets a guard deleted."""
    for good in (
        "Entries belonging to a check that did not execute this run are held, not "
        "dropped. The migration refuses outright only when every baselined check "
        "failed to execute, since then there is nothing it could convert.",
        "`--migrate-baseline` converts your entries in place and keeps your comments.",
        "The whole migration refuses only when EVERY baselined check is in "
        "`skipped_ids`, because then there is nothing to convert.",
    ):
        assert not _unqualified_claims("docs/x.md", good), (
            f"the sweep rejects correct shipped wording: {good!r}"
        )


def test_every_permitted_sentence_is_still_in_the_tree():
    """A permit that outlives its sentence is a hole nobody can see.

    The exemption list is the only judgment in this module, so it is the part
    that has to shrink on its own. If the sentence a permit was written for is
    reworded or deleted, the permit stays behind and silently excuses whatever
    later text happens to contain the same words.
    """
    corpus = ""
    for rel in _shipped_text_files():
        try:
            corpus += (REPO_ROOT / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
    flat = " ".join(corpus.split())
    dead = [p for p in _PERMITTED if p not in flat]
    # An exemption that no longer matches its sentence EXACTLY is also dead —
    # the permit is now whole-sentence, so a reworded sentence silently stops
    # being exempt (correct) while the permit lingers (not).
    assert not dead, (
        f"permitted sentence(s) no longer in the shipped tree: {dead}. Delete "
        "the entry — it now excuses text nobody wrote on purpose."
    )


def test_the_qualifier_is_not_satisfied_by_an_incidental_word():
    """The exact over-match the first cut shipped with.

    `WORKFLOW.md`'s paragraph says "preserves every comment" three sentences
    before it says anything about refusing. A bare `every` in the qualifier made
    that paragraph compliant no matter what the refusal sentence claimed.
    """
    decoy = (
        "**Converting an existing baseline: `--migrate-baseline`, once.** It "
        "rewrites in place and preserves every comment.\n\nIf a baselined check "
        "did not execute, the whole migration refuses and nothing is written."
    )
    assert _unqualified_claims("docs/x.md", decoy), (
        "an incidental `every` elsewhere in the section satisfies the "
        "qualifier — the guard marks the false claim compliant"
    )
    # The sharper case, and the one the first version of this control missed:
    # the incidental word inside the FALSE SENTENCE ITSELF. A battery loosened
    # the qualifier to a bare `\bevery\b` and walked through, because the decoy
    # above happens not to contain the word in its refusal sentence.
    same_sentence = (
        "`--migrate-baseline` refuses as soon as one baselined check is "
        "skipped, dropping every entry it could not convert."
    )
    assert _unqualified_claims("docs/x.md", same_sentence), (
        "a FALSE refusal sentence carrying an incidental `every` is accepted. "
        "The qualifier must name the condition (`every baselined check`), not "
        "match any occurrence of a word that appears in it."
    )


def test_cli_help_strings_are_in_the_swept_population():
    """The site a round found blind, pinned so it cannot go blind again.

    Not a reversion guard on the wording — a reachability guard on the
    EXTRACTOR. Deleting the `help=` arm of `_source_prose` leaves every other
    test in this module green.
    """
    cli = REPO_ROOT / "core/companion/scripts/run_checks/cli.py"
    src = cli.read_text(encoding="utf-8")
    prose = "\n".join(_source_prose(src))
    assert "--migrate-baseline" in prose, (
        "cli.py's help text is not in the swept prose; the `help=` extraction "
        "has stopped working and the most consumer-facing statement of this "
        "claim — what `--help` prints — is unguarded"
    )
    planted = src.replace(
        'if not os.path.exists(baseline_file):',
        'if not os.path.exists(baseline_file):  # noqa', 1)
    planted = planted.replace(
        'help="', 'help="If any baselined check did not execute, '
                  '--migrate-baseline refuses the whole run. ', 1)
    assert _unqualified_claims("core/companion/scripts/run_checks/cli.py", planted), (
        "the retired all-or-nothing claim planted in a `help=` string is not "
        "caught; the extraction reaches the text but the predicate does not"
    )


def test_a_permit_does_not_exempt_a_sentence_that_merely_quotes_it():
    """The substring escape a round found, closed.

    `_PERMITTED` matched as a substring, so appending a false condition to a
    permitted sentence carried the exemption along with it. Permits are
    whole-sentence now.
    """
    permitted = _PERMITTED[0]
    assert not _unqualified_claims("docs/x.md", permitted + "."), (
        "the permitted sentence itself is reported; the permit no longer matches"
    )
    hijacked = (
        permitted + " — and it refuses the entire migration the moment a single "
        "baselined check is skipped."
    )
    assert _unqualified_claims("docs/x.md", hijacked), (
        "a false condition appended to a permitted sentence inherits its "
        "exemption; the permit is matching a substring again"
    )


def test_the_qualifier_is_not_satisfied_by_per_check_inside_the_false_claim():
    """`per-check` was a qualifier until a round put it inside the false claim."""
    sneaky = (
        "`--migrate-baseline` refuses the whole run as soon as one per-check "
        "skip appears."
    )
    assert _unqualified_claims("docs/x.md", sneaky), (
        "a false refusal claim containing the words `per-check` is scored "
        "compliant — the same incidental-token defect as the bare `every`"
    )
