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
     `python3 ingest_security_report.py --root . --mark <dir> [<dir> ...] (--scope-file F --scope-digest D | --full)`

A mark records what the round FOLDED, not the report as a whole. On a scoped round only
the in-scope findings are recorded, and the report is offered again carrying just the
rest, so an out-of-scope finding surfaces when a later round's scope reaches it or on
the next `--full` round. A mark that names neither flag is refused: marking a scoped
round's reports whole loses those findings in silence.

A scoped mark re-reads the scope file, which is a fixed name another round can rewrite
in between, so it also takes the `scope_digest` the ingest printed and refuses when the
file no longer matches it. The flag is also what keeps an older script from taking a
scoped mark: it does not know `--scope-digest`, so argparse exits 2 before anything is
written, where `--scope-file` alone it ignored, and marked the report whole.

The ingest exits 0 for a readable root (degrade cleanly), and 1 only on a `--scope-file` it
cannot read, one given beside `--full`, or a `--scope-digest` given without a scoped mark;
the skill treats any failure as "ingest unavailable, continue the audit". A mark exits 1
when it refuses (a missing, contradictory or stale scope declaration, or a dir it cannot
read; nothing is written) or when what it computed does not write and read back (part may
have landed; the error says so). A mark whose reports had no finding in scope computes
nothing new, records nothing, and exits 0. Options are never abbreviated (exit 2).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
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

# The ingested-report marker (gitignored via sysop/runtime/). A bare report dir
# basename on a line means the whole report is folded and is never offered again,
# so a persistent gitignored report dir is not re-surfaced on every audit.
# `<dir>\t<key>` means one finding of that report is folded (`finding_key`); the
# report is still offered, without it. An older script reads a keyed line as a dir
# name no report has and offers the report again in full, which re-files rather
# than loses.
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
    malformed: int = 0        # results lines that were not a readable finding


def _load_jsonl_counted(path: Path) -> tuple[list | None, int]:
    """Load a JSONL findings file tolerantly: (findings, lines dropped). Blank lines
    are skipped; a line that is not JSON, not an object, or missing a required
    field is dropped (not fatal) and counted, so the caller can say so. None when
    the file cannot be read or is not UTF-8 — the caller skips the report loudly,
    never reads it as empty."""
    out, bad = [], 0
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None, 0
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            bad += 1
            continue
        if isinstance(obj, dict) and all(k in obj for k in REQUIRED_FIELDS):
            out.append(obj)
        else:
            bad += 1
    return out, bad


def _load_jsonl(path: Path) -> list | None:
    """`_load_jsonl_counted` without the count."""
    return _load_jsonl_counted(path)[0]


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
    findings, rep.malformed = _load_jsonl_counted(jsonl)
    if findings is None:
        rep.skipped_reason = f"{RESULTS_JSONL} could not be read, or is not UTF-8"
        return rep
    rep.findings = findings
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


def _commit_changed_files(repo_root: Path, commit: str) -> tuple[set | None, str]:
    """Best-effort: (the set of paths changed between `commit` and the working
    tree, ""), or (None, why git could not answer) — the reason is shown on every
    finding whose staleness it leaves unknown, so it must be the true one."""
    short = str(commit)[:12]
    try:
        exists = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "-e", f"{commit}^{{commit}}"],
            capture_output=True,
        )
        if exists.returncode != 0:
            return None, f"commit {short} not in local history"
        # -c core.quotePath=false + -z: git C-quotes non-ASCII paths by default,
        # which would never match the UTF-8 repo_rel and silently mis-read a
        # changed non-ASCII file as "current". `--` pins commit as a revision.
        res = subprocess.run(
            ["git", "-C", str(repo_root), "-c", "core.quotePath=false",
             "diff", "-z", "--name-only", commit, "--"],
            capture_output=True, text=True,
        )
        if res.returncode != 0:
            return None, f"git diff against {short} failed"
    except UnicodeDecodeError:
        return None, f"git names a file changed since {short} whose path is not UTF-8"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"git could not be run ({type(exc).__name__})"
    return {p for p in res.stdout.split("\0") if p}, ""


class _StalenessResolver:
    """Caches the per-commit changed-file set so staleness costs one git call per
    report, not one per finding."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self._cache: dict = {}

    def changed(self, commit: str) -> set | None:
        return self._lookup(commit)[0]

    def _lookup(self, commit: str) -> tuple[set | None, str]:
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
        changed, why = self._lookup(commit)
        if changed is None:
            return "unknown", why
        dirty_note = " (scanned tree was dirty)" if revision.get("dirty") else ""
        if repo_rel_path in changed:
            return "stale", f"file changed since scan at {str(commit)[:12]}{dirty_note}"
        return "current", ""


# --------------------------------------------------------------------------- #
# Normalization + union
# --------------------------------------------------------------------------- #
def identity(raw: dict, rep: Report, repo_root: Path) -> tuple[str, int, str] | None:
    """(repo-relative path, line, dedup key) for one raw finding, or None when its
    path escapes the repo. `normalize` and the mark both call it, so the finding a
    mark records is exactly the finding the ingest emitted.

    The dedup key uses the RAW (untruncated, unsanitized) title + category so two
    *distinct* findings whose display titles collide after truncation/sanitization
    are never merged-and-dropped (the never-supersede invariant). `ingest()` strips
    it from the emitted output."""
    repo_rel = rebase_path(rep.scan_root, str(raw.get("file", "")), repo_root)
    if repo_rel is None:
        return None
    try:
        line = max(0, int(raw.get("line") or 0))   # a negative line is meaningless
    except (TypeError, ValueError, OverflowError):   # OverflowError: JSON `1e999` is inf
        line = 0
    dedup_key = "\x00".join(
        [repo_rel, str(line), str(raw.get("category", "")), str(raw.get("title", ""))]
    )
    return repo_rel, line, dedup_key


def finding_key(dedup_key: str) -> str:
    """The marker's name for one finding. A hash, because the raw key can hold a
    tab or a newline; `surrogatepass`, because `json.loads` turns a lone `\\ud800`
    escape into a lone surrogate, which strict UTF-8 refuses to encode."""
    return hashlib.sha256(dedup_key.encode("utf-8", "surrogatepass")).hexdigest()


def normalize(raw: dict, rep: Report, repo_root: Path, resolver: _StalenessResolver) -> dict | None:
    """Turn one raw finding into a sanitized, provenance-tagged Sysop finding.
    Returns None if the finding is unusable (path escapes the repo)."""
    ident = identity(raw, rep, repo_root)
    if ident is None:
        return None
    repo_rel, line, dedup_key = ident
    severity = str(raw.get("severity", "")).upper()
    emoji = SEVERITY_EMOJI.get(severity, "🔴")  # security default when unknown

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
# Marker (what earlier rounds folded)
# --------------------------------------------------------------------------- #
def _marker_entries(p: Path) -> tuple[set | None, str]:
    """(the recorded dir names, "") — or (None, why) when the marker exists but
    cannot be read or decoded. A missing marker is (set(), "")."""
    try:
        return {ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()}, ""
    except FileNotFoundError:
        return set(), ""
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _split_marker(entries: set) -> tuple[set, dict]:
    """(whole-report dir names, {dir name: folded finding keys})."""
    whole: set = set()
    keyed: dict = {}
    for e in entries:
        d, tab, k = e.partition("\t")
        if tab:
            keyed.setdefault(d.strip(), set()).add(k.strip())
        else:
            whole.add(e)
    return whole, keyed


def read_marker_state(repo_root: Path) -> tuple[set, dict]:
    """(whole-report dir names, {dir name: folded finding keys}). No marker yet is
    the ordinary first run and reads as empty in silence. A marker that EXISTS but
    cannot be read or decoded also reads as empty, so every folded report is
    offered again — said on stderr."""
    p = repo_root / MARKER_REL
    have, why = _marker_entries(p)
    if have is None:
        print(f"WARN: could not read the ingested marker {sanitize(str(p), 300)} "
              f"({sanitize(why, 300)}) — every report it "
              "recorded is treated as NOT yet ingested and will be offered again",
              file=sys.stderr)
        return set(), {}
    return _split_marker(have)


def read_marker(repo_root: Path) -> set:
    """The report dirs folded whole (see `read_marker_state`)."""
    return read_marker_state(repo_root)[0]


def append_marker(repo_root: Path, dir_names: list, keys: dict | None = None) -> str:
    """Record `dir_names` as folded whole, and each `keys[dir]` finding as folded.
    Returns "" on success, or why the mark did not land — the caller reports it.
    "Landed" means READ BACK: a mark appended to a marker that cannot be decoded is
    written and never read, so the report is offered again while the run said
    `marked`."""
    p = repo_root / MARKER_REL
    have, why = _marker_entries(p)
    if have is None:
        return f"the marker cannot be read ({why}); nothing was appended"
    lines = [d for d in dir_names if d]
    for d, ks in (keys or {}).items():
        lines.extend(f"{d}\t{k}" for k in ks)
    new = list(dict.fromkeys(ln for ln in lines if ln not in have))  # dedup input too
    if not new:
        return ""
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            for ln in new:
                fh.write(ln + "\n")
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    back, why = _marker_entries(p)
    if back is None or not set(new) <= back:
        return f"the mark was written but does not read back ({why or 'entries missing'})"
    return ""


def plan_mark(repo_root: Path, dir_names: list, scope: set | None) -> tuple[list, dict, dict, str]:
    """What a mark records: (dirs folded whole, {dir: newly folded finding keys},
    {dir: findings still deferred}, "" or why nothing may be recorded).

    Every name must be a report directory under the root, whatever the scope: a
    typo recorded is a report offered forever and a mark reported as landed.
    `scope` None is a `--full` round: every finding was folded, so each dir is
    recorded whole without its findings being read. Otherwise each is read, and only the
    findings whose file is in `scope` are recorded, beside any recorded earlier;
    a report whose every finding is now recorded goes whole. One dir that cannot
    be read refuses the whole mark, so nothing is recorded that was not folded."""
    # a shell's tab completion writes `CLAUDE-SECURITY-…/`, a name no report has
    names = list(dict.fromkeys(d.rstrip("/") for d in dir_names if d.rstrip("/")))
    for d in names:
        if not REPORT_DIR_RE.match(d) or not (repo_root / d).is_dir():
            return [], {}, {}, f"{d} is not a report directory under the root; nothing was appended"
    if scope is None:
        return names, {}, {}, ""
    have, why = _marker_entries(repo_root / MARKER_REL)
    if have is None:
        return [], {}, {}, f"the marker cannot be read ({why}); nothing was appended"
    whole_have, keyed_have = _split_marker(have)
    whole, keys, deferred = [], {}, {}
    for d in names:
        if d in whole_have:
            whole.append(d)          # already whole; `append_marker` writes no duplicate
            continue
        rep = parse_report(repo_root / d)
        if rep.skipped_reason:
            return [], {}, {}, f"{d} cannot be read ({rep.skipped_reason}); nothing was appended"
        before = keyed_have.get(d, set())
        folded, every = set(before), set()
        for raw in rep.findings:
            try:
                ident = identity(raw, rep, repo_root)
            except Exception:  # noqa: BLE001 — `ingest` drops the same finding
                ident = None
            if ident is None:
                continue
            k = finding_key(ident[2])
            every.add(k)
            if ident[0] in scope:
                folded.add(k)
        if every <= folded:
            whole.append(d)
        else:
            if folded - before:
                keys[d] = sorted(folded - before)
            deferred[d] = len(every - folded)
    return whole, keys, deferred, ""


def scope_digest(scope: set) -> str:
    """A short name for one scope set, printed by the ingest and required back by a
    scoped mark, so the mark can tell the scope file was rewritten in between."""
    return hashlib.sha256("\n".join(sorted(scope)).encode("utf-8", "surrogatepass")).hexdigest()[:16]


def find_reports(repo_root: Path, include_ingested: bool) -> tuple[list, dict]:
    """(report dirs to read, {dir name: finding keys already folded})."""
    whole, keyed = (set(), {}) if include_ingested else read_marker_state(repo_root)
    dirs = []
    try:
        entries = sorted(repo_root.iterdir())
    except OSError:
        return dirs, keyed
    for d in entries:
        if d.is_dir() and REPORT_DIR_RE.match(d.name) and d.name not in whole:
            dirs.append(d)
    return dirs, keyed


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def ingest(repo_root: Path, scope: set | None, include_ingested: bool) -> dict:
    resolver = _StalenessResolver(repo_root)
    reports_meta = []
    skipped = []
    all_findings = []

    dirs, folded_keys = find_reports(repo_root, include_ingested)
    for rdir in dirs:
        # Belt-and-suspenders on the never-raise contract: a single malformed
        # report (or one bad finding) is surfaced as `skipped`, never allowed to
        # abort the loop and suppress every other report's findings.
        try:
            rep = parse_report(rdir)
            if rep.skipped_reason:
                skipped.append({"report": rep.dir_name, "reason": rep.skipped_reason})
                continue
            norm = []
            dropped = 0
            for raw in rep.findings:
                try:
                    f = normalize(raw, rep, repo_root, resolver)
                except Exception:  # noqa: BLE001 — one bad finding must not sink the report
                    f = None
                if f is not None:
                    norm.append(f)
                else:
                    dropped += 1
            if rep.malformed:
                rep.caveats.append(f"{rep.dir_name}: {rep.malformed} line(s) of {RESULTS_JSONL} "
                                   "were not a readable finding (not JSON, or missing a "
                                   "required field) and were not ingested")
            if dropped:
                # said, never silent: a report scanned from another checkout drops them all
                rep.caveats.append(f"{rep.dir_name}: {dropped} finding(s) not ingested: the path is outside "
                                   "this repo, or the finding could not be normalized")
            # a finding an earlier round's mark recorded is not offered again;
            # the report's other findings are (`plan_mark`)
            folded = folded_keys.get(rep.dir_name, set())
            fresh = [f for f in norm if finding_key(f["_dedup"]) not in folded]
            previously_folded = len(norm) - len(fresh)
            norm = fresh
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
                "previously_folded": previously_folded,
                "dropped": dropped,
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
        "scope_digest": None if scope is None else scope_digest(scope),
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


class ScopeFileUnreadable(Exception):
    """An explicit --scope-file that cannot be read or decoded."""


def _load_scope(scope_file: str | None) -> set | None:
    """None means "no scoping" and is returned ONLY when no --scope-file was given.
    A named file that cannot be read raises: reading it as "no scoping" would file
    a whole-repo report as this round's delta — the flood the flag exists to stop."""
    if not scope_file:
        return None
    try:
        text = Path(scope_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ScopeFileUnreadable(f"{type(exc).__name__}: {exc}") from None
    return {ln.strip().replace(os.sep, "/") for ln in text.splitlines() if ln.strip()}


def main(argv=None) -> int:
    # allow_abbrev=False: `--ma D --fu` would otherwise run as `--mark D --full`, a spelling
    # the skill's guards do not look for
    ap = argparse.ArgumentParser(description="Ingest a claude-security report into /security-audit.",
                                 allow_abbrev=False)
    ap.add_argument("--root", default=".", help="repo root to scan for report dirs")
    ap.add_argument("--scope-file", default=None,
                    help="file listing in-scope repo-relative paths (one per line)")
    ap.add_argument("--json", action="store_true", help="emit JSON on stdout")
    ap.add_argument("--include-ingested", action="store_true",
                    help="do not skip reports already recorded in the marker")
    ap.add_argument("--mark", nargs="*", default=None, metavar="DIR",
                    help="record what this round folded from these report dirs, then exit; "
                         "needs --scope-file (a scoped round) or --full")
    ap.add_argument("--scope-digest", default=None, metavar="D",
                    help="with --mark --scope-file: the scope_digest the round's ingest printed")
    ap.add_argument("--full", action="store_true",
                    help="the round is --full: nothing is out of scope (with --mark, every "
                         "finding of each named report was folded)")
    args = ap.parse_args(argv)

    repo_root = Path(args.root)
    if args.full and args.scope_file:
        print("ERROR: --full and --scope-file contradict each other: a --full round has no "
              "scope file. Nothing was read or recorded.", file=sys.stderr)
        return 1
    if args.scope_digest is not None and not (args.mark is not None and args.scope_file):
        print("ERROR: --scope-digest goes only with --mark --scope-file. Nothing was read or "
              "recorded.", file=sys.stderr)
        return 1
    if args.mark is not None and args.scope_file and not args.scope_digest:
        print("ERROR: a scoped --mark needs --scope-digest <the scope_digest this round's ingest "
              "printed>, so it can tell the scope file was not rewritten since. Nothing was "
              "recorded.", file=sys.stderr)
        return 1
    if args.mark is not None and not (args.full or args.scope_file):
        print("ERROR: --mark needs --scope-file <this round's scope file> on a scoped round, "
              "or --full on a --full round. Marking a scoped round's reports whole would hide "
              "their out-of-scope findings for good. Nothing was recorded.", file=sys.stderr)
        return 1
    try:
        scope = _load_scope(args.scope_file)
    except ScopeFileUnreadable as exc:
        if args.mark is not None:
            print(f"ERROR: --scope-file {sanitize(args.scope_file, 300)} could not be read "
                  f"({sanitize(str(exc), 300)}), so what this round folded is unknown. "
                  "Nothing was recorded; these reports will be offered again.", file=sys.stderr)
        else:
            print(f"ERROR: --scope-file {sanitize(args.scope_file, 300)} could not be read "
                  f"({sanitize(str(exc), 300)}). Refusing to ingest unscoped — fix the file "
                  "and re-run; do not drop the flag on a non-full round.", file=sys.stderr)
        return 1
    if args.mark is not None and scope is not None and scope_digest(scope) != args.scope_digest:
        print(f"ERROR: {sanitize(args.scope_file, 300)} no longer matches the scope this round's "
              f"ingest bucketed with (digest {scope_digest(scope)}, expected "
              f"{sanitize(args.scope_digest, 40)}): another round may have rewritten it. Nothing "
              "was recorded; these reports will be offered again.", file=sys.stderr)
        return 1
    if args.mark is not None:
        whole, keys, deferred, failed = plan_mark(repo_root, args.mark, scope)
        if not failed:
            failed = append_marker(repo_root, whole, keys)
        if failed:
            print(f"ERROR: could not record the mark in {sanitize(str(repo_root / MARKER_REL), 300)} "
                  f"({sanitize(failed, 300)}) — the mark did not land (or landed only in "
                  "part), so these reports can be offered again next round.", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"marked": whole, "deferred": deferred}))
        else:
            print(f"claude-security mark: {len(whole)} report(s) folded whole; "
                  f"{sum(deferred.values())} finding(s) in {len(deferred)} report(s) "
                  "left for a round whose scope reaches them")
        return 0

    if not repo_root.is_dir():
        result = {"scope_digest": None if scope is None else scope_digest(scope),
                  "reports": [], "skipped": [], "trust": {"status": "none", "reasons": [], "caveats": []},
                  "findings": [], "out_of_scope": [],
                  "counts": {"in_scope": 0, "out_of_scope": 0, "stale": 0, "stale_unknown": 0,
                             "reports": 0, "skipped": 0}}
    else:
        result = ingest(repo_root, scope, args.include_ingested)

    if args.json:
        # a lone surrogate (`json.loads` of a `\ud800` escape) cannot be printed as UTF-8;
        # write it back as the same JSON escape
        out = json.dumps(result, indent=2, ensure_ascii=False)
        print(re.sub(r"[\ud800-\udfff]", lambda m: f"\\u{ord(m.group()):04x}", out))
    else:
        c = result["counts"]
        print(f"claude-security ingest: {c['in_scope']} in-scope, {c['out_of_scope']} out-of-scope, "
              f"{c['stale']} stale, {c['reports']} report(s), {c['skipped']} skipped "
              f"[trust: {result['trust']['status']}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
