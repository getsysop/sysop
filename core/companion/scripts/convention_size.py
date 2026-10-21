#!/usr/bin/env python3
"""convention_size.py — `/review-close` Step 2b: measure the convention sections to paste.

    python3 sysop/scripts/convention_size.py "Prevention Conventions" "Testing Patterns" ["<section step 0 identified>" ...]

Run from the repo root. One argument per `CLAUDE.md` section of the widened set, without
its `## `. Prints each section's size in characters, `(absent)` for one that is not there,
and a `TOTAL` line; the total picks the paste or write-once arm. No argument, or an empty one,
one still holding a `<placeholder>`, or one that kept its `## `, exits 1 before anything is
read. A heading's own `#`, `<` or `>` (`#hashtags`, `Frontend -> Backend`) is a name.

The skill text is the contract: `/review-close` Step 2b says what the total decides. This
file was that step's heredoc until Phase 387 (`Q-409` P3), moved verbatim with one declared
change: the runner used to edit a `SECTIONS` list in the program, and the sections are now
arguments.
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
total = 0
for name in SECTIONS:
    m = re.search(rf"^## {re.escape(name)}$.*?(?=^## |\Z)", text, re.M | re.S)
    n = len(m.group(0)) if m else 0
    print(f"{n:>8}  ## {name}" + ("" if m else "   (absent)"))
    total += n
print(f"{total:>8}  TOTAL")
