"""
pr_dependabot.py — classify, plan, and (optionally) sweep Dependabot PRs.

A client-side replacement for GitHub's native auto-merge, which is unavailable
on private repos under the Free plan (`enablePullRequestAutoMerge` is gated
behind Pro/Team/Enterprise). Where GitHub will not be the merge actor, the
invoking agent is: this script lists open Dependabot PRs, classifies each by
ecosystem + semver bump, and either prints a dry-run plan (default) or executes
the plan (`--execute`) by merging the safe ones and closing the rest.

It does not assume the premise. Every run but `--validate` reads the repo's
`autoMergeAllowed` setting over GraphQL and prints one line: `allowed` (GitHub
can merge these PRs itself, so this sweep would be a second merge actor),
`not allowed`, or `unknown` with a reason (no read access, a gh error, an
unreadable response). `unknown` never stops the run; the plan proceeds as if the
setting were off.

Merge policy (validated against ~50 real PRs on the project this was extracted from):

    npm / docker  patch|minor   -> merge   (gated on green CI + MERGEABLE)
    github-actions patch|minor   -> merge   (ONLY if publisher is trusted)
    *              major          -> hold    (human review)
    pip / chore(deps)             -> close   (Python deps owned by pip-compile)
    superseded duplicate          -> close   (older PR for same pkg+dir, lower
                                              target version, both open NOW)
    grouped / unparseable version -> surface (human decides; never superseded,
                                              since there is no target version
                                              to keep the highest of)

Supersession is scoped to the CURRENTLY-OPEN set only — never to history.
Computed over history it produces false positives (the same package is bumped
repeatedly over weeks, each PR merging before the next opens). Dependabot also
auto-closes its own superseded PRs ("Looks like X is up-to-date now"), so this
handler is a safety net for the race window, not a primary job.

Usage:
    python3 sysop/scripts/pr_dependabot.py                 # dry-run plan (open PRs)
    python3 sysop/scripts/pr_dependabot.py --execute       # act on the plan
    python3 sysop/scripts/pr_dependabot.py --json          # structured plan to stdout
    python3 sysop/scripts/pr_dependabot.py --repo owner/n  # override repo autodetect
    python3 sysop/scripts/pr_dependabot.py --validate      # replay vs closed history

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

# Single-sourced via sysop/scripts/_log.py (Phase 68) — `sysop/scripts/` is on
# sys.path[0] when this runs directly and on pythonpath under the test suite.
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
    r"(?P<also>\s+and\s+\S+)?(?:\s+from\s+(?P<from>[\w.\-]+)\s+to\s+(?P<to>[\w.\-]+))?"
    r"(?:\s+in\s+/(?P<dir>\S+))?$"
)

PR_FIELDS = (
    "number,title,state,mergeable,mergeStateStatus,statusCheckRollup,"
    "labels,headRefName,url"
)

# The repo setting the `enablePullRequestAutoMerge` mutation refuses on ("Auto
# merge is not allowed for this repository"). Read over GraphQL because REST returns
# `allow_auto_merge: null` to a caller without admin rights, and `gh repo view`
# has no such field.
AUTO_MERGE_QUERY = (
    "query($owner:String!,$name:String!)"
    "{repository(owner:$owner,name:$name){autoMergeAllowed}}"
)

AUTO_MERGE_ALLOWED = "allowed"
AUTO_MERGE_NOT_ALLOWED = "not allowed"
AUTO_MERGE_UNKNOWN = "unknown"


# ── Data model ───────────────────────────────────────────────────


@dataclass
class AutoMergeReading:
    """The repo's native auto-merge setting, as the probe read it."""

    state: str             # allowed | not allowed | unknown
    reason: str = ""       # why the reading is `unknown`; empty otherwise

    def to_dict(self) -> dict:
        return {"state": self.state, "reason": self.reason}


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
    """Run a `gh` command, return stdout. Raises on non-zero exit.

    `repo` is appended as `-R`, which `gh api` rejects: callers of `gh api`
    pass `repo=None` and name the repo in the request itself."""
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


_REPO_URL_RE = re.compile(r"https?://([^/\s]+)/([^/\s]+)/([^/\s]+?)(?:\.git)?/?")
_PR_URL_RE = re.compile(r"https?://([^/\s]+)/([^/\s]+)/([^/\s]+)/pull/\d+")


def _auto_merge_args(repo: str | None) -> list[str] | None:
    """`gh api graphql` arguments naming the repo, or None if `repo` is not
    `[HOST/]OWNER/REPO` or a URL to one. With no `repo`, gh fills
    `{owner}`/`{repo}` from the current directory's remote but sends the
    request to its default host, so `probe_auto_merge` names the repo from
    the listed PRs first and uses this form only when there are none."""
    if not repo:
        return ["-F", "owner={owner}", "-F", "name={repo}"]
    m = _REPO_URL_RE.fullmatch(repo)
    parts = list(m.groups()) if m else repo.split("/")
    if len(parts) not in (2, 3) or not all(parts):
        return None
    # `-f` sends the value as the string given; `-F` would retype a name such
    # as `true` or `123` into a JSON boolean or number.
    args = ["-f", f"owner={parts[-2]}", "-f", f"name={parts[-1]}"]
    if len(parts) == 3:
        args = ["--hostname", parts[0], *args]
    return args


def _repo_from_prs(prs: list[dict]) -> str | None:
    """`HOST/OWNER/NAME` from the first listed PR's URL: the repo, host
    included, that `gh pr list` read."""
    for pr in prs:
        m = _PR_URL_RE.match(pr.get("url") or "")
        if m:
            return "/".join(m.groups())
    return None


def probe_auto_merge(repo: str | None, prs: list[dict] = ()) -> AutoMergeReading:
    """Read the repo's `autoMergeAllowed`. Any failure is `unknown`; this never
    raises, so a probe failure cannot stop the sweep. With no `repo`, the repo
    is the one the listed `prs` belong to."""
    if not repo:
        repo = _repo_from_prs(list(prs))
    target = _auto_merge_args(repo)
    if target is None:
        return AutoMergeReading(
            AUTO_MERGE_UNKNOWN,
            f"--repo {_sanitize_log(repo, 80)!r} is not OWNER/NAME")
    try:
        out = _gh(["api", "graphql", *target,
                   "-f", f"query={AUTO_MERGE_QUERY}"], None)
    except (RuntimeError, OSError) as e:
        # `_gh`'s message is "`<command>` failed: <stderr>"; keep the stderr.
        detail = _sanitize_log(str(e).split(" failed: ", 1)[-1], 160)
        return AutoMergeReading(AUTO_MERGE_UNKNOWN,
                                f"gh could not read it: {detail}")
    try:
        value = json.loads(out)["data"]["repository"]["autoMergeAllowed"]
    except (ValueError, KeyError, TypeError):
        return AutoMergeReading(AUTO_MERGE_UNKNOWN,
                                "the response did not carry the setting")
    if value is True:
        return AutoMergeReading(AUTO_MERGE_ALLOWED)
    if value is False:
        return AutoMergeReading(AUTO_MERGE_NOT_ALLOWED)
    return AutoMergeReading(AUTO_MERGE_UNKNOWN,
                            f"the setting read as {json.dumps(value)}")


def render_auto_merge(reading: AutoMergeReading) -> str:
    """The plan header's one line about the premise."""
    if reading.state == AUTO_MERGE_ALLOWED:
        return ("native auto-merge: allowed — GitHub can merge these PRs "
                "itself; this sweep would be a second merge actor.")
    if reading.state == AUTO_MERGE_NOT_ALLOWED:
        return ("native auto-merge: not allowed — this sweep is the merge "
                "actor.")
    return (f"native auto-merge: unknown ({reading.reason}) — proceeding as "
            f"if it were not allowed.")


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

    A PR with no target version, or a grouped title, never groups: an
    unparseable title keys as ('?', '?', None) and a grouped title
    (`bump a and b …`, with or without versions) keys on its first package
    only, so either would collapse unrelated PRs.
    """
    groups: dict[tuple, list[int]] = {}
    for i, p in enumerate(plans):
        if p.action not in ("merge", "hold", "surface"):
            continue
        if p.to_version is None:
            continue
        m = TITLE_RE.match(p.title)
        if m and m.group("also"):
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


def render_plan(plans: list[Plan], executing: bool,
                reading: AutoMergeReading | None = None) -> str:
    probe = [render_auto_merge(reading)] if reading is not None else []
    if not plans:
        return "\n".join([*probe, "No open Dependabot PRs. Nothing to sweep."])
    lines = []
    header = "PLANNED ACTIONS" if not executing else "EXECUTING"
    lines.append(header)
    lines.extend(probe)
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
        reading = probe_auto_merge(args.repo, prs)

        if args.json:
            print(json.dumps({"native_auto_merge": reading.to_dict(),
                              "plans": [p.to_dict() for p in plans]},
                             indent=2))
            return 0

        if args.execute:
            print(render_plan(plans, executing=True, reading=reading))
            results = execute(plans, args.repo)
            print()
            print("\n".join(results) if results else "Nothing actuated.")
            if reading.state == AUTO_MERGE_ALLOWED:
                print(render_auto_merge(reading))
        else:
            print(render_plan(plans, executing=False, reading=reading))
        return 0
    except RuntimeError as e:
        print(f"ERROR: {_sanitize_log(e)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
