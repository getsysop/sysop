"""Pre-scan execution accounting (the executed / skipped / failed taxonomy).

The deterministic pre-scan is the layer that is supposed to be
model-independent and trustworthy, but its old summary line counted checks
*selected*, not checks *executed* — a stage that skipped its precondition or
crashed contributed nothing and changed nothing in the summary, so
``0 findings from 13 checks`` was the exact output of a genuinely healthy run
**and** of a run where nothing ran. This module records, per selected check,
which of three terminal states it reached and renders a summary that
distinguishes them.

See ``tools/PRESCAN_ACCOUNTING_SPEC.md`` for the design and provenance
(cross-harness comparison run 2026-07-19/20: five independent silent-skip
paths, 5 of 25 checks executing while the summary said ``890 findings from
25 checks``).

Terminal states (§1 of the spec):

* ``executed``  — the tool/scan ran to completion over its inputs. A
  zero-findings executed check is a real zero.
* ``skipped``   — a precondition was absent; the tool never ran (or ran for
  nothing). Reasons: ``paths-unresolved`` / ``tool-missing`` /
  ``input-missing`` / ``not-installed`` / ``not-configured`` /
  ``misconfigured``.
* ``failed``    — the tool started and broke: nonzero exit with no parseable
  output, timeout, non-JSON output, grep rc≥2, a caught exception.

Cut line: *skipped = precondition absent; failed = attempted and died.*
Timeouts are ``failed`` (work was lost, not declined).
"""
from collections import namedtuple

from _log import _sanitize_log


EXECUTED = "executed"
SKIPPED = "skipped"
FAILED = "failed"

# Grep determines its status but has no check id at the call site, so it hands
# an Outcome back up to ``run_check`` (which owns the single per-check record
# point). The tool-shelling stages (pyright/semgrep/eslint/pip-audit/coverage)
# hold their ids and record directly, so they don't use this.
Outcome = namedtuple("Outcome", ["status", "reason", "detail"])

_Record = namedtuple("_Record", ["status", "stage", "reason", "detail"])


def is_placeholder_token(value):
    """True when a scope entry is unsubstituted placeholder vocabulary.

    Mirrors ``config.check_paths_by_id``'s strip test (an entry is a
    placeholder when it contains an angle bracket, e.g. ``<api module>/``).
    """
    s = str(value)
    return "<" in s or ">" in s


def check_is_localized(check):
    """True when a check has at least one concrete (non-placeholder) scope entry.

    A check with no ``paths:``/``critical_path:`` at all, or whose every scope
    entry is an unsubstituted ``<placeholder>``, is NOT localized — its gate is
    unarmed on this install, so a non-``executed`` state renders as a calm
    "not yet configured" line rather than the dead-gate ⚠. The ⚠ must only ever
    mean "this gate was armed and is now dead"; a warning that is on from the
    first install forever just trains consumers to ignore it (spec §3).

    Non-list scope fields contribute nothing (defensive): ``_validate_check``
    already rejects a scalar ``paths:``/``critical_path:`` at parse time, but a
    ``RunReport`` built directly (a test, a future caller) must never crash or
    char-split a stray scalar into single-character "localized" globs.
    """
    def _entries(field):
        v = check.get(field)
        return v if isinstance(v, list) else []
    entries = _entries("paths") + _entries("critical_path")
    if not entries:
        return False
    return any(not is_placeholder_token(e) for e in entries)


def stderr_excerpt(text, limit=200):
    """One-line, ANSI-stripped, length-capped excerpt for a ``failed`` detail."""
    if not text:
        return "(no stderr)"
    collapsed = " ".join(str(text).split())
    return _sanitize_log(collapsed)[:limit]


class RunReport:
    """Accumulates the per-check terminal state across every pre-scan stage.

    Construct from the *selected* check dicts (the mode-filtered set, or every
    check under ``--update-baseline``). Each stage records its checks as it
    runs; ``render`` turns the accumulated state into the summary block.
    """

    def __init__(self, selected_checks):
        self._checks = list(selected_checks)
        self._order = [c.get("id", "") for c in self._checks]
        self._blocking = {
            c.get("id", "") for c in self._checks if c.get("blocking") is True
        }
        self._localized = {
            c.get("id", ""): check_is_localized(c) for c in self._checks
        }
        self._records = {}  # check_id -> _Record

    def record(self, check_ids, status, stage, reason=None, detail=None):
        """Record ``status`` for each id in ``check_ids``.

        Record-once semantics (spec §2): the first recorded state wins,
        **except** ``failed`` overrides an earlier ``executed`` — a stage that
        scanned and then crashed in post-processing is failed, not clean.
        Same-state re-records are idempotent no-ops.
        """
        for cid in check_ids:
            existing = self._records.get(cid)
            if existing is None or (
                status == FAILED and existing.status == EXECUTED
            ):
                self._records[cid] = _Record(status, stage, reason, detail)

    def status_of(self, check_id):
        rec = self._records.get(check_id)
        return rec.status if rec else None

    def counts(self):
        """Return ``(executed, skipped, failed, unaccounted, selected)``.

        ``unaccounted`` is any selected check that reached no terminal state —
        an accounting bug (a stage wired for dispatch but not for recording),
        not a normal outcome.
        """
        executed = skipped = failed = unaccounted = 0
        for cid in self._order:
            st = self.status_of(cid)
            if st == EXECUTED:
                executed += 1
            elif st == SKIPPED:
                skipped += 1
            elif st == FAILED:
                failed += 1
            else:
                unaccounted += 1
        return (executed, skipped, failed, unaccounted, len(self._order))

    def blocking_failures(self):
        """``(id, stage, reason, detail)`` for every blocking check in ``failed``.

        A ``blocking: true`` check whose stage crashed produces zero findings
        and would otherwise pass the gate silently — this is what the §4
        ``failed``-is-fatal rule keys on. (A *skipped* blocking check is loud
        but non-fatal — see the spec on why gate-on-skipped cannot ship.)
        """
        out = []
        for cid in self._order:
            if cid in self._blocking and self.status_of(cid) == FAILED:
                rec = self._records[cid]
                out.append((cid, rec.stage, rec.reason, rec.detail))
        return out

    def render(self, findings, *, mode, baseline_matched=0, new_blocking=0):
        """Render the multi-line summary block (spec §3).

        ``findings`` is the full finding list (baseline-matched included, as the
        header count has always been); its check ids tell us which *executed*
        checks produced zero findings — the line that separates a real zero
        from a never-ran zero.
        """
        executed, skipped, failed, unaccounted, selected = self.counts()
        ids_with_findings = {cid for cid, _, _ in findings}

        count_parts = [
            f"{executed} executed",
            f"{skipped} skipped",
            f"{failed} failed",
        ]
        if unaccounted:
            count_parts.append(f"{unaccounted} unaccounted")
        header = (
            f"--- {len(findings)} finding(s) · checks: "
            + " / ".join(count_parts)
            + f" of {selected} selected "
            f"(mode: {mode}; baseline-matched: {baseline_matched}; "
            f"new blocking: {new_blocking}) ---"
        )
        lines = [header]

        # Non-executed detail lines, aggregated per (status, stage, reason).
        # Insertion order preserves the record order; failed lines are emitted
        # before skipped (severity-first).
        groups = {}
        for cid in self._order:
            rec = self._records.get(cid)
            if rec is None or rec.status == EXECUTED:
                continue
            key = (rec.status, rec.stage, rec.reason)
            group = groups.setdefault(key, {"ids": [], "detail": rec.detail})
            group["ids"].append(cid)

        for want in (FAILED, SKIPPED):
            for (status, stage, reason), group in groups.items():
                if status != want:
                    continue
                ids = group["ids"]
                noun = "check" if len(ids) == 1 else "checks"
                detail = group["detail"] or reason or "no detail"
                line = f"    {status}: {stage} ({len(ids)} {noun}) — {detail}"
                # ⚠ only for a LOCALIZED blocking check that did not run — an
                # armed gate gone dead. Placeholder-scoped blocking checks are
                # unarmed and render calm (their detail already says so).
                if any(
                    cid in self._blocking and self._localized.get(cid)
                    for cid in ids
                ):
                    line += "  ⚠ BLOCKING CHECK DID NOT RUN"
                lines.append(line)

        unaccounted_ids = [
            cid for cid in self._order if self.status_of(cid) is None
        ]
        if unaccounted_ids:
            lines.append(
                f"    unaccounted: {len(unaccounted_ids)} "
                f"check{'' if len(unaccounted_ids) == 1 else 's'} "
                f"({', '.join(unaccounted_ids)}) — accounting bug, report upstream"
            )

        # executed-with-zero-findings, grouped by stage. Grep-stage ids render
        # as a bare count (a localized 40-check grep registry would otherwise
        # produce an unreadable enumerated line); tool-stage ids are enumerated
        # so a per-check zero is distinguishable from a never-ran check.
        zero_by_stage = {}
        for cid in self._order:
            rec = self._records.get(cid)
            if rec and rec.status == EXECUTED and cid not in ids_with_findings:
                zero_by_stage.setdefault(rec.stage, []).append(cid)
        for stage, ids in zero_by_stage.items():
            noun = "check" if len(ids) == 1 else "checks"
            if stage == "grep":
                lines.append(
                    f"    executed with 0 findings: {len(ids)} grep {noun}"
                )
            else:
                lines.append(
                    f"    executed with 0 findings: {len(ids)} {stage} {noun} "
                    f"({', '.join(ids)})"
                )

        return "\n".join(lines)
