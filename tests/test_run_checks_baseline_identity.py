"""Phase 213 — the baseline key identifies the finding, not just its position.

Four filed defects, one root cause. A key of `check_id|path:line` means
*"whatever this check reports here"*, so an accepted entry excuses a finding
nobody accepted:

  * position (`Q-190`) — edit the accepted line and the entry excuses whatever
    replaces it. On `grant-sensitive-table` (`blocking: true`, `severity:
    critical`) that is a live finding printed `[baseline]` with the gate at
    exit 0.
  * identity, pip-audit (`Q-245`) — the anchor is constant for a whole run, so
    ONE accepted advisory excuses every CVE in the project, for ever.
  * identity, catch-all ids (`Q-246`) — `lint-error` is one id for the whole
    ESLint stage; `tsc-type-error` and `pyright-general-warning` are the same
    shape and were filed nowhere.
  * the false precedent (`Q-247`) — `baseline.py` justified the coverage
    carve-out with a mechanism (`diff-relative` line numbers) that is not true.

The CLI-level tests here drive `run_checks_impl.main()` against a real fixture
tree rather than asserting on source, because every claim above is a property of
what the gate *does*. `tests/test_run_checks_baseline.py` owns baseline I/O and
the internal-tracker-#363 contract; this module owns the identity key.
"""
import re
import subprocess
import sys
from pathlib import Path

import run_checks.baseline as baseline
import run_checks_impl as rci

# The shipped critical/blocking check, copied from packs/postgres so the test
# exercises a REAL registry entry rather than a convenient invention: the
# defect's whole weight is that it lands on a gate someone relies on.
_GRANT_YML = """\
checks:
  - id: grant-sensitive-table
    severity: critical
    blocking: true
    paths: ["migrations/"]
    include: ["*.sql"]
    pattern: 'GRANT[[:space:]]+[A-Z, ]+[[:space:]]+ON[[:space:]]+[a-z_]+[[:space:]]+TO'
    description: "GRANT on sensitive PII table."
    used_by: [codebase-review, security-audit]
"""

_ACCEPTED = "GRANT UPDATE ON payments TO app_writer;\n"
_NEVER_REVIEWED = "GRANT ALL PRIVILEGES ON users TO app_reader;\n"


def _tree(tmp_path, body=_ACCEPTED):
    (tmp_path / ".claude").mkdir(exist_ok=True)
    (tmp_path / ".claude" / "checks.yml").write_text(_GRANT_YML)
    (tmp_path / "migrations").mkdir(exist_ok=True)
    (tmp_path / "migrations" / "001.sql").write_text("-- header\n" + body)
    return tmp_path


def _run(tmp_path, monkeypatch, *extra):
    monkeypatch.setattr(sys, "argv", ["run_checks", "--repo-root", str(tmp_path),
                                      "--mode", "both", *extra])
    try:
        rci.main()
    except SystemExit as e:
        return e.code if e.code is not None else 0
    return 0


# ── Q-190: the position failure, end to end on the real gate ────────────────


def test_editing_an_accepted_line_no_longer_clears_the_critical_gate(
        tmp_path, monkeypatch, capsys):
    """The reproduction, and the assertion that it is closed.

    Against the pre-Phase-213 runner this exact sequence printed
    `[baseline] … CRITICAL` and exited **0** over a GRANT nobody had reviewed.
    """
    _tree(tmp_path)
    assert _run(tmp_path, monkeypatch, "--update-baseline") == 0
    capsys.readouterr()

    # Same line number, different statement, different table, different role.
    (tmp_path / "migrations" / "001.sql").write_text("-- header\n" + _NEVER_REVIEWED)
    code = _run(tmp_path, monkeypatch, "--fail-on-blocking")
    out = capsys.readouterr().out

    assert code == 1, "a never-reviewed CRITICAL finding must fail the gate"
    assert "[baseline]" not in out, out
    assert "app_reader" not in out  # the message cites the check, not the line
    assert "CRITICAL migrations/001.sql:2" in out


def test_the_accepted_statement_itself_still_suppresses(tmp_path, monkeypatch, capsys):
    """The other half: the fix must not make the baseline useless.

    Without this, "nothing is ever suppressed" would pass the test above.
    """
    _tree(tmp_path)
    _run(tmp_path, monkeypatch, "--update-baseline")
    capsys.readouterr()
    code = _run(tmp_path, monkeypatch, "--fail-on-blocking")
    assert code == 0
    assert "[baseline]" in capsys.readouterr().out


def test_a_reindent_does_not_invalidate_an_accepted_entry(tmp_path, monkeypatch, capsys):
    """Normalization is strip + whitespace-collapse, and it earns its keep here.

    A `black` run, a re-indent or a trailing-space fix must not re-fire every
    accepted finding in the file — that noise is what would get the identity
    field switched off.
    """
    _tree(tmp_path)
    _run(tmp_path, monkeypatch, "--update-baseline")
    capsys.readouterr()
    (tmp_path / "migrations" / "001.sql").write_text(
        "-- header\n    GRANT   UPDATE  ON payments TO app_writer;   \n"
    )
    assert _run(tmp_path, monkeypatch, "--fail-on-blocking") == 0
    assert "[baseline]" in capsys.readouterr().out


def test_a_moved_accepted_line_refires_rather_than_excusing_its_replacement(
        tmp_path, monkeypatch, capsys):
    """Under-suppression is the safe direction and stays loud.

    The filing framed Q-190 as line drift; drift is actually the harmless case,
    because the displaced finding re-fires at its new line. The dangerous case
    is the in-place edit above. Both are asserted so neither is "fixed" by
    accident later.
    """
    _tree(tmp_path)
    _run(tmp_path, monkeypatch, "--update-baseline")
    capsys.readouterr()
    (tmp_path / "migrations" / "001.sql").write_text(
        "-- header\n-- a new comment line\n" + _ACCEPTED
    )
    assert _run(tmp_path, monkeypatch, "--fail-on-blocking") == 1
    assert "migrations/001.sql:3" in capsys.readouterr().out


# ── Q-245 / Q-246: the identity failures, at the unit the CLI cannot reach ──


def test_one_pip_audit_entry_no_longer_swallows_every_cve():
    """`pip_audit.py` computes its anchor ONCE, outside the vuln loop.

    So every vulnerability in a run shared `pip-audit-vuln|requirements.txt:1`
    and accepting one advisory as tech debt accepted all of them — including a
    critical RCE on an unrelated package, disclosed later. Content-hashing
    could not have fixed it: the "matched line" is line 1 of requirements.txt.
    """
    accepted = {baseline.finding_key("pip-audit-vuln", "requirements.txt:1",
                                     "GHSA-old")}
    assert baseline.is_baseline_suppressed(
        "pip-audit-vuln", "requirements.txt:1", set(), accepted, "GHSA-old")
    assert not baseline.is_baseline_suppressed(
        "pip-audit-vuln", "requirements.txt:1", set(), accepted, "CVE-9999-RCE")


def test_the_catch_all_ids_each_discriminate():
    """`lint-error` was filed; `tsc-type-error` and `pyright-general-warning`
    are the same defect and were filed nowhere.

    Each is one check id for a whole stage, with the real discriminator parsed
    at the emit site and dropped into the message. `Q-246` named one. There are
    **four** such ids, not three — `pip-audit-vuln` is the fourth, and it is
    covered by its own test above because its anchor is constant too. Saying
    "three" was this phase's own version of the `Q-061` superlative trap, and it
    shipped in a note whose purpose was warning the next session off that trap.
    """
    for check_id, accepted_id, other_id in (
        ("lint-error", "no-unused-vars", "no-new-func"),
        ("tsc-type-error", "TS2322", "TS2551"),
        ("pyright-general-warning", "reportOptionalMemberAccess",
         "reportPrivateUsage"),
    ):
        accepted = {baseline.finding_key(check_id, "src/a.ts:7", accepted_id)}
        assert baseline.is_baseline_suppressed(
            check_id, "src/a.ts:7", set(), accepted, accepted_id), check_id
        assert not baseline.is_baseline_suppressed(
            check_id, "src/a.ts:7", set(), accepted, other_id), check_id


# ── the key itself ──────────────────────────────────────────────────────────


def test_a_legacy_two_field_entry_does_not_suppress_an_identity_finding():
    """No load-time fallback, and that is the design rather than an oversight.

    A fallback would keep the legacy entry meaning "whatever this check finds
    here" — the defect — permanently, and only for the baselines that already
    have it, which is the entire affected population.
    """
    legacy = {"grant-sensitive-table|migrations/001.sql:2"}
    assert not baseline.is_baseline_suppressed(
        "grant-sensitive-table", "migrations/001.sql:2", set(), legacy, "abc123")


def test_identity_of_is_empty_for_blank_content():
    """The empty case is defined rather than left to produce `check|line|`.

    No shipped grep pattern can match a blank line, but `checks.project.yml` is
    the promotion write target, so a consumer-authored one can — and a single
    check emitting both key arities is the ambiguity the two-field form exists
    to avoid.
    """
    assert baseline.identity_of("") == ""
    assert baseline.identity_of("   \t \n ") == ""
    assert baseline.finding_key("c", "a.py:1", baseline.identity_of("  ")) == "c|a.py:1"


def test_identity_is_stable_across_whitespace_but_not_across_content():
    assert baseline.identity_of("x = 1") == baseline.identity_of("   x   =  1  ")
    assert baseline.identity_of("x = 1") != baseline.identity_of("x = 2")


def test_normalization_covers_every_whitespace_kind_not_just_spaces():
    """Every whitespace kind, not just the space character.

    A tab re-indent, a CRLF or a form feed is the same class as a space
    re-indent. Narrowing the normalization class to spaces survived an
    independent battery, because every existing case used spaces.
    """
    base = baseline.identity_of("x = 1")
    for variant in ("\tx\t=\t1", "x \t = \t 1", "  x = 1\r", "x\x0c=\x0c1"):
        assert baseline.identity_of(variant) == base, repr(variant)


# ── the migration ───────────────────────────────────────────────────────────


def _mig(tmp_path, lines, findings, skipped=()):
    p = tmp_path / "b.txt"
    p.write_text("".join(lines))
    rows, refusal = baseline.migrate_baseline(
        str(p), findings, str(tmp_path), skipped)
    return rows, refusal, p.read_text()


def test_migration_preserves_hand_written_rationale(tmp_path):
    """The reason it is not built on load_baseline/write_baseline.

    A real consumer baseline is ~70% comment — signed-off triage rationale that
    the file itself and the project's CLAUDE.md both treat as durable
    documentation. A load/write round-trip drops every line of it.
    """
    rows, refusal, body = _mig(
        tmp_path,
        ["# Format: check_id|path:line  (one per line)\n",
         "\n",
         "# accepted 2026-08-14: app_writer is the ETL role, reviewed in the PR\n",
         "grant-x|m.sql:2\n"],
        [("grant-x", "m.sql:2", "msg", "deadbeef")],
    )
    assert refusal is None
    assert "# accepted 2026-08-14: app_writer is the ETL role" in body
    assert "grant-x|m.sql:2|deadbeef" in body
    # The generated Format: line is the ONE comment rewritten — preserving it
    # would preserve a falsehood this migration itself created.
    assert "check_id|path:line|identity" in body
    assert [r[0] for r in rows] == ["header-updated", "rewritten"]


def test_migration_drops_a_collapsed_key_rather_than_accepting_n_findings(tmp_path):
    """The reason `--update-baseline` cannot serve as the migration.

    For the catch-all producers one entry stood for N findings, so "re-derive
    it" has no 1:1 meaning: expanding to all N accepts N−1 nobody reviewed.
    """
    rows, _refusal, body = _mig(
        tmp_path, ["pip-audit-vuln|requirements.txt:1\n"],
        [("pip-audit-vuln", "requirements.txt:1", "m", "GHSA-a"),
         ("pip-audit-vuln", "requirements.txt:1", "m", "CVE-9999-RCE")],
    )
    assert [r[0] for r in rows] == ["dropped-collapsed"]
    assert "CVE-9999-RCE" not in body
    assert body.strip() == ""


def test_migration_leaves_a_check_with_no_identity_alone(tmp_path):
    """`invert_file_check` has no line and its content is the whole file.

    Hashing that would make the one kind whose key is already stable re-fire on
    any edit anywhere in the file — the filed remedy's worst regression.
    """
    rows, _refusal, body = _mig(
        tmp_path, ["createobjecturl-leak|src/Upload.tsx\n"],
        [("createobjecturl-leak", "src/Upload.tsx", "m", "")],
    )
    assert [r[0] for r in rows] == ["kept-2field"]
    assert "createobjecturl-leak|src/Upload.tsx" in body


def test_a_skipped_checks_entries_are_HELD_not_dropped(tmp_path):
    """The safety property, kept — but per check, not all-or-nothing.

    A skipped stage produces no findings, so its entries look exactly like
    findings that have gone away, and `--update-baseline` deletes them at
    exit 0. This must never do that. But refusing the WHOLE file made the
    upgrade path a dead end: the failing gate routes here, one unexecuted check
    refuses everything, and the gate fails again — on an entirely ordinary tree
    (semgrep not installed, a `paths:` dir absent in this checkout). So the
    skipped check's entries are held and named, and everything else migrates.
    """
    p = tmp_path / "b.txt"
    p.write_text("semgrep-eval|x.py:3\ngrant-x|m.sql:2\n")
    rows, refusal = baseline.migrate_baseline(
        str(p), [("grant-x", "m.sql:2", "m", "aa")], str(tmp_path),
        skipped_ids={"semgrep-eval"})
    assert refusal is None, refusal
    body = p.read_text()
    assert "semgrep-eval|x.py:3\n" in body, "a skipped check's entry was lost"
    assert "grant-x|m.sql:2|aa" in body, "the executable half did not migrate"
    assert ("kept-not-run", "semgrep-eval|x.py:3", "semgrep-eval|x.py:3") == \
        tuple(r[:3] for r in rows if r[0] == "kept-not-run")[0][:3]


def test_migration_refuses_when_NOTHING_could_be_migrated(tmp_path):
    """The total case still refuses, because a report of zero changes would
    leave the operator to infer that the run was the problem."""
    p = tmp_path / "b.txt"
    p.write_text("semgrep-eval|x.py:3\n")
    rows, refusal = baseline.migrate_baseline(
        str(p), [("grant-x", "m.sql:2", "m", "aa")], str(tmp_path),
        skipped_ids={"semgrep-eval"})
    assert rows == []
    assert refusal and "every baselined check did not execute" in refusal
    assert p.read_text() == "semgrep-eval|x.py:3\n", "the file must be untouched"


def test_migration_is_idempotent(tmp_path):
    """A partially-migrated file is a state nobody notices, so re-running is
    the ordinary recovery and must not corrupt what already converted."""
    findings = [("grant-x", "m.sql:2", "m", "deadbeef")]
    _rows, _r, body1 = _mig(tmp_path, ["grant-x|m.sql:2\n"], findings)
    (tmp_path / "b.txt").write_text(body1)
    rows2, _r2, body2 = _mig(tmp_path, [body1], findings)
    assert body1 == body2
    assert [r[0] for r in rows2] == ["kept-3field"]


# ── Q-247: the false mechanism, at every shipped site ───────────────────────


# Every co-occurrence of the term with a line/number noun is flagged, and the
# sentences the tree keeps on purpose are permitted by their EXACT normalized
# text.
#
# Three earlier cuts failed in three different ways and the sequence is the
# argument for this one. A forward-only window missed the noun-first form. Four
# literal constructions fixed those four and let five of six ordinary
# paraphrases through. A proximity window with a fuzzy "does this look like a
# correction?" allowlist then let a false claim planted two lines from a real
# correction inherit that correction's exemption — and widening the exemption
# window to fix a true form re-opened it.
#
# The lesson each time was the same: prose cannot be told apart from its own
# denial by pattern. So the guard stops trying. It flags the CLASS, and the
# handful of true sentences are listed verbatim. A new one — true or false —
# fails until a human adds it here, which is exactly the friction that belongs
# on "I am about to write that a coverage line number is diff-relative".
_WINDOW = 60
_NOUN = re.compile(r"\blines?\b|\bnumbers?\b|\bnumbering\b|\bline-numbers?\b")
_TERM = re.compile(r"diff-relative|relative\s+to\s+the\s+diff")

# Normalized (whitespace-collapsed, `#` stripped) windows that are TRUE and
# ship on purpose. Reflow-tolerant by construction; a reword is not.
_PERMITTED = (
    "and what is *diff-relative* is the **set of lines reported**, not their numbering",
    "what is diff-relative is the set reported, not the numbering",
    "used to say the line number itself shifts every commit",
    "un-matchable because line numbers shift every commit. that half was false",
)


def _normalize(text):
    return " ".join(text.lower().replace("#", " ").split())


def _asserts_a_diff_relative_line(text):
    """True when `text` associates the term with a coverage LINE or NUMBER.

    The claim is false: `diff-cover`'s `violation_lines` are absolute source
    line numbers and `coverage.py` applies no offset arithmetic. What IS
    diff-relative is the *set* of lines reported — which is why "a diff-relative
    coverage gap" is true, ships at three sites, and is not flagged here: it
    carries no line/number noun at all.
    """
    low = _normalize(text)
    # Spans of the permitted sentences within this text. An occurrence is
    # exempt only when it falls INSIDE one of them — not merely when one
    # appears somewhere in the same paragraph. That distinction is the whole
    # guard: a false claim planted two lines from a real correction would
    # otherwise inherit the correction's exemption, which is exactly how a
    # restored `write_baseline` twin walked through the previous cut.
    permitted_spans = []
    for perm in _PERMITTED:
        idx = low.find(perm)
        while idx != -1:
            permitted_spans.append((idx, idx + len(perm)))
            idx = low.find(perm, idx + 1)

    for m in _TERM.finditer(low):
        window = low[max(0, m.start() - _WINDOW):m.start() + _WINDOW]
        if not _NOUN.search(window):
            continue
        if any(lo <= m.start() < hi for lo, hi in permitted_spans):
            continue
        return True
    return False


def _iter_false_claims(body):
    """Yield the line number of every flagged term occurrence in `body`.

    **Whole-body, not a sliding window.** Three earlier cuts scoped this to a
    line and then to a five-line paragraph, and both scopes cut permitted
    sentences away from the occurrences they exempt — the window that starts
    two lines further down sees the claim without its correction and flags it.
    Normalizing the whole body once and letting `_asserts_a_diff_relative_line`
    do the span-based permitting is the only scope where a permit and its
    occurrence are guaranteed to be in the same text.

    Reported by ORDINAL: normalization preserves the order of term occurrences,
    so the Nth flagged occurrence in normalized text is the Nth in the raw file,
    which is enough to name a line.
    """
    low = _normalize(body)
    flagged = []
    permitted_spans = []
    for perm in _PERMITTED:
        idx = low.find(perm)
        while idx != -1:
            permitted_spans.append((idx, idx + len(perm)))
            idx = low.find(perm, idx + 1)
    for n, m in enumerate(_TERM.finditer(low)):
        window = low[max(0, m.start() - _WINDOW):m.start() + _WINDOW]
        if not _NOUN.search(window):
            continue
        if any(lo <= m.start() < hi for lo, hi in permitted_spans):
            continue
        flagged.append(n)
    if not flagged:
        return
    # Map ordinals back to raw line numbers.
    raw_positions = [mm.start() for mm in _TERM.finditer(body.lower())]
    for n in flagged:
        if n < len(raw_positions):
            yield body[:raw_positions[n]].count("\n") + 1


def test_the_diff_relative_predicate_catches_every_form_that_shipped():
    """Acceptance cases, from the four sites the tree actually carried.

    The first cut of this predicate matched the literal phrase
    "diff-relative line" and the author-side battery walked a restored
    `write_baseline` twin straight through it — the real sentence reads "a
    diff-relative coverage line", with a word in between. A guard satisfied by
    an exact phrase is defeated by an adjective, which is how people write.
    """
    for false_form in (
        "the line number is *diff-relative* — it shifts every commit",
        "a baseline entry for a diff-relative coverage line would be a back-door",
        "a diff-relative line number can't stand as tech debt",
        "a diff-relative line can't stand as tech debt, and the carve-out",
    ):
        assert _asserts_a_diff_relative_line(false_form), false_form


def test_the_true_gap_form_is_never_flagged():
    """"A diff-relative coverage *gap*" is true and ships at three sites.

    It needs no permit: it carries no line/number noun, so the class check does
    not reach it. That is the guard's whole shape — flag the association of the
    term with a LINE, leave the association with a SET or a GAP alone.
    """
    for true_form in (
        "a diff-relative coverage gap cannot be accepted as standing tech debt",
        "a diff-relative coverage gap can't stand as tech debt",
        "it never baseline-suppresses (a diff-relative coverage gap can't stand)",
    ):
        assert not _asserts_a_diff_relative_line(true_form), true_form


def test_every_permitted_sentence_is_still_in_the_tree():
    """A permit for a sentence nobody writes any more is dead weight.

    Worse than dead: it is a standing exemption that a future paragraph could
    drift into and inherit. Each entry must still match something shipped, so
    the allowlist shrinks when the prose does.
    """
    root = Path(__file__).resolve().parent.parent
    bodies = " ".join(
        _normalize((root / rel).read_text(errors="replace"))
        for rel in ("core/companion/scripts/run_checks/baseline.py",
                    "core/companion/scripts/run_checks/coverage.py",
                    "core/companion/checks.yml.fragment",
                    "core/companion/docs/WORKFLOW.md")
    )
    for perm in _PERMITTED:
        assert perm in bodies, f"permitted sentence no longer in the tree: {perm!r}"


def test_no_shipped_file_says_a_coverage_LINE_NUMBER_is_diff_relative():
    """`Q-247`, swept over the derived shipped population, not a roster.

    The filing named `baseline.py`'s `_is_coverage` docstring. The tree carried
    **four** — including the twin in `write_baseline`, the other function this
    phase edits, which is the fix-one-and-move-on shape Phase 173 caught. The
    carve-out's real reason (the Phase 61b gate consumes coverage directly, no
    escape hatch) never depended on the false half and is untouched.

    **The file list is derived, and the exclusions are now the honest ones.**
    The first cut named four files and called that "swept across the tree". The
    second derived the population but excluded `tests/` — and said it walked
    "every tracked shipped file", which was false twice over: `tests/` ships to
    the public repo (`tools/make_public_mirror.sh` removes only `tools/` and
    three named test files), and `tests/test_skill_audit_refs.py` was carrying a
    live assertion of the retracted mechanism *into the public repo*, which is
    the precise harm `Q-247` was filed to prevent. A guard whose stated coverage
    exceeds its real one is the `Q-209` shape, and this one hid the finding.

    Excluded now, each for a reason that survives the question "does it ship?":
    the maintainer-only `tools/` tree; the record files, which must be able to
    QUOTE the claim in order to record that it was retracted; and this file,
    which holds the false-form corpus the predicate is tested against.
    """
    root = Path(__file__).resolve().parent.parent
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.split()
    # Maintainer-side surfaces are excluded on purpose: `tools/` never ships,
    # and the record files (`PHASE_LOG.md`, the checklist, the archive) must be
    # able to QUOTE the false claim in order to record that it was corrected.
    skip = ("tools/", "PHASE_LOG.md", "REVIEW_CHECKLIST.md", "REVIEW_ARCHIVE.md",
            "CLAUDE.md")
    shipped = [f for f in tracked
               if not f.startswith(skip) and f != "tests/" + Path(__file__).name]
    # Non-vacuity, tied to the subject rather than to a guessed floor: the four
    # files that actually carried the claim must all be in the swept set. A
    # bare count would have been a number I chose (the first cut said "> 200"
    # against a real population of 177 — a threshold invented, not derived).
    for known in ("core/companion/scripts/run_checks/baseline.py",
                  "core/companion/scripts/run_checks/coverage.py",
                  "core/companion/checks.yml.fragment",
                  "core/companion/docs/WORKFLOW.md"):
        assert known in shipped, f"{known} fell out of the swept population"

    offenders = []
    for rel in shipped:
        f = root / rel
        try:
            body = f.read_text(errors="replace")
        except (OSError, UnicodeDecodeError):
            continue
        if not _TERM.search(body.lower()):
            continue
        for lineno in _iter_false_claims(body):
            offenders.append(f"{rel}:{lineno}")
    assert not offenders, offenders


# ── the producers actually emit an identity ─────────────────────────────────
#
# The author-side battery closed these. The first cut of this file tested
# `finding_key` / `is_baseline_suppressed` with SYNTHETIC identities and never
# once checked that a producer supplies one — so mutations dropping the identity
# at seven of the nine emit sites all survived. Testing the key function is not
# testing the wiring, and a key that is never populated is a two-field key with
# extra steps.

import json
import subprocess as _sp
from unittest.mock import patch

import run_checks.coverage as cov_mod
import run_checks.grep as grep_mod
import run_checks.lint as lint_mod
import run_checks.lsp as lsp_mod
import run_checks.pip_audit as pa_mod
import run_checks.semgrep as sg_mod


def _done(stdout, rc=0):
    return _sp.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr="")


def _grep_check(**over):
    c = {"id": "c1", "severity": "high", "paths": ["src/"], "include": ["*.py"],
         "pattern": "BAD", "description": "d", "used_by": ["codebase-review"]}
    c.update(over)
    return c


def _src(tmp_path, body="x = 'BAD'\n"):
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "a.py").write_text(body)
    return tmp_path


def test_grep_pattern_check_emits_a_nonempty_identity(tmp_path):
    _src(tmp_path)
    out = grep_mod.run_check(_grep_check(), str(tmp_path))
    assert len(out) == 1, out
    assert out[0][3], "a line-level grep finding must carry an identity"
    assert out[0][3] == baseline.identity_of("x = 'BAD'")


def test_grep_negative_pattern_check_emits_a_nonempty_identity(tmp_path):
    _src(tmp_path)
    out = grep_mod.run_check(_grep_check(negative_pattern="NOPE"), str(tmp_path))
    assert len(out) == 1, out
    assert out[0][3] == baseline.identity_of("x = 'BAD'")


def test_position_check_emits_a_nonempty_identity(tmp_path):
    """The 18th line-level grep check, which bypasses `_emit` entirely.

    Its matched line was already read one statement above the key it built, and
    was never threaded through. A mutation dropping it survived the first cut.
    """
    _src(tmp_path, "from app import env\nimport sys\n")
    check = _grep_check(id="pos",
                        position_check={"earlier": r"^import sys",
                                        "later": r"^from app import env"})
    check.pop("pattern")
    out = grep_mod.run_check(check, str(tmp_path))
    assert len(out) == 1, out
    assert out[0][3] == baseline.identity_of("from app import env")


def test_invert_file_check_emits_NO_identity(tmp_path):
    """Deliberately two-field, and asserted so nobody "fixes" it.

    `invert_file_check`'s content is the WHOLE FILE, so hashing it would make
    the one kind whose key is already stable re-fire on any edit anywhere in
    the file — strictly worse than the defect this phase closes. The obvious
    implementation reuses `_emit`'s existing content parameter and does exactly
    that; a mutation doing so survived the first cut.
    """
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "a.py").write_text("x = 'BAD'\n# nothing cleans up\n")
    out = grep_mod.run_check(
        _grep_check(invert_file_check=True, negative_pattern="CLEANUP"),
        str(tmp_path))
    assert len(out) == 1, out
    assert out[0][1] == "src/a.py", "file-level findings cite no line"
    assert out[0][3] == "", "hashing the whole file would regress this kind"


def test_lint_emits_the_rule_id_as_identity(tmp_path):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text("{}")
    (tmp_path / "frontend" / "node_modules").mkdir()
    (tmp_path / "frontend" / "node_modules" / "eslint").mkdir()
    ecn = tmp_path / "frontend" / "node_modules" / "eslint-config-next"
    ecn.mkdir()
    (ecn / "package.json").write_text("{}")
    canned = [{"filePath": str(tmp_path / "frontend" / "a.js"),
               "messages": [{"ruleId": "no-new-func", "line": 7,
                             "severity": 2, "message": "bad"}]}]
    with patch("run_checks.lint.subprocess.run",
               return_value=_done(json.dumps(canned))):
        out = lint_mod._run_eslint(str(tmp_path), {"lint-error"})
    assert len(out) == 1, out
    assert out[0][3] == "no-new-func"


def test_pip_audit_emits_the_vulnerability_id_as_identity(tmp_path):
    canned = {"dependencies": [{"name": "requests", "version": "2.0", "vulns": [
        {"id": "CVE-9999-0001", "aliases": [], "fix_versions": [], "description": "x"},
        {"id": "CVE-9999-0002", "aliases": [], "fix_versions": [], "description": "y"},
    ]}]}
    with patch("run_checks.pip_audit.subprocess.run",
               return_value=_done(json.dumps(canned))):
        out = pa_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert len(out) == 2, out
    # The anchor is identical for both — that IS Q-245 — so the identity is the
    # only thing keeping them apart.
    assert out[0][1] == out[1][1]
    assert {f[3] for f in out} == {"CVE-9999-0001", "CVE-9999-0002"}
    assert len({baseline.finding_key(f[0], f[1], f[3]) for f in out}) == 2


def test_pip_audit_vulns_with_no_id_still_discriminate(tmp_path):
    """`vid` falls back to "?" when an advisory carries no id.

    Two id-less vulns would then share `pip-audit-vuln|requirements.txt:1|?` —
    Q-245 alive again for that subpopulation, on the same constant anchor.
    The package name and version always exist and discriminate by package.
    """
    canned = {"dependencies": [
        {"name": "requests", "version": "2.0", "vulns": [
            {"aliases": [], "fix_versions": [], "description": "x"}]},
        {"name": "urllib3", "version": "1.0", "vulns": [
            {"aliases": [], "fix_versions": [], "description": "y"}]},
    ]}
    with patch("run_checks.pip_audit.subprocess.run",
               return_value=_done(json.dumps(canned))):
        out = pa_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    assert len(out) == 2, out
    assert out[0][1] == out[1][1], "the anchor is constant — that is Q-245"
    assert len({f[3] for f in out}) == 2, [f[3] for f in out]
    assert "?" not in {f[3] for f in out}


def test_pyright_emits_the_rule_as_identity(tmp_path):
    (tmp_path / "app").mkdir()
    canned = json.dumps({"generalDiagnostics": [{
        "file": str(tmp_path / "app" / "x.py"), "severity": "warning",
        "rule": "reportPrivateUsage", "range": {"start": {"line": 11}},
        "message": "m"}]})
    with patch("run_checks.lsp.subprocess.run", return_value=_done(canned)):
        out = lsp_mod._run_pyright(str(tmp_path), {"pyright-general-warning"})
    assert len(out) == 1, out
    assert out[0][3] == "reportPrivateUsage"


def test_tsc_emits_the_error_code_as_identity(tmp_path):
    out = []
    m = lsp_mod._TSC_HEADER_RE.match("a.ts(7,3): error TS2322: not assignable")
    assert m, "the header regex must still match the shape this test pins"
    (tmp_path / "a.ts").write_text("const x: number = 'no'\n")
    lsp_mod._emit_tsc_finding(
        (m, []), str(tmp_path), str(tmp_path),
        {"tsc-type-error": {"paths": ["."]}}, out)
    assert len(out) == 1, out
    assert out[0][3] == "TS2322"


def test_semgrep_emits_the_matched_span_as_identity(tmp_path):
    """`extra.lines`, deliberately NOT `extra.fingerprint`.

    Measured against semgrep 1.157.0: the fingerprint is `hash(path, rule)` plus
    a positional ordinal, so deleting one of two identical matches renumbers the
    survivor onto the deleted one's fingerprint — the accepted key silently
    excusing an unreviewed match, which is Q-190 re-created by Q-190's own
    prescribed remedy.
    """
    (tmp_path / ".claude" / "semgrep").mkdir(parents=True)
    (tmp_path / "x.py").write_text("eval('a')\n")
    canned = json.dumps({"results": [{
        "check_id": "rules.dangerous-eval", "path": str(tmp_path / "x.py"),
        "start": {"line": 1},
        "extra": {"message": "m", "severity": "ERROR", "lines": "eval('a')",
                  "fingerprint": "SHOULD-NOT-BE-USED_0"}}]})
    with patch("run_checks.semgrep.subprocess.run", return_value=_done(canned)):
        out = sg_mod._run_semgrep(
            str(tmp_path), {"semgrep-dangerous-eval": {"paths": ["."]}})
    assert len(out) == 1, out
    assert out[0][3] == baseline.identity_of("eval('a')")
    assert "SHOULD-NOT-BE-USED" not in out[0][3]


def test_coverage_emits_an_EMPTY_identity(tmp_path):
    """Carved out of the baseline at both ends, so it has no identity to carry.

    The field is present rather than absent so every stage really does share one
    finding shape — which nine shipped sentences assert — but populating it would
    imply a coverage finding could be baselined, which is the Phase 61b gate's
    whole carve-out.
    """
    (tmp_path / "billing").mkdir()
    (tmp_path / "billing" / "charge.py").write_text("a = 1\n" * 20)
    (tmp_path / "coverage.xml").write_text("<x/>")
    canned = json.dumps({"src_stats": {"billing/charge.py": {
        "percent_covered": 50.0, "violation_lines": [12]}}})
    with patch("run_checks.coverage.subprocess.run", return_value=_done(canned)):
        out = cov_mod._run_diff_cover_check(str(tmp_path), {
            "id": "coverage-diff-python", "critical_path": ["billing/"],
            "report": "coverage.xml"})
    assert len(out) == 1, out
    assert out[0][3] == "", "coverage never reaches the baseline"


# ── the legacy detector ─────────────────────────────────────────────────────


def test_legacy_entries_names_a_two_field_entry_for_an_identity_bearing_check():
    """The half that replaces the load-time fallback.

    Without it a legacy entry silently stops suppressing and the consumer is
    told nothing. Mutations making this return `[]` survived the first cut.
    """
    found = [("grant-x", "m.sql:2", "msg", "abc123")]
    assert baseline.legacy_entries({"grant-x|m.sql:2"}, found) == ["grant-x|m.sql:2"]


def test_legacy_entries_ignores_checks_that_are_legitimately_two_field():
    """`invert_file_check` entries still match and must not be flagged.

    Naming them would put a permanent warning on every run for entries that are
    working exactly as intended — which is how a real signal gets tuned out.
    """
    found = [("createobjecturl-leak", "src/Up.tsx", "msg", "")]
    assert baseline.legacy_entries({"createobjecturl-leak|src/Up.tsx"}, found) == []


def test_legacy_entries_ignores_an_already_migrated_entry():
    found = [("grant-x", "m.sql:2", "msg", "abc123")]
    assert baseline.legacy_entries({"grant-x|m.sql:2|abc123"}, found) == []


def test_the_run_names_legacy_entries_on_stderr(tmp_path, monkeypatch, capsys):
    """End to end: the warning reaches the operator, with the command."""
    _tree(tmp_path)
    (tmp_path / ".claude" / "checks_baseline.txt").write_text(
        "# h\n\ngrant-sensitive-table|migrations/001.sql:2\n")
    _run(tmp_path, monkeypatch, "--fail-on-blocking")
    err = capsys.readouterr().err
    assert "no longer matches" in err, err
    assert "--migrate-baseline" in err


# ── the migration's remaining branches ──────────────────────────────────────


def test_the_migration_report_shows_the_REAL_source_line(tmp_path):
    """The refusal that reshaped this phase.

    The ratified design was "re-derive in place and print what each entry now
    excuses". `grep.py` composes every grep message from the check's static
    `description:`, so for every one of the 18 grep checks that migrate two
    different statements on one line produce byte-identical report lines — the
    report could not show what it promised. (Not "17 of 19": the 19
    pattern-bearing checks include the two `invert_file_check` entries, which
    emit no report row at all, and the count omits the `position_check`
    dispatch, which carries no `pattern:` and does migrate.) The rewriter re-reads the file instead, and a mutation
    blinding `_source_line` survived the first cut of these guards.
    """
    (tmp_path / "m.sql").write_text("-- h\nGRANT UPDATE ON payments TO app_writer;\n")
    p = tmp_path / "b.txt"
    p.write_text("grant-x|m.sql:2\n")
    rows, refusal = baseline.migrate_baseline(
        str(p),
        [("grant-x", "m.sql:2", "[grant-x] CRITICAL m.sql:2 — GRANT on PII", "d1")],
        str(tmp_path))
    assert refusal is None
    detail = rows[0][3]
    assert "GRANT UPDATE ON payments TO app_writer;" in detail, detail
    # The check's static description must NOT be what the report shows.
    assert "GRANT on PII" not in detail


def test_a_zero_match_entry_is_removed_from_the_file(tmp_path):
    """Dropped, not kept. Keeping it leaves an entry that can never match again
    and that the legacy detector will name on every run for ever."""
    # The file must EXIST: an absent file is the hold case (round 3), because a
    # path that was not scanned cannot be told from a finding that was fixed.
    (tmp_path / "m.sql").write_text("-- the finding here is gone\n" * 3)
    p = tmp_path / "b.txt"
    p.write_text("grant-x|m.sql:99\n")
    rows, refusal = baseline.migrate_baseline(
        str(p), [("grant-x", "m.sql:2", "m", "d1")], str(tmp_path))
    assert refusal is None
    assert [r[0] for r in rows] == ["dropped-no-match"]
    assert p.read_text().strip() == "", p.read_text()


# ── the arity invariant ─────────────────────────────────────────────────────


def test_a_check_id_never_emits_both_key_arities(tmp_path):
    """One check id, one key shape. Found by this phase's own review round.

    `pyright-general-warning` is the bucket for diagnostics with no `rule`, so
    passing `rule` through bare made it emit a TWO-field key for a rule-less
    finding and a THREE-field key for its neighbour — under one check id, in one
    run. `semgrep` had the same shape whenever `extra.lines` was absent.

    The consequence is not cosmetic. `legacy_entries` computes the
    identity-bearing set from what the run emitted, so a legitimate two-field
    entry gets reported as no-longer-matching because some *other* finding of
    the same id carried an identity — and `--migrate-baseline` then rewrites or
    drops a correct entry. `identity_of`'s empty-string branch exists to forbid
    exactly this, and the first cut created it in two producers.
    """
    (tmp_path / "app").mkdir()
    canned = json.dumps({"generalDiagnostics": [
        {"file": str(tmp_path / "app" / "x.py"), "severity": "warning",
         "rule": "", "range": {"start": {"line": 4}}, "message": "no rule here"},
        {"file": str(tmp_path / "app" / "x.py"), "severity": "warning",
         "rule": "reportPrivateUsage", "range": {"start": {"line": 6}},
         "message": "m"},
    ]})
    with patch("run_checks.lsp.subprocess.run", return_value=_done(canned)):
        out = lsp_mod._run_pyright(str(tmp_path), {"pyright-general-warning"})
    assert len(out) == 2, out
    arities = {len(baseline.finding_key(c, f, i).split("|")) for c, f, _m, i in out}
    assert arities == {3}, f"one check id emitted {arities}: {out}"


def test_semgrep_with_no_matched_span_still_emits_one_arity(tmp_path):
    (tmp_path / ".claude" / "semgrep").mkdir(parents=True)
    (tmp_path / "x.py").write_text("eval('a')\n")

    def _res(lines, line):
        return {"check_id": "rules.dangerous-eval", "path": str(tmp_path / "x.py"),
                "start": {"line": line},
                "extra": {"message": "m", "severity": "ERROR", "lines": lines}}

    canned = json.dumps({"results": [_res("", 1), _res("eval('a')", 2)]})
    with patch("run_checks.semgrep.subprocess.run", return_value=_done(canned)):
        out = sg_mod._run_semgrep(
            str(tmp_path), {"semgrep-dangerous-eval": {"paths": ["."]}})
    assert len(out) == 2, out
    arities = {len(baseline.finding_key(c, f, i).split("|")) for c, f, _m, i in out}
    assert arities == {3}, f"one check id emitted {arities}: {out}"


# ── the identity's shape contract ───────────────────────────────────────────
#
# Every producer test above asserts `out[0][3] == baseline.identity_of(x)` —
# which compares the function to ITSELF and is invariant under any change to it.
# An independent battery walked six mutations through that: a 1-character hash
# slice (16 possible identities), a 4-character one, md5 instead of sha1, and
# returning the raw source line unhashed. The last is the worst: the key is
# `|`-delimited and both `legacy_entries` and `migrate_baseline` parse it with
# `split("|")`, so an unhashed line containing a pipe silently changes the
# key's arity. The producer tests could not see any of it.


def test_the_identity_has_a_fixed_hex_shape():
    """A golden vector, so the hash algorithm and width cannot drift silently.

    Changing sha1→md5 or the slice width invalidates every migrated consumer
    baseline at once, with no error — every entry simply stops matching and the
    findings all re-fire. That is loud, but it is loud in the consumer's CI
    rather than here.
    """
    ident = baseline.identity_of("x = 1")
    assert re.fullmatch(r"[0-9a-f]{12}", ident), ident
    # Golden: sha1("x = 1") truncated to 12 hex chars.
    assert ident == "34bce5f775de", ident


def test_the_identity_can_never_contain_the_key_delimiter():
    """The key is `|`-delimited and parsed by `split("|")` in two places.

    An identity carrying a pipe would change the arity of its own key, so
    `legacy_entries` would misread a three-field entry as four-field and
    `migrate_baseline` would misclassify it. A hex digest cannot contain one —
    this asserts that the *contract* holds, not that today's implementation
    happens to.
    """
    for text in ("a|b", "|" * 40, "SELECT * FROM t WHERE x='|'", "x = 1"):
        assert "|" not in baseline.identity_of(text), text


def test_distinct_content_gives_distinct_identities_at_scale():
    """A too-short hash slice collides. `[:1]` gives 16 possible identities.

    A collision is a silent over-suppression: two different statements share a
    key, so accepting one accepts the other — the exact defect this phase
    exists to close, reintroduced through the width of the hash.
    """
    idents = {baseline.identity_of(f"GRANT SELECT ON table_{i} TO role_{i};")
              for i in range(500)}
    assert len(idents) == 500, f"{500 - len(idents)} collisions"


# ── --print-keys ────────────────────────────────────────────────────────────
#
# A shipped CLI flag that had no test at all. Four independent mutations
# survived: printing two-field keys (which is the one thing it must never do,
# since the flag exists BECAUSE the hash cannot be typed by hand), leaking
# coverage keys, printing nothing, and dropping the flag from the written
# baseline header that advertises it.


def test_print_keys_emits_the_key_a_consumer_can_paste(tmp_path, monkeypatch, capsys):
    _tree(tmp_path)
    assert _run(tmp_path, monkeypatch, "--print-keys") == 0
    out = capsys.readouterr().out.strip()
    assert out, "--print-keys printed nothing"
    key = out.split("\t")[0]
    assert key.count("|") == 2, f"a two-field key cannot suppress: {key}"
    # The whole point: pasting it into the baseline must actually suppress.
    (tmp_path / ".claude" / "checks_baseline.txt").write_text(f"# h\n\n{key}\n")
    assert _run(tmp_path, monkeypatch, "--fail-on-blocking") == 0
    assert "[baseline]" in capsys.readouterr().out


def test_print_keys_never_emits_a_coverage_key(tmp_path, monkeypatch, capsys):
    """Coverage is carved out of the baseline, so a coverage key is not an
    entry anyone may add — printing one invites a consumer to write a line that
    can never do anything.

    The fixture must actually PRODUCE a coverage finding. The first cut used a
    tree with no coverage check in it at all, so the assertion was true of a run
    that could not have printed one, and a mutation deleting the filter passed.
    """
    _tree(tmp_path)
    (tmp_path / "billing").mkdir()
    (tmp_path / "billing" / "charge.py").write_text("a = 1\n" * 20)
    (tmp_path / "coverage.xml").write_text("<x/>")
    (tmp_path / ".claude" / "checks.yml").write_text(_GRANT_YML + """\
  - id: coverage-diff-python
    severity: medium
    critical_path: ["billing/"]
    report: coverage.xml
    description: "coverage"
    used_by: [codebase-review]
""")
    canned = json.dumps({"src_stats": {"billing/charge.py": {
        "percent_covered": 50.0, "violation_lines": [12]}}})

    # Dispatch on the command rather than swallowing every subprocess: patching
    # `run_checks.coverage.subprocess.run` sets the attribute on the SHARED
    # subprocess module, so a blanket mock silently muzzles the grep stage too —
    # which is how the first version of this test ended up asserting against an
    # empty string.
    real = _sp.run

    def _dispatch(cmd, *a, **kw):
        if cmd and cmd[0] == "diff-cover":
            return _done(canned)
        return real(cmd, *a, **kw)

    with patch("run_checks.coverage.subprocess.run", side_effect=_dispatch):
        _run(tmp_path, monkeypatch, "--print-keys")
    out = capsys.readouterr().out
    # Non-vacuity: the grep finding proves --print-keys ran and printed.
    assert "grant-sensitive-table|" in out, out
    assert "coverage-" not in out, out


def test_the_written_header_advertises_print_keys(tmp_path):
    """The header is where a consumer learns the key is not typeable."""
    p = str(tmp_path / ".claude" / "checks_baseline.txt")
    baseline.write_baseline(p, [("c", "a.py:1", "m", "abc")], blocking_ids=set())
    header = "".join(l for l in open(p) if l.startswith("#"))
    assert "--print-keys" in header, header
    assert "identity" in header


# ── the refusal's plumbing ──────────────────────────────────────────────────


def test_non_executed_ids_counts_failed_as_well_as_skipped():
    """`Q-253` is that `--update-baseline` guards only on FAILED *blocking*.

    The migration's refusal is advertised as not having that hole, so counting
    only SKIPPED here would reintroduce it inside the function that claims to
    close it — a mutation doing exactly that survived an independent battery.
    """
    from run_checks.accounting import EXECUTED, FAILED, SKIPPED, UNROUTABLE, RunReport
    checks = [{"id": cid} for cid in ("ok", "skipped", "failed", "unroutable")]
    r = RunReport(checks)
    r.record(["ok"], EXECUTED, "grep")
    r.record(["skipped"], SKIPPED, "grep", "tool-missing")
    r.record(["failed"], FAILED, "semgrep", "crash")
    r.record(["unroutable"], UNROUTABLE, "grep")
    assert r.non_executed_ids() == {"skipped", "failed", "unroutable"}


def test_the_cli_hands_the_migration_a_real_skipped_set(tmp_path, monkeypatch, capsys):
    """End to end, through the CLI rather than by passing the set in by hand.

    The unit test hands `skipped_ids` in directly, so a CLI that passed `()`
    would satisfy it while shipping the defect.
    """
    _tree(tmp_path)
    # A check whose `paths:` cannot resolve -> skipped, with an entry present.
    (tmp_path / ".claude" / "checks.yml").write_text(_GRANT_YML + """\
  - id: ghost-check
    severity: high
    paths: ["nowhere/"]
    include: ["*.py"]
    pattern: 'ZZZ'
    description: "d"
    used_by: [codebase-review]
""")
    before = "# h\n\nghost-check|nowhere/x.py:1\n"
    (tmp_path / ".claude" / "checks_baseline.txt").write_text(before)
    code = _run(tmp_path, monkeypatch, "--migrate-baseline")
    # Every entry belongs to the skipped check here, so nothing is migratable.
    assert code == 1, "must refuse rather than delete a skipped stage's entries"
    assert "did not execute" in capsys.readouterr().err
    assert (tmp_path / ".claude" / "checks_baseline.txt").read_text() == before


# ── the migration's remaining unguarded branches ────────────────────────────


def test_a_malformed_entry_is_kept_not_dropped(tmp_path):
    """The code goes out of its way to keep an unparseable line; nothing
    asserted it, and a mutation dropping it — silent data loss on a consumer's
    file — survived."""
    p = tmp_path / "b.txt"
    p.write_text("garbage line without a pipe\ngrant-x|m.sql:2\n")
    rows, refusal = baseline.migrate_baseline(
        str(p), [("grant-x", "m.sql:2", "m", "d1")], str(tmp_path))
    assert refusal is None
    assert "garbage line without a pipe" in p.read_text()
    assert "kept-malformed" in [r[0] for r in rows]


def test_the_migration_writes_atomically(tmp_path):
    """`write_baseline`'s atomicity is guarded; the migration's was not — and it
    is the riskier writer, because it rewrites a file the consumer authored
    rather than one the tool generated.

    Asserted as the PROPERTY, not as the absence of a `.tmp`: a version that
    writes the target in place leaves no `.tmp` either, so the obvious check
    passes on the mutation it exists to catch. Here the swap is made to fail,
    and the consumer's file must survive it byte for byte.
    """
    p = tmp_path / "b.txt"
    original = "# rationale worth keeping\ngrant-x|m.sql:2\n"
    p.write_text(original)
    with patch("run_checks.baseline.os.replace", side_effect=OSError("boom")):
        try:
            baseline.migrate_baseline(
                str(p), [("grant-x", "m.sql:2", "m", "d1")], str(tmp_path))
        except OSError:
            pass
    assert p.read_text() == original, "a failed swap damaged the consumer's file"


def test_the_migration_never_rewrites_an_entry_to_itself(tmp_path):
    """A rewrite that changes nothing but reports `rewritten` is a loop.

    If a producer emitted an empty identity for one finding and a real one for
    another under the same check id, the empty case would be "rewritten" to the
    key it already had — and the run would flag it as legacy again on the next
    pass, for ever. The arity invariant above prevents the mixed case; this
    asserts the migration itself never claims a no-op as a change.
    """
    p = tmp_path / "b.txt"
    p.write_text("mixed|a.py:1\n")
    rows, _refusal = baseline.migrate_baseline(
        str(p), [("mixed", "a.py:1", "m", ""), ("mixed", "a.py:9", "m", "abc")],
        str(tmp_path))
    for action, old, new, _detail in rows:
        assert not (action == "rewritten" and old == new), (action, old, new)


def test_the_migration_is_idempotent_INCLUDING_the_header(tmp_path):
    """The header branch is the one that was not idempotent, and the original
    idempotence test could not see it because its fixture had no header.

    The `# Format:` line was replaced by a TWO-line block whose first line
    still matched the prefix, so each run replaced it again and left the
    previous continuation behind as an ordinary comment — unbounded growth on
    the command whose own docstring calls re-running "the ordinary recovery".
    """
    p = tmp_path / "b.txt"
    p.write_text("# Pre-scan baseline\n"
                 "# Format: check_id|path:line  (one per line)\n"
                 "# my rationale\n"
                 "grant-x|m.sql:2\n")
    findings = [("grant-x", "m.sql:2", "m", "deadbeef")]
    bodies = []
    for _ in range(4):
        baseline.migrate_baseline(str(p), findings, str(tmp_path))
        bodies.append(p.read_text())
    assert len(set(bodies)) == 1, "the migration is not idempotent"
    assert bodies[0].count("# Format:") == 1, bodies[0]
    assert "# my rationale" in bodies[0]


# ── the reporting surfaces ──────────────────────────────────────────────────


def test_the_legacy_warning_names_the_actual_entries(tmp_path, monkeypatch, capsys):
    """A warning that says "N entries no longer match" without naming any is
    not actionable, and the first end-to-end test asserted only that the words
    appeared — so a mutation printing zero names passed."""
    _tree(tmp_path)
    (tmp_path / "migrations" / "002.sql").write_text(
        "-- h\nGRANT DELETE ON orders TO app_admin;\n")
    # TWO entries: with one, "name them all" and "name only the first" are
    # indistinguishable, and a mutation truncating the list to [:1] survived.
    (tmp_path / ".claude" / "checks_baseline.txt").write_text(
        "# h\n\ngrant-sensitive-table|migrations/001.sql:2\n"
        "grant-sensitive-table|migrations/002.sql:2\n")
    _run(tmp_path, monkeypatch, "--fail-on-blocking")
    err = capsys.readouterr().err
    assert "grant-sensitive-table|migrations/001.sql:2" in err, err
    assert "grant-sensitive-table|migrations/002.sql:2" in err, err


def test_write_baseline_deduplicates_identical_keys(tmp_path):
    """The returned tally means "suppressions recorded", which the docstring
    defines and nothing asserted."""
    p = str(tmp_path / ".claude" / "checks_baseline.txt")
    f = ("c", "a.py:1", "m", "abc")
    written = baseline.write_baseline(p, [f, f, f], blocking_ids=set())
    assert written == 1
    body = [l for l in open(p) if l.strip() and not l.startswith("#")]
    assert body == ["c|a.py:1|abc\n"], body


# ── what lens A found by running it ─────────────────────────────────────────


def test_the_three_baseline_verbs_are_mutually_exclusive(tmp_path, monkeypatch, capsys):
    """`--update-baseline` and `--migrate-baseline` are semantically opposed.

    One regenerates the file and keeps no comment; the other converts entries
    in place and preserves every one. Passing both ran the destroyer and exited
    0 — reading as success while a consumer's hand-written rationale went to
    zero — because dispatch order was the only thing deciding which won.
    """
    _tree(tmp_path)
    original = ("# Format: check_id|path:line  (one per line)\n"
                "# accepted 2026-08-14: ETL role, reviewed in the PR\n"
                "grant-sensitive-table|migrations/001.sql:2\n")
    bl = tmp_path / ".claude" / "checks_baseline.txt"
    bl.write_text(original)
    for combo in (("--migrate-baseline", "--update-baseline"),
                  ("--migrate-baseline", "--print-keys"),
                  ("--update-baseline", "--print-keys")):
        bl.write_text(original)
        assert _run(tmp_path, monkeypatch, *combo) == 2, combo
        assert "cannot be combined" in capsys.readouterr().err
        assert bl.read_text() == original, f"{combo} touched the file"


def test_the_failure_routes_to_the_converter_when_entries_are_stale(
        tmp_path, monkeypatch, capsys):
    """Two remedies for one failure, and the destructive one was attached to it.

    Every existing consumer's first post-upgrade run fails, because legacy
    entries stop suppressing by design. The ⚠ said `--migrate-baseline`; the
    error attached to the non-zero exit said `--update-baseline`. Following the
    one attached to the failure discards the rationale AND silently accepts the
    unreviewed finding that just failed the gate.
    """
    _tree(tmp_path)
    (tmp_path / ".claude" / "checks_baseline.txt").write_text(
        "# h\n\ngrant-sensitive-table|migrations/001.sql:2\n")
    assert _run(tmp_path, monkeypatch, "--fail-on-blocking") == 1
    err = capsys.readouterr().err
    # Scoped to the ERROR BLOCK, not the whole stream. The first cut compared
    # positions across all of stderr, so it passed on the ⚠ printed further up
    # — a mutation removing the routing from the error itself survived.
    block = err[err.index("new blocking finding(s)"):]
    assert "--migrate-baseline" in block, block
    assert block.index("--migrate-baseline") < block.index("--update-baseline"), block


def test_print_keys_reports_what_did_not_run(tmp_path, monkeypatch, capsys):
    """The list a consumer picks an entry to accept FROM must say what is
    missing from it. A skipped stage contributes no keys, so without the
    accounting block the list is silently partial."""
    _tree(tmp_path)
    (tmp_path / ".claude" / "checks.yml").write_text(_GRANT_YML + """\
  - id: ghost-check
    severity: high
    paths: ["nowhere/"]
    include: ["*.py"]
    pattern: 'ZZZ'
    description: "d"
    used_by: [codebase-review]
""")
    _run(tmp_path, monkeypatch, "--print-keys")
    err = capsys.readouterr().err
    assert "skipped" in err, err


def test_one_check_emitting_both_arities_does_not_produce_a_false_warning(
        tmp_path, monkeypatch, capsys):
    """The tool flagged a two-field entry it had just written itself.

    Arity is a property of the FINDING, not the check: a consumer-authored
    pattern matching both a blank line and a statement emits one of each. Keyed
    per check id, `legacy_entries` reported the blank-line entry as "predating
    the identity field" while it was suppressing correctly in the same output —
    and the conversion it prescribed could not change it, so the warning
    repeated on every run for ever.
    """
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "checks.yml").write_text("""\
checks:
  - id: empty-or-pass
    description: blank or bare pass
    pattern: '^[[:space:]]*(pass)?[[:space:]]*$'
    paths: ["api/"]
    include: ["*.py"]
    severity: low
    used_by: [codebase-review]
""")
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "a.py").write_text("x = 1\n\npass\n")
    _run(tmp_path, monkeypatch, "--update-baseline")
    capsys.readouterr()
    entries = [l for l in (tmp_path / ".claude" / "checks_baseline.txt")
               .read_text().splitlines() if l and not l.startswith("#")]
    assert len(entries) == 2, entries
    assert any(e.count("|") == 1 for e in entries), "no two-field entry produced"
    _run(tmp_path, monkeypatch)
    assert "no longer match" not in capsys.readouterr().err


def test_the_migration_preserves_the_file_it_is_given(tmp_path):
    """Byte-, line-ending-, permission- and symlink-preserving.

    Every one of these was silently wrong in the first cut, in the one command
    whose stated purpose is preserving what the consumer wrote: a non-UTF-8
    byte in a comment became U+FFFD, a CRLF file was converted to LF, a
    read-only file was reset to 0644, and a symlinked baseline was replaced by
    a regular file — leaving the real target holding the stale entries.
    """
    import os as _os
    target = tmp_path / "real_baseline.txt"
    body = ("# Format: check_id|path:line  (one per line)\r\n"
            "# café — accepted by hand\r\n"
            "grant-x|m.sql:2\r\n")
    target.write_bytes(body.encode("utf-8"))
    _os.chmod(target, 0o444)
    link = tmp_path / "checks_baseline.txt"
    link.symlink_to(target)

    baseline.migrate_baseline(
        str(link), [("grant-x", "m.sql:2", "m", "deadbeef")], str(tmp_path))

    assert link.is_symlink(), "the symlink was replaced by a regular file"
    raw = target.read_bytes()
    assert b"\r\n" in raw, "CRLF converted to LF"
    assert "café".encode("utf-8") in raw, "non-UTF-8-safe rewrite"
    assert b"grant-x|m.sql:2|deadbeef" in raw
    assert _os.stat(target).st_mode & 0o777 == 0o444, "permissions changed"


def test_an_unrepresentable_entry_is_named_not_silently_kept(tmp_path):
    """A path containing `|` cannot be keyed, and was classified `kept-3field`
    — which made it look already-migrated and hid it from `legacy_entries` too.
    Dead in both directions and silent."""
    p = tmp_path / "b.txt"
    p.write_text("check|weird|a|b.py:2\ncheck|path.py:1|\n")
    rows, refusal = baseline.migrate_baseline(
        str(p), [("check", "path.py:1", "m", "abc")], str(tmp_path))
    assert refusal is None
    actions = [r[0] for r in rows]
    assert "kept-unrepresentable" in actions, actions
    assert "kept-empty-identity" in actions, actions
    assert p.read_text() == "check|weird|a|b.py:2\ncheck|path.py:1|\n"


def test_kept_2field_distinguishes_permanent_from_transient(tmp_path):
    """"Check has no derivable identity" is a permanent property, and it was
    reported for an entry whose check merely found nothing this run."""
    p = tmp_path / "b.txt"
    p.write_text("absent-check|gone.py:1\n")
    rows, _refusal = baseline.migrate_baseline(
        str(p), [("other", "a.py:1", "m", "abc")], str(tmp_path))
    assert rows[0][0] == "kept-2field"
    assert "no findings this run" in rows[0][3], rows[0][3]


# ── round 2: what reviewing the FIXES found ─────────────────────────────────


def test_a_null_or_empty_vuln_id_still_discriminates(tmp_path):
    """`.get("id", "?")` tests key ABSENCE, and `"id": null` is legal JSON.

    Both `null` and `""` sailed past the round-1 fallback and produced a
    two-field pip-audit key — Q-245 alive again on a `blocking: true` gate,
    where one accepted null-id advisory excuses every other, including an
    unreviewed critical RCE on an unrelated package. And the round-1 fix to
    `legacy_entries` (per-finding keying, correctly) removed the one warning
    that would have surfaced it, so it was silent in every direction.
    """
    canned = {"dependencies": [
        {"name": "flask", "version": "1.0", "vulns": [
            {"id": None, "aliases": [], "fix_versions": [], "description": "a"},
            {"id": "", "aliases": [], "fix_versions": [], "description": "b"}]},
        {"name": "requests", "version": "2.0", "vulns": [
            {"id": "CVE-1", "aliases": [], "fix_versions": [],
             "description": "c"}]}]}
    with patch("run_checks.pip_audit.subprocess.run",
               return_value=_done(json.dumps(canned))):
        out = pa_mod._run_pip_audit(str(tmp_path), {"pip-audit-vuln"})
    keys = [baseline.finding_key(c, f, i) for c, f, _m, i in out]
    assert len(keys) == 3, keys
    assert all(k.count("|") == 2 for k in keys), keys
    # Two id-less advisories on the SAME package must not collapse either.
    assert len(set(keys)) == 3, keys


def test_a_rule_less_pyright_warning_with_an_empty_message_still_keys(tmp_path):
    """The round-1 fallback was `rule or identity_of(msg)`, which is `""` for a
    rule-less diagnostic with a blank message — mixed arity again, one layer
    down. Semgrep's sibling had a terminal literal; pyright's did not."""
    (tmp_path / "app").mkdir()
    canned = json.dumps({"generalDiagnostics": [
        {"file": str(tmp_path / "app" / "x.py"), "severity": "warning",
         "rule": "", "range": {"start": {"line": 0}}, "message": "   "},
        {"file": str(tmp_path / "app" / "x.py"), "severity": "warning",
         "rule": "reportPrivateUsage", "range": {"start": {"line": 4}},
         "message": "m"}]})
    with patch("run_checks.lsp.subprocess.run", return_value=_done(canned)):
        out = lsp_mod._run_pyright(str(tmp_path), {"pyright-general-warning"})
    arities = {len(baseline.finding_key(c, f, i).split("|")) for c, f, _m, i in out}
    assert arities == {3}, out


def test_a_hand_written_comment_is_never_mistaken_for_the_generated_header():
    """The round-1 branch matched the PREFIX `# Format: check_id|`, beside a
    docstring claiming "a hand-written comment cannot match this, so nobody's
    rationale is touched". It was false, and the loss was permanent: a consumer
    note whose first line began that way had it replaced, and the survivor read
    "accept a grant-* entry without sign-off" — with the negation gone.
    """
    from run_checks.baseline import _GENERATED_FORMAT_LINE as rx
    # ONLY shapes this tool has actually emitted. The first cut also asserted
    # `#Format: check_id|path:line` (no space) is generated — `write_baseline`
    # has never written that, and pinning an over-broad shape means the guard
    # lands RED on any tightening, which is how a corpus stops protecting the
    # thing and starts protecting the implementation.
    for generated in (
        "# Format: check_id|path:line  (one per line)",
        "# Format: check_id|path:line|identity  (identity absent when a check has none)",
    ):
        assert rx.match(generated), generated
    for handwritten in (
        "# Format: check_id|path:line|identity — see docs/baseline.md, and NEVER",
        "# Format: check_id|path:line — ask Wade before adding a grant-* entry",
        "# Format: check_id|path:line (one per line) plus our own convention:",
        # The round-3 case: the caveat written wholly INSIDE the parentheses.
        # Round 2 closed only the trailing-prose form and declared the class
        # shut in eleven lines of comment.
        "# Format: check_id|path:line|identity  (do NOT accept a grant-* entry "
        "without SEC sign-off, ticket SEC-114)",
        "#Format: check_id|path:line",
    ):
        assert not rx.match(handwritten), handwritten


def test_a_crlf_baseline_stays_wholly_crlf(tmp_path):
    """`newline=""` preserved UNTOUCHED lines; every line the migration composed
    hardcoded `\\n`, so a CRLF file came out mixed — while the code comment
    beside it claimed the rewrite was line-ending-preserving."""
    p = tmp_path / "b.txt"
    p.write_bytes(b"# Format: check_id|path:line  (one per line)\r\n"
                  b"# rationale\r\n"
                  b"grant-x|m.sql:2\r\n")
    baseline.migrate_baseline(
        str(p), [("grant-x", "m.sql:2", "m", "deadbeef")], str(tmp_path))
    raw = p.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\r\n") == raw.count(b"\n"), "mixed line endings: " + repr(raw)


def test_a_single_pipe_in_a_path_is_named_not_read_as_migrated(tmp_path):
    """The round-1 branch caught `> 3` parts; the commoner SINGLE-pipe case
    splits to exactly 3 and read as `kept-3field` — already migrated — and was
    invisible to `legacy_entries` too. Dead in both directions, which is the
    shape the branch was added to end.
    """
    p = tmp_path / "b.txt"
    p.write_text("grant-x|migrations/we|ird.sql:2\n")
    rows, refusal = baseline.migrate_baseline(str(p), [], str(tmp_path))
    assert refusal is None
    assert [r[0] for r in rows] == ["kept-unrepresentable"], rows
    assert p.read_text() == "grant-x|migrations/we|ird.sql:2\n"


def test_the_migration_survives_a_leftover_tmp(tmp_path):
    """A killed earlier run leaves a `.tmp` behind. A leftover SYMLINK was
    followed — writing the consumer's baseline to an arbitrary path and making
    the baseline itself a symlink — and a leftover directory raised a bare
    traceback."""
    p = tmp_path / "b.txt"
    p.write_text("grant-x|m.sql:2\n")
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("do not touch\n")
    (tmp_path / "b.txt.tmp").symlink_to(outside)
    baseline.migrate_baseline(
        str(p), [("grant-x", "m.sql:2", "m", "aa")], str(tmp_path))
    assert not p.is_symlink(), "the baseline became a symlink"
    assert outside.read_text() == "do not touch\n", "wrote outside the baseline"
    assert "grant-x|m.sql:2|aa" in p.read_text()

    p.write_text("grant-x|m.sql:2\n")
    # The migration already cleared the leftover symlink above.
    (tmp_path / "b.txt.tmp").unlink(missing_ok=True)
    (tmp_path / "b.txt.tmp").mkdir()
    rows, refusal = baseline.migrate_baseline(
        str(p), [("grant-x", "m.sql:2", "m", "aa")], str(tmp_path))
    assert refusal and "is a directory" in refusal, refusal
    assert p.read_text() == "grant-x|m.sql:2\n"


def test_the_migration_reports_the_reasons_it_records(tmp_path, monkeypatch, capsys):
    """Four `kept-*` reasons were written and printed to nobody: the CLI
    narrated only `rewritten` and `dropped*`, so the transient-vs-permanent
    distinction that motivated writing them never reached the operator."""
    _tree(tmp_path)
    (tmp_path / ".claude" / "checks.yml").write_text(_GRANT_YML + """\
  - id: ghost-check
    severity: high
    paths: ["nowhere/"]
    include: ["*.py"]
    pattern: 'ZZZ'
    description: "d"
    used_by: [codebase-review]
""")
    (tmp_path / ".claude" / "checks_baseline.txt").write_text(
        "# h\nghost-check|nowhere/x.py:1\ngrant-sensitive-table|migrations/001.sql:2\n")
    assert _run(tmp_path, monkeypatch, "--migrate-baseline") == 0
    out = capsys.readouterr().out
    assert "did not execute" in out, out


def test_a_hand_written_comment_survives_an_actual_migration(tmp_path):
    """The regex is guarded; its CALL SITE was not.

    `test_a_hand_written_comment_is_never_mistaken_for_the_generated_header`
    exercises `_GENERATED_FORMAT_LINE` directly, so loosening the condition at
    the call site back to a bare `startswith` prefix — the exact defect round 2
    found — passed it. This drives the migration and reads the file after.

    The note is the real one from the finding: a consumer's convention line
    whose first line begins like the generated header, whose replacement
    silently deleted the word NEVER.
    """
    p = tmp_path / "b.txt"
    note = ("# Format: check_id|path:line|identity — see docs/baseline.md, and NEVER\n"
            "#   accept a grant-* entry without sign-off. Ticket SEC-114.\n")
    p.write_text(note + "grant-x|m.sql:2\n")
    baseline.migrate_baseline(
        str(p), [("grant-x", "m.sql:2", "m", "deadbeef")], str(tmp_path))
    body = p.read_text()
    assert "NEVER" in body, "the negation was destroyed:\n" + body
    assert "see docs/baseline.md" in body
    assert "grant-x|m.sql:2|deadbeef" in body


# ── round 3: what reviewing round 2's fixes found ───────────────────────────


def test_an_entry_under_an_UNSCANNED_path_is_held_not_dropped(tmp_path):
    """The per-check hold protected checks; the property that matters is paths.

    `grep.py` runs a check when **any** of its `paths:` resolves, so a
    multi-path check in a partial checkout EXECUTES while some of its paths are
    never scanned — and the hold cannot see it, because the check is not
    skipped. Round 2 therefore deleted a signed-off `blocking: true`,
    `severity: critical` entry and printed "it will re-fire if it moved", which
    was false: it never moved and was never scanned. Round 1's blunter global
    refusal had covered this by accident.

    The file's absence is the honest signal — this run cannot tell "fixed" from
    "not scanned", so it must not delete.
    """
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "001.sql").write_text("-- h\nGRANT X;\n")
    p = tmp_path / "b.txt"
    p.write_text("grant-x|frontend/migrations/002.sql:4\n"
                 "grant-x|migrations/001.sql:2\n")
    rows, refusal = baseline.migrate_baseline(
        str(p), [("grant-x", "migrations/001.sql:2", "m", "aa")], str(tmp_path))
    assert refusal is None
    body = p.read_text()
    assert "grant-x|frontend/migrations/002.sql:4" in body, body
    assert "kept-unscanned" in [r[0] for r in rows], rows


def test_an_entry_whose_file_EXISTS_is_still_dropped(tmp_path):
    """The other direction: the hold must not become "never drop anything".

    Without this, "hold every zero-match entry" passes the test above while
    making the migration inert.
    """
    (tmp_path / "m.sql").write_text("-- nothing here now\n")
    (tmp_path / "other.sql").write_text("GRANT X;\n")
    p = tmp_path / "b.txt"
    p.write_text("grant-x|m.sql:2\n")  # file present, finding gone
    # The check must still be identity-bearing this run, or the entry lands in
    # `kept-2field` before the zero-match branch is ever reached.
    rows, _refusal = baseline.migrate_baseline(
        str(p), [("grant-x", "other.sql:1", "m", "aa")], str(tmp_path))
    assert [r[0] for r in rows] == ["dropped-no-match"], rows
    assert p.read_text().strip() == ""


def test_pip_audit_id_less_keys_survive_an_earlier_advisory_being_fixed():
    """`#{index}` keys a LIST POSITION, so fixing an unrelated advisory shifts
    every later one — and the accepted key silently excuses a different,
    unreviewed advisory. Q-245's exact failure mode, reintroduced by the fix
    for Q-245. The identity must be content."""
    def key_for(vulns, name="flask", version="1.0"):
        out = []
        for i, v in enumerate(vulns):
            desc = v.get("description", "")
            vid = v.get("id") or ""
            out.append(vid or f"{name}=={version}#"
                       f"{baseline.identity_of(desc) or i}")
        return out

    before = key_for([{"id": "GHSA-x", "description": "unrelated"},
                      {"description": "advisory A, accepted"},
                      {"description": "advisory B, unreviewed"}])
    after = key_for([{"description": "advisory A, accepted"},
                     {"description": "advisory B, unreviewed"}])
    assert before[1] == after[0], "the accepted key must follow its advisory"
    assert before[2] == after[1]
    assert before[1] != before[2]
    # Reordering must not move a key either.
    flipped = key_for([{"description": "advisory B, unreviewed"},
                       {"description": "advisory A, accepted"}])
    assert set(flipped) == set(after)


def test_a_bare_path_entry_with_a_pipe_is_named(tmp_path):
    """`invert_file_check` anchors are bare paths with NO line number, so the
    colon rule could not see a pipe in one — still reading as already-migrated
    and still invisible to `legacy_entries`, which is the dead-in-both-
    directions shape the branch exists to end."""
    p = tmp_path / "b.txt"
    p.write_text("createobjecturl-leak|src/Up|load.tsx\n")
    rows, _refusal = baseline.migrate_baseline(str(p), [], str(tmp_path))
    assert [r[0] for r in rows] == ["kept-unrepresentable"], rows


def test_eol_detection_ignores_an_unterminated_final_line(tmp_path):
    """The majority divided by ALL lines, counting the unterminated last one
    against CRLF — so a two-line CRLF file with no final newline was rewritten
    wholesale to LF, by the guard meant to stop exactly that."""
    p = tmp_path / "b.txt"
    p.write_bytes(b"# Format: check_id|path:line  (one per line)\r\ngrant-x|m.sql:2")
    baseline.migrate_baseline(
        str(p), [("grant-x", "m.sql:2", "m", "dead")], str(tmp_path))
    raw = p.read_bytes()
    assert b"\r\n" in raw, raw
    assert raw.count(b"\r\n") == raw.count(b"\n"), raw


def test_a_stray_line_cannot_disable_the_total_case_refusal(tmp_path):
    """`entry_checks` took `split("|")[0]` from every non-comment line, so a
    merge marker or a note that lost its `#` entered the set and made
    `held == entry_checks` unsatisfiable — one stray line silently switching
    the refusal off."""
    p = tmp_path / "b.txt"
    p.write_text("semgrep-eval|x.py:3\n<<<<<<< HEAD\n")
    rows, refusal = baseline.migrate_baseline(
        str(p), [("grant-x", "m.sql:2", "m", "aa")], str(tmp_path),
        skipped_ids={"semgrep-eval"})
    assert refusal and "every baselined check did not execute" in refusal, refusal
    assert p.read_text() == "semgrep-eval|x.py:3\n<<<<<<< HEAD\n"


def test_the_header_rewrite_is_reported_as_a_rewrite(tmp_path, monkeypatch, capsys):
    """It is the one line the migration replaces, and it printed under the word
    `kept` beside the text it had just destroyed — which reads as confirmation
    that nothing happened."""
    _tree(tmp_path)
    (tmp_path / ".claude" / "checks_baseline.txt").write_text(
        "# Format: check_id|path:line  (one per line)\n"
        "grant-sensitive-table|migrations/001.sql:2\n")
    _run(tmp_path, monkeypatch, "--migrate-baseline")
    out = capsys.readouterr().out
    assert "REPLACED the generated header" in out, out
    assert "kept     # Format:" not in out, out


def test_a_degraded_check_does_not_deadlock_the_upgrade_path():
    """`degraded` is the one non-executed state where the stage RAN.

    `non_executed_ids` returned everything that was not `executed`, sweeping it
    in — so a semgrep run degraded by one unparseable file made the migration
    refuse outright, on a persistent tree property, leaving `--update-baseline`
    as the only escape: the command whose destruction of consumer rationale is
    the reason the remedy routing was rewritten at all. Round 1 replaced a
    global refusal *because* it dead-ended the upgrade path; degraded walked
    back through the narrowed door.

    The docstring said "union of skipped, failed and unroutable" while the code
    did otherwise, and the test enumerated the same three — so the one state
    that mattered was never tried.
    """
    from run_checks.accounting import (DEGRADED, EXECUTED, FAILED, SKIPPED,
                                       UNROUTABLE, RunReport)
    ids = ("ok", "skipped", "failed", "unroutable", "degraded")
    r = RunReport([{"id": c} for c in ids])
    r.record(["ok"], EXECUTED, "grep")
    r.record(["skipped"], SKIPPED, "grep", "tool-missing")
    r.record(["failed"], FAILED, "semgrep", "crash")
    r.record(["unroutable"], UNROUTABLE, "grep")
    r.record(["degraded"], DEGRADED, "semgrep", "partial-parse")
    assert r.non_executed_ids() == {"skipped", "failed", "unroutable"}
    assert r.incomplete_ids() == {"degraded"}


def test_a_degraded_checks_unmatched_entry_is_held_not_dropped(tmp_path):
    """It emitted findings, so matched entries migrate — but an entry it did
    not match may be in the part it could not read."""
    (tmp_path / "x.py").write_text("eval('a')\n")
    p = tmp_path / "b.txt"
    p.write_text("semgrep-eval|x.py:1\nsemgrep-eval|x.py:9\n")
    rows, refusal = baseline.migrate_baseline(
        str(p), [("semgrep-eval", "x.py:1", "m", "aa")], str(tmp_path),
        skipped_ids=(), incomplete_ids={"semgrep-eval"})
    assert refusal is None, refusal
    body = p.read_text()
    assert "semgrep-eval|x.py:1|aa" in body, body
    assert "semgrep-eval|x.py:9" in body, "an unmatched entry was dropped"
    assert "kept-incomplete" in [r[0] for r in rows], rows


def test_one_finding_reported_twice_is_not_read_as_a_collapse(tmp_path):
    """`write_baseline` dedupes by key; this counted raw findings.

    The two functions therefore read the same condition oppositely, in the same
    file: one says "a shared key means the findings really are the same
    finding", the other called it a collapse and DROPPED a reviewed entry with
    a false explanation. Duplicate emission is ordinary — overlapping `paths:`
    re-scan a file, and the shipped python and postgres packs overlap after an
    unremarkable substitution.
    """
    (tmp_path / "h.py").write_text("eval('x')\n")
    p = tmp_path / "b.txt"
    p.write_text("overlap-check|h.py:1\n")
    dup = ("overlap-check", "h.py:1", "m", "sameid")
    rows, refusal = baseline.migrate_baseline(
        str(p), [dup, dup], str(tmp_path))
    assert refusal is None
    assert [r[0] for r in rows] == ["rewritten"], rows
    assert "overlap-check|h.py:1|sameid" in p.read_text()


def test_a_genuine_collapse_is_still_dropped(tmp_path):
    """The other direction: two DISTINCT identities at one anchor is the real
    catch-all case and must still refuse to expand."""
    (tmp_path / "a.js").write_text("var x\n")
    p = tmp_path / "b.txt"
    p.write_text("lint-error|a.js:1\n")
    rows, _refusal = baseline.migrate_baseline(
        str(p), [("lint-error", "a.js:1", "m", "no-unused-vars"),
                 ("lint-error", "a.js:1", "m", "no-new-func")], str(tmp_path))
    assert [r[0] for r in rows] == ["dropped-collapsed"], rows
