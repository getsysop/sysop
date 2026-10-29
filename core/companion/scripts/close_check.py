#!/usr/bin/env python3
"""close_check.py — `/review-close` Step 4c item 5: check the writes before the pending docs are deleted.

    python3 sysop/scripts/close_check.py

Run once every write in item 4 is done. It compares `PROJECT_STATUS.md` and the tracked
changelog on disk with `HEAD` and resolves the repository root itself. Prints its findings
and `RESULT: ok` (exit 0), `RESULT: STOP` (exit 1), or `RESULT: UNCHECKED — <why>` (exit 2).

The skill text is the contract: `/review-close` Step 4c item 5 says what it checks and what
each result means. This file was that step's heredoc until Phase 387 (`Q-409` P3), moved
verbatim.
"""
import os, re, subprocess, sys
from collections import Counter
sys.stdout.reconfigure(errors="backslashreplace")
KEEP, TRIGGER = 6, 8
ENTRY = re.compile(r"\s{0,3}(?:[-*+]\s+)?\d{4}-\d{2}-\d{2}:")
S6 = re.compile(r"\s{0,3}(?:(#{1,6})\s+)?(?:6\.\s+)?Recent Major Updates\s*#*\s*$", re.I)
FENCE = re.compile(r"[ ]{0,3}(`{3,}|~{3,})(.*)$")
ENV = dict((k, v) for k, v in os.environ.items()
       if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"))
problems, warns = [], []

def unchecked(why):
    print("RESULT: UNCHECKED — " + why)
    sys.exit(2)

def git(*args):
    return subprocess.run(["git", *args], capture_output=True, env=ENV)

top = git("rev-parse", "--show-toplevel")
if top.returncode:
    unchecked("not inside a git work tree")
os.chdir(os.fsdecode(top.stdout.strip()))

def read(path, at_head):
    try:
        if at_head:
            listed = git("ls-tree", "--name-only", "HEAD", "--", path)
            if listed.returncode:
                unchecked("git could not list HEAD")
            if not listed.stdout.strip():
                return None
            shown = git("show", "HEAD:" + path)
            if shown.returncode:
                unchecked(f"git could not read HEAD:{path}")
            return shown.stdout.decode("utf-8").splitlines()
        if not os.path.exists(path):
            return None
        with open(path, encoding="utf-8") as f:
            return f.read().splitlines()
    except (OSError, UnicodeDecodeError) as e:
        unchecked(f"{path} could not be read ({type(e).__name__}: {e})")

def ends_section(line, level):
    m = re.match(r"\s{0,3}(#{1,6})\s", line)
    if m:
        return len(m.group(1)) <= (level or 2)
    m = re.match(r"\s{0,3}(\d+)\.\s+\S", line)
    return bool(m) and int(m.group(1)) > 6

def split6(lines, where):
    heads = [(i, m) for i, l in enumerate(lines) for m in [S6.match(l)] if m]
    if len(heads) != 1:
        unchecked(f"PROJECT_STATUS.md has {len(heads)} 'Recent Major Updates' headings, not 1")
    h, level = heads[0][0], len(heads[0][1].group(1) or "")
    stop = next((j for j in range(h + 1, len(lines)) if ends_section(lines[j], level)), len(lines))
    start = next((j for j in range(h + 1, stop) if ENTRY.match(lines[j])), stop)
    end, entries = start, []
    while end < stop:
        line = lines[end]
        if ENTRY.match(line):
            entries.append(line.strip())
        elif line.strip():
            if line[:1] in (" ", "\t") and ENTRY.match(lines[end - 1]):
                unchecked(f"PROJECT_STATUS.md {where}, line {end + 1}, is indented directly under a §6 entry:"
                          " a wrapped entry and indented furniture look the same there")
            break
        end += 1
    furniture = [l.rstrip() for l in lines[:start] + lines[end:] if l.strip()]
    section = [l.strip() for l in lines[h + 1:stop] if l.strip() and not ENTRY.match(l)]
    return entries, furniture, section

before, after = read("PROJECT_STATUS.md", True), read("PROJECT_STATUS.md", False)
section = []
if after is None:
    print("S6: PROJECT_STATUS.md absent — nothing to check")
    if before is not None:
        problems.append("PROJECT_STATUS.md was deleted")
else:
    eb, fb, section = split6(before, "at HEAD") if before is not None else ([], None, [])
    ea, fa, _ = split6(after, "on disk")
    added = list((Counter(ea) - Counter(eb)).elements())
    total = len(eb) + len(added)
    expect = KEEP if total > TRIGGER else total
    print(f"S6_ENTRIES: before {len(eb)} · added {len(added)} · after {len(ea)} · expected {expect}")
    print(f"ROTATED: {sum((Counter(eb) - Counter(ea)).values())}")
    if fb is not None and fb != fa:
        lost = [f"removed {l.strip()[:80]!r}" for l in (Counter(fb) - Counter(fa)).elements()]
        got = [f"added {l.strip()[:80]!r}" for l in (Counter(fa) - Counter(fb)).elements()]
        problems.append("PROJECT_STATUS.md changed outside §6's entries: "
                        + ("; ".join(lost + got) or "lines reordered"))
    if len(ea) != expect:
        problems.append(f"§6 holds {len(ea)} entries; the Rotation check leaves {expect}")
    elif (Counter(ea[:len(added)]) != Counter(added)
          or ea[len(added):] != eb[:len(ea) - len(added)]):
        problems.append("§6's entries are not the new ones above the newest old ones, in order")

tracked = [os.fsdecode(p) for p in git("ls-files", "-z", "--", ":(icase)CHANGELOG.md").stdout.split(b"\0") if p]
if len(tracked) > 1:
    unchecked("more than one tracked changelog: " + ", ".join(tracked))
path = (tracked or ["CHANGELOG.md"])[0]
cl_after, cl_before = read(path, False), read(path, True)

def classes(lines):
    live, opener = [], None
    for l in lines:
        m = FENCE.match(l)
        if opener is None and m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            opener = m.group(1)
        elif opener and m and m.group(1)[0] == opener[0] and len(m.group(1)) >= len(opener) and not m.group(2).strip():
            opener = None
        elif opener is None:
            live.append(True)
            continue
        live.append(False)
    u = [i for i, l in enumerate(lines) if live[i] and re.match(r"##\s+\[Unreleased\]", l, re.I)]
    if not u:
        return 0, {}
    end = next((j for j in range(u[0] + 1, len(lines)) if live[j] and re.match(r"##\s", lines[j])), len(lines))
    at = {}
    for j in range(u[0] + 1, end):
        m = re.match(r"###\s+(\S.*?)\s*$", lines[j]) if live[j] else None
        if m:
            at.setdefault(m.group(1).lower(), []).append(j + 1)
    return len(u), at

if cl_after is None:
    print("CHANGELOG: absent — nothing to check")
    if cl_before is not None:
        problems.append(f"{path} was deleted")
else:
    print("CHANGELOG: " + path)
    cl_before = cl_before or []
    ub, at_b = classes(cl_before)
    ua, at_a = classes(cl_after)
    if ua > 1:
        (problems if ua > ub else warns).append(f"{path} has {ua} '## [Unreleased]' sections")
    for name, where in sorted(at_a.items()):
        if len(where) > 1:
            msg = (f"'### {name.title()}' appears {len(where)} times under [Unreleased]"
                   f" (lines {', '.join(map(str, where))})")
            (problems if len(where) > len(at_b.get(name, [])) else warns).append(msg)
    gone = list((Counter(l.rstrip() for l in cl_before if l.strip())
                 - Counter(l.rstrip() for l in cl_after if l.strip())).elements())
    if gone:
        problems.append(f"{path} lost {len(gone)} line(s) it had at HEAD, the first {gone[0].strip()[:80]!r}")
    new_lines = list((Counter(cl_after) - Counter(cl_before)).elements())
    for line in section:
        if len(line) >= 10 and any(line in n for n in new_lines):
            problems.append(f"{path} gained a line of §6's furniture: {line[:80]!r}")

for w in warns:
    print("WARN: " + w + " — the file already had this; report it, do not fix it here")
for p in problems:
    print("PROBLEM: " + p)
print("RESULT: " + ("STOP" if problems else "ok"))
sys.exit(1 if problems else 0)
