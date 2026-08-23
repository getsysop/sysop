"""Baseline file I/O — load known-accepted findings and write fresh snapshots."""
import hashlib
import os
import re


def load_baseline(path):
    """Load baseline keys as a set of "check_id|file_line[|identity]" strings.

    Baseline file format (one per line):
        check_id|path:line|identity     three-field, identity-bearing checks
        check_id|path:line              two-field, checks with no derivable identity
    Lines starting with # are comments. Blank lines ignored.

    **Comments are dropped here and that is a read-side fact only.** A consumer's
    baseline is substantially comment — the one real corpus is two-thirds
    comment, ~140 lines of it hand-written triage rationale — so nothing that
    *writes* a consumer's baseline may be built on a `load_baseline` →
    `write_baseline` round-trip. See `migrate_baseline`.
    """
    if not os.path.exists(path):
        return set()

    keys = set()
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            keys.add(line)
    return keys


_WS_RUN = re.compile(r"\s+")

# ONLY a line this tool generated. The first cut matched the prefix
# `# Format: check_id|`, and the docstring beside it claimed "a hand-written
# comment cannot match this, so nobody's rationale is touched" — which was
# false. A consumer note beginning
#   `# Format: check_id|path:line|identity — see docs/…, and NEVER accept a`
#   `#   grant-* entry without sign-off. Ticket SEC-114.`
# had its first line replaced, and the survivor read "accept a grant-* entry
# without sign-off" — the negation destroyed, permanently and unrecoverably, by
# the command whose whole purpose is preserving what the consumer wrote.
# Anchored end-to-end so only the declaration itself matches.
_GENERATED_FORMAT_LINE = re.compile(
    r"^# Format: check_id\|path:line(?:\|identity)?"
    r"(?:\s*\((?:one per line|identity absent when a check has none)\))?\s*$"
)


def identity_of(text):
    """Return the stable identity hash for a finding's matched text.

    Normalized by strip + whitespace-collapse before hashing, so a re-indent, a
    `black` run, a wrap-in-`if` or a trailing-whitespace fix does NOT invalidate
    an accepted entry — while a rename, a reflow or a changed argument does
    (which re-fires the finding, the loud and safe direction).

    Returns `""` for empty or whitespace-only text, which yields a two-field key.
    No shipped grep pattern can match an empty line, but `checks.project.yml` is
    the promotion write target (`_shared/promotion-write-target.md`), so a
    consumer-authored pattern can — and one check emitting both key arities is
    the ambiguity this branch exists to forbid.
    """
    normalized = _WS_RUN.sub(" ", (text or "").strip())
    if not normalized:
        return ""
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


def finding_key(check_id, file_line, identity=""):
    """Build the baseline key.

    Three fields when the producer supplied an identity, two when it did not.
    **There is no load-time fallback between the two forms** — a legacy two-field
    entry does not suppress an identity-bearing finding. A fallback would preserve
    the defect permanently for every baseline that already exists, which is the
    only population that has it; `legacy_entries` names those entries instead so
    the run can say what needs re-triage.
    """
    if identity:
        return f"{check_id}|{file_line}|{identity}"
    return f"{check_id}|{file_line}"


def legacy_entries(baseline, all_findings):
    """Return the sorted two-field baseline entries that can no longer match.

    An entry is legacy when it has two fields *and* its check id is one this run
    emitted with a non-empty identity — i.e. the check became identity-bearing
    and the entry predates that. Derived from the run rather than from a static
    table, so a check that changes bucket (a `pattern` check gaining
    `invert_file_check`, say) needs no second place to be registered.

    Entries for checks that legitimately stay two-field (`invert_file_check`,
    and any producer that emitted no identity) are NOT reported — they still
    match, and naming them would be noise on every run forever.

    **Keyed per finding, not per check id.** Arity is a property of the
    individual finding, not of the check that produced it: one check can emit
    both, whenever its matched text normalizes to nothing (a consumer-authored
    pattern matching a blank line does exactly that, and `checks.project.yml`
    is the promotion write target, so consumer-authored patterns are the
    ordinary case). Keyed per check id, the run flagged a two-field entry that
    the tool ITSELF had just written and that was suppressing correctly in the
    same output — telling the operator it "predates the identity field", and
    pointing at a conversion that could not change it, on every run for ever.
    Checking whether the anchor still has a matching identity-free finding is
    the exact question, and it costs one dict.
    """
    identity_free_anchors = {
        (check_id, file_line)
        for check_id, file_line, _msg, identity in all_findings if not identity
    }
    identity_bearing = {
        check_id for check_id, _fl, _msg, identity in all_findings if identity
    }
    out = []
    for entry in baseline:
        parts = entry.split("|")
        if len(parts) != 2 or parts[0] not in identity_bearing:
            continue
        # Still matched by a live identity-free finding at this exact anchor.
        if tuple(parts) in identity_free_anchors:
            continue
        out.append(entry)
    return sorted(out)


def _is_coverage(check_id):
    """Coverage findings never participate in the baseline (Phase 61b).

    A coverage finding's key is ``coverage-…|path:line``, and what is
    *diff-relative* is the **set of lines reported**, not their numbering:
    `coverage.py` reads `diff-cover`'s ``violation_lines``, which are absolute
    source line numbers, and applies no offset arithmetic. So a baselined
    coverage gap re-matches on a later PR exactly as any other finding would.
    (This paragraph used to say the line number itself shifts every commit.
    That was false, and it is corrected here rather than carried forward,
    because the conclusion below never depended on it.)

    The reason that actually holds is the second one: "accepting" an uncovered
    crown-jewel line as standing tech debt is exactly what the Phase 61b hard
    gate exists to forbid: the gate consumes the coverage number directly as a
    block, **not through the baseline/audit loop**. That is coverage-specific
    and ratified, and it is why coverage is the only carve-out — a check left
    at a two-field key (`invert_file_check`, or any producer with no derivable
    identity) is still fully baselinable, which is a different thing.

    So coverage is excluded from *both* ends of the baseline — it is never
    written (`write_baseline`) and never suppresses a finding
    (`is_baseline_suppressed`). A genuinely untestable line is excluded at the
    report-producer layer with a coverage pragma (`# pragma: no cover`,
    `/* istanbul ignore */`), which drops it from the report so it is not a
    violation — not via the baseline here.
    """
    return str(check_id).startswith("coverage-")


def is_baseline_suppressed(check_id, file_line, blocking_ids, baseline,
                           identity=""):
    """Return True when a finding is baseline-suppressed.

    A suppressed finding is printed with a ``[baseline]`` tag and does NOT
    count toward ``--fail-on-blocking``. Suppression requires only that the
    key be in the baseline — *except* coverage findings, which never suppress
    (see `_is_coverage`): a blocking coverage gap always fails the gate,
    baseline or no baseline.

    ``identity`` is trailing and defaults to `""` so the re-exported signature
    stays call-compatible for positional callers. When it is non-empty the key
    is three-field, and **a two-field entry for the same check and line does
    not match it** — that is the whole point, not an oversight: such an entry
    means "whatever this check finds here", which is the defect. `cli.py`
    surfaces those entries through `legacy_entries` rather than honouring them.

    ``blocking_ids`` is accepted and deliberately unused (internal tracker #363).
    Suppression used to require ``check_id in blocking_ids`` as well, which
    made a baseline entry for a ``blocking: false`` check unable to suppress
    anything *and* unable to be written — inert state that reads as live
    state, so a triager who recorded ~300 advisory verdicts as accepted
    findings recorded them nowhere. What the gate keys off is unchanged:
    ``--fail-on-blocking`` reads ``blocking_ids`` itself (`cli.py`), so
    suppressing an advisory finding changes what is *printed* and nothing
    about the exit code. The parameter stays in the signature because the
    caller has it and a future rule may key on it; dropping it would be a
    breaking change to the re-exported API for no gain.
    """
    if _is_coverage(check_id):
        return False
    return finding_key(check_id, file_line, identity) in baseline


def write_baseline(path, all_findings, blocking_ids, non_executed_ids=()):
    """Write baseline file containing all current findings. Returns the count.

    Atomic rewrite via `<path>.tmp` + `os.replace` so a crash mid-write
    never leaves a truncated baseline that future runs would then load
    as authoritative.

    ``non_executed_ids`` names every check whose verdict this run cannot stand
    behind: those that PRODUCED NOTHING (skipped, failed, unroutable —
    `RunReport.non_executed_ids`) **and** those that ran over less than their
    declared inputs (`degraded` — `RunReport.incomplete_ids`). **Their existing
    baseline entries are carried forward verbatim instead of being dropped.**
    The caller passes the union; the parameter keeps its name because what it
    means to this function is "do not treat this check's silence as evidence".

    The `degraded` half was missing from the first cut and was found by this
    phase's review round. It mattered more than the arithmetic suggests: a
    degraded stage produces zero *carried* entries but a non-empty findings
    list, so the "carried forward unverified" warning the caller prints did not
    fire either — the deletion was as silent as the one being fixed.
    Without this the regeneration is a silent delete: a check that did not run
    contributes zero findings, so a wholesale rewrite discards every entry it
    owned and exits 0 with a `Wrote N baseline finding(s)` line that reads like
    success. Measured on the one real corpus (86 entries): regenerating on a
    machine without semgrep installed silently discarded all five `semgrep-*`
    verdicts.

    **The fix is to narrow the write, not to refuse the run.** Refusing here —
    the way `--migrate-baseline` refuses when EVERY baselined check was skipped —
    looks symmetrical and is not, for a
    reason visible in this repo's own shipped defaults: `skipped` is the
    UNIVERSAL STARTING STATE. Both coverage checks ship `blocking: true` with
    placeholder `critical_path` globs, and five pack grep checks ship
    `blocking: true` with placeholder paths, so a brand-new install has several
    non-executed blocking checks before the consumer has done anything wrong.
    (Do not carry that count without re-deriving it. It read "three" when this
    docstring was written and was already five in the same commit, because the
    phase writing it had just added two such checks. Derive it from the pack
    fragments, never from here.) A
    refusal keyed to `non_executed_ids` would refuse the baseline write on every
    fresh install, and would remove the only escape from the `--migrate-baseline`
    refusal that fires when every baselined check was skipped (see
    `RunReport.non_executed_ids`).
    Preserving costs nothing and loses nothing. (The design note recording that
    trade-off is maintainer-side and does not ship; the argument above is the
    whole of it.)

    Coverage findings are never written (see `_is_coverage`) — a baseline
    entry for a coverage gap would be a back-door around the Phase 61b
    crown-jewel gate. (This used to add a second reason, about the entry being
    un-matchable because line numbers shift every commit. That half was false —
    `diff-cover` reports absolute source lines — so it is dropped rather than
    carried, per `_is_coverage`.) That carve-out is the
    *only* one: an advisory (`blocking: false`) check's findings are written
    like any other (internal tracker #363 — see `is_baseline_suppressed`).

    ``blocking_ids`` is accepted and deliberately unused, for the reason given
    there. **The return value exists so no caller has to restate the filter:**
    the printed tally used to re-implement this predicate by hand at the call
    site, which is one copy too many of a condition this change had to edit.

    **This writes a whole file and keeps no comment.** It is the regeneration
    path (`--update-baseline`), not a migration path: it silently accepts every
    finding present at run time, and it discards any hand-written rationale the
    consumer's file carried. `migrate_baseline` exists because those two
    properties make this function unusable for converting an existing baseline.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp_path = path + ".tmp"
    # Deduplicated, because the key is what `load_baseline` returns and it returns a
    # SET: two findings sharing a key are one suppression however many lines get
    # written. The catch-all ids used to make that ordinary rather than exotic —
    # `lint-error` carries the real rule in the message, not the id, so every ESLint
    # rule on one line shared a key, and one accepted entry excused all of them.
    # That collapse is now discriminated by the identity field, so a shared key
    # means the findings really are the same finding. Writing it once keeps the
    # file honest and makes the returned tally mean "suppressions recorded" rather
    # than "findings seen", which is what the caller prints it as.
    # Entries owned by a check that did not run this pass. Read BEFORE the
    # truncating open below — `tmp_path` is a sibling, but a caller that ever
    # passes `path` as its own tmp would otherwise read what it just emptied.
    preserved = set()
    if non_executed_ids:
        non_executed = set(non_executed_ids)
        for key in load_baseline(path):
            check_id = key.split("|", 1)[0]
            if check_id in non_executed and not _is_coverage(check_id):
                preserved.add(key)

    seen = set()
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(
            "# Pre-scan baseline — known findings accepted as tech debt or "
            "triaged as non-issues.\n"
            "# Format: check_id|path:line|identity  (identity absent when a check has none)\n"
            "# Print the exact key for a live finding: "
            "bash sysop/scripts/run_checks.sh --print-keys\n"
            "# Regenerate: bash sysop/scripts/run_checks.sh --mode both --update-baseline\n"
            "# A `blocking: true` check's new findings — ones NOT in this file "
            "— fail CI.\n"
            "# A `blocking: false` check's entries record a triage verdict: "
            "they tag the\n"
            "# finding `[baseline]` instead of hiding it, and gate nothing "
            "either way.\n"
            "# (coverage-* findings are never baselined — see write_baseline.)\n"
            "\n"
        )
        for check_id, file_line, _msg, identity in sorted(all_findings):
            if _is_coverage(check_id):
                continue
            key = finding_key(check_id, file_line, identity)
            if key in seen:
                continue
            seen.add(key)
            f.write(f"{key}\n")
        # Carried-forward entries last, sorted, so a diff of two regenerations
        # is stable. A key already emitted above is not re-written: a check can
        # be non-executed in one stage and produce findings in another.
        for key in sorted(preserved - seen):
            seen.add(key)
            f.write(f"{key}\n")
    os.replace(tmp_path, path)
    return len(seen)


def _source_line(repo_root, file_line):
    """Return the current source text at ``file_line``, or "" if unreadable.

    The migration report has to show *the statement an entry now excuses*, and
    it cannot get that from the finding: `grep.py` builds every grep message
    from the check's static `description:` field, so two different statements
    on one line produce byte-identical messages. Re-reading the file is the
    only way the report says anything the reader could not have guessed.
    """
    path, _, lineno = str(file_line).rpartition(":")
    if not path or not lineno.isdigit():
        return ""
    try:
        with open(os.path.join(repo_root, path), encoding="utf-8",
                  errors="replace") as f:
            for i, raw in enumerate(f, 1):
                if i == int(lineno):
                    return raw.strip()
    except OSError:
        return ""
    return ""


def migrate_baseline(path, all_findings, repo_root, skipped_ids=(),
                     incomplete_ids=()):
    """Convert a two-field baseline in place. Returns (rows, refusal).

    **Line-oriented and comment-preserving.** A consumer's baseline is mostly
    comment — the one real corpus is 200 comment lines to 86 entries, ~140 of them
    hand-written triage rationale that the file itself calls durable
    documentation — so this reads and rewrites lines rather than
    round-tripping through `load_baseline` / `write_baseline`, which would drop
    every comment and stamp a fresh header over the lot.

    Per entry, keyed on how many current findings share its ``check_id`` and
    ``file_line``:

    * **already three-field** — passed through untouched.
    * **check emitted no identity this run** — left two-field. Legitimate:
      `invert_file_check` and any producer with nothing to key on.
    * **exactly one match** — rewritten to the three-field key. Unambiguous:
      there is one finding it can mean.
    * **zero matches** — dropped. The finding it accepted is gone or has moved;
      if it moved it re-fires at its new line, which is loud and correct.
    * **two or more matches** — dropped. This is the collapsed-key case
      (`pip-audit-vuln`, `lint-error`, `tsc-type-error`,
      `pyright-general-warning`): one entry stood for N findings, so expanding
      it to all N would accept every one of them — including a critical CVE
      nobody reviewed — which is exactly the silent acceptance that rules
      `--update-baseline` out as a migration. Dropping forces re-triage of a
      short list instead.

    ``skipped_ids`` HOLDS the entries of a check that did not execute, per
    check rather than all-or-nothing. A skipped stage yields no findings, so
    every one of its entries would look like the zero-match case and be dropped
    — turning an uninstalled semgrep into permanent loss of every accepted
    semgrep verdict. (`--update-baseline` has this defect today and this does
    not inherit it.) The whole migration refuses only when EVERY baselined
    check is in ``skipped_ids``, because then there is nothing to convert; a
    global refusal on any single skip made the upgrade path a dead end — see
    the comment at the ``held == entry_checks`` test below.
    """
    identity_bearing = {
        cid for cid, _fl, _msg, ident in all_findings if ident
    }

    # `surrogateescape` + `newline=""` so the rewrite is byte- and
    # line-ending-preserving. `errors="replace"` silently turned a non-UTF-8
    # byte in a hand-written comment into U+FFFD, and universal newlines
    # silently converted a CRLF file to LF — both in the one command whose
    # stated purpose is preserving what the consumer wrote. `realpath` so a
    # baseline that is a SYMLINK is written through rather than replaced by a
    # regular file (which left the real target holding stale entries).
    path = os.path.realpath(path)
    with open(path, encoding="utf-8", errors="surrogateescape", newline="") as f:
        original = f.readlines()

    # Write new lines with the file's OWN dominant ending. `newline=""` keeps
    # untouched lines verbatim, but every line this function composes used a
    # hardcoded "\n", so a CRLF baseline came out MIXED — which the code
    # comment above called "byte- and line-ending-preserving".
    # Majority over TERMINATED lines only. Dividing by every line counted the
    # unterminated last one against CRLF, so a two-line CRLF file with no final
    # newline was rewritten wholesale to LF — by the guard meant to stop exactly
    # that. Ties and empty files fall to "\n", which is what this tool writes.
    terminated = [l for l in original if l.endswith(("\n", "\r"))]
    crlf = sum(1 for l in terminated if l.endswith("\r\n"))
    eol = "\r\n" if terminated and crlf * 2 > len(terminated) else "\n"

    # Index the run once: (check_id, file_line) -> [identity, ...]
    # DISTINCT identities, because `write_baseline` dedupes by key and this must
    # read the same condition the same way. Counting raw findings made the two
    # functions disagree in the same file: `write_baseline`'s comment says "a
    # shared key means the findings really are the same finding", while this
    # called the duplicate a collapse and DROPPED a reviewed entry. Duplicate
    # emission is ordinary — overlapping `paths:` re-scan a file, and the shipped
    # python and postgres packs overlap after an unremarkable substitution
    # (`<api module>`=backend, `<tests dir>`=backend/tests). The genuine collapse
    # (`lint-error` with two different rule ids) still has two identities and is
    # still dropped.
    by_anchor = {}
    for cid, file_line, _msg, ident in all_findings:
        by_anchor.setdefault((cid, file_line), set()).add(ident)

    entry_checks = set()
    for raw in original:
        line = raw.strip()
        # A line with no `|` is not an entry — it is a merge marker, or a note
        # whose `#` was lost. Counting it as a check made `held == entry_checks`
        # unsatisfiable, so one stray line silently disabled the refusal.
        if line and not line.startswith("#") and "|" in line:
            entry_checks.add(line.split("|")[0])
    # Per check, not all-or-nothing. A global refusal made the upgrade path a
    # DEAD END: the failing gate routes here, one unexecuted check refuses the
    # whole file, and the gate fails again — with no route out, on an entirely
    # ordinary tree (semgrep not installed, a `paths:` dir absent in this
    # checkout, frontend checks in a backend worktree). The safety property
    # that matters is narrower than the refusal was: never delete a SKIPPED
    # check's entries. So those entries are held, named, and everything else
    # migrates.
    held = entry_checks & set(skipped_ids)
    if entry_checks and held == entry_checks:
        # Every entry belongs to a check that did not run, so there is nothing
        # this pass could migrate. Refusing keeps the caller's error path live
        # and, more usefully, tells the operator the run itself was the problem
        # rather than leaving them to read a report of zero changes.
        return [], (
            "REFUSED: every baselined check did not execute this run ("
            + ", ".join(sorted(held)) + "). Nothing could be migrated. Re-run "
            "with those stages available — the entries are untouched."
        )
    rows, out = [], []
    for raw in original:
        line = raw.strip()
        if not line or line.startswith("#"):
            # Comments pass through verbatim — that is the point of this
            # function — with ONE exception: the generated `# Format:` line
            # states the key shape, and preserving it would preserve a
            # falsehood the migration itself created. Matched on its stable
            # prefix rather than the whole line, because a consumer's file may
            # carry an older generated header (a pre-vendor-namespace one is
            # known to exist in the wild). A hand-written comment cannot match
            # this, so nobody's rationale is touched.
            if _GENERATED_FORMAT_LINE.match(line.lstrip("\ufeff")):
                replacement = (
                    "# Format: check_id|path:line|identity  "
                    "(identity absent when a check has none)" + eol
                )
                # ONE line in, ONE line out. The first cut replaced this
                # single line with a two-line block, and the new first line
                # still matched the prefix above — so every re-run replaced
                # it again and left the previous continuation behind as an
                # ordinary comment. The file grew by a line per run, without
                # bound, on the command whose own docstring calls re-running
                # "the ordinary recovery". Single-line keeps the branch
                # idempotent by construction rather than by a second check.
                if raw == replacement:
                    out.append(raw)
                    continue
                out.append(replacement)
                rows.append(("header-updated", line, None,
                             "the generated Format: line stated the old key shape"))
                continue
            out.append(raw)
            continue
        parts = line.split("|")
        if len(parts) > 3:
            # The key is `|`-delimited, so a path containing one cannot be
            # represented. Classified `kept-3field` before, which made it look
            # already-migrated and hid it from `legacy_entries` too — dead in
            # both directions and silent. Named instead; the file is not the
            # place to fix it, the path is.
            rows.append(("kept-unrepresentable", line, line,
                         "contains more than two `|` — cannot be parsed as a "
                         "key; check whether the path contains a pipe"))
            out.append(raw)
            continue
        if len(parts) == 3 and (":" in parts[2] or "/" in parts[2]
                                or "." in parts[2].rsplit("#", 1)[0]):
            # An identity never contains a colon (hex digest, rule id, TS
            # number, CVE id, name==version); a `file_line` almost always ends
            # in one. So a colon in the LAST field means the split went wrong —
            # a `|` in the path — and the entry only LOOKED already-migrated.
            # The `> 3` branch below caught the two-pipe case and this one, the
            # commoner single-pipe case, still read as `kept-3field`: invisible
            # to `legacy_entries` too, which is the dead-in-both-directions
            # shape the branch was added to end.
            rows.append(("kept-unrepresentable", line, line,
                         "a `|` in the path cannot be keyed; rename the file "
                         "or drop the entry"))
            out.append(raw)
            continue
        if len(parts) == 3:
            if not parts[2]:
                rows.append(("kept-empty-identity", line, line,
                             "trailing `|` with no identity — matches nothing; "
                             "re-accept it with --print-keys"))
            else:
                rows.append(("kept-3field", line, line, ""))
            out.append(raw)
            continue
        if len(parts) != 2:
            rows.append(("kept-malformed", line, line,
                         "not a recognisable key; left untouched"))
            out.append(raw)
            continue
        cid, file_line = parts
        if cid in held:
            rows.append(("kept-not-run", line, line,
                         "this check did not execute — its entry is held "
                         "untouched; re-run the migration with the stage "
                         "available"))
            out.append(raw)
            continue
        if cid not in identity_bearing:
            # Two very different causes, and the old wording asserted the first
            # for both: the check may have NO derivable identity (permanent —
            # `invert_file_check`), or it may simply have found nothing this
            # run (transient — its paths did not resolve, its file is gone).
            # Saying "has no derivable identity" about the transient case sends
            # the reader looking for a property that is not there.
            seen_this_run = any(c == cid for c, _f in by_anchor)
            reason = ("check has no derivable identity" if seen_this_run else
                      "check produced no findings this run — entry kept "
                      "unexamined; re-run the migration when it does")
            rows.append(("kept-2field", line, line, reason))
            out.append(raw)
            continue
        matches = sorted(by_anchor.get((cid, file_line), set()))
        if len(matches) == 1 and not matches[0]:
            # The one current finding carries no identity, so the two-field
            # entry still means exactly what it meant. Rewriting it would
            # produce the key it already has while reporting `rewritten` — a
            # no-op claimed as a change, and worse, `legacy_entries` would flag
            # it again on the very next run, for ever. Reachable whenever one
            # check id emits a mix of arities; the producers no longer do, and
            # a consumer-authored pattern matching a blank line still can.
            rows.append(("kept-2field", line, line,
                         "the current finding at this anchor has no identity"))
            out.append(raw)
            continue
        if len(matches) == 1:
            new_key = finding_key(cid, file_line, matches[0])
            source = _source_line(repo_root, file_line)
            detail = (f"now excuses: {source!r}" if source
                      else "now excuses: (source line unreadable — verify by hand)")
            rows.append(("rewritten", line, new_key, detail))
            out.append(new_key + eol)
        elif not matches:
            # A check runs when ANY of its `paths:` resolves (`grep.py`), so a
            # multi-path check in a partial checkout EXECUTES while some of its
            # paths are never scanned — and every baselined anchor under an
            # unscanned path looks exactly like a finding that went away. The
            # per-check hold cannot see this: the check is not skipped.
            #
            # The file's absence is the signal, and it is the honest one: if the
            # file is not there, this run cannot distinguish "the finding was
            # fixed" from "the path was not scanned", so it must not delete. It
            # also covers a moved file, a narrowed `include:`, a widened
            # `exclude:` — every way an anchor can fall out of scope without the
            # check skipping. Round 1's global refusal happened to cover this
            # case; round 2's narrower rule dropped a signed-off CRITICAL entry
            # and printed "it will re-fire if it moved", which was false.
            anchor_path = file_line.rsplit(":", 1)[0] if ":" in file_line else file_line
            if cid in incomplete_ids:
                # `degraded`: the stage ran and emitted findings, so its matched
                # entries migrate — but an entry it did NOT match may simply be
                # in the part it could not read. Absence of evidence.
                rows.append(("kept-incomplete", line, line,
                             "this check ran over less than its declared inputs "
                             "— held; re-run when the stage completes"))
                out.append(raw)
                continue
            if not os.path.exists(os.path.join(repo_root, anchor_path)):
                rows.append(("kept-unscanned", line, line,
                             f"{anchor_path} is not present in this checkout — "
                             "held, because a path that was not scanned cannot "
                             "be distinguished from a finding that was fixed"))
                out.append(raw)
                continue
            rows.append(("dropped-no-match", line, None,
                         "no current finding at this anchor, and the file is "
                         "present — the finding is gone or has moved"))
        else:
            rows.append(("dropped-collapsed", line, None,
                         f"{len(matches)} findings share this key; accepting "
                         f"all would accept {len(matches) - 1} never reviewed"))

    tmp_path = path + ".tmp"
    # Remove any pre-existing scratch file FIRST. `open(tmp, "w")` follows a
    # symlink, so a planted `.tmp` symlink wrote the consumer's baseline to an
    # arbitrary path and `os.replace` then made the baseline itself a symlink;
    # a planted `.tmp` DIRECTORY raised a bare traceback. Neither is hostile in
    # the usual case — a killed earlier run leaves one behind.
    try:
        if os.path.islink(tmp_path) or os.path.isfile(tmp_path):
            os.unlink(tmp_path)
        elif os.path.isdir(tmp_path):
            return [], (f"REFUSED: {tmp_path} is a directory — remove it and "
                        "re-run; the baseline is untouched.")
    except OSError as exc:
        return [], f"REFUSED: cannot clear {tmp_path}: {exc}"

    try:
        with open(tmp_path, "w", encoding="utf-8", errors="surrogateescape",
                  newline="") as f:
            f.writelines(out)
    except OSError as exc:
        # A raw traceback here reads as a crash; this is an ordinary,
        # actionable condition (a read-only `.claude/`, a full disk).
        return [], f"REFUSED: cannot write {tmp_path}: {exc}"
    # Carry the original mode across: a read-only baseline was silently reset
    # to 0644 by the replace, which is a permission change the consumer never
    # asked for on a file they had deliberately locked.
    try:
        os.chmod(tmp_path, os.stat(path).st_mode & 0o7777)
    except OSError:
        pass
    os.replace(tmp_path, path)
    return rows, None
