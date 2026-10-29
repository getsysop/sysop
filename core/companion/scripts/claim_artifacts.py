#!/usr/bin/env python3
"""claim_artifacts.py — `/review-close` Step 2e: the claim-artifact report.

    python3 sysop/scripts/claim_artifacts.py "<branch 1>" "<branch 2>" ...

Run from the repo root, one argument per branch under review. Prints, for each branch, the
claim's newest run and which artifacts it holds, or why that is `UNKNOWN`. It reports and
never rejects. An unsubstituted argument exits 2.

The skill text is the contract: `/review-close` Step 2e says what each line means. This
file was that step's heredoc until Phase 387 (`Q-409` P3), moved verbatim.
"""
import json, re, subprocess, sys
from pathlib import Path

branches = [b for b in sys.argv[1:] if b.strip()]
if any("<" in b for b in branches):
    print("ERROR: placeholder not substituted: {!r}".format(branches), file=sys.stderr)
    sys.exit(2)
if not branches:
    print("2e: no branches under review — nothing to report.")
    sys.exit(0)

common = subprocess.run(["git", "rev-parse", "--git-common-dir"],
                        capture_output=True, text=True, check=True).stdout.strip()
main_root = Path(common).resolve().parent
runtime = main_root / "sysop" / "runtime"

# branch -> [claim ids]. FIRST `branch:` line per lock wins, matching
# `claim_task.sh`'s `awk '/^branch:/{...; exit}'` — a lock's free-text `notes:`
# tail can carry a column-0 `branch:` line, and two readers of that field
# disagreeing about which one counts is worse than either rule alone.
# Ambiguity is REPORTED, not resolved: `/sitrep` has no duplicate-lock-branch
# check (its duplicate check is on batch NUMBERS), so nothing else surfaces it.
by_branch = {}
locks_dir = runtime / "locks"
if locks_dir.is_dir():
    for lf in sorted(locks_dir.glob("*.lock")):
        try:
            if not lf.is_file():     # a FIFO blocks `read_text` forever
                continue
        except OSError:              # raised on EACCES below Python 3.13
            continue
        try:
            lines = lf.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        fields = {}
        for line in lines:
            if not line or line[0].isspace() or line.startswith(("-", "#")):
                continue
            k, sep, v = line.partition(":")
            if sep and k.strip() not in fields:
                fields[k.strip()] = v.strip()
        if fields.get("branch"):
            by_branch.setdefault(fields["branch"], []).append(
                fields.get("task_id") or lf.stem)

# Five of nine files Step 7-pre's resume router treats as authoritative; with
# the hook envelope(s) that is the six-artifact set. The spec's Q1 names four —
# it predates Part A, which shipped `planner-integrity.md` and `outcome.md` as
# first-class routing artifacts, so a four-item report is blind to the two files
# answering "was the plan re-gated?" and "did the executor already run?".
NAMES = ["plan.md", "planner-integrity.md", "review.md",
         "classification.md", "outcome.md"]


def verdict_of(path):
    """Parse the FENCED body first. `/claim-task` Step 7c writes `json.dumps(...)`
    inside a yaml fence, so its line on disk is `  "verdict": "PROCEED"`. The
    line fallback reads that line too, and `/auto-build` Phase 6d's unfenced
    one, whose one two-word verdict is `ALL FIXABLE`."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "unreadable"
    # `\x60{3}` rather than a literal fence: this block lives INSIDE a markdown
    # fence, and three literal backticks here close it early — which silently
    # reshuffles every later fence pair in the file. A shipped guard
    # (`test_flag_contract.py`) caught exactly that, by then reading unrelated
    # prose as a command block.
    m = re.search(r"\x60{3}(?:yaml|json)?[^\n]*\n(.*?)\n\x60{3}", text, re.S)
    if m:
        try:
            doc = json.loads(m.group(1))
            if isinstance(doc, dict) and isinstance(doc.get("verdict"), str):
                return doc["verdict"].strip()
        except Exception:
            pass
    m = re.search(r'^[\s>*_-]*"?verdict"?:[\s*_"]*([A-Za-z_]+(?:[ \t]+FIXABLE\b)?)',
                  text, re.MULTILINE | re.IGNORECASE)
    return " ".join(m.group(1).split()) if m else ""


for branch in branches:
    ids = by_branch.get(branch) or []
    if not ids:
        print("  {}: no lock names this branch — claim id unknown, "
              "so no artifacts were looked for".format(branch))
        continue
    if len(ids) > 1:
        print("  {}: AMBIGUOUS — {} locks name this branch ({}). Reporting none; "
              "reconcile the locks first.".format(branch, len(ids), ", ".join(ids)))
        continue
    claim_id = ids[0]
    claim_root = runtime / "claim" / claim_id
    if not claim_root.is_dir():
        print("  {} ({}): no artifact directory on disk — UNKNOWN, not "
              "'did not run' (sysop/runtime/ is gitignored)".format(branch, claim_id))
        continue
    # Per-branch containment for every filesystem call below. One unreadable
    # claim directory must not abort the whole report and take the healthy
    # branches' rows with it — that is the Phase-219 shape, and this step's own
    # three-valued rule makes an unreadable thing "cannot tell", not a crash.
    try:
        runs = sorted((q for q in claim_root.iterdir() if q.is_dir()), reverse=True)
    except OSError as exc:
        print("  {} ({}): claim directory unreadable ({}) — UNKNOWN"
              .format(branch, claim_id, exc.__class__.__name__))
        continue
    if not runs:
        print("  {} ({}): claim directory exists but holds no run — UNKNOWN"
              .format(branch, claim_id))
        continue
    run = runs[0]
    # Containment. This step only READS, so a symlinked run directory risks
    # disclosure rather than damage — but reporting an arbitrary directory's
    # contents as this claim's artifacts is a false report either way.
    try:
        if not run.resolve().is_relative_to(claim_root.resolve()):
            print("  {} ({}): newest run {} resolves outside the claim root — "
                  "skipped, not reported".format(branch, claim_id, run.name))
            continue
    except (OSError, ValueError):
        print("  {} ({}): run path could not be resolved — UNKNOWN"
              .format(branch, claim_id))
        continue
    extra = " (+{} older run(s))".format(len(runs) - 1) if len(runs) > 1 else ""
    try:
        present = [n for n in NAMES if (run / n).is_file()]
    except OSError:
        print("  {} ({}) run {}: artifacts unreadable — UNKNOWN"
              .format(branch, claim_id, run.name))
        continue
    absent = [n for n in NAMES if n not in present]
    # Both shapes Step 7-pre globs: the phased `<CLAIM_ID>.<phase>.json` the
    # build emits, and the bare `<CLAIM_ID>.json` that predates `PHASE:`.
    env_dir = runtime / "subagent-envelopes"
    try:
        envs = sorted(set(env_dir.glob(claim_id + ".*.json"))
                      | set(env_dir.glob(claim_id + ".json"))) if env_dir.is_dir() else []
        # An envelope the hook wrote but could not key lands under a different
        # name. Count those, so absence is never attributed to "the harness does
        # not write these" when one WAS written and simply failed to key.
        stray = len([q for q in env_dir.glob("*.json")
                     if q not in envs]) if env_dir.is_dir() else 0
    except OSError:
        envs, stray = [], 0
    print("  {} ({}) run {}{}".format(branch, claim_id, run.name, extra))
    print("      present: " + (", ".join(present) or "none"))
    print("      absent:  " + (", ".join(absent) or "none"))
    if envs:
        print("      hook envelopes: " + ", ".join(q.name for q in envs))
    elif stray:
        print("      hook envelopes: none matched this claim id ({} other envelope "
              "file(s) in the mailbox — check whether one failed to key)".format(stray))
    else:
        print("      hook envelopes: none on disk — Claude Code only, and transient")
    cls = run / "classification.md"
    print("      verdict: " + (verdict_of(cls) if cls.is_file()
                               else "no classification.md in this run"))
