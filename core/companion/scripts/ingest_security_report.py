#!/usr/bin/env python3
"""Ingest a `claude-security` plugin scan report into `/security-audit` (Phase 144).

Anthropic's `claude-security` Claude Code plugin runs an expensive, nondeterministic
multi-agent scan and writes a report to the repo root. Sysop cannot *launch* it (the
`Workflow` tool is stripped from every subagent, so `/security-audit` can't drive the
plugin's scan), but it can *read the report off disk* — which needs no harness support
at all. One head-to-head (2026-07-23, a single production codebase at one pinned commit)
measured **zero overlapping findings** between the two tools — one run, not a general
property, but consistent with the design: the plugin surfaces deep code-reasoning defects
the deterministic loop can't, so folding its report in as tracked `review_tasks.md` tasks
is real added coverage.

This module is the read-and-normalize boundary. It emits **sanitized, provenance-tagged
findings** on stdout as JSON for the `/security-audit` skill to file; the skill never
hand-copies from the raw report (it is untrusted input — see `sanitize`).

Hardened to a two-reviewer adversarial pass on the Phase-144 plan. The load-bearing
stances, each earned by a finding:

* **Tolerant parse, trust keyed off the STABLE contract.** The plugin promises only
  three things stable across releases: the two filenames, the JSONL field *order*, and
  `verification.status`/`reason` semantics (`render_report.py` docstring). The stamp's
  `run_shape`/`verification` sub-key *sets* are variable (3 keys when coverage is absent,
  ~14 when present) — so we read them defensively and NEVER assert an exact key set, and
  we key trust off `verification.status`+`reason`, not a hand-picked signal bundle. A
  drifted/unreadable report is *skipped with a loud reason*, never raised into the audit.
* **`verified` != coverage.** `verification.status` certifies per-finding panel
  completion, not that the scan covered the repo; a truncated run still renders
  `verified`. So untrusted-status is surfaced from `reason`, and coverage caveats
  (reduced-depth / examined-nothing / unaccounted dirs / unreviewed sites / dispatched>
  returned) are surfaced *as caveats*, informational, not alarm-triggers.
* **Untrusted text is sanitized before it can reach markdown.** Finding titles/bodies are
  model summaries of scanned code that may contain adversarial text; the raw JSONL escapes
  only its own line separators, not markdown. `sanitize` collapses newlines, neutralizes
  backticks and brackets (killing forged `[verified]` tags, `- [ ]` checkboxes, and
  `TASK-` rows), and caps length.
* **Provenance = `[reported]`, always.** The plugin's panel-verification is an upstream
  tool claim, not a Sysop site-read (`_shared/fanout-evidence.md`). It maps to `[reported]`;
  the panel result goes in the annotation as data, never onto the row's provenance tag, and
  an actuator must re-read the site before applying a fix.
* **Conservative union, never drop.** Across multiple report dirs we merge only exact
  `(file, line, category, title)` duplicates and keep every distinct finding — line drift
  between nondeterministic runs is left for the skill's ±5-line dedup + the human, because
  a lossy identity key that dropped a distinct finding would itself be the "supersede" the
  never-supersede rule forbids.
* **Best-effort git staleness.** Flagging "file changed since the scanned commit" needs
  git and is undefined for unversioned/dirty/absent-commit reports — those return
  `unknown`, noted, never dropped. Paths are rebased from the stamp's `scan_root`.

CLI: `python3 ingest_security_report.py --root . [--scope-file F] --json`
     `python3 ingest_security_report.py --root . --mark <dir> [<dir> ...]`
Exit is always 0 for a readable root (degrade cleanly); the skill treats any failure as
"ingest unavailable, continue the audit."
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# The plugin's canonical report-dir shape (mirrors the plugin's own
# patch_artifacts.py and its pre-approved `find` probe). Anchored so an aborted
# or renamed dir does not match.
REPORT_DIR_RE = re.compile(r"^CLAUDE-SECURITY-[0-9][0-9-]*$")
RESULTS_JSONL = "CLAUDE-SECURITY-RESULTS.jsonl"
STAMP_GLOB = "CLAUDE-SECURITY-REVISION-*.json"

# Fields we consume from each JSONL finding. A finding missing one of the
# load-bearing ones (identity + display) is skipped, not fatal.
REQUIRED_FIELDS = ("title", "file", "line", "category", "severity")

SEVERITY_EMOJI = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}

# The ingested-report marker (gitignored via sysop/runtime/). One report dir
# basename per line — a report folds in once, so a persistent gitignored report
# dir is not re-surfaced on every subsequent audit.
MARKER_REL = "sysop/runtime/ingested-security-reports"


# --------------------------------------------------------------------------- #
# Sanitization — the untrusted-input boundary
# --------------------------------------------------------------------------- #
def sanitize(text, limit: int = 500) -> str:
    """Neutralize a free-text field so it cannot break out of, or forge, the
    `review_tasks.md` markdown it will be written into.

    Defenses, each covering a demonstrated injection:
    * newlines/tabs -> space: a finding cannot start a new markdown line, so it
      cannot forge a `- [ ] **TASK-N**` row, a `### Batch`/`## Round` header, or a
      `> **OWASP:**` metadata line.
    * backticks -> apostrophe: cannot break the row's `` `file:line` `` / `` `[reported]` ``
      inline-code spans, nor open a ``` fence (relevant if a snippet is ever written).
    * brackets -> parens: kills a forged `[verified]`/`[reported]` provenance tag, a
      `[ ]`/`[x]` checkbox, and markdown link/reference syntax in one stroke.
    * length cap: bounds a giant blob.
    """
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = text.replace("`", "'")
    text = text.replace("[", "(").replace("]", ")")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


# --------------------------------------------------------------------------- #
# Report model
# --------------------------------------------------------------------------- #
@dataclass
class Report:
    dir_name: str
    findings: list = field(default_factory=list)  # raw dicts from the JSONL
    mode: str = ""            # scan | changes | commit | ""
    scan_root: str = ""       # stamp scan_root (finding paths are relative to it)
    revision: dict = field(default_factory=dict)
    generated_at: str = ""
    status: str = "unverified"
    reason: str = ""
    caveats: list = field(default_factory=list)
    skipped_reason: str = ""  # non-empty => the whole report could not be used


def _load_jsonl(path: Path) -> list:
    """Load a JSONL findings file tolerantly. Blank lines and lines missing a
    required field are dropped (not fatal); a line that is not JSON is dropped
    with the rest of the file left intact."""
    out = []
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        if all(k in obj for k in REQUIRED_FIELDS):
            out.append(obj)
    return out


def _load_stamp(report_dir: Path) -> dict | None:
    stamps = sorted(report_dir.glob(STAMP_GLOB))
    if not stamps:
        return None
    try:
        data = json.loads(stamps[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def trust(stamp: dict) -> tuple[str, str, list]:
    """Return (status, reason, caveats) from the stamp.

    PRIMARY (contractually stable): `verification.status`; if not "verified",
    the reason is `verification.reason`. SUPPLEMENTARY (best-effort, informational
    coverage caveats — read defensively): reduced-depth collapse, examined-nothing,
    unaccounted top-level dirs, unreviewed candidate sites, dispatched>returned.
    Deliberately NOT alarm-triggers: `skipped_components` and
    `completeness_check_outcome` are normal disclosure on scoped/whole-repo scans.
    """
    # verification / run_shape may be a non-dict on a drifted or hostile stamp —
    # coerce exactly as `revision` is (a truthy non-dict would AttributeError on
    # `.get`, violating the never-raise contract).
    ver = stamp.get("verification")
    ver = ver if isinstance(ver, dict) else {}
    status = sanitize(str(ver.get("status") or "unverified"), 40)
    if status == "verified":
        reason = ""
    else:
        reason = sanitize(str(ver.get("reason") or "verification.status is not 'verified'"))

    caveats: list = []
    shape = stamp.get("run_shape")
    shape = shape if isinstance(shape, dict) else {}
    collapsed = shape.get("collapsed")
    if collapsed:
        caveats.append(f"reduced-depth scan (collapsed: {sanitize(str(collapsed), 40)})")
    if shape.get("empty_scope") or shape.get("empty_diff"):
        caveats.append("scan examined nothing (empty scope/diff)")
    unaccounted = shape.get("unaccounted_top_level_dirs") or []
    if isinstance(unaccounted, list) and unaccounted:
        names = ", ".join(sanitize(str(d), 40) for d in unaccounted[:6])
        caveats.append(f"{len(unaccounted)} top-level dir(s) unaccounted: {names}")
    unreviewed = ver.get("unreviewed_candidate_sites")
    if isinstance(unreviewed, int) and unreviewed > 0:
        caveats.append(f"{unreviewed} candidate site(s) left unreviewed")
    disp = ver.get("researchers_dispatched")
    ret = ver.get("researchers_returned")
    if isinstance(disp, int) and isinstance(ret, int) and disp > ret:
        caveats.append(f"{disp} researchers dispatched, only {ret} returned")
    return status, reason, caveats


def parse_report(report_dir: Path) -> Report:
    """Load one report dir tolerantly. On any structural problem, return a Report
    whose `skipped_reason` is set — never raise."""
    rep = Report(dir_name=report_dir.name)
    jsonl = report_dir / RESULTS_JSONL
    if not jsonl.is_file():
        rep.skipped_reason = "no CLAUDE-SECURITY-RESULTS.jsonl (aborted or non-report dir)"
        return rep
    rep.findings = _load_jsonl(jsonl)
    stamp = _load_stamp(report_dir)
    if stamp is None:
        # No usable stamp -> cannot establish trust or paths. Keep findings but
        # mark untrusted; the skill surfaces this loudly.
        rep.status = "unverified"
        rep.reason = "no readable revision stamp — coverage and trust unknown"
        return rep
    # mode / generated_at are display fields written into markdown -> sanitize.
    # scan_root stays raw: it is used for path math (join/relpath), not display.
    rep.mode = sanitize(str(stamp.get("mode") or ""), 40)
    rep.scan_root = str(stamp.get("scan_root") or "")
    rev = stamp.get("revision")
    rep.revision = rev if isinstance(rev, dict) else {}
    rep.generated_at = sanitize(str(stamp.get("generated_at") or ""), 40)
    rep.status, rep.reason, rep.caveats = trust(stamp)
    return rep


# --------------------------------------------------------------------------- #
# Path rebasing + staleness (best-effort git)
# --------------------------------------------------------------------------- #
def rebase_path(scan_root: str, finding_file: str, repo_root: Path) -> str | None:
    """Rebase a finding's `file` (relative to the report's scan_root) to a path
    relative to the audit repo root. Returns None if it escapes the repo."""
    finding_file = (finding_file or "").strip()
    if not finding_file:
        return None
    try:
        if scan_root:
            abs_path = (Path(scan_root) / finding_file).resolve()
        else:
            abs_path = (repo_root / finding_file).resolve()
        rel = os.path.relpath(abs_path, repo_root.resolve())
    except (OSError, ValueError):
        return None
    # a real escape is exactly ".." or "../…" — a repo file named "..cfg" is fine
    if rel == ".." or rel.startswith(".." + os.sep):
        return None
    return rel.replace(os.sep, "/")


def _commit_changed_files(repo_root: Path, commit: str) -> set | None:
    """Best-effort: the set of paths changed between `commit` and the working
    tree. None if git can't answer (shallow clone, gc'd object, not a repo)."""
    try:
        exists = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "-e", f"{commit}^{{commit}}"],
            capture_output=True,
        )
        if exists.returncode != 0:
            return None
        # -c core.quotePath=false + -z: git C-quotes non-ASCII paths by default,
        # which would never match the UTF-8 repo_rel and silently mis-read a
        # changed non-ASCII file as "current". `--` pins commit as a revision.
        res = subprocess.run(
            ["git", "-C", str(repo_root), "-c", "core.quotePath=false",
             "diff", "-z", "--name-only", commit, "--"],
            capture_output=True, text=True,
        )
        if res.returncode != 0:
            return None
    except (OSError, subprocess.SubprocessError):
        return None
    return {p for p in res.stdout.split("\0") if p}


class _StalenessResolver:
    """Caches the per-commit changed-file set so staleness costs one git call per
    report, not one per finding."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self._cache: dict = {}

    def changed(self, commit: str) -> set | None:
        if commit not in self._cache:
            self._cache[commit] = _commit_changed_files(self.repo_root, commit)
        return self._cache[commit]

    def assess(self, revision: dict, repo_rel_path: str | None) -> tuple[str, str]:
        """Return (state, note) where state is 'stale' | 'current' | 'unknown'."""
        if not revision or revision.get("versioned") is False:
            return "unknown", "report scanned an unversioned tree"
        commit = revision.get("commit")
        if not commit:
            return "unknown", "report stamp has no commit"
        commit = str(commit)
        # commit is untrusted stamp text passed to git — require it look like a
        # hash (defense-in-depth; the `cat-file -e` gate already rejects options).
        if not re.fullmatch(r"[0-9a-fA-F]{7,64}", commit):
            return "unknown", "report stamp commit is not a valid hash"
        if repo_rel_path is None:
            return "unknown", "finding path could not be rebased into this repo"
        changed = self.changed(commit)
        if changed is None:
            return "unknown", f"commit {str(commit)[:12]} not in local history"
        dirty_note = " (scanned tree was dirty)" if revision.get("dirty") else ""
        if repo_rel_path in changed:
            return "stale", f"file changed since scan at {str(commit)[:12]}{dirty_note}"
        return "current", ""


# --------------------------------------------------------------------------- #
# Normalization + union
# --------------------------------------------------------------------------- #
def normalize(raw: dict, rep: Report, repo_root: Path, resolver: _StalenessResolver) -> dict | None:
    """Turn one raw finding into a sanitized, provenance-tagged Sysop finding.
    Returns None if the finding is unusable (path escapes the repo)."""
    repo_rel = rebase_path(rep.scan_root, str(raw.get("file", "")), repo_root)
    if repo_rel is None:
        return None
    severity = str(raw.get("severity", "")).upper()
    emoji = SEVERITY_EMOJI.get(severity, "🔴")  # security default when unknown
    try:
        line = max(0, int(raw.get("line") or 0))   # a negative line is meaningless
    except (TypeError, ValueError):
        line = 0

    category = sanitize(str(raw.get("category", "")), limit=60)
    title = sanitize(str(raw.get("title", "")), limit=160)
    stale_state, stale_note = resolver.assess(rep.revision, repo_rel)

    confidence = sanitize(str(raw.get("confidence", "")), limit=20)
    cwe = raw.get("cwe_id")
    cwe = sanitize(str(cwe), limit=20) if cwe else ""
    # commit is untrusted stamp text written into the row -> sanitize (12-char cap
    # alone does not neutralize a `\n- [ ] **TA` payload).
    commit = sanitize(str(rep.revision.get("commit") or "")[:12], 20) or "unversioned"
    annotation = (
        f"Source: claude-security scan, confidence {confidence or 'n/a'}, "
        f"cat {category or 'n/a'}, rev {commit}"
        + (f", generated {rep.generated_at}" if rep.generated_at else "")
        + (f", {cwe}" if cwe else "")
    )

    # Cross-report dedup key uses the RAW (untruncated, unsanitized) title +
    # category so two *distinct* findings whose display titles collide after
    # truncation/sanitization are never merged-and-dropped (the never-supersede
    # invariant). Stripped from the emitted output before return (see ingest()).
    dedup_key = "\x00".join(
        [repo_rel, str(line), str(raw.get("category", "")), str(raw.get("title", ""))]
    )

    return {
        "file": repo_rel,
        "line": line,
        "severity": severity or "HIGH",
        "severity_emoji": emoji,
        "provenance": "[reported]",
        "category": category,
        "title": title,
        "impact": sanitize(str(raw.get("impact", "")), limit=200),
        "summary": sanitize(str(raw.get("description", "")), limit=400),
        "exploit_scenario": sanitize(str(raw.get("exploit_scenario", "")), limit=400),
        "remediation": sanitize(str(raw.get("recommendation", "")), limit=400),
        "cwe_id": cwe,
        "confidence": confidence,
        "annotation": annotation,
        "stale": stale_state,           # stale | current | unknown
        "stale_note": stale_note,
        "source_revisions": [commit],
        "source_reports": [rep.dir_name],
        "_dedup": dedup_key,
    }


def union(findings_by_report: list) -> list:
    """Conservative cross-report union. Merge only exact
    (file, line, category, title) duplicates; keep every distinct finding.
    On a duplicate, record both source revisions/reports (never drop)."""
    merged: dict = {}
    order: list = []
    for f in findings_by_report:
        key = f["_dedup"]   # raw (file, line, category, title) — never the truncated display
        if key in merged:
            prev = merged[key]
            for rev in f["source_revisions"]:
                if rev not in prev["source_revisions"]:
                    prev["source_revisions"].append(rev)
            for rep in f["source_reports"]:
                if rep not in prev["source_reports"]:
                    prev["source_reports"].append(rep)
            # keep the higher severity label for display, but never drop
            if f["severity"] == "HIGH" and prev["severity"] != "HIGH":
                prev["severity"], prev["severity_emoji"] = "HIGH", "🔴"
        else:
            merged[key] = dict(f)
            order.append(key)
    return [merged[k] for k in order]


# --------------------------------------------------------------------------- #
# Marker (fold-once)
# --------------------------------------------------------------------------- #
def read_marker(repo_root: Path) -> set:
    p = repo_root / MARKER_REL
    try:
        return {ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()}
    except OSError:
        return set()


def append_marker(repo_root: Path, dir_names: list) -> None:
    p = repo_root / MARKER_REL
    have = read_marker(repo_root)
    new = list(dict.fromkeys(d for d in dir_names if d and d not in have))  # dedup input too
    if not new:
        return
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            for d in new:
                fh.write(d + "\n")
    except OSError:
        pass  # best-effort; a missed mark re-ingests once, not data loss


def find_reports(repo_root: Path, include_ingested: bool) -> list:
    ingested = set() if include_ingested else read_marker(repo_root)
    dirs = []
    try:
        entries = sorted(repo_root.iterdir())
    except OSError:
        return dirs
    for d in entries:
        if d.is_dir() and REPORT_DIR_RE.match(d.name) and d.name not in ingested:
            dirs.append(d)
    return dirs


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def ingest(repo_root: Path, scope: set | None, include_ingested: bool) -> dict:
    resolver = _StalenessResolver(repo_root)
    reports_meta = []
    skipped = []
    all_findings = []

    for rdir in find_reports(repo_root, include_ingested):
        # Belt-and-suspenders on the never-raise contract: a single malformed
        # report (or one bad finding) is surfaced as `skipped`, never allowed to
        # abort the loop and suppress every other report's findings.
        try:
            rep = parse_report(rdir)
            if rep.skipped_reason:
                skipped.append({"report": rep.dir_name, "reason": rep.skipped_reason})
                continue
            norm = []
            for raw in rep.findings:
                try:
                    f = normalize(raw, rep, repo_root, resolver)
                except Exception:  # noqa: BLE001 — one bad finding must not sink the report
                    f = None
                if f is not None:
                    norm.append(f)
            all_findings.extend(norm)
            reports_meta.append({
                "report": rep.dir_name,
                "mode": rep.mode,
                "revision": sanitize(str(rep.revision.get("commit") or "")[:12], 20) or "unversioned",
                "dirty": bool(rep.revision.get("dirty")),
                "generated_at": rep.generated_at,
                "status": rep.status,
                "reason": rep.reason,
                "caveats": rep.caveats,
                "finding_count": len(norm),
            })
        except Exception as exc:  # noqa: BLE001 — a bad report must not sink the ingest
            skipped.append({"report": rdir.name, "reason": f"unreadable report: {exc}"})
            continue

    findings = union(all_findings)

    # Partition by scope (never drop — out-of-scope is surfaced, not discarded).
    if scope is None:
        in_scope, out_of_scope = findings, []
    else:
        in_scope, out_of_scope = [], []
        for f in findings:
            (in_scope if f["file"] in scope else out_of_scope).append(f)

    statuses = {r["status"] for r in reports_meta}
    overall_status = "verified" if reports_meta and statuses == {"verified"} else (
        "unverified" if reports_meta else "none"
    )
    all_caveats = []
    for r in reports_meta:
        for c in r["caveats"]:
            if c not in all_caveats:
                all_caveats.append(c)
    reasons = [r["reason"] for r in reports_meta if r["reason"]]

    stale_count = sum(1 for f in in_scope if f["stale"] == "stale")
    unknown_stale = sum(1 for f in in_scope if f["stale"] == "unknown")

    for f in in_scope + out_of_scope:      # drop the internal dedup key from output
        f.pop("_dedup", None)

    return {
        "reports": reports_meta,
        "skipped": skipped,
        "trust": {
            "status": overall_status,
            "reasons": reasons,
            "caveats": all_caveats,
        },
        "findings": in_scope,
        "out_of_scope": out_of_scope,
        "counts": {
            "in_scope": len(in_scope),
            "out_of_scope": len(out_of_scope),
            "stale": stale_count,
            "stale_unknown": unknown_stale,
            "reports": len(reports_meta),
            "skipped": len(skipped),
        },
    }


def _load_scope(scope_file: str | None) -> set | None:
    if not scope_file:
        return None
    try:
        text = Path(scope_file).read_text(encoding="utf-8")
    except OSError:
        return None
    return {ln.strip().replace(os.sep, "/") for ln in text.splitlines() if ln.strip()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Ingest a claude-security report into /security-audit.")
    ap.add_argument("--root", default=".", help="repo root to scan for report dirs")
    ap.add_argument("--scope-file", default=None,
                    help="file listing in-scope repo-relative paths (one per line)")
    ap.add_argument("--json", action="store_true", help="emit JSON on stdout")
    ap.add_argument("--include-ingested", action="store_true",
                    help="do not skip reports already recorded in the marker")
    ap.add_argument("--mark", nargs="*", default=None, metavar="DIR",
                    help="append these report dir names to the ingested marker, then exit")
    args = ap.parse_args(argv)

    repo_root = Path(args.root)
    if args.mark is not None:
        append_marker(repo_root, args.mark)
        if args.json:
            print(json.dumps({"marked": args.mark}))
        return 0

    if not repo_root.is_dir():
        result = {"reports": [], "skipped": [], "trust": {"status": "none", "reasons": [], "caveats": []},
                  "findings": [], "out_of_scope": [],
                  "counts": {"in_scope": 0, "out_of_scope": 0, "stale": 0, "stale_unknown": 0,
                             "reports": 0, "skipped": 0}}
    else:
        result = ingest(repo_root, _load_scope(args.scope_file), args.include_ingested)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        c = result["counts"]
        print(f"claude-security ingest: {c['in_scope']} in-scope, {c['out_of_scope']} out-of-scope, "
              f"{c['stale']} stale, {c['reports']} report(s), {c['skipped']} skipped "
              f"[trust: {result['trust']['status']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
