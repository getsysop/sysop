"""Positive fixtures — each call site should be flagged by recompile-inside-def."""

import re


def lookup(text: str) -> bool:
    # ruleid: recompile-inside-def — static pattern compiled per call
    pat = re.compile(r"^\d{3}_[a-z0-9_]+\.sql$")
    return bool(pat.match(text))


async def async_lookup(text: str) -> bool:
    # ruleid: recompile-inside-def — fires inside async def too
    return bool(re.compile(r"^[a-z]+$").match(text))


class Helper:
    def method(self, value: str) -> bool:
        # ruleid: recompile-inside-def — fires inside method bodies
        return bool(re.compile(r"^\w+$").match(value))
