"""Negative fixtures — none should fire.

Note: parameterized memoization helpers (re.compile inside def with the
result cached in a module-level dict) WILL fire because the rule cannot
statically distinguish them from a hot loop. The codebase triages them
as legitimate exceptions during review (see orchestrator.py:_header_pattern).
This file documents only the genuinely-clean patterns.
"""

import re

# ok: recompile-inside-def — module-scope constant
_VALID_SLUG = re.compile(r"^[a-z0-9-]+$")

# ok: recompile-inside-def — module-scope tuple of patterns
_PATTERNS = (
    re.compile(r"^foo$"),
    re.compile(r"^bar$"),
)


def is_valid_slug(s: str) -> bool:
    # ok: recompile-inside-def — uses the module-level constant
    return bool(_VALID_SLUG.match(s))


def find_pattern(s: str) -> re.Pattern | None:
    # ok: recompile-inside-def — references but does not compile
    for p in _PATTERNS:
        if p.match(s):
            return p
    return None
