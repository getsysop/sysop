"""
pr_dependabot.py — classify, plan, and (optionally) sweep Dependabot PRs.

A client-side replacement for GitHub's native auto-merge, which is unavailable
on private repos under the Free plan (`enablePullRequestAutoMerge` is gated
behind Pro/Team/Enterprise). Because GitHub will not be the merge actor, the
invoking agent is: this script lists open Dependabot PRs, classifies each by
ecosystem + semver bump, and either prints a dry-run plan (default) or executes
the plan (`--execute`) by merging the safe ones and closing the rest.

Merge policy (validated against ~50 real PRs — see Phase 53 in PHASE_LOG.md):

    npm / docker  patch|minor   -> merge   (gated on green CI + MERGEABLE)
    github-actions patch|minor   -> merge   (ONLY if publisher is trusted)
    *              major          -> hold    (human review)
    pip / chore(deps)             -> close   (Python deps owned by pip-compile)
    superseded duplicate          -> close   (older PR for same pkg+dir, lower
                                              target version, both open NOW)
    grouped / unparseable version -> surface (human decides)

Supersession is scoped to the CURRENTLY-OPEN set only — never to history.
Computed over history it produces false positives (the same package is bumped
repeatedly over weeks, each PR merging before the next opens). Dependabot also
auto-closes its own superseded PRs ("Looks like X is up-to-date now"), so this
handler is a safety net for the race window, not a primary job.

Usage:
    python3 scripts/pr_dependabot.py                 # dry-run plan (open PRs)
    python3 scripts/pr_dependabot.py --execute       # act on the plan
    python3 scripts/pr_dependabot.py --json          # structured plan to stdout
    python3 scripts/pr_dependabot.py --repo owner/n  # override repo autodetect
    python3 scripts/pr_dependabot.py --validate      # replay vs closed history

`gh` must be installed and authenticated (`gh auth status`). Repo is taken from
the current directory's git remote unless `--repo` is given.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field

# Single-sourced via scripts/_log.py (Phase 68) — `scripts/` is on sys.path[0]
# when this runs directly and on pythonpath under the test suite.
from _log import _sanitize_log

# ── Policy constants ─────────────────────────────────────────────

DEPENDABOT_AUTHOR = "app/dependabot"

# chore(<scope>): the scope maps to a Dependabot ecosystem. `deps` is this
# repo's label for pip security bumps (pip itself is excluded from
# dependabot.yml, but security updates bypass the ecosystem exclusion).
SCOPE_TO_ECOSYSTEM = {
    "npm": "npm",
    "actions": "github-actions",
    "deps": "pip",
    "pip": "pip",
    "docker": "docker",
}

# github-actions auto-merge is a supply-chain decision: a malicious Action
# update runs in CI with repo secrets. Only auto-merge patch/minor SHA bumps
# from publishers on this allowlist; everything else is surfaced for human eyes.
# Consumers EDIT this list. Org prefixes only (the part before the first `/`).
TRUSTED_ACTION_PUBLISHERS = {
    "actions", "github", "dependabot", "googleapis", "docker",
    "peter-evans", "gitleaks",
}

# Ecosystems whose patch/minor bumps auto-merge without a publisher gate.
AUTO_MERGE_ECOSYSTEMS = {"npm", "docker"}

# Terminal-state expectations used by --validate to score the classifier
# against real history. hold/surface are "human decides" — either outcome OK.
_VALIDATE_EXPECT = {
    "merge": "MERGED",
    "close-pip": "CLOSED",
    "close-superseded": "CLOSED",
}

# chore(<scope>): bump <pkg> [and <pkg2>] from <X> to <Y> [in /<dir>]
TITLE_RE = re.compile(
    r"chore\((?P<scope>[\w-]+)\):\s*bump\s+(?P<pkg>\S+?)"
    r"(?:\s+and\s+\S+)?(?:\s+from\s+(?P<from>[\w.\-]+)\s+to\s+(?P<to>[\w.\-]+))?"
    r"(?:\s+in\s+/(?P<dir>\S+))?$"
)

PR_FIELDS = (
    "number,title,state,mergeable,mergeStateStatus,statusCheckRollup,"
    "labels,headRefName,url"
)


# ── Data model ───────────────────────────────────────────────────


@dataclass
class Plan:
    """One PR's classification + planned action."""

    number: int
    title: str
    url: str
    ecosystem: str
    pkg: str
    bump: str | None       # patch | minor | major | None
    to_version: str | None
    directory: str | None
    action: str            # merge | hold | close-pip | close-superseded | surface
    reason: str
    state: str = "OPEN"    # terminal state (used by --validate)
    ci: str = "unknown"    # green | failing | pending | none | unknown
    mergeable: str = "UNKNOWN"

    def to_dict(self) -> dict:
        return {
            "number": self.number, "title": self.title, "url": self.url,
            "ecosystem": self.ecosystem, "pkg": self.pkg, "bump": self.bump,
            "directory": self.directory, "action": self.action,
            "reason": self.reason, "ci": self.ci, "mergeable": self.mergeable,
        }


# ── gh shell-out ─────────────────────────────────────────────────


def _gh(args: list[str], repo: str | None) -> str:
    """Run a `gh` command, return stdout. Raises on non-zero exit."""
    cmd = ["gh", *args]
    if repo:
        cmd += ["-R", repo]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"`{' '.join(cmd)}` failed: {r.stderr.strip()}")
    return r.stdout


def _list_prs(repo: str | None, state: str, limit: int = 50) -> list[dict]:
    out = _gh(
        ["pr", "list", "--author", DEPENDABOT_AUTHOR, "--state", state,
         "--limit", str(limit), "--json", PR_FIELDS],
        repo,
    )
    return json.loads(out)


# ── Pure classification helpers ──────────────────────────────────


def semver_bump(frm: str | None, to: str | None) -> str | None:
    """Return 'patch' | 'minor' | 'major', or None if versions are unparseable."""
    if not frm or not to:
        return None

    def parts(v: str) -> list[int]:
        nums = re.findall(r"\d+", v)
        return [int(n) for n in (nums + ["0", "0", "0"])[:3]]

    a, b = parts(frm), parts(to)
    if b[0] != a[0]:
        return "major"
    if b[1] != a[1]:
        return "minor"
    return "patch"


def ci_state(rollup: list[dict] | None) -> str:
    """Summarize statusCheckRollup -> 'green' | 'failing' | 'pending' | 'none'."""
    if not rollup:
        return "none"
    conclusions = []
    for c in rollup:
        status = c.get("status")
        conclusion = c.get("conclusion") or c.get("state")
        # A check still running (not COMPLETED, and not a terminal status state)
        # means we cannot gate yet.
        if status is not None and status != "COMPLETED" and conclusion not in (
            "SUCCESS", "FAILURE", "ERROR", "NEUTRAL", "SKIPPED",
        ):
            return "pending"
        conclusions.append(conclusion)
    if any(c in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED")
           for c in conclusions):
        return "failing"
    if all(c in ("SUCCESS", "NEUTRAL", "SKIPPED", None) for c in conclusions):
        return "green"
    return "pending"


def _publisher(pkg: str) -> str:
    """Org prefix of an Action ref: 'actions/checkout' -> 'actions'."""
    return pkg.split("/", 1)[0] if "/" in pkg else pkg


def classify(pr: dict) -> Plan:
    """Classify a single PR into an action. Supersession is applied later, over
    the full open set (see mark_superseded)."""
    m = TITLE_RE.match(pr["title"])
    base = dict(
        number=pr["number"], title=pr["title"], url=pr.get("url", ""),
        state=pr.get("state", "OPEN"),
        ci=ci_state(pr.get("statusCheckRollup")),
        mergeable=pr.get("mergeable", "UNKNOWN"),
    )
    if not m:
        return Plan(ecosystem="?", pkg="?", bump=None, to_version=None,
                    directory=None, action="surface",
                    reason="unparseable title — human decides", **base)

    eco = SCOPE_TO_ECOSYSTEM.get(m["scope"], m["scope"])
    bump = semver_bump(m["from"], m["to"])
    plan = Plan(ecosystem=eco, pkg=m["pkg"], bump=bump, to_version=m["to"],
                directory=m["dir"], action="surface", reason="", **base)

    if eco == "pip":
        plan.action, plan.reason = "close-pip", "pip owned by pip-compile workflow"
    elif bump is None:
        plan.action = "surface"
        plan.reason = "grouped/unparseable version — human decides"
    elif bump == "major":
        plan.action, plan.reason = "hold", f"{eco} major bump — human review"
    elif eco == "github-actions":
        if _publisher(m["pkg"]) in TRUSTED_ACTION_PUBLISHERS:
            plan.action = "merge"
            plan.reason = f"actions {bump} from trusted publisher — merge if green"
        else:
            plan.action = "surface"
            plan.reason = (f"actions {bump} from untrusted publisher "
                           f"'{_publisher(m['pkg'])}' — human review (supply chain)")
    elif eco in AUTO_MERGE_ECOSYSTEMS:
        plan.action = "merge"
        plan.reason = f"{eco} {bump} — merge if green"
    else:
        plan.action = "surface"
        plan.reason = f"{eco} {bump} — unrecognized ecosystem, human decides"
    return plan


def mark_superseded(plans: list[Plan]) -> None:
    """Flip older duplicates to close-superseded, IN PLACE.

    Two PRs are duplicates when they share (ecosystem, pkg, directory) and both
    are still candidates (merge/hold/surface). Keep the highest target version;
    the rest are superseded. Only fires when ≥2 such PRs coexist in the open set
    passed in — never across history.
    """
    groups: dict[tuple, list[int]] = {}
    for i, p in enumerate(plans):
        if p.action not in ("merge", "hold", "surface"):
            continue
        groups.setdefault((p.ecosystem, p.pkg, p.directory), []).append(i)

    for idxs in groups.values():
        if len(idxs) < 2:
            continue

        def version_key(i: int) -> list[int]:
            v = plans[i].to_version or "0"
            return [int(n) for n in (re.findall(r"\d+", v) + ["0", "0", "0"])[:3]]

        winner = max(idxs, key=version_key)
        for i in idxs:
            if i != winner:
                plans[i].action = "close-superseded"
                plans[i].reason = (f"superseded by newer {plans[i].pkg} bump "
                                   f"(#{plans[winner].number})")


def build_plans(prs: list[dict]) -> list[Plan]:
    plans = [classify(pr) for pr in prs]
    mark_superseded(plans)
    plans.sort(key=lambda p: -p.number)
    return plans


# ── Execution ────────────────────────────────────────────────────


def _resolve_mergeable(number: int, repo: str | None,
                       tries: int = 5, delay: float = 2.0) -> tuple[str, str]:
    """GitHub computes `mergeable` lazily; a fresh list often returns UNKNOWN.
    Poll `gh pr view` until it resolves or tries run out."""
    for attempt in range(tries):
        out = _gh(["pr", "view", str(number), "--json",
                   "mergeable,statusCheckRollup"], repo)
        data = json.loads(out)
        mergeable = data.get("mergeable", "UNKNOWN")
        ci = ci_state(data.get("statusCheckRollup"))
        if mergeable != "UNKNOWN":
            return mergeable, ci
        if attempt < tries - 1:
            time.sleep(delay)
    return "UNKNOWN", ci


def execute(plans: list[Plan], repo: str | None) -> list[str]:
    """Act on the plan. Returns a list of human-readable result lines."""
    results = []
    for p in plans:
        if p.action == "merge":
            mergeable, ci = _resolve_mergeable(p.number, repo)
            p.mergeable, p.ci = mergeable, ci
            if ci != "green":
                results.append(f"⏭  #{p.number} skip — CI not green (CI={ci})")
                continue
            if mergeable != "MERGEABLE":
                results.append(f"⏭  #{p.number} skip — not mergeable "
                               f"(mergeable={mergeable})")
                continue
            _gh(["pr", "merge", str(p.number), "--squash"], repo)
            results.append(f"✅ #{p.number} merged — {p.pkg} {p.to_version}")
        elif p.action == "close-pip":
            _gh(["pr", "close", str(p.number), "--comment",
                 "Closing: Python dependencies are managed by the pip-compile "
                 "workflow, not Dependabot. (pr-dependabot)"], repo)
            results.append(f"❌ #{p.number} closed — pip ({p.pkg})")
        elif p.action == "close-superseded":
            _gh(["pr", "close", str(p.number), "--comment",
                 f"Closing: {p.reason}. (pr-dependabot)"], repo)
            results.append(f"❌ #{p.number} closed — superseded ({p.pkg})")
        # hold / surface: never actuated — left open for the human.
    return results


# ── Rendering ────────────────────────────────────────────────────


_ICON = {"merge": "✅", "hold": "✋", "surface": "👀",
         "close-pip": "❌", "close-superseded": "❌"}


def render_plan(plans: list[Plan], executing: bool) -> str:
    if not plans:
        return "No open Dependabot PRs. Nothing to sweep."
    lines = []
    header = "PLANNED ACTIONS" if not executing else "EXECUTING"
    lines.append(header)
    lines.append("-" * 72)
    for p in plans:
        icon = _ICON.get(p.action, "?")
        gate = ""
        if p.action == "merge":
            gate = f"  [CI={p.ci}, mergeable={p.mergeable}]"
        bump = p.bump or "—"
        lines.append(f"{icon} #{p.number:<4} {p.action:<16} "
                     f"{p.ecosystem}/{p.pkg} {bump}{gate}")
        lines.append(f"       └─ {p.reason}")
    lines.append("-" * 72)
    counts: dict[str, int] = {}
    for p in plans:
        counts[p.action] = counts.get(p.action, 0) + 1
    summary = "  ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    lines.append(f"summary — {summary}")
    if not executing:
        lines.append("dry-run — nothing changed. Re-run with --execute to act.")
    return "\n".join(lines)


def render_validation(plans: list[Plan]) -> str:
    lines = [f"{'PR':>4}  {'verdict':<16} {'actual':<7} {'':2} pkg",
             "-" * 72]
    ok = mism = human = 0
    for p in sorted(plans, key=lambda x: -x.number):
        predicted = _VALIDATE_EXPECT.get(p.action)
        if predicted is None:           # hold / surface — human decides
            flag, human = "··", human + 1
        elif predicted == p.state:
            flag, ok = "OK", ok + 1
        else:
            flag, mism = "XX", mism + 1
        lines.append(f"{p.number:>4}  {p.action:<16} {p.state:<7} {flag:2} "
                     f"{p.ecosystem}/{p.pkg} {p.bump or ''}")
    lines.append("-" * 72)
    lines.append(f"deterministic — matches: {ok}  mismatches: {mism}   "
                 f"human-decides (hold/surface): {human}")
    lines.append("note: XX rows are worth inspecting — a 'merge' verdict on a "
                 "PR you closed may be a Dependabot self-close (open-set "
                 "supersession the validator cannot see).")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Classify & sweep Dependabot PRs.")
    ap.add_argument("--execute", action="store_true",
                    help="act on the plan (merge/close); default is dry-run")
    ap.add_argument("--json", action="store_true",
                    help="emit the structured plan as JSON")
    ap.add_argument("--repo", help="owner/name (default: autodetect from cwd)")
    ap.add_argument("--validate", action="store_true",
                    help="replay against closed history and score the classifier")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args(argv)

    try:
        if args.validate:
            prs = _list_prs(args.repo, "all", args.limit)
            plans = build_plans(prs)
            print(render_validation(plans))
            return 0

        prs = _list_prs(args.repo, "open", args.limit)
        plans = build_plans(prs)

        if args.json:
            print(json.dumps([p.to_dict() for p in plans], indent=2))
            return 0

        if args.execute:
            print(render_plan(plans, executing=True))
            results = execute(plans, args.repo)
            print()
            print("\n".join(results) if results else "Nothing actuated.")
        else:
            print(render_plan(plans, executing=False))
        return 0
    except RuntimeError as e:
        print(f"ERROR: {_sanitize_log(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
