#!/usr/bin/env python3
"""security_map_filter.py — `/review-close` Step 2b: the security twin's gate and its map copy (`Q-666`).

Step 2b used to hand every security agent the whole security map, and to decide by hand whether
any glob in it reached the target's diff. This does both from one read, so the gate and the copy
cannot disagree about what matched:

    python3 sysop/scripts/security_map_filter.py "<target>" "<default branch>"

run from the repo root, after the target's `gate_verdict.py lookup security` missed. `<target>`
is a branch, or `unpushed-main` for the unpushed-main group; the diff basis is the one
`gate_verdict.py` keys on (the target's commit and its merge-base with `<default branch>`, or
with `origin/<default branch>` for the group).

The maps are `.claude/security_map.project.md` (the consumer overlay) and
`.claude/security_map.md` beneath it, read from the top level of the checkout. `install.sh`
appends the overlay to the shipped map, so a shipped map ending with the overlay is read without
that copy. Headings are read outside fences and HTML comments, ATX (up to three spaces of
indent) and setext alike; a heading inside a blockquote or a list item counts for the gate and
for keeping its section, and cuts nothing. A `#` or `##` heading starts a section; deeper
headings belong to the section above them.

**The gate reads leniently.** Every backticked token in every heading, at any level, is a glob:
the map's `###` headings route paths too (a consumer's `### \\`migrations/*.sql\\`` under a `##`
that names none). The target spawns when one of them, placeholders aside, matches the diff.

**The cut reads strictly.** A `##` section is DROPPED only when its own heading parses as
`## <globs> — <Name>` with every glob concrete, no heading in the section carries a placeholder,
and no glob in any of its headings matches. Every other section is kept: a placeholder glob
(`<api module>`) cannot rule a path out, and a heading this cannot parse names nothing it could
rule out. Text before a map's first section, and under a `#` heading, is kept. A map with a fence
or comment that never closes is kept whole, and its gate reads every heading-shaped line in it.

A glob matches when `git diff --quiet --no-renames <base> <tip> -- ':(top,glob)<glob>'` reports a
change: git's `**`, against the diff itself, from the top level whatever the current directory. A
renamed file matches under both names: the pathspec limits the diff before renames are detected,
and `--no-renames` says so explicitly. Braces are expanded first (`*.{ts,tsx}`), and a leading `/`
or `./` is dropped. A glob git cannot read is printed as `UNMATCHABLE:` and treated as matching,
so it keeps its section and spawns the twin rather than skipping it.

Writes, in the MAIN checkout's `sysop/runtime/`:
    2b-security.md                       both maps, verbatim: the full copy
    2b-security-<hash of target>.md      the kept sections, verbatim, in the same order

Prints, then exits:
    0   SPAWN <target> — <n> of <m> map sections matched
        then `MATCHED:`, `OMITTED:`, `PLACEHOLDER:` and `UNMATCHABLE:` lines, one each,
        `FULL: <path>`, `COPY: <path> (<characters> characters)`, and `ARM: inline` at or below
        10,000 characters or `ARM: file` above.
    3   SKIP <target> — no security-map glob matches this diff, and how many of the sections
        still carry placeholder globs. Nothing is written.
    2   the gate could not be computed; the message says why. Nothing is written, or only the full
        copy when the per-target copy's write failed.
"""
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from gate_verdict import GIT_ENV, Refuse, ends, main_root, read_text, top_level
from security_partition import SECTION_RE

MAPS = (".claude/security_map.project.md", ".claude/security_map.md")
INLINE_LIMIT = 10_000
ATX = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
SETEXT = re.compile(r" {0,3}(=+|-+)[ \t]*$")
# A heading inside a blockquote or a list item: read for the gate and for keeping its section,
# never as a cut.
NESTED = re.compile(r" {0,3}(?:>[ \t]?|[-*+][ \t]+|\d+[.)][ \t]+)+#{1,6}[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
EXPAND_LIMIT = 256


def fence_mark(line: str):
    """`(char, length)` if the line is a fence marker, else None (`claim_record.py`'s rule). A
    backtick run followed by another backtick is an inline span, not a fence, and a marker
    indented four spaces or by a tab is indented code (CommonMark). Missing a fence errs toward
    reading its lines as text, which keeps; a phantom fence would hide the headings after it."""
    s = line.lstrip(" ")
    if line.startswith("\t") or len(line) - len(s) > 3:
        return None
    for ch in ("`", "~"):
        if s.startswith(ch * 3):
            n = len(s) - len(s.lstrip(ch))
            if ch == "`" and "`" in s[n:]:
                return None
            return ch, n
    return None


def fence_closes(line: str, open_mark) -> bool:
    """Same character, at least as long, and no info string: an opener may carry one, a closer
    may not (`Q-468`)."""
    mark = fence_mark(line)
    return (bool(mark) and mark[0] == open_mark[0] and mark[1] >= open_mark[1]
            and not line.strip().strip(mark[0]))


def blocked(lines: list) -> tuple:
    """Per line, whether it sits in a fence or an HTML comment, and whether one is left open. A
    comment opens only where `<!--` starts its line (up to three spaces of indent) and the line
    holds no `-->`, as CommonMark's HTML block does: a `<!--` mid-line is text."""
    out, fence, comment = [], None, False
    for line in lines:
        if fence:
            out.append(True)
            if fence_closes(line, fence):
                fence = None
        elif comment:
            out.append(True)
            comment = "-->" not in line
        elif fence_mark(line):
            out.append(True)
            fence = fence_mark(line)
        elif re.match(r" {0,3}<!--", line):
            out.append(True)
            comment = "-->" not in line.lstrip()[2:]
        else:
            out.append(False)
    return out, bool(fence) or comment


def headings(lines: list, skip: list) -> list:
    """`(index, level, text, atx)` for each heading line not in `skip`."""
    out = []
    for i, line in enumerate(lines):
        if skip[i]:
            continue
        bare = line.rstrip("\r\n")
        m = ATX.match(bare)
        nested = NESTED.match(bare)
        if nested and not m:
            out.append((i, 6, nested.group(1).strip(), False))
        elif m:
            out.append((i, len(m.group(1)), (m.group(2) or "").strip(), True))
        elif (i and SETEXT.match(bare) and not skip[i - 1] and lines[i - 1].strip()
              and not ATX.match(lines[i - 1].rstrip("\r\n")) and not (out and out[-1][0] == i - 1)):
            out.append((i - 1, 1 if "=" in bare else 2, lines[i - 1].strip(), False))
    return out


def tokens(text: str) -> list:
    """Every backticked token, braces expanded, a leading `/` or `./` dropped."""
    def expand(g):
        m = re.search(r"\{([^{}]*)\}", g)
        return [g] if not m else [x for alt in m.group(1).split(",")
                                  for x in expand(g[:m.start()] + alt + g[m.end():])]

    def count(g):
        m = re.search(r"\{([^{}]*)\}", g)
        return 1 if not m else (m.group(1).count(",") + 1) * count(g[:m.start()] + "x" + g[m.end():])
    out = []
    for raw in re.findall(r"`([^`]+)`", text):
        if count(raw.strip()) > EXPAND_LIMIT:
            out.append("\0" + raw.strip())  # too many to match: `reaches` counts it as matching
            continue
        for g in expand(raw.strip()):
            while g.startswith("./"):
                g = g[2:]
            g = g.lstrip("/")
            if g:
                out.append(g)
    return out


def strict(text: str) -> list:
    """The heading's globs when it parses as `## <globs> — <Name>`, else none."""
    m = SECTION_RE.match("## " + text)
    return tokens(m.group("globs")) if m else []


def reaches(base: str, tip: str, globs: list, unmatchable: list) -> bool:
    """Whether a glob reaches the diff. One git cannot read, cannot be given (an argument list
    too long) or expands past `EXPAND_LIMIT` is `unmatchable`, and counts as reaching."""
    wide = [g.lstrip("\0") for g in globs if g.startswith("\0")]
    if wide:
        unmatchable.extend(g for g in wide if g not in unmatchable)
        return True
    try:
        p = subprocess.run(["git", "diff", "--quiet", "--no-renames", base, tip, "--",
                            *(f":(top,glob){g}" for g in globs)], capture_output=True, env=GIT_ENV)
    except OSError:
        p = None
    if p is None or p.returncode not in (0, 1):
        unmatchable.extend(g for g in globs if g not in unmatchable)
        return True
    return p.returncode == 1


def sections(text: str):
    """`([(heading, body, headings in it)], every heading)`: a heading is `headings()`'s tuple,
    or None for the text before the first. The list is None when a block never closes."""
    lines = text.splitlines(keepends=True)
    skip, open_ = blocked(lines)
    if open_:
        return None, headings(lines, [False] * len(lines))
    found = headings(lines, skip)
    cuts = [h for h in found if h[1] <= 2]
    starts = [0] + [h[0] for h in cuts]
    out = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        if start == end:
            continue
        head = cuts[n - 1] if n else None
        inner = [h for h in found if start <= h[0] < end]
        out.append((head, "".join(lines[start:end]), inner))
    return out, found


def write(p: Path, text: str) -> None:
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=".2b-security-")
    except OSError as e:
        raise Refuse(f"{p} could not be written ({type(e).__name__}: {e})") from e
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, p)
    except BaseException as e:
        Path(tmp).unlink(missing_ok=True)
        if isinstance(e, OSError):
            raise Refuse(f"{p} could not be written ({type(e).__name__}: {e})") from e
        raise


def run(target: str, default: str) -> int:
    if not target.strip() or not default.strip() or re.search(r"<[^<>]*>", target + default):
        raise Refuse("substitute the target and the default branch")
    tip, base = ends(target, default)
    root = top_level()
    full, kept, matched, omitted, placeholder, unmatchable, count = [], [], [], [], [], [], 0
    overlay = read_text(root / MAPS[0]) if (root / MAPS[0]).is_file() else None
    for rel in MAPS:
        if not (root / rel).is_file():
            continue
        text = read_text(root / rel)
        if rel == MAPS[1] and overlay and text.endswith("\n" + overlay):
            # `install.sh` appends the overlay to the shipped map (Phase 24a); it is read once,
            # live, above. An overlay edited since the last update does not match and is read
            # twice, which repeats a rule and loses none.
            text = text[:-len("\n" + overlay)]
        text = text[1:] if text.startswith("\ufeff") else text
        text += "" if not text or text.endswith("\n") else "\n"
        full.append(f"<!-- {rel} -->\n{text}")
        kept.append(f"<!-- {rel} -->\n")
        parts, found = sections(text)
        if parts is None:
            print(f"WHOLE: {rel} has a fence or comment that never closes, so it is kept whole")
            kept.append(text)
            count += sum(h[1] == 2 for h in found)
            placeholder += [h[2] for h in found if h[1] == 2 and any("<" in g for g in tokens(h[2]))]
            globs = [g for h in found for g in tokens(h[2]) if "<" not in g]
            if globs and reaches(base, tip, globs, unmatchable):
                matched.append(f"{rel} (read whole)")
            continue
        for head, body, inner in parts:
            label = body.splitlines()[0].strip() if head else None
            level = head[1] if head else 0
            count += level == 2
            every = [g for h in inner for g in tokens(h[2])]
            concrete = [g for g in every if "<" not in g]
            if level == 2 and len(concrete) < len(every):
                placeholder.append(label)
            if concrete and reaches(base, tip, concrete, unmatchable):
                matched.append(label or f"{rel} (before its first section)")
            elif level == 2 and head[3] and strict(head[2]) and concrete == every:
                omitted.append(label)
                continue
            kept.append(body)
    if not matched:
        why = "no security map exists" if not full else (
            f"{len(placeholder)} of {count} map sections still carry placeholder globs")
        print(f"SKIP {target} — no security-map glob matches this diff ({why})")
        return 3
    runtime = main_root() / "sysop" / "runtime"
    full_path = runtime / "2b-security.md"
    copy_path = runtime / f"2b-security-{hashlib.sha256(target.encode()).hexdigest()[:16]}.md"
    copy = "".join(kept)
    write(full_path, "".join(full))
    write(copy_path, copy)
    print(f"SPAWN {target} — {len(matched)} of {count} map sections matched")
    for label, items in (("MATCHED", matched), ("OMITTED", omitted), ("PLACEHOLDER", placeholder),
                         ("UNMATCHABLE", unmatchable)):
        for item in items:
            print(f"{label}: {item}")
    print(f"FULL: {full_path}")
    print(f"COPY: {copy_path} ({len(copy):,} characters)")
    print(f"ARM: {'inline' if len(copy) <= INLINE_LIMIT else 'file'}")
    return 0


def main(argv: list) -> int:
    if len(argv) != 2:
        print('usage: security_map_filter.py "<target>" "<default branch>"', file=sys.stderr)
        return 2
    try:
        return run(*argv)
    except Refuse as e:
        print(f"security_map_filter: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
