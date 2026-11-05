#!/usr/bin/env python3
"""convention_size.py — `/review-close` Step 2b: measure the convention sections to paste.

    python3 sysop/scripts/convention_size.py "Prevention Conventions" "Testing Patterns" ["<section step 0 identified>" ...]

Run from the repo root. One argument per `CLAUDE.md` section of the widened set, without
its `## `. Prints each section's size in characters, `(absent)` for one that is not there,
and a `TOTAL` line; the total picks the paste or write-once arm. No argument, or an empty one,
one still holding a `<placeholder>`, or one that kept its `## `, exits 1 before anything is
read. A heading's own `#`, `<` or `>` (`#hashtags`, `Frontend -> Backend`) is a name.

A section runs from its `## <name>` heading (as CommonMark reads it: blanks after `##`, trailing
blanks and a closing `#` run allowed) to the next `# ` or `## ` heading, and every occurrence of a
name is measured. Fenced lines and HTML comments are skipped: a heading quoted in an example
neither starts nor ends a section. A name found only inside one is named on stderr. A fence or
comment that never closes is reported on stderr, and the rest of the file is measured as text.

The skill text is the contract: `/review-close` Step 2b says what the total decides. This
file was that step's heredoc until Phase 387 (`Q-409` P3), moved verbatim with one declared
change: the runner used to edit a `SECTIONS` list in the program, and the sections are now
arguments. Phase 465 (`Q-361`) made it fence-aware and every-occurrence.
"""
import re, sys
# One argument per section of the widened set: the two the step names, plus each
# section step 0 identified. A measurement of fewer sections than you paste lands the
# prompt on the wrong arm, so an empty or unsubstituted argument is refused.
SECTIONS = sys.argv[1:]
_bad = [s for s in SECTIONS if not s.strip() or re.match(r"#+\s", s) or re.search(r"<[^<>]*>", s)]
if not SECTIONS or _bad:
    sys.exit(f"ERROR: pass each section's name as one argument, without its `## `: {_bad or SECTIONS!r}")
try:
    text = open("CLAUDE.md", encoding="utf-8").read()
except (OSError, UnicodeDecodeError) as e:
    sys.exit(f"ERROR: CLAUDE.md could not be read ({type(e).__name__}: {e})")

# Fenced lines and HTML comments are not headings: a `## ` quoted in an example neither opens a
# section nor ends one. `security_map_filter.blocked` is the reader Step 2b's security cut
# already uses: a fence opens on ``` or ~~~ indented at most three spaces (a backtick run with
# another backtick after it is an inline span), and closes on the same character, at least as
# long, with no info string; a comment opens where `<!--` starts its line.
from security_map_filter import blocked

lines = text.split("\n")
starts = [0]
for ln in lines:
    starts.append(starts[-1] + len(ln) + 1)
starts[-1] = len(text)  # the last line has no newline after it
fenced, left_open = blocked(lines)
if left_open:
    # An unclosed block would hide every heading after it. Measure its run as text, and say so:
    # a wrong arm is cheaper than a silent zero. Blocks that closed before it stay skipped.
    k = len(lines)
    while k > 0 and fenced[k - 1]:
        k -= 1
    print(f"NOTE: CLAUDE.md line {k + 1} opens a fence or comment that never closes; "
          "measured the rest of the file without skipping it.", file=sys.stderr)
    fenced[k:] = [False] * (len(lines) - k)

# A section runs from its `## ` heading to the next `# ` or `## ` heading outside a block, so a
# `### ` inside it belongs to it and a following h1 ends it. The heading is CommonMark's: blanks
# after `##`, trailing blanks, and a closing `#` run are not part of the name.
END = re.compile(r"#{1,2}(?:[ \t]|$)")
total = 0
for name in SECTIONS:
    head = re.compile(rf"##[ \t]+{re.escape(name)}(?:[ \t]+#+)?[ \t]*")
    n = found = 0
    quoted = []
    for i, ln in enumerate(lines):
        if not head.fullmatch(ln):
            continue
        if fenced[i]:
            quoted.append(i + 1)
            continue
        j = i + 1
        while j < len(lines) and (fenced[j] or not END.match(lines[j])):
            j += 1
        n += starts[j] - starts[i]
        found += 1
    if found > 1:
        # Every occurrence is measured, so each one belongs in the paste or the written copy.
        print(f"NOTE: ## {name} appears {found} times in CLAUDE.md; all are measured.",
              file=sys.stderr)
    if not found and quoted:
        # Usually a quoted example. It is also what a forgotten fence closer above a real
        # section looks like, and only a reader of the file can tell the two apart.
        print(f"NOTE: ## {name} appears only inside a fenced block or comment (line "
              f"{quoted[0]}); measured as absent.", file=sys.stderr)
    print(f"{n:>8}  ## {name}" + ("" if found else "   (absent)"))
    total += n
print(f"{total:>8}  TOTAL")
