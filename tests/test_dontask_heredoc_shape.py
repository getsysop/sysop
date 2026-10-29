"""Phase 380's round (lens 1, HIGH-1): under `dontAsk`, Claude Code denies a heredoc whose
Python body has a quote inside a `{…}` group, despite the seeded `Bash(python3 -:*)` rule.

Measured on Claude Code 2.1.296 in headless `dontAsk` sessions, one Bash call each, on a
trusted scratch consumer: denied were `{"a": 1}` (twice), `{'a': 1}`, the set literal
`{"true", "yes"}` and the env-strip comprehension `{k: v for k, v in os.environ.items() if k
not in ("GIT_DIR", …)}`; admitted were `{1: 2}`, `{k: v for k, v in os.environ.items()}`,
`dict(os.environ)` plus `pop`, a list comprehension with a string, and an f-string field with
a quote inside it (`f"{x or 'absent'}"`). Phase 380's round added: `{1: f"{x}"}` denied, `# don't`
before a dict still denied and before an f-string still admitted (so the gate reads quotes the
way the tokenizer does, not by a shell-style scan), and `# {"a": 1}` in a comment denied. So
the shape is a brace group outside any string literal that holds a string token, or a comment
that holds one.

`/review-close`, the skill an unattended night runs under `dontAsk` (spec § 13 (az)), carried
none after Phase 380. Phase 420 (`Q-665`) rewrote the last eight, in `/claim-task`,
`/auto-build` and `/document-work`, so no shipped skill carries one and the ceiling table that
held each skill at its count is gone: the rule is zero, everywhere.
"""
from __future__ import annotations

import io
import re
import tokenize
from collections import Counter

from _heredoc_population import REPO_ROOT, shipped_heredocs

# Skill heredocs run through Claude Code's Bash tool; `install.sh` and companion scripts run
# their heredocs in a shell of their own, which no permission gate reads.


_COMMENT_GROUP = re.compile(r"\{[^{}]*['\"][^{}]*\}")


def denied_groups(body: str) -> list[int] | None:
    """Body rows of each brace group outside a string literal that holds a string token,
    or None when the body does not tokenize."""
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(body).readline))
    except (tokenize.TokenError, SyntaxError):
        return None
    out: list[int] = []
    stack: list[list] = []
    fdepth = 0
    for t in toks:
        name = tokenize.tok_name[t.type]
        if name == "FSTRING_START":
            fdepth += 1
        elif name == "FSTRING_END":
            fdepth -= 1
            if not fdepth and stack:
                stack[-1][1] = True
            continue
        if fdepth:
            continue
        if t.type == tokenize.COMMENT and _COMMENT_GROUP.search(t.string):
            out.append(t.start[0])  # measured: `# {"a": 1}` alone is denied
            continue
        if t.type == tokenize.STRING and stack:
            stack[-1][1] = True
        elif t.type == tokenize.OP and t.string == "{":
            stack.append([t.start[0], False])
        elif t.type == tokenize.OP and t.string == "}" and stack:
            row, has = stack.pop()
            if has:
                out.append(row)
                if stack:
                    stack[-1][1] = True
    return out


def _skill_counts() -> tuple[Counter, list[str]]:
    counts: Counter = Counter()
    unread: list[str] = []
    for path, line, _, body in shipped_heredocs():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if "/skills/" not in f"/{rel}":
            continue
        groups = denied_groups(body)
        if groups is None:
            unread.append(f"{rel}:{line}")
        elif groups:
            counts[rel] += 1
    return counts, unread


def test_the_detector_matches_the_measured_shapes() -> None:
    denied = ['d = {"a": 1}', "d = {'a': 1}", 'x in {"true", "yes"}',
              'env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR",)}',
              'e = {"k": f"{x}"}', 'd = {1: f"{x}"}', '# {"a": 1}\nx = 1',
              "# don't\nd = {\"a\": 1}"]
    admitted = ["d = {1: 2}", "env = {k: v for k, v in os.environ.items()}",
                'env = dict(os.environ)\nenv.pop("GIT_DIR", None)',
                'names = [k for k in os.environ if k != "GIT_DIR"]',
                "print(f\"ok {x or 'absent'}\")", 'print("ok {x}")',
                "# don't\ns = f\"{d['k']}\"", "# a {set} of words\nx = 1"]
    for body in denied:
        assert denied_groups(body), body
    for body in admitted:
        assert denied_groups(body) == [], body


def test_no_skill_heredoc_gains_a_shape_dontask_denies() -> None:
    counts, unread = _skill_counts()
    assert not unread, f"skill heredocs that do not tokenize: {unread}"
    assert not counts, (
        "heredocs with a quote inside a {…} group outside any string, which Claude Code denies "
        "under dontAsk (Phase 380): rewrite each as dict(...)/set(...)/a tuple. "
        f"(file: count) {dict(counts)}")


def test_the_scan_reads_the_skill_heredocs() -> None:
    """With no ceiling left, an empty count is also what a scan that read nothing reports."""
    seen = {path.relative_to(REPO_ROOT).as_posix() for path, _, _, _ in shipped_heredocs()}
    for rel in ("core/skills/claim-task/SKILL.md", "core/skills/auto-build/SKILL.md",
                "core/skills/document-work/SKILL.md"):
        assert rel in seen, f"the heredoc scan no longer reads {rel}"
