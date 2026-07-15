#!/usr/bin/env python3
"""Mine gdp-query-system's review history for the workflow-gets-quieter analysis.

Read-only against the gdp repo (file reads + read-only git commands). Produces
``gdp_review_metrics.json`` next to this script. Filed as colleague-review
item 4 in REVIEW_CHECKLIST.md: test the monograph's "quieter over time" thesis
before claiming it publicly.

Three deterministic metrics:
  1. Findings per review round over time, split by round type
     (quality / security / mixed / other).
  2. Severity mix per round (share of critical 🔴 findings).
  3. Convention accretion over time — first git-history appearance of each
     current CLAUDE.md § Prevention Conventions bullet.

Caveat carried into the output: conventions reworded since promotion get a
later-than-true first-appearance date (substring match on the current name).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

GDP = Path.home() / "Projects" / "gdp-query-system"
OUT = Path(__file__).parent / "gdp_review_metrics.json"

ROUND_RE = re.compile(r"^## Round (\d+)[^(]*\((\d{4}-\d{2}-\d{2})\)(?:\s*—\s*(.*))?")
FINDING_RE = re.compile(r"^- \[[ x]\] \*\*([A-Za-z0-9_-]+)\*\*:?\s*(.*)")
SEVERITY = {"🔴": "critical", "🟡": "medium", "🟢": "low"}
BULLET_RE = re.compile(r"^- \*\*(.+?)\*\*")


def classify(title: str | None) -> str:
    t = (title or "").lower()
    quality = "code quality" in t
    security = "security" in t
    if quality and security:
        return "mixed"
    if security:
        return "security"
    if quality:
        return "quality"
    return "other"


def parse_rounds() -> list[dict]:
    sections: list[dict] = []
    current: dict | None = None
    for path in (GDP / "review_tasks_archive.md", GDP / "review_tasks.md"):
        for line in path.read_text().splitlines():
            m = ROUND_RE.match(line)
            if m:
                current = {
                    "round": int(m.group(1)),
                    "date": m.group(2),
                    "type": classify(m.group(3)),
                    "findings": 0,
                    "critical": 0,
                    "medium": 0,
                    "low": 0,
                }
                sections.append(current)
                continue
            if current is None or not FINDING_RE.match(line):
                continue
            current["findings"] += 1
            for emoji, key in SEVERITY.items():
                if emoji in line:
                    current[key] += 1
                    break
    return sections


def merge_rounds(sections: list[dict]) -> list[dict]:
    """Aggregate duplicate `## Round N` sections into one record per round."""
    by_round: dict[int, dict] = {}
    for s in sections:
        r = by_round.setdefault(
            s["round"],
            {"round": s["round"], "date": s["date"], "types": set(),
             "findings": 0, "critical": 0, "medium": 0, "low": 0},
        )
        r["date"] = min(r["date"], s["date"])
        r["types"].add(s["type"])
        for k in ("findings", "critical", "medium", "low"):
            r[k] += s[k]
    out = []
    for r in sorted(by_round.values(), key=lambda x: x["round"]):
        types = r.pop("types") - {"other"} or {"other"}
        r["type"] = "mixed" if len(types) > 1 else next(iter(types))
        out.append(r)
    return out


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(GDP), *args],
        capture_output=True, text=True, check=True,
    ).stdout


def convention_names() -> list[str]:
    text = (GDP / "CLAUDE.md").read_text()
    section = text.split("## Prevention Conventions", 1)[1]
    section = re.split(r"\n## (?!#)", section, maxsplit=1)[0]
    return [m.group(1) for line in section.splitlines() if (m := BULLET_RE.match(line))]


def first_appearances(names: list[str]) -> dict[str, str]:
    """Date each convention name first appears in CLAUDE.md history (oldest-first walk)."""
    commits = [
        line.split(" ", 1)
        for line in git("log", "--reverse", "--format=%H %as", "--", "CLAUDE.md").splitlines()
    ]
    pending = {f"**{n}**": n for n in names}
    dates: dict[str, str] = {}
    for sha, date in commits:
        if not pending:
            break
        try:
            blob = git("show", f"{sha}:CLAUDE.md")
        except subprocess.CalledProcessError:
            continue
        for needle in [k for k in pending if k in blob]:
            dates[pending.pop(needle)] = date
    return dates


# Vendored/generated paths excluded from the lines-changed denominator.
EXCLUDES = [
    ":(exclude,glob)**/node_modules/**", ":(exclude)node_modules",
    ":(exclude)google-cloud-sdk", ":(exclude,glob)**/package-lock.json",
    ":(exclude,glob)**/*.lock", ":(exclude)test-results", ":(exclude)logs",
    ":(exclude)data", ":(exclude)seed_data", ":(exclude)data_seed",
]


def lines_changed(since: str, until: str) -> tuple[int, int]:
    """(total effective lines changed, median raw lines per commit) for the window."""
    out = git("log", "--no-merges", f"--since={since} 00:00", f"--until={until} 00:00",
              "--numstat", "--format=", "--", ".", *EXCLUDES)
    total = sum(
        int(p[0]) + int(p[1])
        for line in out.splitlines()
        if len(p := line.split("\t")) == 3 and p[0] != "-"
    )
    raw = git("log", "--no-merges", f"--since={since} 00:00", f"--until={until} 00:00",
              "--shortstat", "--format=%H")
    sizes = []
    for line in raw.splitlines():
        if "changed" in line:
            n = 0
            for part in line.split(","):
                if "insertion" in part or "deletion" in part:
                    n += int(part.split()[0])
            sizes.append(n)
    sizes.sort()
    median = sizes[len(sizes) // 2] if sizes else 0
    return total, median


def monthly(rounds: list[dict]) -> list[dict]:
    """Aggregate by calendar month, normalized by commit activity in the window."""
    months: dict[str, dict] = {}
    for r in rounds:
        m = months.setdefault(
            r["date"][:7],
            {"month": r["date"][:7], "rounds": 0,
             "findings": 0, "critical": 0, "medium": 0, "low": 0},
        )
        m["rounds"] += 1
        for k in ("findings", "critical", "medium", "low"):
            m[k] += r[k]
    out = []
    for key in sorted(months):
        m = months[key]
        y, mo = int(key[:4]), int(key[5:7])
        until = f"{y + (mo == 12)}-{mo % 12 + 1:02d}-01"
        commits = int(git("rev-list", "--count",
                          f"--since={key}-01 00:00", f"--until={until} 00:00", "HEAD"))
        m["commits"] = commits
        eff, median = lines_changed(f"{key}-01", until)
        m["effective_lines_changed"] = eff
        m["median_lines_per_commit"] = median
        m["critical_per_100_commits"] = round(100 * m["critical"] / commits, 2)
        m["critical_per_10k_lines"] = round(10_000 * m["critical"] / eff, 2)
        m["findings_per_100_commits"] = round(100 * m["findings"] / commits, 1)
        m["critical_share_pct"] = round(100 * m["critical"] / m["findings"], 1)
        m["low_share_pct"] = round(100 * m["low"] / m["findings"], 1)
        out.append(m)
    return out


def main() -> int:
    rounds = merge_rounds(parse_rounds())
    names = convention_names()
    promoted = first_appearances(names)

    accretion = Counter(promoted.values())
    timeline = []
    total = 0
    for date in sorted(accretion):
        total += accretion[date]
        timeline.append({"date": date, "cumulative_conventions": total})

    result = {
        "source": "gdp-query-system review_tasks.md + review_tasks_archive.md + CLAUDE.md git history",
        "rounds": rounds,
        "monthly": monthly(rounds),
        "convention_count": len(names),
        "conventions_dated": len(promoted),
        "convention_accretion": timeline,
        "caveats": [
            "Reworded conventions get a later-than-true first-appearance date.",
            "Findings-per-round has no size denominator; the codebase grew throughout.",
            "Round type from section titles; untitled rounds classified 'other'.",
            "Late rounds file one task per call site (earlier rounds bundled), inflating "
            "late-period counts.",
            "Commit size shrank ~6x over the period (median_lines_per_commit), inflating "
            "per-commit rates — prefer critical_share_pct / low_share_pct (denominator-free) "
            "with critical_per_10k_lines as the activity-normalized check.",
            "First month (2026-02) is the repo bootstrap; the last month is partial — "
            "anchor rate claims on interior full months.",
        ],
    }
    OUT.write_text(json.dumps(result, indent=2) + "\n")

    print(f"rounds: {len(rounds)}  findings: {sum(r['findings'] for r in rounds)}")
    print(f"conventions: {len(names)} current, {len(promoted)} dated in history")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
